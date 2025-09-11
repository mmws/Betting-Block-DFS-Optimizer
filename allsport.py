import streamlit as st
import pandas as pd
import tempfile
from pydfs_lineup_optimizer import get_optimizer, Site, Sport
from pydfs_lineup_optimizer.exceptions import LineupOptimizerException

# -----------------------------
# App Title
# -----------------------------
st.title("Multi-Sport DFS Optimizer")

# -----------------------------
# File Upload
# -----------------------------
uploaded_file = st.file_uploader("Upload salaries CSV", type=["csv"])

# -----------------------------
# Site & Sport Selection
# -----------------------------
site = st.selectbox("Select Site", [Site.DRAFTKINGS, Site.FANDUEL, Site.YAHOO])
sport = st.selectbox(
    "Select Sport",
    [Sport.FOOTBALL, Sport.BASKETBALL, Sport.BASEBALL, Sport.HOCKEY, Sport.GOLF],
)

# -----------------------------
# Number of Lineups
# -----------------------------
num_lineups = st.number_input("Number of lineups", min_value=1, max_value=150, value=20)

if uploaded_file:
    try:
        optimizer = get_optimizer(site, sport)
        
        # Save uploaded file to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            tmp_file_path = tmp_file.name

        # Load players from the temp CSV file
        optimizer.load_players_from_csv(tmp_file_path)

        players = list(optimizer.players)
        players_sorted = sorted(players, key=lambda p: p.fppg, reverse=True)

        # -----------------------------
        # Exposure Settings
        # -----------------------------
        st.subheader("Exposure Settings (Top 20 Players)")
        exposure_settings = {}
        for player in players_sorted[:20]:
            col1, col2 = st.columns(2)
            with col1:
                max_exp = st.slider(
                    f"{player.full_name} (Max)",
                    min_value=0.0, max_value=1.0, step=0.05, value=1.0,
                )
            with col2:
                min_exp = st.slider(
                    f"{player.full_name} (Min)",
                    min_value=0.0, max_value=max_exp, step=0.05, value=0.0,
                )
            exposure_settings[player.full_name] = {"min": min_exp, "max": max_exp}

        # -----------------------------
        # Optimize Button
        # -----------------------------
        if st.button("Optimize Lineups"):
            # Apply exposure settings
            for name, exp in exposure_settings.items():
                if exp["max"] < 1.0:
                    optimizer.settings.exposure.set_max(name, exp["max"])
                if exp["min"] > 0.0:
                    optimizer.settings.exposure.set_min(name, exp["min"])

            # Run optimizer
            lineups = list(optimizer.optimize(n=num_lineups))

            # Get roster positions dynamically
            positions = [pos.name for pos in optimizer.settings.positions]

            # Build export data
            export_data = []
            for lineup in lineups:
                row = {}
                for pos in positions:
                    # Check if position is in player's positions list
                    players_at_pos = [p for p in lineup.players if pos in p.positions]
                    if players_at_pos:
                        row[pos] = ", ".join(f"{p.full_name}({p.id})" for p in players_at_pos)
                    else:
                        row[pos] = ""
                row["Budget"] = lineup.salary_costs
                row["FPPG"] = round(lineup.fantasy_points_projection, 2)
                export_data.append(row)

            df = pd.DataFrame(export_data, columns=positions + ["Budget", "FPPG"])

            st.dataframe(df)

            # Download button
            csv = df.to_csv(index=False)
            st.download_button(
                "Download CSV",
                csv.encode("utf-8"),
                "dfs_lineups.csv",
                "text/csv"
            )

    except LineupOptimizerException as e:
        st.error(f"Optimizer error: {e}")
import streamlit as st
import pandas as pd
import tempfile
from pydfs_lineup_optimizer import get_optimizer, Site, Sport
from pydfs_lineup_optimizer.exceptions import LineupOptimizerException

# -----------------------------
# App Title
# -----------------------------
st.title("Multi-Sport DFS Optimizer")

# -----------------------------
# File Upload
# -----------------------------
uploaded_file = st.file_uploader("Upload salaries CSV", type=["csv"])

# -----------------------------
# Site & Sport Selection
# -----------------------------
site = st.selectbox("Select Site", [Site.DRAFTKINGS, Site.FANDUEL, Site.YAHOO])
sport = st.selectbox(
    "Select Sport",
    [Sport.FOOTBALL, Sport.BASKETBALL, Sport.BASEBALL, Sport.HOCKEY, Sport.GOLF],
)

# -----------------------------
# Number of Lineups
# -----------------------------
num_lineups = st.number_input("Number of lineups", min_value=1, max_value=150, value=20)

if uploaded_file:
    try:
        optimizer = get_optimizer(site, sport)
        
        # Save uploaded file to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_file:
            tmp_file.write(uploaded_file.getbuffer())
            tmp_file_path = tmp_file.name

        # Load players from the temp CSV file
        optimizer.load_players_from_csv(tmp_file_path)

        players = list(optimizer.players)
        players_sorted = sorted(players, key=lambda p: p.fppg, reverse=True)

        # -----------------------------
        # Exposure Settings
        # -----------------------------
        st.subheader("Exposure Settings (Top 20 Players)")
        exposure_settings = {}
        for player in players_sorted[:20]:
            col1, col2 = st.columns(2)
            with col1:
                max_exp = st.slider(
                    f"{player.full_name} (Max)",
                    min_value=0.0, max_value=1.0, step=0.05, value=1.0,
                )
            with col2:
                min_exp = st.slider(
                    f"{player.full_name} (Min)",
                    min_value=0.0, max_value=max_exp, step=0.05, value=0.0,
                )
            exposure_settings[player.full_name] = {"min": min_exp, "max": max_exp}

        # -----------------------------
        # Optimize Button
        # -----------------------------
        if st.button("Optimize Lineups"):
            # Apply exposure settings
            for name, exp in exposure_settings.items():
                if exp["max"] < 1.0:
                    optimizer.settings.exposure.set_max(name, exp["max"])
                if exp["min"] > 0.0:
                    optimizer.settings.exposure.set_min(name, exp["min"])

            # Run optimizer
            lineups = list(optimizer.optimize(n=num_lineups))

            # Get roster positions dynamically
            positions = [pos.name for pos in optimizer.settings.positions]

            # Build export data
            export_data = []
            for lineup in lineups:
                row = {}
                for pos in positions:
                    # Check if position is in player's positions list
                    players_at_pos = [p for p in lineup.players if pos in p.positions]
                    if players_at_pos:
                        row[pos] = ", ".join(f"{p.full_name}({p.id})" for p in players_at_pos)
                    else:
                        row[pos] = ""
                row["Budget"] = lineup.salary_costs
                row["FPPG"] = round(lineup.fantasy_points_projection, 2)
                export_data.append(row)

            df = pd.DataFrame(export_data, columns=positions + ["Budget", "FPPG"])

            st.dataframe(df)

            # Download button
            csv = df.to_csv(index=False)
            st.download_button(
                "Download CSV",
                csv.encode("utf-8"),
                "dfs_lineups.csv",
                "text/csv"
            )

    except LineupOptimizerException as e:
        st.error(f"Optimizer error: {e}")

