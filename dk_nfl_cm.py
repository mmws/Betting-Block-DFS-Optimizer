# app_captain_mode.py
import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player
from pydfs_lineup_optimizer.exceptions import LineupOptimizerException

st.set_page_config(page_title="DFS Captain Mode Optimizer", layout="wide")
st.title("DFS Captain Mode Optimizer (DraftKings)")

uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if not uploaded_file:
    st.stop()

# --- Read CSV ---
try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("### Preview")
st.dataframe(df.head(10))

# --- User settings ---
num_lineups = st.slider("Number of lineups", 1, 50, 5)
min_salary_cap = st.number_input("Minimum salary cap", value=49200)
max_repeating_players = st.slider("Max repeating players", 0, 10, 3)

# --- Column detection ---
def normalize_colname(c: str):
    return ''.join(filter(str.isalnum, str(c).lower()))

def find_column(df: pd.DataFrame, candidates):
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    return None

name_col = find_column(df, ["Name","Player"])
id_col = find_column(df, ["ID","PlayerID"])
salary_col = find_column(df, ["Salary"])
team_col = find_column(df, ["TeamAbbrev","Team"])
fppg_col = find_column(df, ["AvgPointsPerGame","FPPG"])
pos_col = find_column(df, ["Roster Position","Position"])

# --- Build players ---
players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        full_name = str(row.get("Name", f"Player{idx}"))
        first, last = full_name.split(" ", 1) if " " in full_name else (full_name, "")
        player_id = str(row.get(id_col, f"p{idx}"))
        salary = float(row[salary_col])
        fppg = float(row[fppg_col]) if fppg_col else 0.0
        team = str(row[team_col]) if team_col else None

        raw_pos = str(row[pos_col]).strip().upper() if pos_col else "FLEX"
        positions = ["CPT"] if raw_pos == "CPT" else ["FLEX"]

        players.append(Player(player_id, first, last, positions, team, salary, fppg))
    except:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if len(players) == 0:
    st.error("No valid players!")
    st.stop()

# --- Initialize optimizer ---
optimizer = get_optimizer(Site.DRAFTKINGS_CAPTAIN_MODE, Sport.FOOTBALL)
optimizer.player_pool.load_players(players)
optimizer.set_min_salary_cap(min_salary_cap)
optimizer.set_max_repeating_players(max_repeating_players)

# --- Generate lineups ---
gen_btn = st.button("Generate Lineups")
if gen_btn:
    try:
        with st.spinner("Generating lineups..."):
            lineups = list(optimizer.optimize(n=num_lineups))
        st.success(f"Generated {len(lineups)} lineup(s)")

        # Convert to DataFrame
        lineup_rows = []
        for lineup in lineups:
            row = {}
            row["Captain"] = getattr(lineup.captain, "full_name", str(lineup.captain))
            for idx, p in enumerate(lineup.players):
                col = f"FLEX{idx+1}" if getattr(p, "positions", ["FLEX"])[0] == "FLEX" else "Captain"
                row[col] = f"{p.full_name}({getattr(p,'id','')})"
            row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
            row["ProjectedPoints"] = sum(getattr(p,"fppg",0) for p in lineup.players)
            lineup_rows.append(row)

        df_lineups = pd.DataFrame(lineup_rows)
        st.markdown("### Generated Lineups")
        st.dataframe(df_lineups)

        csv_bytes = df_lineups.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv_bytes, file_name="captain_mode_lineups.csv", mime="text/csv")

    except LineupOptimizerException as e:
        st.error(f"Can't generate lineups: {e}")
