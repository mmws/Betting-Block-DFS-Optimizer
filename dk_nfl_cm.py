import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import get_optimizer, Site, Player, Sport

st.title("DraftKings NFL Captain Mode Optimizer")

# Upload CSV
uploaded_file = st.file_uploader("Upload salaries CSV", type=["csv"])
if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # Create optimizer for DraftKings NFL
    optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
    
    # Add players
    for _, row in df.iterrows():
        # Map roster positions CPT/FLEX to pydfs positions
        positions = [row["Roster Position"]]
        
        player = Player(
            player_id=str(row["ID"]),
            first_name=row["Name"].split()[0],
            last_name=" ".join(row["Name"].split()[1:]),
            positions=positions,
            fppg=row["AvgPointsPerGame"],
            salary=row["Salary"],
            team=row["TeamAbbrev"]
        )
        optimizer.add_player(player)
    
    # Set lineup constraints (Captain Mode = 1 CPT + 5 FLEX by default)
    optimizer.settings.max_exposure = 1.0
    try:
        lineups = optimizer.optimize(n=5)  # generate 5 lineups
        output = []
        for lineup in lineups:
            lineup_dict = {"CPT": "", "FLEX": []}
            for player in lineup.players:
                if "CPT" in player.positions:
                    lineup_dict["CPT"] = f"{player.first_name} {player.last_name}"
                else:
                    lineup_dict["FLEX"].append(f"{player.first_name} {player.last_name}")
            output.append(lineup_dict)
        
        st.write(pd.DataFrame(output))
        st.download_button(
            label="Download Lineups CSV",
            data=pd.DataFrame(output).to_csv(index=False),
            file_name="dk_cpt_lineups.csv",
            mime="text/csv"
        )
        
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
