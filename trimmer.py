import streamlit as st
import pandas as pd

st.title("DFS GPP Player Trimmer")

# Upload CSV
uploaded_file = st.file_uploader("Upload Salaries CSV", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)

    # Display original data
    st.subheader("Original Data")
    st.dataframe(df)

    # Position selection
    positions = df['Position'].unique()
    selected_positions = st.multiselect("Select Positions to Filter", positions, default=positions)

    # Filter criteria
    st.subheader("Filter Criteria for GPP Strategy")
    min_ceiling = st.slider("Minimum Ceiling (for high-upside GPP)", min_value=0.0, max_value=50.0, value=20.0)
    max_salary = st.slider("Maximum Salary (mid-tier focus, avoid high-chalk)", min_value=0, max_value=10000, value=7000)
    max_dvp_rank = st.slider("Maximum DVP Rank (lower = weaker defense)", min_value=1, max_value=32, value=16)  # Top half defenses are weaker
    min_bb_proj = st.slider("Minimum BB Proj (projected points)", min_value=0.0, max_value=30.0, value=10.0)

    # Filter dataframe
    filtered_df = df[df['Position'].isin(selected_positions)]
    filtered_df = filtered_df[(filtered_df['Ceiling'] >= min_ceiling) &
                              (filtered_df['Salary'] <= max_salary) &
                              (filtered_df['Def v Pos'] <= max_dvp_rank) &
                              (filtered_df['BB Proj'] >= min_bb_proj)]

    # Ensure diversification: Aim for enough players per position
    # Rough targets: QB: 10-15, RB: 20-30, WR: 30-50, TE: 10-20, DST: 5-10
    st.subheader("Trimmed Players for GPP (High Ceiling, Favorable DVP, Mid-Tier Value)")
    st.dataframe(filtered_df)

    # Group by position to check counts for diversification
    position_counts = filtered_df['Position'].value_counts()
    st.subheader("Player Counts by Position (For 200 Lineups w/ 30% Max Exposure)")
    st.write(position_counts)
    st.write("Note: For 200 lineups at 30% max exposure, need ~7x players per slot to diversify (e.g., 20+ RBs for 2-3 RB slots).")

    # Download trimmed CSV
    csv = filtered_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download Trimmed CSV",
        data=csv,
        file_name='trimmed_gpp_players.csv',
        mime='text/csv',
    )
else:
    st.write("Please upload the salaries CSV to begin.")