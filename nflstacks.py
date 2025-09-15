import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, GameInfo
from pydfs_lineup_optimizer.stacks import GameStack, TeamStack

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("NFL DFS Optimizer with Stacks")

uploaded_file = st.file_uploader("Upload DraftKings CSV", type="csv")

num_lineups = st.number_input("Number of lineups", min_value=1, max_value=20, value=5)
use_team_stack = st.checkbox("Add 3-player Team Stack")
use_game_stack = st.checkbox("Add Game Stacks (3 + 5 w/2 from each team)")

if uploaded_file:
    df = pd.read_csv(uploaded_file)

    # Identify columns
    name_col = "Name" if "Name" in df.columns else None
    id_col = "ID" if "ID" in df.columns else None
    pos_col = "Position" if "Position" in df.columns else None
    team_col = "TeamAbbrev" if "TeamAbbrev" in df.columns else None
    salary_col = "Salary" if "Salary" in df.columns else None
    fppg_col = "AvgPointsPerGame" if "AvgPointsPerGame" in df.columns else None
    game_col = "Game Info" if "Game Info" in df.columns else None

    players = []

    for _, row in df.iterrows():
        # Parse basic fields
        pid = str(row[id_col]) if id_col else str(row[name_col])
        fn, ln = "", str(row[name_col]) if name_col else pid
        pos = [p.strip() for p in str(row[pos_col]).split("/")] if pos_col else []
        team = str(row[team_col]) if team_col else ""
        sal = float(row[salary_col]) if salary_col else 0
        fppg = float(row[fppg_col]) if fppg_col else 0.0

        # Parse Game Info into GameInfo object
        gi_str = str(row[game_col]).strip() if game_col and not pd.isna(row[game_col]) else None
        game_info = None
        if gi_str:
            try:
                teams = gi_str.split()[0]  # "CHI@DET"
                away, home = teams.split("@")
                game_info = GameInfo(home_team=home.strip(), away_team=away.strip())
            except Exception:
                game_info = None

        players.append(Player(
            player_id=pid,
            first_name=fn,
            last_name=ln,
            positions=pos,
            team=team,
            salary=sal,
            fppg=fppg,
            game_info=game_info
        ))

    # -----------------------------
    # Run optimizer
    # -----------------------------
    optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
    optimizer.load_players(players)

    if use_team_stack:
        optimizer.add_stack(TeamStack(3))

    if use_game_stack:
        optimizer.add_stack(GameStack(3))  # 3 players from same game
        optimizer.add_stack(GameStack(5, min_from_team=2))  # 3+2 split from game

    try:
        lineups = list(optimizer.optimize(n=num_lineups))
        for i, lineup in enumerate(lineups, 1):
            st.subheader(f"Lineup {i}")
            st.write(lineup)
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
