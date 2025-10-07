# nfl_captain_mode.py
import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player
from pydfs_lineup_optimizer.exceptions import OptimizationError

st.set_page_config(page_title="NFL Captain Mode Optimizer", layout="wide")
st.title("NFL Captain Mode DFS Optimizer")

# --- Upload CSV ---
st.write("Upload a DraftKings NFL Captain Mode CSV (salary file).")
uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded_file:
    st.info("Please upload a CSV file to continue.")
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("**Preview (first 10 rows):**")
st.dataframe(df.head(10))

# --- Detect columns ---
def find_column(df, candidates):
    for c in df.columns:
        if c.lower() in [x.lower() for x in candidates]:
            return c
    return None

id_col = find_column(df, ["id","playerid","player_id","ID"])
name_col = find_column(df, ["name","full_name","player"])
pos_col = find_column(df, ["position","positions","pos"])
team_col = find_column(df, ["team","teamabbr","team_abbrev"])
salary_col = find_column(df, ["salary","salary_usd"])
fppg_col = find_column(df, ["avgpointspergame","fppg","projectedpoints","proj"])

# --- Build players ---
players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        player_id = str(row[id_col]) if id_col else f"r{idx}"
        name = str(row[name_col]) if name_col else f"Player{idx}"
        positions = [row[pos_col]] if pos_col else ["FLEX"]
        team = row[team_col] if team_col else None
        salary = float(row[salary_col]) if salary_col else None
        fppg = float(row[fppg_col]) if fppg_col else 0.0
        if salary is None:
            skipped += 1
            continue
        players.append(Player(player_id, name, "", positions, team, salary, fppg))
    except:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if len(players) == 0:
    st.error("No valid players!")
    st.stop()

# --- Initialize Captain Mode Optimizer ---
optimizer = get_optimizer(Site.DRAFTKINGS_CAPTAIN_MODE, Sport.FOOTBALL)
optimizer.player_pool.load_players(players)

# --- Lineup settings ---
num_lineups = st.slider("Number of lineups", 1, 50, 5)
max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
max_repeating_players = st.slider("Max repeating players", 0, 6, 2)
optimizer.set_max_repeating_players(max_repeating_players)

min_salary_options = list(range(int(min(p.salary for p in players)), int(max(p.salary for p in players))+1, 100))
min_salary = st.selectbox("Minimum lineup salary", min_salary_options, index=len(min_salary_options)-1)
optimizer.set_min_salary_cap(min_salary)

gen_btn = st.button("Generate Lineups")

if gen_btn:
    st.write("Generating lineups...")
    try:
        with st.spinner("Optimizing..."):
            lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure))
        st.success(f"Generated {len(lineups)} lineup(s)!")
    except OptimizationError as e:
        st.error(f"Could not generate lineups: {e}")
        lineups = []

    # --- Display lineups ---
    if lineups:
        df_rows = []
        for lineup in lineups:
            row = {}
            for idx, p in enumerate(lineup.players):
                col = "Captain" if p.is_captain else f"Flex{idx}" if idx>0 else "Flex1"
                row[col] = f"{p.first_name} ({p.id})"
            row["TotalSalary"] = sum(p.salary for p in lineup.players)
            row["ProjectedPoints"] = sum(p.fppg for p in lineup.players)
            df_rows.append(row)

        df_wide = pd.DataFrame(df_rows)
        st.markdown("### Generated Lineups")
        st.dataframe(df_wide)

        csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
        st.download_button("Download Lineups CSV", csv_bytes, file_name="captain_mode_lineups.csv", mime="text/csv")
