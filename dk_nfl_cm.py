import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

st.title("NFL DraftKings Captain Mode Optimizer")

# Upload CSV
uploaded_file = st.file_uploader("Upload DraftKings CSV", type=["csv"])
if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # Preview
    st.write(df.head())

    # Initialize optimizer
    optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL, use_captain=True)

    # Add players
    for _, row in df.iterrows():
        position = row["Position"]
        is_captain = row["Roster Position"] == "CPT"
        
        player = Player(
            player_id=str(row["ID"]),
            first_name=row["Name"].split()[0],
            last_name=" ".join(row["Name"].split()[1:]),
            positions=[position],
            fppg=row["AvgPointsPerGame"],
            salary=row["Salary"],
            team=row["TeamAbbrev"],
            is_captain=is_captain
        )
        
        optimizer.add_player(player)
    
    # Generate lineups
    num_lineups = st.slider("Number of lineups", 1, 10, 5)
    try:
        lineups = optimizer.optimize(n=num_lineups)
        results = []

        for lineup in lineups:
            lineup_dict = {}
            for player in lineup.players:
                if lineup.captain and player.id == lineup.captain.id:
                    lineup_dict["Captain"] = f"{player.first_name} {player.last_name}"
                else:
                    # FLEX or normal
                    if "FLEX" not in lineup_dict:
                        lineup_dict["FLEX"] = f"{player.first_name} {player.last_name}"
                    else:
                        lineup_dict["FLEX"] += f", {player.first_name} {player.last_name}"
            lineup_dict["Total Salary"] = lineup.salary_cost
            lineup_dict["Projected Points"] = lineup.fantasy_points_projection
            results.append(lineup_dict)
        
        st.write(pd.DataFrame(results))

        # Export CSV
        if st.button("Export CSV"):
            pd.DataFrame(results).to_csv("draftkings_cpt_lineups.csv", index=False)
            st.success("Lineups exported successfully!")

    except Exception as e:
        st.error(f"Error generating lineups: {e}")
