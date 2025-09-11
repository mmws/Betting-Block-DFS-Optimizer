# app_diverse.py
import streamlit as st
import pandas as pd
import re
from typing import Optional, Tuple, List
from itertools import combinations, chain
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

st.set_page_config(page_title="DFS Optimizer with Diversification", layout="wide")

# --- Config / mappings ---
SITE_MAP = {
    "DraftKings NFL": (Site.DRAFTKINGS, Sport.FOOTBALL),
    "FanDuel NFL": (Site.FANDUEL, Sport.FOOTBALL),
}

NFL_POSITION_HINTS = {"QB", "RB", "WR", "TE", "K", "DST"}

# --- Helpers ---
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
            if cand.lower().replace(' ','') in col.lower().replace(' ',''):
                return col
    return None

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
st.title("DFS Optimizer with Diversification")
st.write("Upload a DraftKings or FanDuel NFL salary CSV.")

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded_file:
    st.stop()

df = pd.read_csv(uploaded_file)
st.dataframe(df.head(10))

# --- Detect columns ---
name_col = find_column(df, ["name","full_name","player"])
pos_col = find_column(df, ["position","pos"])
salary_col = find_column(df, ["salary"])
fppg_col = find_column(df, ["fppg","proj","projectedpoints"])

# --- Load players ---
players = []
for idx,row in df.iterrows():
    name = str(row[name_col]).strip() if name_col else f"Player{idx}"
    pos = [p.strip() for p in re.split(r'[\/\|,]', str(row[pos_col]))] if pos_col else []
    salary = parse_salary(row[salary_col]) if salary_col else None
    fppg = safe_float(row[fppg_col]) if fppg_col else 0.0
    if salary is None:
        continue
    players.append(Player(f"r{idx}", name.split(" ")[0], " ".join(name.split(" ")[1:]), pos, None, salary, fppg))

st.write(f"Loaded {len(players)} players")
if not players:
    st.error("No valid players")
    st.stop()

# --- Optimizer ---
site, sport = Site.DRAFTKINGS, Sport.FOOTBALL
optimizer = get_optimizer(site, sport)
optimizer.player_pool.load_players(players)

num_lineups = st.slider("Number of lineups",1,50,5)
max_repeating = st.slider("Max repeating players across lineups",1, num_lineups, 2)
gen_btn = st.button("Generate lineups")

if gen_btn:
    st.info("Generating lineups...")
    candidate_lineups = list(optimizer.optimize(n=num_lineups*5))  # generate extra to diversify
    
    # --- Apply max repeating players constraint ---
    final_lineups = []
    player_counts = {}
    for lineup in candidate_lineups:
        lineup_players = list(lineup)
        exceed = False
        for p in lineup_players:
            if player_counts.get(p.id,0) >= max_repeating:
                exceed = True
                break
        if not exceed:
            final_lineups.append(lineup_players)
            for p in lineup_players:
                player_counts[p.id] = player_counts.get(p.id,0)+1
        if len(final_lineups) >= num_lineups:
            break

    # --- Prepare CSV ---
    headers = ["QB","RB","RB","WR","WR","WR","TE","FLEX","DST","TotalSalary","ProjectedPoints"]
    csv_rows = []
    for lineup in final_lineups:
        row = {h:"" for h in headers}
        for i, p in enumerate(lineup):
            if i<len(headers)-2:
                row[headers[i]] = f"{player_display_name(p)}({p.id})"
        row["TotalSalary"] = sum([p.salary for p in lineup])
        row["ProjectedPoints"] = sum([safe_float(p.fppg) for p in lineup])
        csv_rows.append(row)

    df_wide = pd.DataFrame(csv_rows)
    st.dataframe(df_wide)
    csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
    st.download_button("Download Lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
