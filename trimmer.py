import streamlit as st
import pandas as pd

st.title("DFS GPP Player Trimmer")

# Upload merged CSV
uploaded_file = st.file_uploader("Upload Merged DFS Players CSV", type=["csv"])

if uploaded_file is not None:
    # Read the CSV and store in session state to persist across interactions
    if 'df' not in st.session_state:
        st.session_state.df = pd.read_csv(uploaded_file)

    df = st.session_state.df

    # Display original data
    st.subheader("Original Data")
    st.dataframe(df)

    # Position selection
    positions = df['Position'].unique()
    selected_positions = st.multiselect("Select Positions to Filter", positions, default=positions)

    # Filter criteria for GPP strategy
    st.subheader("Filter Criteria for GPP Strategy")
    min_ceiling = st.slider("Minimum Ceiling (for high-upside GPP)", min_value=0.0, max_value=50.0, value=15.0)
    max_salary = st.slider("Maximum Salary (mid-tier focus, avoid high-chalk)", min_value=0, max_value=10000, value=8000)
    min_dvp_rank = st.slider("Minimum DVP Rank (higher = weaker defense)", min_value=1, max_value=32, value=12)  # Reversed: higher DVP = easier matchup
    min_bb_proj = st.slider("Minimum BB Proj (projected points)", min_value=0.0, max_value=30.0, value=8.0)

    # Trim button to apply filters
    if st.button("Trim Player Pool"):
        # Filter dataframe
        filtered_df = df[df['Position'].isin(selected_positions)]
        filtered_df = filtered_df[(filtered_df['Ceiling'] >= min_ceiling) &
                                 (filtered_df['Salary'] <= max_salary) &
                                 (filtered_df['DVP'] >= min_dvp_rank) &  # Reversed to filter for higher DVP ranks
                                 (filtered_df['BB Proj'] >= min_bb_proj)]

        # Store filtered dataframe in session state
        st.session_state.filtered_df = filtered_df

    # Display filtered data if trimming has been applied
    if 'filtered_df' in st.session_state:
        st.subheader("Trimmed Players for GPP (High Ceiling, Favorable DVP, Mid-Tier Value)")
        st.dataframe(st.session_state.filtered_df)

        # Group by position to check counts for diversification
        position_counts = st.session_state.filtered_df['Position'].value_counts()
        st.subheader("Player Counts by Position (For 200 Lineups w/ 30% Max Exposure)")
        st.write(position_counts)
        st.write("Note: For 200 lineups at 30% max exposure, need ~7x players per slot to diversify (e.g., 20+ RBs for 2-3 RB slots).")

        # Download trimmed CSV
        csv = st.session_state.filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Trimmed CSV",
            data=csv,
            file_name='trimmed_gpp_players.csv',
            mime='text/csv',
        )
    else:
        st.write("Click the 'Trim Player Pool' button to apply filters.")

else:
    st.write("Please upload the merged DFS players CSV to begin.")
