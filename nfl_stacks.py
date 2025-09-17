import streamlit as st
import pandas as pd
import datetime
import os
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, GameInfo
from pydfs_lineup_optimizer.stacks import TeamStack, GameStack

# Streamlit app configuration
st.set_page_config(page_title="DFS Lineup Optimizer", layout="wide")
st.title("DraftKings NFL Lineup Optimizer")

# Initialize temp_file as None
temp_file = None

# File uploader for CSV
uploaded_file = st.file_uploader("Upload NFL Salaries CSV", type="csv")

if uploaded_file is not None:
    # Save the uploaded file temporarily to disk
    temp_file = f"temp_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    with open(temp_file, 'wb') as f:
        f.write(uploaded_file.getvalue())

    # Initialize optimizer
    optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)

    # Load players from the temporary CSV file with game info
    try:
        df = pd.read_csv(temp_file)
        players = []
        game_col = None
        for col in df.columns:
            if 'game' in col.lower().replace(' ', ''):
                game_col = col
                break
        for idx, row in df.iterrows():
            player_id = str(row.get('ID', f'r{idx}')).strip()
            name = str(row.get('Name', f'Player{idx}')).strip()
            parts = name.split(" ", 1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts) > 1 else ""
            raw_pos = str(row.get('Position', '')).strip()
            positions = [p.strip() for p in re.split(r'[\/|,]', raw_pos)] if raw_pos else []
            team = str(row.get('Team', '')).strip() if 'Team' in row else None
            salary = float(str(row.get('Salary', '')).replace('$', '').replace(',', '').strip()) if 'Salary' in row else None
            fppg = float(str(row.get('FPPG', 0)).replace(',', '').strip()) if 'FPPG' in row else 0.0
            game = str(row[game_col]).strip() if game_col and not saying(row[game_col]) else None
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
            raise ValueError("No valid players loaded from CSV")
        st.write(f"Loaded {len(players)} players")
    except Exception as e:
        st.error(f"Error loading players: {str(e)}")
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        st.stop()

    # Sidebar for optimizer settings
    st.sidebar.header("Optimizer Settings")
    num_lineups = st.sidebar.slider("Number of Lineups", min_value=1, max_value=100, value=50)
    min_salary = st.sidebar.number_input("Minimum Salary Cap", min_value=40000, max_value=50000, value=49000)
    use_stacks = st.sidebar.checkbox("Enable Stacking Constraints", value=True)

    # Apply settings
    optimizer.set_min_salary_cap(min_salary)
    if use_stacks:
        optimizer.restrict_positions_for_same_team(('RB', 'RB'))
        optimizer.force_positions_for_opposing_team([('QB', 'WR'), ('QB', 'RB')])
        optimizer.set_max_repeating_players(3)
        optimizer.add_stack(TeamStack(3, for_positions=['QB', 'WR', 'TE']))
        optimizer.add_stack(GameStack(4, min_from_team=1))

    # Optimize button
    if st.button("Generate Lineups"):
        try:
            # Optimize lineups
            lineups = []
            num = 1
            for lineup in optimizer.optimize(n=num_lineups, max_exposure=0.3):
                lineup_data = {
                    "Lineup #": num,
                    "Players": ", ".join([f"{p.full_name} ({p.positions[0]})" for p in lineup.players]),
                    "Total Salary": sum(p.salary for p in lineup.players),
                    "Projected FPTS": sum(p.fppg for p in lineup.players)
                }
                lineups.append(lineup_data)
                num += 1

            # Display results
            st.subheader("Generated Lineups")
            lineups_df = pd.DataFrame(lineups)
            st.dataframe(lineups_df, use_container_width=True)

            # Download button for lineups
            csv = lineups_df.to_csv(index=False)
            st.download_button(
                label="Download Lineups as CSV",
                data=csv,
                file_name=f"dfs_lineups_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )

        except Exception as e:
            st.error(f"Error generating lineups: {str(e)}")

    # Clean up temporary file
    if temp_file and os.path.exists(temp_file):
        os.remove(temp_file)

else:
    st.info("Please upload a CSV file with player salaries to start.")

# Clean up temporary file if it exists
if temp_file and os.path.exists(temp_file):
    os.remove(temp_file)
