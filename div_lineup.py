# app.py
import streamlit as st
import pandas as pd
import re
import random
from collections import Counter
from typing import Optional, Tuple, List, Dict

from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

st.set_page_config(page_title="The Betting Block DFS Optimizer", layout="wide")

# -------------------------
# Helpers
# -------------------------
NFL_POSITION_HINTS = {"QB", "RB", "WR", "TE", "K", "DST"}

def normalize_name(n: str) -> str:
    """Normalize a player name for stable lookup keys."""
    if n is None:
        return ""
    s = str(n).strip().lower()
    # remove punctuation except spaces and alphanum
    s = re.sub(r'[^a-z0-9\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def parse_name_and_id_from_field(val: str) -> Tuple[str, Optional[str]]:
    s = str(val or "").strip()
    m = re.match(r'^(.*?)\s*\((\d+)\)\s*$', s)
    if m:
        return m.group(1).strip(), m.group(2)
    m = re.match(r'^(.*?)\s*[-\|\/]\s*(\d+)\s*$', s)
    if m:
        return m.group(1).strip(), m.group(2)
    m = re.match(r'^(.*\D)\s+(\d+)\s*$', s)
    if m:
        return m.group(1).strip(), m.group(2)
    return s, None

def parse_salary(x) -> Optional[float]:
    if pd.isna(x):
        return None
    try:
        t = str(x).replace('$', '').replace(',', '').strip()
        return float(t) if t != '' else None
    except Exception:
        return None

def safe_float(x) -> float:
    try:
        if pd.isna(x):
            return 0.0
        return float(x)
    except Exception:
        try:
            return float(str(x).replace(',', '').strip())
        except Exception:
            return 0.0

def name_key_from_cell(cell: str) -> str:
    """Extract normalized name from a cell like 'Joe Burrow(39971296)' or 'Joe Burrow (TEAM)'"""
    if not isinstance(cell, str):
        return normalize_name(str(cell))
    # split at "(" (id or team), take left part
    base = cell.split("(")[0].strip()
    # remove trailing team indicators in some cases "Joe Burrow - QB" but keep simple
    return normalize_name(base)

def parse_positions_field(s: str) -> List[str]:
    if s is None:
        return []
    return [p.strip().upper() for p in re.split(r'[\/\|,]', str(s)) if p.strip()]

def player_display_name(p) -> str:
    """Return readable player name for Player-like objects (supports pydfs Player)"""
    if p is None:
        return ""
    fn = getattr(p, "first_name", None)
    ln = getattr(p, "last_name", None)
    if fn or ln:
        return f"{fn or ''} {ln or ''}".strip()
    full = getattr(p, "full_name", None)
    if full:
        return full
    name_alt = getattr(p, "name", None) or getattr(p, "fullName", None)
    if name_alt:
        return str(name_alt)
    return str(p)

# slot → allowed positions
SLOT_TO_ALLOWED_POS = {
    "QB": ["QB"],
    "RB1": ["RB"],
    "RB2": ["RB"],
    "WR1": ["WR"],
    "WR2": ["WR"],
    "WR3": ["WR"],
    "TE": ["TE"],
    "FLEX": ["RB", "WR", "TE"],
    "DST": ["DST"],
}

# -------------------------
# Build player info map from salary CSV
# -------------------------
def build_player_info_from_salary_df(
    salary_df: pd.DataFrame,
    name_col: Optional[str],
    pos_col: Optional[str],
    team_col: Optional[str],
    salary_col: Optional[str],
    fppg_col: Optional[str],
    id_col: Optional[str]
) -> Dict[str, Dict]:
    info = {}
    for _, r in salary_df.iterrows():
        raw_name = str(r.get(name_col) or r.get("Name") or "").strip() if name_col else str(r.get("Name") or "").strip()
        parsed_name, parsed_id = parse_name_and_id_from_field(raw_name)
        pid = None
        if id_col and not pd.isna(r.get(id_col)):
            pid = str(r.get(id_col)).strip()
        elif parsed_id:
            pid = parsed_id

        display = parsed_name.strip()
        key = normalize_name(display)
        positions = parse_positions_field(r.get(pos_col)) if pos_col else []
        team = str(r.get(team_col) or "").strip() if team_col else str(r.get("Team") or "").strip()
        salary = parse_salary(r.get(salary_col)) if salary_col else parse_salary(r.get("Salary"))
        salary = salary or 0
        fppg = safe_float(r.get(fppg_col)) if fppg_col else safe_float(r.get("FPPG") or r.get("Proj") or 0)

        info[key] = {
            "display": display,
            "id": pid,
            "positions": positions,
            "team": team,
            "salary": salary,
            "fppg": fppg,
        }
    return info

# -------------------------
# Exposure/pair helpers
# -------------------------
def compute_exposures_and_pairs(df_wide: pd.DataFrame, slot_cols: List[str]):
    players = []
    pairs = []
    for i in df_wide.index:
        lineup_players = []
        for c in slot_cols:
            v = df_wide.at[i, c]
            if isinstance(v, str) and v.strip():
                lineup_players.append(name_key_from_cell(v))
                players.append(name_key_from_cell(v))
        for a in range(len(lineup_players)):
            for b in range(a+1, len(lineup_players)):
                pairs.append(tuple(sorted([lineup_players[a], lineup_players[b]])))
    return Counter(players), Counter(pairs)

# -------------------------
# Diversification algorithm
# -------------------------
def diversify_lineups_wide(
    df_wide: pd.DataFrame,
    player_info: Dict[str, dict],
    slot_order: List[str],
    max_exposure: float = 0.4,
    max_pair_exposure: float = 0.6,
    randomness: float = 0.15,
    salary_cap: int = 50000,
    salary_min: int = 49500
):
    df = df_wide.copy(deep=True).reset_index(drop=True)
    if df.shape[0] == 0:
        return df

    slot_cols = [c for c in slot_order if c in df.columns]
    total_lineups = len(df)
    exposure, pair_exposure = compute_exposures_and_pairs(df, slot_cols)

    # precompute candidates by slot (normalized keys)
    candidates_by_slot = {}
    for slot, allowed in SLOT_TO_ALLOWED_POS.items():
        cands = []
        for key, inf in player_info.items():
            pos_list = [p.upper() for p in inf.get("positions") or []]
            # if no position info in salary file accept all for flex fallback
            if not pos_list and slot == "FLEX":
                cands.append(key)
                continue
            if any(p in allowed for p in pos_list):
                cands.append(key)
        candidates_by_slot[slot] = cands

    # For each lineup, attempt to diversify slots that are over-exposed or in over-exposed pairs
    for li in range(total_lineups):
        # get current lineup normalized names
        current_names = []
        for s in slot_cols:
            cell = df.at[li, s]
            if isinstance(cell, str) and cell.strip():
                current_names.append(name_key_from_cell(cell))

        # iterate slots (randomize order to reduce bias)
        for s in random.sample(slot_cols, len(slot_cols)):
            cell = df.at[li, s]
            if not isinstance(cell, str) or not cell.strip():
                continue
            original = name_key_from_cell(cell)
            player_exp = exposure.get(original, 0) / total_lineups
            # check any pair exposures involving this player
            current_line_pairs = [tuple(sorted([original, other])) for other in current_names if other != original]
            pair_flag = any((pair_exposure.get(p, 0) / total_lineups) > max_pair_exposure for p in current_line_pairs)
            if player_exp <= max_exposure and not pair_flag:
                continue
            if random.random() > randomness:
                # skip by randomness throttle
                continue

            # try replacements for slot s
            allowed_candidates = candidates_by_slot.get(s, [])
            random.shuffle(allowed_candidates)
            accepted = False

            # prepare old pairs to remove if we replace original
            old_pairs_in_line = set(tuple(sorted([original, other])) for other in current_names if other != original)

            for cand_key in allowed_candidates:
                if cand_key == original:
                    continue
                # candidate must not already be in this lineup
                if cand_key in current_names:
                    continue
                # candidate exposure check
                cand_new_exp = (exposure.get(cand_key, 0) + 1) / total_lineups
                if cand_new_exp > max_exposure:
                    continue

                # simulate new lineup
                sim_players = [n for n in current_names if n != original] + [cand_key]
                sim_salary = sum(player_info.get(n, {}).get("salary", 0) for n in sim_players)
                sim_points = sum(player_info.get(n, {}).get("fppg", 0) for n in sim_players)
                if sim_salary < salary_min or sim_salary > salary_cap:
                    continue

                # simulate pair exposure changes
                new_pairs = set()
                for a in range(len(sim_players)):
                    for b in range(a+1, len(sim_players)):
                        new_pairs.add(tuple(sorted([sim_players[a], sim_players[b]])))

                temp_pair_counts = pair_exposure.copy()
                # remove old pairs from this lineup
                for p in old_pairs_in_line:
                    temp_pair_counts[p] = max(0, temp_pair_counts.get(p, 0) - 1)
                # add new pairs from this lineup
                for p in new_pairs:
                    temp_pair_counts[p] = temp_pair_counts.get(p, 0) + 1

                # check pair exposure constraints
                violates = any((cnt / total_lineups) > max_pair_exposure for cnt in temp_pair_counts.values())
                if violates:
                    continue

                # Accept candidate - build display string
                inf = player_info.get(cand_key, {})
                pid = inf.get("id")
                team = inf.get("team", "")
                display = inf.get("display", cand_key)
                if pid:
                    new_cell = f"{display}({pid})"
                else:
                    new_cell = f"{display} ({team})" if team else display

                # apply replacement
                df.at[li, s] = new_cell

                # update exposures
                exposure[original] = max(0, exposure.get(original, 0) - 1)
                exposure[cand_key] = exposure.get(cand_key, 0) + 1

                # update pair_exposure: remove old pairs, add new pairs
                for p in old_pairs_in_line:
                    pair_exposure[p] = max(0, pair_exposure.get(p, 0) - 1)
                for p in new_pairs:
                    pair_exposure[p] = pair_exposure.get(p, 0) + 1

                # update current_names and totals for this lineup
                current_names = [name_key_from_cell(df.at[li, c]) for c in slot_cols if isinstance(df.at[li, c], str) and df.at[li, c].strip()]
                new_salary = sum(player_info.get(n, {}).get("salary", 0) for n in current_names)
                new_points = sum(player_info.get(n, {}).get("fppg", 0) for n in current_names)
                df.at[li, "TotalSalary"] = new_salary
                df.at[li, "ProjectedPoints"] = new_points

                accepted = True
                break

            # end candidate loop
            # continue to next slot
    # final pass: ensure all totals up-to-date and fill zeros if invalid
    for i in range(len(df)):
        current_names = [name_key_from_cell(df.at[i, c]) for c in slot_cols if isinstance(df.at[i, c], str) and df.at[i, c].strip()]
        total_salary = sum(player_info.get(n, {}).get("salary", 0) for n in current_names)
        total_points = sum(player_info.get(n, {}).get("fppg", 0) for n in current_names)
        df.at[i, "TotalSalary"] = total_salary
        df.at[i, "ProjectedPoints"] = total_points

    return df

# -------------------------
# UI / App
# -------------------------
st.title("The Betting Block DFS Optimizer — integrated (generate + diversify)")

uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if not uploaded_file:
    st.info("Upload a salary CSV (e.g. DKSalaries.csv) with columns: Name (or Name (ID)), Position, Team, Salary, FPPG (or ProjectedPoints).")
    st.stop()

try:
    salary_df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read uploaded CSV: {e}")
    st.stop()

st.markdown("**Preview (first 10 rows)**")
st.dataframe(salary_df.head(10))

# detect useful columns
def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm_map = {normalize_name(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_name(cand)
        if n in norm_map:
            return norm_map[n]
    for col in df.columns:
        for cand in candidates:
            if cand and normalize_name(cand) in normalize_name(str(col)):
                return col
    return None

id_col = find_column(salary_df, ["id", "playerid", "player_id", "ID"])
name_col = find_column(salary_df, ["name", "full_name", "player", "player_name", "Name"])
pos_col = find_column(salary_df, ["position", "positions", "pos"])
team_col = find_column(salary_df, ["team", "teamabbr", "team_abbrev", "Team"])
salary_col = find_column(salary_df, ["salary", "salary_usd", "Salary"])
fppg_col = find_column(salary_df, ["fppg", "projectedpoints", "proj", "ProjectedPoints", "FPPG"])

st.markdown("### Detected columns")
st.write({
    "id_col": id_col,
    "name_col": name_col,
    "pos_col": pos_col,
    "team_col": team_col,
    "salary_col": salary_col,
    "fppg_col": fppg_col
})

# Build player_info
player_info = build_player_info_from_salary_df(
    salary_df,
    name_col,
    pos_col,
    team_col,
    salary_col,
    fppg_col,
    id_col
)

# initialize optimizer
site = Site.DRAFTKINGS
sport = Sport.FOOTBALL
optimizer = get_optimizer(site, sport)

# Build Player objects from salary_df and load into optimizer
players = []
skipped = 0
for idx, row in salary_df.iterrows():
    raw_name = str(row.get(name_col) or row.get("Name") or "").strip()
    parsed_name, parsed_id = parse_name_and_id_from_field(raw_name)
    pid = None
    if id_col and not pd.isna(row.get(id_col)):
        pid = str(row.get(id_col)).strip()
    elif parsed_id:
        pid = parsed_id
    else:
        pid = f"r{idx}"

    parts = parsed_name.split(" ", 1)
    first_name = parts[0].strip() if parts else parsed_name
    last_name = parts[1].strip() if len(parts) > 1 else ""

    positions = parse_positions_field(row.get(pos_col)) if pos_col else []
    team = str(row.get(team_col) or "").strip()
    salary = parse_salary(row.get(salary_col)) if salary_col else None
    fppg = safe_float(row.get(fppg_col)) if fppg_col else safe_float(row.get("FPPG") or row.get("Proj") or 0)

    if salary is None:
        skipped += 1
        continue

    try:
        p = Player(pid, first_name, last_name, positions or None, team or None, salary, fppg or 0.0)
        players.append(p)
    except Exception:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped}) into optimizer.")
optimizer.player_pool.load_players(players)

# UI options
num_lineups = st.slider("Number of lineups", 1, 150, 10)
max_exposure = st.slider("Max player exposure (global)", 0.0, 1.0, 0.4, 0.05)
salary_min_buffer = st.number_input("Min lineup salary (buffer)", min_value=0, max_value=50000, value=49500, step=100)
salary_cap = st.number_input("Max lineup salary (cap)", min_value=0, max_value=100000, value=50000, step=100)

# generate
if st.button("Generate lineups"):
    with st.spinner("Generating lineups..."):
        try:
            lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure))
        except Exception as e:
            st.error(f"Could not generate lineups: {e}")
            st.stop()

    # convert lineups to wide rows
    wide_rows = []
    slot_order = ["QB", "RB1", "RB2", "WR1", "WR2", "WR3", "TE", "FLEX", "DST"]
    for lineup in lineups:
        l_players = getattr(lineup, "players", None) or getattr(lineup, "_players", None) or list(lineup)
        slot_map = {s: "" for s in slot_order}
        assigned = set()

        # first assign QB, TE, DST if present
        for p in l_players:
            positions = [str(x).upper() for x in (getattr(p, "positions", None) or [])] or \
                        ([getattr(p, "position", "").upper()] if getattr(p, "position", None) else [])
            display = player_display_name(p)
            pid = getattr(p, "id", None) or getattr(p, "player_id", None) or getattr(p, "playerId", None) or ""
            cell = f"{display}({pid})" if pid else display

            if "QB" in positions and not slot_map["QB"]:
                slot_map["QB"] = cell
                assigned.add(normalize_name(display))
            elif "DST" in positions and not slot_map["DST"]:
                slot_map["DST"] = cell
                assigned.add(normalize_name(display))
            elif "TE" in positions and not slot_map["TE"]:
                slot_map["TE"] = cell
                assigned.add(normalize_name(display))

        # RB/WR assignment
        for p in l_players:
            positions = [str(x).upper() for x in (getattr(p, "positions", None) or [])] or \
                        ([getattr(p, "position", "").upper()] if getattr(p, "position", None) else [])
            display = player_display_name(p)
            pid = getattr(p, "id", None) or getattr(p, "player_id", None) or getattr(p, "playerId", None) or ""
            cell = f"{display}({pid})" if pid else display
            key = normalize_name(display)
            if key in assigned:
                continue
            if "RB" in positions:
                if not slot_map["RB1"]:
                    slot_map["RB1"] = cell
                    assigned.add(key)
                    continue
                elif not slot_map["RB2"]:
                    slot_map["RB2"] = cell
                    assigned.add(key)
                    continue
            if "WR" in positions:
                if not slot_map["WR1"]:
                    slot_map["WR1"] = cell
                    assigned.add(key)
                    continue
                elif not slot_map["WR2"]:
                    slot_map["WR2"] = cell
                    assigned.add(key)
                    continue
                elif not slot_map["WR3"]:
                    slot_map["WR3"] = cell
                    assigned.add(key)
                    continue

        # fill remaining slots incl FLEX with remaining players
        for p in l_players:
            display = player_display_name(p)
            pid = getattr(p, "id", None) or getattr(p, "player_id", None) or getattr(p, "playerId", None) or ""
            cell = f"{display}({pid})" if pid else display
            key = normalize_name(display)
            if key in assigned:
                continue
            for s in ["RB1", "RB2", "WR1", "WR2", "WR3", "TE", "FLEX", "DST"]:
                if s in slot_map and not slot_map[s]:
                    slot_map[s] = cell
                    assigned.add(key)
                    break

        # compute totals using player_info lookup (robust)
        assigned_names = [name_key_from_cell(slot_map[s]) for s in slot_order if slot_map[s]]
        total_salary = sum(player_info.get(n, {}).get("salary", 0) for n in assigned_names)
        total_points = sum(player_info.get(n, {}).get("fppg", 0) for n in assigned_names)

        row = {s: slot_map[s] for s in slot_order}
        row["TotalSalary"] = total_salary
        row["ProjectedPoints"] = total_points
        wide_rows.append(row)

    df_wide = pd.DataFrame(wide_rows, columns=slot_order + ["TotalSalary", "ProjectedPoints"])

    # save for diversification step
    st.session_state["df_wide_original"] = df_wide
    st.session_state["player_info"] = player_info
    st.session_state["slot_order"] = slot_order

    st.markdown("### Lineups (wide)")
    st.dataframe(df_wide)

    csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
    st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")

# Diversify UI
if "df_wide_original" in st.session_state:
    st.markdown("---")
    st.header("Diversify generated lineups")

    max_exposure_ui = st.slider("Max player exposure (during diversify)", 0.05, 1.0, 0.4, 0.05, key="div_max_exp")
    max_pair_exposure_ui = st.slider("Max pair exposure (during diversify)", 0.05, 1.0, 0.6, 0.05, key="div_max_pair")
    randomness_ui = st.slider("Diversify randomness (probability to attempt replacements)", 0.0, 1.0, 0.15, 0.05, key="div_random")
    salary_min_ui = st.number_input("Minimum lineup salary allowed (diversify)", min_value=0, max_value=50000, value=salary_min_buffer, step=100, key="div_sal_min")
    salary_cap_ui = st.number_input("Maximum lineup salary allowed (diversify)", min_value=0, max_value=100000, value=salary_cap, step=100, key="div_sal_max")

    if st.button("Diversify Lineups"):
        df_wide = st.session_state["df_wide_original"].copy()
        info = st.session_state["player_info"]
        slot_order = st.session_state["slot_order"]

        diversified = diversify_lineups_wide(
            df_wide,
            info,
            slot_order,
            max_exposure=max_exposure_ui,
            max_pair_exposure=max_pair_exposure_ui,
            randomness=randomness_ui,
            salary_cap=salary_cap_ui,
            salary_min=salary_min_ui,
        )

        st.session_state["df_wide_diversified"] = diversified
        st.markdown("### Diversified Lineups")
        st.dataframe(diversified)

        csv_bytes = diversified.to_csv(index=False).encode("utf-8")
        st.download_button("Download diversified CSV", csv_bytes, file_name="lineups_diversified.csv", mime="text/csv")
