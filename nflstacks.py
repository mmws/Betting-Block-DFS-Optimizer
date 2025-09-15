import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import Site, Sport, get_optimizer, AfterEachExposureStrategy, GameStack
import datetime
import os

# --- Streamlit config ---
st.set_page_config(page_title="DFS Lineup Optimizer", layout="wide")
st.title("DraftKings NFL Lineup Optimizer")

# --- File uploader ---
uploaded_file = st.file_uploader("Upload Week 3 Salaries CSV", type="csv")
temp_file = None

if uploaded_file is not None:
    try:
        # Read CSV
        players_df = pd.read_csv(uploaded_file)

        # Save temporary file (required by pydfs_lineup_optimizer CSV loader)
        temp_file = f"temp_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        players_df.to_csv(temp_file, index=False)

        # --- Initialize optimizer ---
        optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
        optimizer.load_players_from_csv(temp_file)

        # --- Sidebar: settings ---
        st.sidebar.header("Optimizer Settings")
        num_lineups = st.sidebar.slider("Number of Lineups", 1, 100, 50)
        min_salary = st.sidebar.number_input("Minimum Salary Cap", min_value=40000, max_value=50000, value=49000)
        game_stack_size = st.sidebar.slider("Game Stack Size (Players)", 2, 5, 3)
        max_repeating_players = st.sidebar.slider("Max repeating players", 1, 10, 3)

        # Apply basic settings
        optimizer.set_min_salary_cap(min_salary)
        optimizer.set_max_repeating_players(max_repeating_players)

        # --- Stacking rules ---
        if game_stack_size > 1:
            optimizer.add_stack(GameStack(game_stack_size))  # stack N players from the same game

        # --- Generate lineups ---
        if st.button("Generate Lineups"):
            try:
                lineups = []
                for i, lineup in enumerate(optimizer.optimize(n=num_lineups, exposure_strategy=AfterEachExposureStrategy), start=1):
                    lineup_data = {
                        "Lineup #": i,
                        "Players": ", ".join([f"{p.first_name} {p.last_name} ({','.join(p.positions)})" for p in lineup.players]),
                        "Total Salary": lineup.total_salary,
                        "Projected FPTS": lineup.fantasy_points()
                    }
                    lineups.append(lineup_data)

                # Display results
                st.subheader("Generated Lineups")
                lineups_df = pd.DataFrame(lineups)
                st.dataframe(lineups_df, use_container_width=True)

                # Download CSV
                csv = lineups_df.to_csv(index=False)
                st.download_button(
                    label="Download Lineups as CSV",
                    data=csv,
                    file_name=f"dfs_lineups_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )

            except Exception as e:
                st.error(f"Error generating lineups: {e}")

    except Exception as e:
        st.error(f"Error reading or loading CSV: {e}")

else:
    st.info("Please upload a CSV file with player salaries to start.")

# --- Cleanup temp file ---
if temp_file and os.path.exists(temp_file):
    os.remove(temp_file)
