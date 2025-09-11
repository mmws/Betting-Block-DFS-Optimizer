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

def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (c or "").lower())

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    # substring fallback
    for col in df.columns:
        for cand in candidates:
            if cand and cand.lower().replace(' ', '') in str(col).lower().replace(' ', ''):
                return col
    return None

def parse_name_and_id_from_field(val: str) -> Tuple[str, Optional[str]]:
    s = str(val or "").strip()
    m = re.match(r'^(.*?)\s*\((\d+)\)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    m = re.match(r'^(.*?)\s*[-\|\/]\s*(\d+)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    m = re.match(r'^(.*\D)\s+(\d+)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    return s, None

def parse_salary(x) -> Optional[float]:
    if pd.isna(x): return None
    try:
        t = str(x).replace('$', '').replace(',', '').strip()
        if t == '': return None
        return float(t)
    except:
        return None

def safe_float(x) -> float:
    try:
        if pd.isna(x): return 0.0
        return float(x)
    except:
        try:
            return float(str(x).replace(',', '').strip())
        except:
            return 0.0

def name_key_from_cell(cell: str) -> str:
    """Extract plain name from a cell like 'Joe Burrow(12345)' or 'Joe Burrow (TEAM)'"""
    if not isinstance(cell, str):
        return str(cell)
    # split on "(" and take left part
    return cell.split("(")[0].strip()

def parse_positions_field(s: str) -> List[str]:
    if s is None: return []
    return [p.strip().upper() for p in re.split(r'[\/\|,]', str(s)) if p.strip()]

def player_display_name(p) -> str:
    """
    Return a readable player name for Player-like objects (supports pydfs Player).
    """
    if p is None:
        return ""
    fn = getattr(p, "first_name", None)
    ln = getattr(p, "last_name", None)
    if fn or ln:
        return f"{fn or ''} {ln or ''}".strip()
    full = getattr(p, "full_name", None)
    if full:
        return full
    # some Player objects use 'name' or 'fullName'
    name_alt = getattr(p, "name", None) or getattr(p, "fullName", None)
    if name_alt:
        return str(name_alt)
    # fallback to str
    return str(p)

# -------------------------
# Diversification logic
# -------------------------
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

def build_player_info_from_salary_df(salary_df: pd.DataFrame,
                                     name_col: str, pos_col: str, team_col: str,
                                     salary_col: str, fppg_col: str, id_col: Optional[str]):
    info = {}
    for _, r in salary_df.iterrows():
        raw_name = str(r.get(name_col) or r.get("Name") or "").strip()
        parsed_name, parsed_id = parse_name_and_id_from_field(raw_name)
        pid = None
        if id_col and not pd.isna(r.get(id_col)):
            pid = str(r.get(id_col)).strip()
        elif parsed_id:
            pid = parsed_id

        name_key = parsed_name.strip()
        positions = parse_positions_field(r.get(pos_col)) if pos_col else []
        team = str(r.get(team_col) or "").strip()
        salary = parse_salary(r.get(salary_col)) or 0
        fppg = safe_float(r.get(fppg_col)) if fppg_col else safe_float(r.get("FPPG") or r.get("Proj") or 0)

        info[name_key] = {
            "id": pid,
            "positions": positions,
            "team": team,
            "salary": salary,
            "fppg": fppg,
        }
    return info

def compute_exposures_and_pairs(df_wide: pd.DataFrame):
    total = len(df_wide)
    players = []
    pairs = []
    slot_cols = [c for c in df_wide.columns if c not in ("TotalSalary", "ProjectedPoints")]
    for i in df_wide.index:
        line_players = []
        for col in slot_cols:
            val = df_wide.at[i, col]
            if isinstance(val, str) and val.strip():
                name = name_key_from_cell(val)
                line_players.append(name)
                players.append(name)
        for a in range(len(line_players)):
            for b in range(a+1, len(line_players)):
                pairs.append(tuple(sorted([line_players[a], line_players[b]])))
    return Counter(players), Counter(pairs)

def diversify_lineups_wide(
    df_wide: pd.DataFrame,
    player_info: Dict[str, dict],
    max_exposure: float = 0.4,
    max_pair_exposure: float = 0.6,
    randomness: float = 0.15,
    salary_cap: int = 50000,
    salary_min: int = 49500
):
    diversified = df_wide.copy(deep=True).reset_index(drop=True)
    if diversified.shape[0] == 0:
        return diversified

    slot_cols = [c for c in diversified.columns if c not in ("TotalSalary", "ProjectedPoints")]
    exposure, pair_exposure = compute_exposures_and_pairs(diversified)
    total_lineups = len(diversified)

    # precompute candidates by slot
    candidates_by_slot = {}
    for slot, allowed in SLOT_TO_ALLOWED_POS.items():
        cand = []
        for name, info in player_info.items():
            if any(p in allowed for p in info.get("positions", [])):
                cand.append(name)
        candidates_by_slot[slot] = cand

    for li in range(total_lineups):
        # current lineup names
        current_names = [name_key_from_cell(diversified.at[li, c]) for c in slot_cols if isinstance(diversified.at[li, c], str)]
        for col in slot_cols:
            cell = diversified.at[li, col]
            if not isinstance(cell, str) or not cell.strip():
                continue
            name = name_key_from_cell(cell)
            player_exp = exposure.get(name, 0) / total_lineups if total_lineups > 0 else 0.0
            lineup_pairs = [tuple(sorted((name, other))) for other in current_names if other != name]
            pair_flag = any((pair_exposure.get(p, 0) / total_lineups) > max_pair_exposure for p in lineup_pairs)

            if player_exp <= max_exposure and not pair_flag:
                continue
            if random.random() > randomness:
                continue

            allowed_candidates = candidates_by_slot.get(col, [])
            random.shuffle(allowed_candidates)
            original_name = name
            for candidate in allowed_candidates:
                if candidate == original_name:
                    continue
                if candidate in current_names:
                    continue
                cand_new_exp = (exposure.get(candidate, 0) + 1) / total_lineups
                if cand_new_exp > max_exposure:
                    continue

                sim_players = [n for n in current_names if n != original_name] + [candidate]
                sim_salary = sum(player_info.get(n, {}).get("salary", 0) for n in sim_players)
                sim_points = sum(player_info.get(n, {}).get("fppg", 0) for n in sim_players)
                if not (salary_min <= sim_salary <= salary_cap):
                    continue

                # check new pair exposure
                new_pairs = []
                violates_pair = False
                for a in range(len(sim_players)):
                    for b in range(a+1, len(sim_players)):
                        p = tuple(sorted([sim_players[a], sim_players[b]]))
                        # prospective count: current global count + 1 if this lineup introduces this pair newly
                        current_count = pair_exposure.get(p, 0)
                        # if the original lineup didn't already include this pair, prospective increases by 1
                        if p not in lineup_pairs:
                            prospective = current_count + 1
                        else:
                            prospective = current_count  # replacement may remove/add but conservatively assume current
                        if prospective / total_lineups > max_pair_exposure:
                            violates_pair = True
                            break
                    if violates_pair:
                        break
                if violates_pair:
                    continue

                # Accept candidate
                candidate_id = player_info.get(candidate, {}).get("id")
                team = player_info.get(candidate, {}).get("team", "")
                if candidate_id:
                    new_cell = f"{candidate}({candidate_id})"
                else:
                    new_cell = f"{candidate} ({team})" if team else candidate

                diversified.at[li, col] = new_cell

                # update exposure counters
                exposure[original_name] = max(0, exposure.get(original_name, 0) - 1)
                exposure[candidate] = exposure.get(candidate, 0) + 1

                # update pair exposure: remove old pairs including original_name, add new pairs including candidate
                for other in current_names:
                    if other == original_name:
                        continue
                    old_pair = tuple(sorted([original_name, other]))
                    pair_exposure[old_pair] = max(0, pair_exposure.get(old_pair, 0) - 1)
                    new_pair = tuple(sorted([candidate, other]))
                    pair_exposure[new_pair] = pair_exposure.get(new_pair, 0) + 1

                # recompute current names and totals for this lineup
                current_names = [name_key_from_cell(diversified.at[li, c]) for c in slot_cols if isinstance(diversified.at[li, c], str)]
                new_salary = sum(player_info.get(n, {}).get("salary", 0) for n in current_names)
                new_points = sum(player_info.get(n, {}).get("fppg", 0) for n in current_names)
                diversified.at[li, "TotalSalary"] = new_salary
                diversified.at[li, "ProjectedPoints"] = new_points

                break  # stop searching for this slot

    return diversified

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
id_col = find_column(salary_df, ["id", "playerid", "player_id", "ID"])
name_col = find_column(salary_df, ["name", "full_name", "player", "player_name", "Name"])
pos_col = find_column(salary_df, ["position", "positions", "pos"])
team_col = find_column(salary_df, ["team", "teamabbr", "team_abbrev"])
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

player_info = build_player_info_from_salary_df(
    salary_df,
    name_col or "Name",
    pos_col,
    team_col or "Team",
    salary_col or "Salary",
    fppg_col or "FPPG",
    id_col
)

# get optimizer
site = Site.DRAFTKINGS
sport = Sport.FOOTBALL
optimizer = get_optimizer(site, sport)

# build Player objects and load into optimizer
players = []
skipped = 0
for idx, row in salary_df.iterrows():
    raw_name = str(row.get(name_col) if name_col else row.get("Name", "")).strip()
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
    fppg = safe_float(row.get(fppg_col)) if fppg_col else 0.0

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

        # assign strict slots: QB, DST, TE
        for p in l_players:
            positions = [str(x).upper() for x in (getattr(p, "positions", None) or [])] or ([getattr(p, "position", "").upper()] if getattr(p, "position", None) else [])
            pname = f"{player_display_name(p)}"
            pid = getattr(p, "id", None) or getattr(p, "player_id", None) or getattr(p, "playerId", None) or ""
            pname_with_id = f"{pname}({pid})" if pid else pname

            if "QB" in positions and not slot_map["QB"]:
                slot_map["QB"] = pname_with_id
                assigned.add(pname)
            elif "DST" in positions and not slot_map["DST"]:
                slot_map["DST"] = pname_with_id
                assigned.add(pname)
            elif "TE" in positions and not slot_map["TE"]:
                slot_map["TE"] = pname_with_id
                assigned.add(pname)

        # RB/WR pass
        for p in l_players:
            positions = [str(x).upper() for x in (getattr(p, "positions", None) or [])] or ([getattr(p, "position", "").upper()] if getattr(p, "position", None) else [])
            pname = f"{player_display_name(p)}"
            pid = getattr(p, "id", None) or getattr(p, "player_id", None) or getattr(p, "playerId", None) or ""
            pname_with_id = f"{pname}({pid})" if pid else pname
            if pname in assigned:
                continue
            if "RB" in positions:
                if not slot_map["RB1"]:
                    slot_map["RB1"] = pname_with_id
                    assigned.add(pname)
                    continue
                elif not slot_map["RB2"]:
                    slot_map["RB2"] = pname_with_id
                    assigned.add(pname)
                    continue
            if "WR" in positions:
                if not slot_map["WR1"]:
                    slot_map["WR1"] = pname_with_id
                    assigned.add(pname)
                    continue
                elif not slot_map["WR2"]:
                    slot_map["WR2"] = pname_with_id
                    assigned.add(pname)
                    continue
                elif not slot_map["WR3"]:
                    slot_map["WR3"] = pname_with_id
                    assigned.add(pname)
                    continue

        # final pass to fill remaining slots (including FLEX)
        for p in l_players:
            pname = f"{player_display_name(p)}"
            pid = getattr(p, "id", None) or getattr(p, "player_id", None) or getattr(p, "playerId", None) or ""
            pname_with_id = f"{pname}({pid})" if pid else pname
            if pname in assigned:
                continue
            placed = False
            for s in ["RB1", "RB2", "WR1", "WR2", "WR3", "TE", "FLEX", "DST"]:
                if not slot_map[s]:
                    slot_map[s] = pname_with_id
                    assigned.add(pname)
                    placed = True
                    break
            if not placed:
                pass

        assigned_names = [name_key_from_cell(slot_map[s]) for s in slot_order if slot_map[s]]
        total_salary = sum(player_info.get(n, {}).get("salary", 0) for n in assigned_names)
        total_points = sum(player_info.get(n, {}).get("fppg", 0) for n in assigned_names)

        row = {s: slot_map[s] for s in slot_order}
        row["TotalSalary"] = total_salary
        row["ProjectedPoints"] = total_points
        wide_rows.append(row)

    df_wide = pd.DataFrame(wide_rows, columns=slot_order + ["TotalSalary", "ProjectedPoints"])

    # store for diversify button
    st.session_state["df_wide_original"] = df_wide
    st.session_state["player_info"] = player_info

    st.markdown("### Lineups (wide)")
    st.dataframe(df_wide)

    csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
    st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")

# Diversify UI
if "df_wide_original" in st.session_state:
    st.markdown("---")
    st.header("Diversify generated lineups")

    max_exposure_ui = st.slider("Max player exposure (during diversify)", 0.05, 1.0, 0.4, 0.05)
    max_pair_exposure_ui = st.slider("Max pair exposure (during diversify)", 0.05, 1.0, 0.6, 0.05)
    randomness_ui = st.slider("Diversify randomness (probability to attempt replacements)", 0.0, 1.0, 0.15, 0.05)
    salary_min_ui = st.number_input("Minimum lineup salary allowed (diversify)", min_value=0, max_value=50000, value=salary_min_buffer, step=100)
    salary_cap_ui = st.number_input("Maximum lineup salary allowed (diversify)", min_value=0, max_value=100000, value=salary_cap, step=100)

    if st.button("Diversify Lineups"):
        df_wide = st.session_state["df_wide_original"].copy()
        info = st.session_state["player_info"]
        diversified = diversify_lineups_wide(
            df_wide,
            info,
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
