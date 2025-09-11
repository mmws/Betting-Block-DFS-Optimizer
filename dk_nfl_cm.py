# app_captain_mode.py
import streamlit as st
import pandas as pd
import re
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, AfterEachExposureStrategy

st.set_page_config(page_title="DFS Captain Mode Optimizer", layout="wide")
st.title("DFS Captain Mode Optimizer (DraftKings)")

# --- Upload CSV ---
uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if not uploaded_file:
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("### Preview")
st.dataframe(df.head(10))

# --- Helpers ---
def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates):
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map: 
            return norm_map[n]
    return None

# --- Detect columns ---
name_col = find_column(df, ["name","player"])
salary_col = find_column(df, ["salary"])
pos_col = find_column(df, ["position","positions","pos","rosterposition"])
team_col = find_column(df, ["team","teamabbrev","team_abbrev"])
fppg_col = find_column(df, ["fppg","avgpointspergame","projectedpoints"])

# --- User inputs ---
num_lineups = st.slider("Number of lineups", 1, 50, 5)
max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
max_repeating_players = st.slider("Max repeating players across lineups", 0, 10, 3)
min_salary_cap = st.number_input("Minimum salary cap", value=49200)

# --- Build players ---
players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        name = str(row[name_col])
        salary = float(row[salary_col])
        positions = [p.strip() for p in str(row[pos_col]).split('/')] if pos_col else None
        team = str(row[team_col]) if team_col else None
        fppg = float(row[fppg_col]) if fppg_col else 0.0
        players.append(Player(f"p{idx}", *name.split(" ",1), positions, team, salary, fppg))
    except:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if not players:
    st.error("No valid players to optimize!")
    st.stop()

# --- Initialize optimizer ---
optimizer = get_optimizer(Site.DRAFTKINGS_CAPTAIN_MODE, Sport.FOOTBALL)
optimizer.player_pool.load_players(players)
optimizer.set_max_repeating_players(max_repeating_players)
optimizer.set_min_salary_cap(min_salary_cap)

# --- Generate lineups ---
st.info("Click to generate lineups")
gen_btn = st.button("Generate Lineups")

if gen_btn:
    lineups_list = []
    with st.spinner("Generating lineups..."):
        try:
            for lineup in optimizer.optimize(n=num_lineups, exposure_strategy=AfterEachExposureStrategy, max_exposure=max_exposure):
                row = {}
                # Captain
                row["Captain"] = getattr(lineup.captain, "full_name", str(lineup.captain))
                # FLEX positions
                for i, p in enumerate(lineup.players):
                    if p != lineup.captain:
                        row[f"FLEX{i+1}"] = getattr(p, "full_name", str(p))
                row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
                row["ProjectedPoints"] = sum(getattr(p,"fppg",0) for p in lineup.players)
                lineups_list.append(row)
        except Exception as e:
            st.error(f"Error generating lineups: {e}")

    if lineups_list:
        df_lineups = pd.DataFrame(lineups_list)
        st.markdown("### Generated Lineups")
        st.dataframe(df_lineups)

        csv_bytes = df_lineups.to_csv(index=False).encode("utf-8")
        st.download_button("Download Lineups CSV", csv_bytes, file_name="captain_mode_lineups.csv", mime="text/csv")
