# nfl_captain_mode.py
import streamlit as st
import pandas as pd
import re
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

st.set_page_config(page_title="NFL Captain Mode DFS Optimizer", layout="wide")

st.title("NFL Captain Mode DFS Optimizer")
st.write("Upload a DraftKings NFL CSV. Captain Mode: 1 Captain + 5 Flex players.")

# --- Upload CSV ---
uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if not uploaded_file:
    st.info("Upload a CSV (e.g. DraftKings NFL CSV).")
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("**Preview (first 10 rows):**")
st.dataframe(df.head(10))

# --- detect columns ---
def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates):
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    return None

name_col = find_column(df, ["name","full_name","player"])
id_col = find_column(df, ["id","playerid","player_id","ID"])
pos_col = find_column(df, ["position","pos","roster position"])
team_col = find_column(df, ["team","teamabbrev","team_abbrev"])
salary_col = find_column(df, ["salary"])
fppg_col = find_column(df, ["avgpointspergame","fppg","projectedpoints"])

# --- build players ---
players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        player_id = str(row[id_col]).strip() if id_col and not pd.isna(row[id_col]) else f"r{idx}"
        name = str(row[name_col]).strip() if name_col else f"Player{idx}"
        pos = [str(row[pos_col]).strip()] if pos_col and not pd.isna(row[pos_col]) else None
        team = str(row[team_col]).strip() if team_col else None
        salary = float(row[salary_col]) if salary_col and not pd.isna(row[salary_col]) else None
        fppg = float(row[fppg_col]) if fppg_col and not pd.isna(row[fppg_col]) else 0.0

        if salary is None:
            skipped += 1
            continue

        players.append(Player(player_id, name, "", pos, team, salary, fppg))
    except:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if len(players) == 0:
    st.error("No valid players!"); st.stop()

optimizer = get_optimizer("DraftKings", Sport.FOOTBALL)
optimizer.player_pool.load_players(players)

# --- lineup settings ---
num_lineups = st.slider("Number of lineups", 1, 200, 5)
max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
max_repeating_players = st.slider("Max repeating players", 0, 6, 2)
optimizer.set_max_repeating_players(max_repeating_players)

# --- generate lineups ---
gen_btn = st.button("Generate")
if gen_btn:
    st.write("Generating lineups...")
    try:
        with st.spinner("Generating..."):
            lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure, lineup_positions={
                "CPT": 1,  # Captain
                "FLEX": 5  # 5 Flex
            }))
        st.success(f"Generated {len(lineups)} lineup(s)")
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
        lineups = []

    # --- display lineups ---
    if lineups:
        df_rows = []
        for lineup in lineups:
            row = {}
            for p in lineup.players:
                pos_type = getattr(p, "lineup_position", "FLEX")
                row[pos_type] = f"{p.full_name}({p.id})"
            row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
            row["ProjectedPoints"] = sum(getattr(p,"fppg",0) for p in lineup.players)
            df_rows.append(row)

        df_wide = pd.DataFrame(df_rows)
        st.markdown("### Lineups")
        st.dataframe(df_wide)

        csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
        st.download_button("Download lineups CSV", csv_bytes, file_name="captain_mode_lineups.csv", mime="text/csv")
