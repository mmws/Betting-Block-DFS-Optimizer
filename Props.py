import streamlit as st
import requests
import pandas as pd

def american_to_prob(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)

api_key = st.text_input("API Key")
sport = st.selectbox("Sport", ["americanfootball_nfl", "basketball_nba"])  # Add more from docs

if api_key and st.button("Fetch Props"):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "player_pass_tds,player_rush_yds",  # Customize props
        "oddsFormat": "american"
    }
    data = requests.get(url, params=params).json()
    
    props = []
    for game in data:
        for bookmaker in game.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    if "point" in outcome:  # For over/under
                        prop = {
                            "Game": f"{game['home_team']} vs {game['away_team']}",
                            "Player": outcome.get("description", ""),
                            "Prop": f"{outcome['name']} {outcome['point']}",
                            "Odds": outcome["price"],
                            "Prob": f"{american_to_prob(outcome['price']) * 100:.1f}%"
                        }
                        props.append(prop)
    
    if props:
        st.dataframe(pd.DataFrame(props))
    else:
        st.write("No data")