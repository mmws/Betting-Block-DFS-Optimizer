import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import Site, Sport, get_optimizer, AfterEachExposureStrategy, Player, TeamStack
import datetime
import os

st.set_page_config(page_title="DFS Lineup Optimizer", layout="wide")
st.title("DraftKings NFL Lineup Optimizer")

# File uploader
uploaded_file = st.file_uploader("Upload Week 3 Salaries CSV", type="csv")

if uploaded_file:
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    st.write("Preview of uploaded CSV")
    st.dataframe(df.head(10))

    # Initialize optimizer
    optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)

    # --- Convert CSV rows to Player objects ---
    players = []
    skipped = 0
    for idx, row in df.iterrows():
        try:
            # Extract name
            name = str(row.get("Name", row.get("name", f"Player{idx}"))).strip()
            if "(" in name:
                name = name.split("(")[0].strip()
            first_name, *last = name.split(" ")
            last_name = " ".join(last) if last else ""
            
            # Extract position
            pos = str(row.get("Position", row.get("position", "WR"))).strip()
            positions = [p.strip() for p in pos.split("/")]

            # Extract team
            team = str(row.get("Team", row.get("team", "NA"))).strip()

            # Extract salary and FPPG
            salary = float(row.get("Salary", row.get("salary", 0)))
            fppg = float(row.get("AvgPointsPerGame", row.get("avgpointspergame", 0)))

            players.append(Player(
                player_id=str(idx),
                first_name=first_name,
                last_name=last_name,
                positions=positions,
                team=team,
                salary=salary,
                fppg=fppg
            ))
        except Exception:
            skipped += 1
            continue

    optimizer.player_pool.load_players(players)
    st.write(f"Loaded {len(players)} players, skipped {skipped}")

    # --- Sidebar settings ---
    st.sidebar.header("Optimizer Settings")
    num_lineups = st.sidebar.slider("Number of Lineups", 1, 100, 50)
    min_salary = st.sidebar.number_input("Minimum Salary Cap", 40000, 50000, 49000)
    optimizer.set_min_salary_cap(min_salary)
    optimizer.set_max_repeating_players(3)

    # Add a sample team stack
    optimizer.add_stack(TeamStack(3, for_positions=["QB", "WR", "TE"]))

    # Generate lineups
    if st.button("Generate Lineups"):
        try:
            lineups_data = []
            for i, lineup in enumerate(optimizer.optimize(n=num_lineups, exposure_strategy=AfterEachExposureStrategy), 1):
                lineup_data = {
                    "Lineup #": i,
                    "Players": ", ".join([f"{p.first_name} {p.last_name} ({','.join(p.positions)})" for p in lineup.players]),
                    "Total Salary": lineup.salary_cost,
                    "Projected FPTS": lineup.fantasy_points_projection
                }
                lineups_data.append(lineup_data)

            df_lineups = pd.DataFrame(lineups_data)
            st.subheader("Generated Lineups")
            st.dataframe(df_lineups, use_container_width=True)

            # Download button
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
            st.download_button(
                "Download Lineups as CSV",
                df_lineups.to_csv(index=False).encode("utf-8"),
                file_name=f"dfs_lineups_{now}.csv",
                mime="text/csv"
            )
        except Exception as e:
            st.error(f"Error generating lineups: {e}")

else:
    st.info("Please upload a CSV file with player salaries.")
