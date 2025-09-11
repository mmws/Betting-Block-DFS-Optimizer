# app_cm.py
import streamlit as st
import pandas as pd
import re
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player
from typing import List, Optional, Tuple

st.set_page_config(page_title="DFS Captain Mode Optimizer", layout="wide")

# --- Helpers ---
def parse_salary(s) -> Optional[float]:
    if pd.isna(s): return None
    try:
        return float(str(s).replace('$','').replace(',','').strip())
    except:
        return None

def safe_float(x) -> Optional[float]:
    try:
        if pd.isna(x): return None
        return float(x)
    except:
        try: return float(str(x).replace(',', '').strip())
        except: return None

def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    return None

def parse_name_and_id(val: str) -> Tuple[str, Optional[str]]:
    s = str(val).strip()
    m = re.match(r'^(.*?)\s*\((\d+)\)$', s)
    if m:
        return m.group(1).strip(), m.group(2)
    return s, None

def player_display_name(p) -> str:
    return getattr(p, "full_name", f"{getattr(p,'first_name','')} {getattr(p,'last_name','')}").strip()

# --- UI ---
st.title("DFS Captain Mode Optimizer (DraftKings)")
st.write("Upload DraftKings CSV salaries. Captain Mode only (1 CPT + 5 FLEX).")

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded_file:
    st.info("Upload a DraftKings CSV for NFL/NBA Captain Mode.")
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("**Preview:**")
st.dataframe(df.head(10))

# --- Detect columns ---
name_plus_id_col = find_column(df, ["Name + ID","Name+ID","name_plus_id","name_id","nameandid"])
salary_col = find_column(df, ["Salary","salary_usd"])
fppg_col = find_column(df, ["AvgPointsPerGame","fppg","proj","projectedpoints"])

if not all([name_plus_id_col, salary_col]):
    st.error("Cannot find Name + ID or Salary column.")
    st.stop()

# --- Build player pool ---
players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        full_name, player_id = parse_name_and_id(row[name_plus_id_col])
        salary = parse_salary(row[salary_col])
        fppg = safe_float(row[fppg_col]) if fppg_col else 0.0
        if salary is None: 
            skipped += 1
            continue
        players.append(Player(
            player_id or f"r{idx}",
            full_name.split(" ")[0],
            " ".join(full_name.split(" ")[1:]),
            positions=["FLEX"],  # <- All FLEX
            team=None,
            salary=salary,
            fppg=fppg
        ))
    except:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if len(players) < 6:
    st.error("Not enough players for Captain Mode (need at least 6).")
    st.stop()

# --- Optimizer ---
optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
optimizer.player_pool.load_players(players)

num_lineups = st.slider("Number of lineups", 1, 50, 5)
max_repeating_players = st.slider("Max repeating players", 0, len(players), 2)
optimizer.set_max_repeating_players(max_repeating_players)

gen_btn = st.button("Generate lineups")

# --- Generate lineups ---
if gen_btn:
    try:
        with st.spinner("Generating lineups..."):
            lineups = list(optimizer.optimize(n=num_lineups))
        st.success(f"Generated {len(lineups)} lineup(s)")
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
        st.stop()

    # --- Convert to DataFrame ---
    df_rows = []
    for lineup in lineups:
        row = {}
        row["Captain"] = player_display_name(lineup.captain)
        flex_players = [p for p in lineup.players if p != lineup.captain]
        for i, p in enumerate(flex_players, start=1):
            row[f"FLEX{i}"] = player_display_name(p)
        row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
        row["ProjectedPoints"] = sum(safe_float(getattr(p,"fppg",0)) for p in lineup.players)
        df_rows.append(row)

    df_lineups = pd.DataFrame(df_rows)
    st.markdown("### Generated Lineups")
    st.dataframe(df_lineups)

    csv_bytes = df_lineups.to_csv(index=False).encode("utf-8")
    st.download_button("Download lineups CSV", csv_bytes, file_name="lineups_cm.csv", mime="text/csv")
