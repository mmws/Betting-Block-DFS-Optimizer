# app_captain.py
import streamlit as st
import pandas as pd
import re
from pydfs_lineup_optimizer import (
    get_optimizer, Site, Sport, Player, AfterEachExposureStrategy
)
from pydfs_lineup_optimizer.stacks import PositionsStack

# --- Streamlit config ---
st.set_page_config(page_title="DFS CAPTAIN Mode Optimizer", layout="wide")
st.title("DFS CAPTAIN Mode Optimizer (DraftKings)")

# --- File upload ---
uploaded_file = st.file_uploader("Upload DraftKings Salary CSV", type=["csv"])
if not uploaded_file:
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("### Salary CSV Preview")
st.dataframe(df.head(10))

# --- User inputs ---
num_lineups = st.slider("Number of lineups", 1, 50, 5)
max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
max_repeating_players = st.slider("Max repeating players across lineups", 0, 10, 3)
stack_qb_wr_te = st.checkbox("Stack QB + WR/TE?", value=True)
min_salary_cap = st.number_input("Minimum salary cap", value=49000)

# --- Column detection helpers ---
def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates):
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    return None

name_col = find_column(df, ["name", "player"])
salary_col = find_column(df, ["salary", "salary_usd"])
pos_col = find_column(df, ["position", "positions", "pos"])
team_col = find_column(df, ["team", "teamabbrev", "team_abbrev"])
fppg_col = find_column(df, ["fppg", "projectedpoints", "avgpointspergame"])

# --- Initialize optimizer ---
optimizer = get_optimizer(Site.DRAFTKINGS_CAPTAIN_MODE, Sport.FOOTBALL)

players = []
for idx, row in df.iterrows():
    try:
        name = str(row[name_col])
        salary = float(row[salary_col])
        pos = [p.strip() for p in str(row[pos_col]).split('/')] if pos_col else None
        team = str(row[team_col]) if team_col else None
        fppg = float(row[fppg_col]) if fppg_col else 0.0
        players.append(Player(f"p{idx}", *name.split(" ", 1), pos, team, salary, fppg))
    except Exception:
        continue

optimizer.player_pool.load_players(players)

# --- Apply constraints ---
optimizer.set_max_repeating_players(max_repeating_players)
optimizer.set_min_salary_cap(min_salary_cap)
optimizer.set_max_exposure(max_exposure)

if stack_qb_wr_te:
    optimizer.add_stack(PositionsStack(["QB", "WR"]))
    optimizer.add_stack(PositionsStack(["QB", "TE"]))

# --- Generate lineups ---
if st.button("Generate Lineups"):
    lineups_list = []
    with st.spinner("Generating..."):
        for lineup in optimizer.optimize(n=num_lineups, exposure_strategy=AfterEachExposureStrategy):
            row = {}
            # captain
            row["Captain"] = getattr(lineup.captain, "full_name", str(lineup.captain))
            # flex players
            for idx, p in enumerate(lineup.players):
                col = f"{p.positions[0]}{idx+1}" if p.positions else f"FLEX{idx+1}"
                row[col] = f"{p.full_name}({getattr(p,'id','')})"
            # totals
            row["TotalSalary"] = sum([getattr(p, "salary", 0) for p in lineup.players])
            row["ProjectedPoints"] = sum([getattr(p, "fppg", 0) for p in lineup.players])
            lineups_list.append(row)

    df_lineups = pd.DataFrame(lineups_list)
    st.markdown("### Generated Lineups")
    st.dataframe(df_lineups)

    csv_bytes = df_lineups.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Lineups CSV",
        csv_bytes,
        file_name="captain_mode_lineups.csv",
        mime="text/csv",
    )
