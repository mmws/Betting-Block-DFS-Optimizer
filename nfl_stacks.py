import streamlit as st
import pandas as pd
import datetime
import os
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, GameInfo
from pydfs_lineup_optimizer.stacks import TeamStack, GameStack

# App setup
st.set_page_config(page_title="DFS Lineup Optimizer", layout="wide")
st.title("DraftKings NFL Lineup Optimizer")

# CSV uploader
uploaded_file = st.file_uploader("Upload DraftKings NFL CSV", type="csv")
if not uploaded_file:
    st.info("Upload a CSV with columns: ID, Name, Position, Team, Salary, FPPG, Game (e.g., 'KC@BAL')")
    st.stop()

# Save CSV temporarily
temp_file = f"temp_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
with open(temp_file, 'wb') as f:
    f.write(uploaded_file.getvalue())

# Initialize optimizer
optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)

# Load players
try:
    df = pd.read_csv(temp_file)
    players = []
    game_col = next((col for col in df.columns if 'game' in col.lower().replace(' ', '')), None)
    if not game_col:
        st.error("CSV must include a 'Game' column (e.g., 'KC@BAL') for stacking.")
        os.remove(temp_file)
        st.stop()
    for idx, row in df.iterrows():
        player_id = str(row.get('ID', f'r{idx}')).strip()
        name = str(row.get('Name', f'Player{idx}')).strip()
        parts = name.split(" ", 1)
        first_name = parts[0].strip()
        last_name = parts[1].strip() if len(parts) > 1 else ""
        raw_pos = str(row.get('Position', '')).strip()
        positions = [p.strip() for p in raw_pos.split('/|,') if p.strip()] if raw_pos else []
        team = str(row.get('Team', '')).strip() if 'Team' in row else None
        salary = None
        if 'Salary' in row:
            try:
                salary = float(str(row['Salary']).replace('$', '').replace(',', '').strip())
            except:
                pass
        fppg = float(str(row.get('FPPG', 0)).replace(',', '').strip()) if 'FPPG' in row else 0.0
        game = str(row[game_col]).strip() if game_col and not pd.isna(row[game_col]) else None
        opponent = None
        game_info = None
        if game and '@' in game:
            t1, t2 = game.split('@')
            opponent = t2 if team == t1 else t1 if team == t2 else None
            game_info = GameInfo(home_team=t1, away_team=t2, game_time=None)
        if salary is None:
            continue
        players.append(Player(
            player_id=player_id,
            first_name=first_name,
            last_name=last_name,
            positions=positions or None,
            team=team,
            salary=salary,
            fppg=fppg,
            opponent=opponent,
            game_info=game_info
        ))
    optimizer.player_pool.load_players(players)
    if not players:
        raise ValueError("No valid players loaded")
    st.write(f"Loaded {len(players)} players")
except Exception as e:
    st.error(f"Error loading players: {str(e)}")
    if os.path.exists(temp_file):
        os.remove(temp_file)
    st.stop()

# Optimizer settings
st.sidebar.header("Settings")
num_lineups = st.sidebar.slider("Number of Lineups", 1, 100, 50)
max_exposure = st.sidebar.slider("Max Exposure per Player", 0.0, 1.0, 0.3, 0.05)

# Apply stacking constraints
optimizer.restrict_positions_for_same_team(('RB', 'RB'))
optimizer.force_positions_for_opposing_team([('QB', 'WR'), ('QB', 'RB')])
optimizer.set_max_repeating_players(3)
optimizer.add_stack(TeamStack(3, for_positions=['QB', 'WR', 'TE']))
optimizer.add_stack(GameStack(4, min_from_team=1))

# Generate button
if st.button("Generate Lineups"):
    try:
        with st.spinner("Generating..."):
            lineups = []
            for i, lineup in enumerate(optimizer.optimize(n=num_lineups, max_exposure=max_exposure), 1):
                lineup_data = {
                    "Lineup #": i,
                    "Players": ", ".join([f"{p.full_name} ({p.positions[0]})" for p in lineup.players]),
                    "Total Salary": sum(p.salary for p in lineup.players),
                    "Projected FPTS": sum(p.fppg for p in lineup.players)
                }
                lineups.append(lineup_data)
        st.success(f"Generated {len(lineups)} lineup(s)")
        lineups_df = pd.DataFrame(lineups)
        st.subheader("Lineups")
        st.dataframe(lineups_df, use_container_width=True)
        csv = lineups_df.to_csv(index=False)
        st.download_button(
            label="Download Lineups",
            data=csv,
            file_name=f"dfs_lineups_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    except Exception as e:
        st.error(f"Error generating lineups: {str(e)}")

# Cleanup
if os.path.exists(temp_file):
    os.remove(temp_file)
