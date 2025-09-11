# dk_nfl_captain_mode.py
import streamlit as st
import pandas as pd
import re
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

st.set_page_config(page_title="DraftKings Captain Mode Optimizer", layout="wide")
st.title("DFS Captain Mode Optimizer (DraftKings)")

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

# --- Helpers ---
def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates):
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map: return norm_map[n]
    return None

# --- Detect columns ---
name_col = find_column(df, ["name","player"])
salary_col = find_column(df, ["salary","salary_usd"])
pos_col = find_column(df, ["position","positions","pos"])
team_col = find_column(df, ["team","teamabbrev","team_abbrev"])
fppg_col = find_column(df, ["fppg","projectedpoints","avgpointspergame"])

# --- Load players ---
players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        player_id = f"p{idx}"
        name = str(row[name_col])
        first_name, last_name = (name.split(" ", 1) + [""])[:2]
        positions = [str(row[pos_col]).strip()] if pos_col else ["FLEX"]  # ignore CPT/FLEX
        team = str(row[team_col]) if team_col else None
        salary = float(row[salary_col])
        fppg = float(row[fppg_col]) if fppg_col else 0.0
        players.append(Player(player_id, first_name, last_name, positions, team, salary, fppg))
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

# --- Lineup settings ---
num_lineups = st.slider("Number of lineups", 1, 50, 5)
max_repeating_players = st.slider("Max repeating players across lineups", 0, 10, 3)
optimizer.set_max_repeating_players(max_repeating_players)

gen_btn = st.button("Generate Lineups")

# --- Generate lineups ---
if gen_btn:
    try:
        with st.spinner("Generating lineups..."):
            lineups = list(optimizer.optimize(n=num_lineups))

        st.success(f"Generated {len(lineups)} lineup(s)")

        # --- Format output ---
        df_lineups = []
        for lineup in lineups:
            row = {}
            # Captain
            row["Captain"] = getattr(lineup.captain, "full_name", str(lineup.captain))
            # FLEX (all other players)
            for idx, p in enumerate(lineup.players):
                col = f"FLEX{idx+1}"
                row[col] = f"{getattr(p,'full_name', str(p))}({getattr(p,'id','')})"
            row["TotalSalary"] = sum([getattr(p,"salary",0) for p in lineup.players])
            row["ProjectedPoints"] = sum([getattr(p,"fppg",0) for p in lineup.players])
            df_lineups.append(row)

        df_lineups = pd.DataFrame(df_lineups)
        st.markdown("### Generated Lineups")
        st.dataframe(df_lineups)

        csv_bytes = df_lineups.to_csv(index=False).encode("utf-8")
        st.download_button("Download Lineups CSV", csv_bytes, file_name="captain_mode_lineups.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Error generating lineups: {e}")
