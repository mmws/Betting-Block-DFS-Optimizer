import streamlit as st
import pandas as pd
import tempfile
from pydfs_lineup_optimizer import Site, Sport, get_optimizer, AfterEachExposureStrategy
from pydfs_lineup_optimizer.stacks import PositionsStack

st.title("DraftKings CAPTAIN Mode Lineup Optimizer 🏈")

uploaded_file = st.file_uploader("Upload your CSV (DraftKings CAPTAIN mode)", type=["csv"])
if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    st.success("CSV Loaded Successfully!")
    st.dataframe(df.head())

    # Save uploaded file to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_file:
        tmp_file.write(uploaded_file.getbuffer())
        tmp_filepath = tmp_file.name

    # Initialize optimizer
    optimizer = get_optimizer(Site.DRAFTKINGS_CAPTAIN_MODE, Sport.FOOTBALL)
    optimizer.load_players_from_csv(tmp_filepath)  # <- use the file path

    # Stacking options
    st.subheader("Stacking Options")
    stack_option = st.selectbox("Choose a stacking option:", ("None", "QB + WR", "QB + TE"))
    if stack_option == "QB + WR":
        optimizer.add_stack(PositionsStack(['QB','WR']))
    elif stack_option == "QB + TE":
        optimizer.add_stack(PositionsStack(['QB','TE']))

    # Team exposures
    st.subheader("Team Exposure")
    teams = df['TeamAbbrev'].unique()
    exposures = {}
    for team in teams:
        exposures[team] = st.slider(f"Max exposure for {team}", 0.0, 1.0, 0.5, 0.05)
    optimizer.set_teams_max_exposures(exposures)

    # Salary range
    min_salary = st.number_input("Min Salary Cap", value=49200)
    max_salary = st.number_input("Max Salary Cap", value=50000)
    optimizer.set_min_salary_cap(min_salary)
    optimizer.set_max_salary_cap(max_salary)

    # Number of lineups
    num_lineups = st.number_input("Number of Lineups to Generate", min_value=1, max_value=100, value=10)

    st.subheader("Generated Lineups")
    try:
        lineups_list = []
        for lineup in optimizer.optimize(n=num_lineups, exposure_strategy=AfterEachExposureStrategy):
            lineup_dict = {
                p.lineup_position: f"{p.full_name} ({p.position}) - ${p.salary}"
                for p in lineup.players
            }
            lineup_dict['FPPG'] = lineup.fantasy_points_projection
            lineups_list.append(lineup_dict)

        # Display lineups
        lineups_df = pd.DataFrame(lineups_list)
        max_fppg = lineups_df['FPPG'].max()

        def highlight_top(row):
            return ['background-color: #b3ffb3' if row['FPPG'] == max_fppg else '' for _ in row]

        st.dataframe(lineups_df.style.apply(highlight_top, axis=1))

        # Export button
        csv_export = lineups_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "Export Lineups to CSV",
            data=csv_export,
            file_name="captain_mode_lineups.csv",
            mime="text/csv"
        )

    except Exception as e:
        st.error(f"Error generating lineups: {e}")
