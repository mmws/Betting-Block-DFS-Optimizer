import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import Site, Sport, get_optimizer, AfterEachExposureStrategy, PositionsStack, TeamStack
import datetime
import io

# Streamlit app configuration
st.set_page_config(page_title="DFS Lineup Optimizer", layout="wide")
st.title("DraftKings NFL Lineup Optimizer")

# File uploader for CSV
uploaded_file = st.file_uploader("Upload Week 3 Salaries CSV", type="csv")
if uploaded_file is not None:
    # Read CSV directly from the uploaded file
    players_df = pd.read_csv(uploaded_file)
    
    # Initialize optimizer
    optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
    
    # Save the uploaded file temporarily to disk for pydfs_lineup_optimizer
    temp_file = f"temp_{datetime.datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')}.csv"
    players_df.to_csv(temp_file, index=False)
    
    # Load players from the temporary CSV file
    try:
        optimizer.load_players_from_csv(temp_file)
    except Exception as e:
        st.error(f"Error loading players: {str(e)}")
        st.stop()
    
    # Sidebar for optimizer settings
    st.sidebar.header("Optimizer Settings")
    num_lineups = st.sidebar.slider("Number of Lineups", min_value=1, max_value=100, value=50)
    min_salary = st.sidebar.number_input("Minimum Salary Cap", min_value=40000, max_value=50000, value=49000)
    max_exposure = st.sidebar.slider("Max Player Exposure", min_value=0.1, max_value=1.0, value=0.5, step=0.05)
    
    # Apply settings
    optimizer.set_min_salary_cap(min_salary)
    optimizer.set_max_exposure(max_exposure)
    
    # Stacking and restriction rules
    optimizer.restrict_positions_for_same_team(('RB', 'RB'))
    optimizer.restrict_positions_for_opposing_team(['DST'], ['QB', 'WR', 'RB', 'TE'])
    optimizer.force_positions_for_opposing_team(('QB', 'WR'))
    optimizer.set_max_repeating_players(3)
    optimizer.add_stack(TeamStack(3, for_positions=['QB', 'WR', 'TE']))
    
    # Optimize button
    if st.button("Generate Lineups"):
        try:
            # Optimize lineups
            lineups = []
            num = 1
            for lineup in optimizer.optimize(n=num_lineups, exposure_strategy=AfterEachExposureStrategy):
                lineup_data = {
                    "Lineup #": num,
                    "Players": ", ".join([f"{p.full_name} ({p.position})" for p in lineup.players]),
                    "Total Salary": lineup.salary_cost,
                    "Projected FPTS": lineup.fantasy_points_projection
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
                file_name=f"dfs_lineups_{datetime.datetime.now(datetime.UTC).strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
            
        except Exception as e:
            st.error(f"Error generating lineups: {str(e)}")
else:
    st.info("Please upload a CSV file with player salaries to start.")

# Clean up temporary file
import os
if os.path.exists(temp_file):
    os.remove(temp_file)
