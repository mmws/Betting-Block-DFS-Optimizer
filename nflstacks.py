import streamlit as st
import pandas as pd
import re
from typing import Optional, Tuple, List
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, AfterEachExposureStrategy
from pydfs_lineup_optimizer.stacks import PositionsStack, GameStack, TeamStack
from pydfs_lineup_optimizer.fantasy_points_strategy import RandomFantasyPointsStrategy

st.set_page_config(page_title="The Betting Block DFS Optimizer", layout="wide")

SITE_MAP = {
    "DraftKings NFL": (Site.DRAFTKINGS, Sport.FOOTBALL),
    "FanDuel NFL": (Site.FANDUEL, Sport.FOOTBALL),
    "DraftKings NBA": (Site.DRAFTKINGS, Sport.BASKETBALL),
    "FanDuel NBA": (Site.FANDUEL, Sport.BASKETBALL),
}

NFL_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST"}
NBA_POSITIONS = {"PG", "SG", "SF", "PF", "C", "G", "F"}

# ---------- Helpers ----------
def normalize(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm = {normalize(c): c for c in df.columns}
    for cand in candidates:
        if normalize(cand) in norm:
            return norm[normalize(cand)]
    return None

def parse_name_and_id(val: str) -> Tuple[str, Optional[str]]:
    s = str(val).strip()
    m = re.match(r'^(.*?)\s*\((\d+)\)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    return s, None

def parse_salary(s) -> Optional[float]:
    if pd.isna(s): return None
    try:
        return float(str(s).replace('$','').replace(',',''))
    except: return None

def safe_float(x) -> Optional[float]:
    try: return float(x)
    except: return None

def player_display(p) -> str:
    fn = getattr(p, "first_name", "")
    ln = getattr(p, "last_name", "")
    return f"{fn} {ln}".strip() or str(p)

# ---------- UI ----------
st.title("The Betting Block DFS Optimizer")
uploaded_file = st.file_uploader("Upload DraftKings/FanDuel Salary CSV", type=["csv"])

if not uploaded_file:
    st.stop()

df = pd.read_csv(uploaded_file)
st.dataframe(df.head(10))

# Detect columns
id_col = find_column(df, ["ID", "PlayerID"])
name_col = find_column(df, ["Name"])
pos_col = find_column(df, ["Position", "Roster Position"])
salary_col = find_column(df, ["Salary"])
team_col = find_column(df, ["TeamAbbrev", "Team"])
fppg_col = find_column(df, ["AvgPointsPerGame", "FPPG", "Projection"])
game_col = find_column(df, ["Game Info", "Game"])

# Choose site/sport
site_choice = st.selectbox("Site/Sport", list(SITE_MAP.keys()))
site, sport = SITE_MAP[site_choice]
optimizer = get_optimizer(site, sport)

# Build players
players = []
for i, row in df.iterrows():
    try:
        pid = str(row[id_col]) if id_col else f"r{i}"
        name, pid2 = parse_name_and_id(row[name_col]) if name_col else (f"Player{i}", None)
        if pid2: pid = pid2
        parts = name.split(" ", 1)
        fn, ln = parts[0], parts[1] if len(parts) > 1 else ""
        pos = str(row[pos_col]).split("/") if pos_col else []
        team = str(row[team_col]) if team_col else None
        sal = parse_salary(row[salary_col]) if salary_col else None
        fppg = safe_float(row[fppg_col]) if fppg_col else None
        gi = str(row[game_col]) if game_col else None
        if not sal or not pos or not team:
            continue
        players.append(Player(pid, fn, ln, pos, team, sal, fppg or 0.0, game_info=gi))
    except: 
        continue

optimizer.player_pool.load_players(players)
st.success(f"Loaded {len(players)} players")

# ---------- Settings ----------
num_lineups = st.slider("Number of Lineups", 1, 100, 10)
max_exposure = st.slider("Max Exposure", 0.0, 1.0, 0.3)
stack_type = st.radio("Stacking Style", ["None", "QB + Skill", "Game Stack", "Team Stack"])

if stack_type == "QB + Skill":
    optimizer.add_stack(PositionsStack(("QB", "WR")))
    optimizer.add_stack(PositionsStack(("QB", "TE")))
elif stack_type == "Game Stack":
    size = st.slider("Game Stack Size", 2, 6, 3)
    optimizer.add_stack(GameStack(size))
elif stack_type == "Team Stack":
    size = st.slider("Team Stack Size", 2, 5, 3)
    optimizer.add_stack(TeamStack(size))

optimizer.set_fantasy_points_strategy(RandomFantasyPointsStrategy(max_deviation=0.05))

# ---------- Run ----------
if st.button("Generate Lineups"):
    try:
        lineups = list(optimizer.optimize(
            n=num_lineups,
            max_exposure=max_exposure,
            exposure_strategy=AfterEachExposureStrategy
        ))
        st.success(f"Generated {len(lineups)} lineups")
        rows = []
        for lu in lineups:
            row = {p.positions[0]: player_display(p) for p in lu.players}
            row["Salary"] = lu.salary_costs
            row["ProjPts"] = lu.fantasy_points
            rows.append(row)
        out = pd.DataFrame(rows)
        st.dataframe(out)
        st.download_button("Download CSV", out.to_csv(index=False), "lineups.csv")
    except Exception as e:
        st.error(f"Error: {e}")
