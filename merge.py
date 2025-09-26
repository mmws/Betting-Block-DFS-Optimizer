import pandas as pd
import streamlit as st

st.title("DFS GPP Player Data Merger")

# File upload for both CSVs
salaries_file = st.file_uploader("Upload Raw Salaries CSV (DKSalaries (6).csv)", type=["csv"])
stats_file = st.file_uploader("Upload Stats CSV (draftkings_NFL_2025-week-4_players.csv)", type=["csv"])

if salaries_file is not None and stats_file is not None:
    # Read the CSV files
    salaries_df = pd.read_csv(salaries_file)
    stats_df = pd.read_csv(stats_file)

    # Display original dataframes
    st.subheader("Raw Salaries Data")
    st.dataframe(salaries_df.head())
    st.subheader("Stats Data")
    st.dataframe(stats_df.head())

    # Select relevant columns from stats_df and rename 'Player' to 'Name'
    stats_subset = stats_df[['Player', 'Def v Pos', 'FC Proj']].rename(
        columns={'Def v Pos': 'DVP', 'FC Proj': 'BB Proj', 'Player': 'Name'}
    )

    # Merge dataframes on 'Name'
    merged_df = pd.merge(
        salaries_df,
        stats_subset,
        on='Name',
        how='left'
    )

    # Check for missing merges
    missing = merged_df[merged_df['DVP'].isna() | merged_df['BB Proj'].isna()]
    if not missing.empty:
        st.warning(f"Warning: {len(missing)} players could not be matched. Check Name consistency.")
        st.dataframe(missing[['Name', 'ID']])

    # Reorder columns to match desired output
    output_columns = [
        'Position', 'Name + ID', 'Name', 'ID', 'Roster Position', 'Salary',
        'Game Info', 'TeamAbbrev', 'AvgPointsPerGame', 'DVP', 'BB Proj'
    ]
    merged_df = merged_df[output_columns]

    # Display merged dataframe
    st.subheader("Merged Data")
    st.dataframe(merged_df)

    # Download merged CSV
    csv = merged_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download Merged CSV",
        data=csv,
        file_name='merged_dfs_players.csv',
        mime='text/csv',
    )

    # Summary statistics
    st.subheader("Merge Summary")
    st.write(f"Total players in merged file: {len(merged_df)}")
    st.write(f"Players with DVP and BB Proj: {len(merged_df[~merged_df['DVP'].isna()])}")
    position_counts = merged_df['Position'].value_counts()
    st.write("Player counts by position:")
    st.write(position_counts)
    st.write("Note: Ensure sufficient players per position (QB: 10-15, RB: 20-30, WR: 30-50, TE: 10-20, DST: 5-10) for 200 lineups with 30% max exposure.")
else:
    st.write("Please upload both the Raw Salaries CSV and Stats CSV to proceed.")
