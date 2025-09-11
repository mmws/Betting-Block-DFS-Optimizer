# app_captain.py
import streamlit as st
import pandas as pd
import re
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, AfterEachExposureStrategy

st.set_page_config(page_title="DFS CAPTAIN Mode Optimizer", layout="wide")
st.title("DFS CAPTAIN Mode Optimizer (DraftKings)")

# --- Upload CSV ---
uploaded_file = st.file_uploader("Upload DraftKings salary CSV", type=["csv"])
if not uploaded_file:
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("### Preview")
st.dataframe(df.head(10))

# --- User selections ---
num_lineups = st.slider("Number of lineups", 1, 50, 5)
max_repeating_players = st.slider("Max repeating players across lineups", 0, 10, 3)
min_salary_cap = st.number_input("Minimum salary cap", value=49200)

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

def player_display_name(p):
    if hasattr(p, "full_name") and p.full_name:
        return p.full_name
    fn = getattr(p, "first_name", "")
    ln = getattr(p, "last_name", "")
    if fn or ln:
        return f"{fn} {ln}".strip()
    return str(p)

# --- Detect columns ---
name_col = find_column(df, ["name","player","full_name"])
id_col = find_column(df, ["id","playerid","player_id"])
pos_col = find_column(df, ["position","rosterposition","pos"])
salary_col = find_column(df, ["salary","salary_usd"])
team_col = find_column(df, ["team","teamabbrev"])
fppg_col = find_column(df, ["fppg","avgpointspergame","projectedpoints","proj"])

# --- Initialize optimizer ---
optimizer = get_optimizer(Site.DRAFTKINGS_CAPTAIN_MODE, Sport.FOOTBALL)

players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        player_id = str(row[id_col]) if id_col else f"p{idx}"
        name = str(row[name_col]) if name_col else f"Player{idx}"
        first_name, last_name = (name.split(" ", 1) + [""])[:2]
        positions = [str(row[pos_col]).strip()] if pos_col else ["FLEX"]
        team = str(row[team_col]) if team_col else None
        salary = float(row[salary_col]) if salary_col else 0
        fppg = float(row[fppg_col]) if fppg_col else 0.0
        players.append(Player(player_id, first_name, last_name, positions, team, salary, fppg))
    except:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if len(players) == 0:
    st.error("No valid players!")
    st.stop()

optimizer.player_pool.load_players(players)
optimizer.set_max_repeating_players(max_repeating_players)
optimizer.set_min_salary_cap(min_salary_cap)

# --- Generate lineups ---
st.info("Click to generate lineups")
gen_btn = st.button("Generate Lineups")

if gen_btn:
    lineups_list = []
    with st.spinner("Generating..."):
        try:
            lineups = list(optimizer.optimize(n=num_lineups, exposure_strategy=AfterEachExposureStrategy))
            st.success(f"Generated {len(lineups)} lineup(s)")
        except Exception as e:
            st.error(f"Error generating lineups: {e}")
            lineups = []

        for lineup in lineups:
            row = {}
            # Captain
            row["Captain"] = player_display_name(lineup.captain)
            # FLEX players
            flex_idx = 1
            for p in lineup.players:
                if getattr(p, "positions", ["FLEX"])[0] != "CPT":
                    row[f"FLEX{flex_idx}"] = f"{player_display_name(p)}({getattr(p,'id','')})"
                    flex_idx += 1
            row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
            row["ProjectedPoints"] = sum(getattr(p,"fppg",0) for p in lineup.players)
            lineups_list.append(row)

    if lineups_list:
        df_lineups = pd.DataFrame(lineups_list)
        st.markdown("### Generated Lineups")
        st.dataframe(df_lineups)

        csv_bytes = df_lineups.to_csv(index=False).encode("utf-8")
        st.download_button("Download Lineups CSV", csv_bytes, file_name="captain_mode_lineups.csv", mime="text/csv")
