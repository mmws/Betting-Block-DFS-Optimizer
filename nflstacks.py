import streamlit as st
import pandas as pd
import re
from typing import Optional, Tuple, List
from datetime import datetime
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, AfterEachExposureStrategy
from pydfs_lineup_optimizer.stacks import GameStack
from pydfs_lineup_optimizer.fantasy_points_strategy import RandomFantasyPointsStrategy

st.set_page_config(page_title="The Betting Block DFS Optimizer", layout="wide")

# --- Config
SITE_MAP = {
    "DraftKings NFL": (Site.DRAFTKINGS, Sport.FOOTBALL),
    "FanDuel NFL": (Site.FANDUEL, Sport.FOOTBALL),
}

NFL_POSITION_HINTS = {"QB", "RB", "WR", "TE", "DST"}

# --- Helpers
def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    return None

def parse_game_info(game_info: str):
    """Parse DK/FanDuel 'Game Info' like 'CHI@DET 09/14/2025 01:00PM ET'."""
    try:
        parts = str(game_info).split()
        if len(parts) >= 2:
            teams = parts[0]
            date = parts[1]
            time_str = parts[2] + " " + parts[3] if len(parts) > 3 else None
            home_away = teams.split("@")
            away, home = home_away[0], home_away[1]
            start_time = None
            if time_str:
                try:
                    start_time = datetime.strptime(date + " " + time_str, "%m/%d/%Y %I:%M%p %Z")
                except:
                    pass
            return home, away, start_time
    except:
        return None, None, None
    return None, None, None

def safe_float(x) -> Optional[float]:
    try:
        return float(x)
    except:
        try:
            return float(str(x).replace(",", "").strip())
        except:
            return None

# --- UI
st.title("The Betting Block DFS Optimizer")
uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if not uploaded_file:
    st.stop()

df = pd.read_csv(uploaded_file)
st.dataframe(df.head(10))

# --- Detect columns
name_col = find_column(df, ["Name", "Player", "full_name"])
pos_col = find_column(df, ["Position", "Roster Position"])
team_col = find_column(df, ["TeamAbbrev", "Team"])
salary_col = find_column(df, ["Salary"])
fppg_col = find_column(df, ["AvgPointsPerGame", "FPPG"])
game_col = find_column(df, ["Game Info", "Game"])

site_choice = st.selectbox("Site/sport", list(SITE_MAP.keys()), index=0)
site, sport = SITE_MAP[site_choice]
optimizer = get_optimizer(site, sport)

# --- Build players
players = []
for idx, row in df.iterrows():
    try:
        first, *rest = str(row[name_col]).split(" ")
        last = " ".join(rest)
        positions = str(row[pos_col]).split("/")
        team = str(row[team_col])
        salary = safe_float(row[salary_col])
        fppg = safe_float(row[fppg_col]) or 0.0
        game_info = str(row[game_col]) if game_col else None
        home, away, start = parse_game_info(game_info)
        players.append(Player(
            player_id=str(idx),
            first_name=first,
            last_name=last,
            positions=positions,
            team=team,
            salary=salary,
            fppg=fppg,
            game_info={"home_team": home, "away_team": away, "start_time": start}
        ))
    except Exception as e:
        st.warning(f"Skipping row {idx}: {e}")

optimizer.player_pool.load_players(players)

# --- Settings
num_lineups = st.slider("Number of lineups", 1, 50, 5)
game_stack_size = st.slider("Game Stack Size", 2, 6, 3)

optimizer.add_stack(GameStack(game_stack_size))
optimizer.set_fantasy_points_strategy(RandomFantasyPointsStrategy(max_deviation=0.05))

# --- Generate
if st.button("Generate Lineups"):
    lineups = list(optimizer.optimize(
        n=num_lineups,
        max_exposure=0.4,
        exposure_strategy=AfterEachExposureStrategy
    ))
    st.success(f"Generated {len(lineups)} lineups")

    for i, lineup in enumerate(lineups, 1):
        st.write(f"**Lineup {i}** – {lineup.fantasy_points_projection:.2f} proj pts")
        st.table([(p.full_name, p.positions, p.team, p.salary) for p in lineup.players])
