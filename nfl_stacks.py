# app.py
import streamlit as st
import pandas as pd
import re
from collections import Counter
from typing import Optional, Tuple, List

from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player
from pydfs_lineup_optimizer.stacks import GameStack, TeamStack, PositionsStack


st.set_page_config(page_title="The Betting Block DFS Optimizer", layout="wide")

# --- Config / mappings ---
SITE_MAP = {
    "DraftKings NFL": (Site.DRAFTKINGS, Sport.FOOTBALL),
    "FanDuel NFL": (Site.FANDUEL, Sport.FOOTBALL),
    "DraftKings NBA": (Site.DRAFTKINGS, Sport.BASKETBALL),
    "FanDuel NBA": (Site.FANDUEL, Sport.BASKETBALL),
}

NFL_POSITION_HINTS = {"QB", "RB", "WR", "TE", "K", "DST"}
NBA_POSITION_HINTS = {"PG", "SG", "SF", "PF", "C", "G", "F"}

# --- helpers ---
def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    for col in df.columns:
        for cand in candidates:
            if cand.lower().replace(' ', '') in col.lower().replace(' ', ''):
                return col
    return None

def guess_site_from_filename(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = name.lower()
    if "draftkings" in n or re.search(r'\bdk\b', n):
        return "DraftKings"
    if "fanduel" in n or re.search(r'\bfd\b', n):
        return "FanDuel"
    return None

def guess_sport_from_positions(series: pd.Series) -> Optional[str]:
    if series is None:
        return None
    try:
        all_pos = (
            series.dropna()
                  .astype(str)
                  .str.replace(' ', '')
                  .str.upper()
                  .str.split('/|,')
                  .explode()
                  .unique()
        )
        posset = set([str(p).strip() for p in all_pos if p])
        if posset & NFL_POSITION_HINTS:
            return "NFL"
        if posset & NBA_POSITION_HINTS:
            return "NBA"
    except Exception:
        pass
    return None

def parse_name_and_id_from_field(val: str) -> Tuple[str, Optional[str]]:
    s = str(val).strip()
    m = re.match(r'^(.*?)\s*\((\d+)\)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    m = re.match(r'^(.*?)\s*[-\|\/]\s*(\d+)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    m = re.match(r'^(.*\D)\s+(\d+)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    return s, None

def parse_salary(s) -> Optional[float]:
    if pd.isna(s): return None
    try:
        t = str(s).replace('$','').replace(',','').strip()
        if t == '': return None
        return float(t)
    except: return None

def safe_float(x) -> Optional[float]:
    try:
        if pd.isna(x): return None
        return float(x)
    except:
        try: return float(str(x).replace(',', '').strip())
        except: return None

def player_display_name(p) -> str:
    fn = getattr(p, "first_name", None)
    ln = getattr(p, "last_name", None)
    if fn or ln: return f"{fn or ''} {ln or ''}".strip()
    full = getattr(p, "full_name", None)
    if full: return full
    return str(p)

# --- UI ---
st.title("The Betting Block DFS Optimizer")
st.write("Upload a salary CSV exported from DraftKings or FanDuel (NFL/NBA).")

uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if not uploaded_file:
    st.info("Upload a CSV (e.g. `DKSalaries.csv`). The app will try to auto-detect site & sport.")
    st.info("Upload a CSV (e.g. DKSalaries.csv). The app will try to auto-detect site & sport.")
    st.stop()

try:
@@ -258,111 +258,52 @@



       if gen_btn:
    st.write("Generating lineups...")

    # --- define position columns globally ---
    position_columns = {
        "QB": ["QB"],
        "RB": ["RB", "RB1"],
        "WR": ["WR", "WR1", "WR2"],
        "TE": ["TE"],
        "FLEX": ["FLEX"],
        "DST": ["DST"]
    }

    # --- apply stacking and restrictions safely ---
        try:
            # Clear previous stacks to avoid duplicates if user presses generate multiple times
            optimizer.stacks = []
            optimizer.restrictions = []

            if enable_qb_wr:
                try: optimizer.add_stack(PositionsStack(("QB", "WR")))
                except: st.warning("Could not apply QB+WR stack")
            if enable_qb_te:
                try: optimizer.add_stack(PositionsStack(("QB", "TE")))
                except: st.warning("Could not apply QB+TE stack")
            if enable_qb_rb_wr:
                try: optimizer.add_stack(PositionsStack(("QB", "RB", "WR")))
                except: st.warning("Could not apply QB+RB+WR stack")
            if enable_qb_rb_te:
                try: optimizer.add_stack(PositionsStack(("QB", "RB", "TE")))
                except: st.warning("Could not apply QB+RB+TE stack")
            if enable_qb_wr_wr:
                try: optimizer.add_stack(PositionsStack(("QB", "WR", "WR")))
                except: st.warning("Could not apply QB+WR+WR stack")
            if enable_qb_te_wr:
                try: optimizer.add_stack(PositionsStack(("QB", "TE", "WR")))
                except: st.warning("Could not apply QB+TE+WR stack")
            if enable_team_stack:
                try: optimizer.add_stack(TeamStack(3, for_positions=["QB", "WR", "TE"]))
                except: st.warning("Could not apply Team stack")
            if enable_game_stack:
                try: optimizer.add_stack(GameStack(3, min_from_team=1))
                except: st.warning("Could not apply Game stack")
            if no_double_rb:
                try: optimizer.restrict_positions_for_same_team(("RB", "RB"))
                except: st.warning("Could not restrict 2 RBs from same team")

            # Min salary (optional)
            if min_salary:
                try: optimizer.set_min_salary_cap(min_salary)
                except: st.warning("Could not enforce min salary; may be too high for this player pool")

            # Generate lineups
            with st.spinner("Generating..."):
                lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure))
            st.success(f"Generated {len(lineups)} lineup(s)")
        except Exception as e:
            st.error(f"Error generating lineups: {e}")
            lineups = []

        if lineups:
            # --- build wide DataFrame and track exposures ---
            df_rows = []
            all_players = []

            for lineup in lineups:
                row = {}
                pos_counter = {k: 0 for k in position_columns.keys()}

                for p in lineup.players:
                    all_players.append(player_display_name(p))
                    assigned = False
                    for pos in p.positions or []:
                        if pos in position_columns and pos_counter[pos] < len(position_columns[pos]):
                            col = position_columns[pos][pos_counter[pos]]
                            row[col] = f"{player_display_name(p)}({p.id})"
                            pos_counter[pos] += 1
                            assigned = True
                            break
                    if not assigned:
                        if pos_counter["FLEX"] < 1:
                            row["FLEX"] = f"{player_display_name(p)}({p.id})"
                            pos_counter["FLEX"] += 1

                for col in position_columns.keys():
                    if col not in row:
                        row[col] = ""

                row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
                row["ProjectedPoints"] = sum(safe_float(getattr(p,"fppg",0)) for p in lineup.players)
                df_rows.append(row)

            df_wide = pd.DataFrame(df_rows)
            st.markdown("### Lineups (wide)")
            st.dataframe(df_wide)

            # --- calculate player exposures ---
            from collections import Counter
            exposures = Counter(all_players)
            exposures_df = pd.DataFrame(exposures.items(), columns=["Player","Count"])
            exposures_df["Exposure %"] = exposures_df["Count"] / len(lineups) * 100
            exposures_df = exposures_df.sort_values("Exposure %", ascending=False)
            st.markdown("### Player Exposures")
            st.dataframe(exposures_df)

            # --- CSV download ---
            csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
            st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
        with st.spinner("Generating..."):
            lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure))
        st.success(f"Generated {len(lineups)} lineup(s)")
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
        lineups = []

    if lineups:
        # --- map positions safely ---
        position_columns = {
            "QB": ["QB"],
            "RB": ["RB", "RB1"],
            "WR": ["WR", "WR1", "WR2"],
            "TE": ["TE"],
            "FLEX": ["FLEX"],
            "DST": ["DST"]
        }

        df_rows = []
        for lineup in lineups:
            row = {}
            pos_counter = {k: 0 for k in position_columns.keys()}
            for p in lineup.players:
                assigned = False
                for pos in p.positions or []:
                    if pos in position_columns and pos_counter[pos] < len(position_columns[pos]):
                        col = position_columns[pos][pos_counter[pos]]
                        row[col] = f"{player_display_name(p)}({p.id})"
                        pos_counter[pos] += 1
                        assigned = True
                        break
                if not assigned:
                    if pos_counter["FLEX"] < 1:
                        row["FLEX"] = f"{player_display_name(p)}({p.id})"
                        pos_counter["FLEX"] += 1

            for col in ["QB","RB","RB1","WR","WR1","WR2","TE","FLEX","DST"]:
                if col not in row: row[col] = ""

            row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
            row["ProjectedPoints"] = sum(safe_float(getattr(p,"fppg",0)) for p in lineup.players)
            df_rows.append(row)

        df_wide = pd.DataFrame(df_rows)
        st.markdown("### Lineups (wide)")
        st.dataframe(df_wide)

        csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
        st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
