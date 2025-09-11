import streamlit as st
import pandas as pd
import random
from collections import Counter
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, AfterEachExposureStrategy
from pydfs_lineup_optimizer.stacks import GameStack, PositionsStack
from pydfs_lineup_optimizer.fantasy_points_strategy import RandomFantasyPointsStrategy

# ---------------- Diversification Logic ---------------- #
def diversify_lineups_wide(
    df_wide, salary_df,
    max_exposure=0.4,
    max_pair_exposure=0.6,
    randomness=0.15,
    salary_cap=50000,
    salary_min=49500
):
    diversified = df_wide.copy()
    total_lineups = len(diversified)
    
    # Build salary + projection lookup
    player_info = {}
    for _, row in salary_df.iterrows():
        player_info[row["Name"]] = {
            "team": row.get("TeamAbbrev", ""),
            "salary": row.get("Salary", 0),
            "fppg": row.get("AvgPointsPerGame", 0),
            "position": row.get("Position", "")
        }
    
    # Initialize exposure counters
    exposure = Counter()
    pair_exposure = Counter()
    
    # Calculate initial exposures
    for i in range(total_lineups):
        lineup_players = []
        for col in diversified.columns:
            if col in ["Budget", "FPPG"]:
                continue
            val = diversified.at[i, col]
            if isinstance(val, str):
                name = val.split("(")[0].strip()
                exposure[name] += 1
                lineup_players.append(name)
        for a in range(len(lineup_players)):
            for b in range(a + 1, len(lineup_players)):
                pair_exposure[tuple(sorted([lineup_players[a], lineup_players[b]]))] += 1
    
    # Diversify
    for lineup_idx in range(total_lineups):
        lineup_players = [
            diversified.at[lineup_idx, c].split("(")[0].strip()
            for c in diversified.columns
            if c not in ["Budget", "FPPG"] and isinstance(diversified.at[lineup_idx, c], str)
        ]
        for col in diversified.columns:
            if col in ["Budget", "FPPG"]:
                continue
            val = diversified.at[lineup_idx, col]
            if not isinstance(val, str):
                continue
            name = val.split("(")[0].strip()
            player_exp = exposure[name] / total_lineups
            lineup_pairs = [tuple(sorted([name, p])) for p in lineup_players if p != name]
            pair_flags = [pair_exposure[pair] / total_lineups > max_pair_exposure for pair in lineup_pairs]
            
            if player_exp > max_exposure or any(pair_flags):
                if random.random() < randomness:
                    # Find replacement candidates with same position
                    current_pos = player_info[name]["position"]
                    possible_replacements = [
                        p for p in player_info.keys()
                        if p != name and player_info[p]["position"] == current_pos
                    ]
                    random.shuffle(possible_replacements)
                    for candidate in possible_replacements:
                        temp_lineup = diversified.loc[lineup_idx].copy()
                        temp_lineup[col] = f"{candidate} ({player_info[candidate]['team']})"
                        
                        # Recalculate totals
                        lineup_salary, lineup_points = 0, 0
                        temp_players = []
                        for pos in diversified.columns:
                            if pos in ["Budget", "FPPG"]:
                                continue
                            val2 = temp_lineup[pos]
                            if isinstance(val2, str):
                                nm = val2.split("(")[0].strip()
                                temp_players.append(nm)
                                lineup_salary += player_info.get(nm, {}).get("salary", 0)
                                lineup_points += player_info.get(nm, {}).get("fppg", 0)
                        
                        # Check salary and pair constraints
                        if salary_min <= lineup_salary <= salary_cap:
                            new_pairs = [
                                tuple(sorted([a, b]))
                                for i, a in enumerate(temp_players)
                                for b in temp_players[i+1:]
                            ]
                            if all((pair_exposure[pair] + 1) / total_lineups <= max_pair_exposure for pair in new_pairs):
                                # Accept replacement
                                diversified.loc[lineup_idx, col] = f"{candidate} ({player_info[candidate]['team']})"
                                diversified.at[lineup_idx, "Budget"] = lineup_salary
                                diversified.at[lineup_idx, "FPPG"] = lineup_points
                                # Update exposures
                                exposure[name] -= 1
                                exposure[candidate] += 1
                                for pair in lineup_pairs:
                                    pair_exposure[pair] -= 1
                                for pair in new_pairs:
                                    pair_exposure[pair] += 1
                                break
    
    return diversified

# ---------------- Streamlit App ---------------- #
st.title("DFS Lineup Optimizer (NFL DraftKings)")
st.write("Upload your DraftKings salaries CSV (Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame) to generate optimized NFL lineups.")

# Upload CSV
uploaded_file = st.file_uploader("Upload DraftKings Salaries CSV", type="csv")

if uploaded_file:
    try:
        salary_df = pd.read_csv(uploaded_file)
        st.success("✅ CSV loaded successfully!")
        
        # Validate CSV format
        expected_cols = ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame"]
        missing = [col for col in expected_cols if col not in salary_df.columns]
        if missing:
            st.error(f"⚠️ Missing required columns: {missing}")
        else:
            # Check data types and NaN values
            if salary_df["Position"].isna().any() or salary_df["Name"].isna().any() or salary_df["ID"].isna().any() or \
               salary_df["Salary"].isna().any() or salary_df["TeamAbbrev"].isna().any() or salary_df["Game Info"].isna().any() or \
               salary_df["AvgPointsPerGame"].isna().any():
                st.error("⚠️ CSV contains NaN values in required columns!")
            elif not (salary_df["Position"].isin(["QB", "RB", "WR", "TE", "DST"])).all():
                st.error("⚠️ Invalid Position values! Must be QB, RB, WR, TE, or DST.")
            elif not (salary_df["Roster Position"].isin(["QB", "RB/FLEX", "WR/FLEX", "TE/FLEX", "DST"])).all():
                st.error("⚠️ Invalid Roster Position values! Must be QB, RB/FLEX, WR/FLEX, TE/FLEX, or DST.")
            elif not salary_df["Salary"].apply(lambda x: isinstance(x, (int, float)) and x >= 0).all():
                st.error("⚠️ Invalid Salary values! Must be non-negative numbers.")
            elif not salary_df["AvgPointsPerGame"].apply(lambda x: isinstance(x, (int, float)) and x >= 0).all():
                st.error("⚠️ Invalid AvgPointsPerGame values! Must be non-negative numbers.")
            elif not salary_df["Game Info"].str.match(r"^[A-Z]{2,4}@[A-Z]{2,4}\s+\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(AM|PM)\s+ET$").all():
                invalid_games = salary_df[~salary_df["Game Info"].str.match(r"^[A-Z]{2,4}@[A-Z]{2,4}\s+\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(AM|PM)\s+ET$")]["Game Info"].unique()
                st.error(f"⚠️ Invalid Game Info values: {invalid_games}. Must be format 'TEAM1@TEAM2 MM/DD/YYYY HH:MMAM/PM ET'")
            else:
                # Preview
                st.subheader("Salaries Preview")
                st.write("Player Counts:", salary_df["Position"].value_counts().to_dict())
                st.write("Game Counts:", salary_df["Game Info"].value_counts().to_dict())
                st.dataframe(salary_df.head().style.format({"Salary": "${:,.0f}", "AvgPointsPerGame": "{:.2f}"}))

                # Optimization Settings
                st.subheader("Optimization Settings")
                col1, col2 = st.columns(2)
                with col1:
                    salary_cap = st.number_input("Salary Cap", value=50000, step=500)
                    min_salary = st.number_input("Minimum Salary", value=49500, step=500)
                    num_lineups = st.number_input("Number of Lineups", min_value=1, max_value=150, value=10)
                with col2:
                    max_players_per_team = st.number_input("Max Players per Team", value=4, step=1)
                    max_exposure = st.slider("Max Player Exposure (%)", 10, 100, 40, step=5) / 100.0
                    max_pair_exposure = st.slider("Max Pair Exposure (%)", 10, 100, 60, step=5) / 100.0
                    game_stack_size = st.slider("Game Stack Size (Players)", 0, 5, 0)

                use_advanced_constraints = st.checkbox("Use Advanced Constraints (QB+WR Stack, No Two RBs, WR+WR Opp Stack)", value=True)
                if use_advanced_constraints:
                    col3, col4 = st.columns(2)
                    with col3:
                        qb_stack = st.checkbox("QB + WR Stack", value=True)
                    with col4:
                        no_two_rbs = st.checkbox("No Two RBs from Same Team", value=True)
                        wr_opp_stack = st.checkbox("WR + WR Opposing Team Stack", value=True)
                else:
                    qb_stack = False
                    no_two_rbs = False
                    wr_opp_stack = False

                if st.button("Generate Lineups"):
                    st.write("Generating lineups with pydfs-lineup-optimizer, please wait...")
                    try:
                        optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
                        
                        # Load players manually
                        players = []
                        for _, row in salary_df.iterrows():
                            try:
                                name_parts = str(row['Name']).split(" ", 1)
                                first_name = name_parts[0]
                                last_name = name_parts[1] if len(name_parts) > 1 else ""
                                game_info = str(row['Game Info'])
                                player = Player(
                                    player_id=str(row['ID']),
                                    first_name=first_name,
                                    last_name=last_name,
                                    positions=str(row['Position']).split('/'),
                                    team=str(row['TeamAbbrev']),
                                    salary=float(row['Salary']),
                                    fppg=float(row['AvgPointsPerGame']),
                                    game_info=game_info if game_info != "nan" else None
                                )
                                players.append(player)
                            except Exception as e:
                                st.warning(f"Skipping player {row['Name']} due to error: {e}")
                        optimizer.player_pool.load_players(players)
                        
                        # Set constraints
                        optimizer.set_min_salary_cap(min_salary)
                        optimizer.set_max_players_from_team(max_players_per_team)
                        if qb_stack:
                            optimizer.add_stack(PositionsStack(('QB', 'WR')))
                        if no_two_rbs:
                            for team in salary_df["TeamAbbrev"].unique():
                                optimizer.restrict_positions_for_same_team(('RB', 'RB'))
                        if wr_opp_stack:
                            optimizer.force_positions_for_opposing_team(('WR', 'WR'))
                        if game_stack_size > 0:
                            optimizer.add_stack(GameStack(game_stack_size))
                        optimizer.set_fantasy_points_strategy(RandomFantasyPointsStrategy(max_deviation=0.05))
                        
                        # Generate lineups
                        lineups = []
                        for lineup in optimizer.optimize(n=num_lineups, exposure_strategy=AfterEachExposureStrategy, max_exposure=max_exposure):
                            lineup_data = {
                                "QB": "", "RB": "", "RB_2": "", "WR": "", "WR_2": "", "WR_3": "",
                                "TE": "", "FLEX": "", "DST": "", "Budget": 0, "FPPG": 0
                            }
                            players = lineup.players
                            total_salary = sum(player.salary for player in players)
                            total_points = sum(player.fppg for player in players)
                            lineup_data["Budget"] = total_salary
                            lineup_data["FPPG"] = total_points

                            qb = [p for p in players if "QB" in p.positions]
                            rbs = sorted([p for p in players if "RB" in p.positions], key=lambda x: x.salary, reverse=True)
                            wrs = sorted([p for p in players if "WR" in p.positions], key=lambda x: x.salary, reverse=True)
                            tes = sorted([p for p in players if "TE" in p.positions], key=lambda x: x.salary, reverse=True)
                            dst = [p for p in players if "DST" in p.positions]

                            if qb:
                                lineup_data["QB"] = f"{qb[0].full_name} ({qb[0].id})"
                            if len(rbs) >= 1:
                                lineup_data["RB"] = f"{rbs[0].full_name} ({rbs[0].id})"
                            if len(rbs) >= 2:
                                lineup_data["RB_2"] = f"{rbs[1].full_name} ({rbs[1].id})"
                            if len(wrs) >= 1:
                                lineup_data["WR"] = f"{wrs[0].full_name} ({wrs[0].id})"
                            if len(wrs) >= 2:
                                lineup_data["WR_2"] = f"{wrs[1].full_name} ({wrs[1].id})"
                            if len(wrs) >= 3:
                                lineup_data["WR_3"] = f"{wrs[2].full_name} ({wrs[2].id})"
                            if tes:
                                lineup_data["TE"] = f"{tes[0].full_name} ({tes[0].id})"
                            if dst:
                                lineup_data["DST"] = f"{dst[0].full_name} ({dst[0].id})"
                            if len(rbs) == 3:
                                lineup_data["FLEX"] = f"{rbs[2].full_name} ({rbs[2].id})"
                            elif len(wrs) == 4:
                                lineup_data["FLEX"] = f"{wrs[3].full_name} ({wrs[3].id})"
                            elif len(tes) == 2:
                                lineup_data["FLEX"] = f"{tes[1].full_name} ({tes[1].id})"

                            lineups.append(pd.DataFrame([lineup_data]))
                        
                        df_wide = pd.concat(lineups, ignore_index=True)
                        st.session_state["df_wide"] = df_wide
                        st.session_state["salary_df"] = salary_df
                        
                        # Diversify lineups
                        diversified = diversify_lineups_wide(
                            df_wide,
                            salary_df,
                            max_exposure=max_exposure,
                            max_pair_exposure=max_pair_exposure,
                            salary_cap=salary_cap,
                            salary_min=min_salary
                        )
                        
                        st.subheader("Optimized Lineups")
                        if not diversified.empty:
                            player_usage = Counter()
                            for i in range(len(diversified)):
                                for name in diversified[["QB", "RB", "RB_2", "WR", "WR_2", "WR_3", "TE", "FLEX", "DST"]].iloc[i].values:
                                    if isinstance(name, str):
                                        player_name = name.split(" (")[0]
                                        player_usage[player_name] += 1
                            
                            st.dataframe(diversified.style.format({
                                "Budget": "${:,.0f}",
                                "FPPG": "{:.2f}"
                            }))
                            st.write("**Player Exposure:**")
                            for name, count in player_usage.items():
                                exposure = count / len(diversified) * 100
                                if exposure > max_exposure * 100:
                                    st.warning(f"- {name}: {count}/{len(diversified)} lineups ({exposure:.1f}%) exceeds max exposure ({max_exposure*100:.1f}%)")
                                else:
                                    st.write(f"- {name}: {count}/{len(diversified)} lineups ({exposure:.1f}%)")
                            
                            # Calculate pair exposure
                            pair_usage = Counter()
                            for i in range(len(diversified)):
                                lineup_players = [
                                    diversified.iloc[i][col].split(" (")[0]
                                    for col in ["QB", "RB", "RB_2", "WR", "WR_2", "WR_3", "TE", "FLEX", "DST"]
                                    if isinstance(diversified.iloc[i][col], str)
                                ]
                                for a in range(len(lineup_players)):
                                    for b in range(a + 1, len(lineup_players)):
                                        pair_usage[tuple(sorted([lineup_players[a], lineup_players[b]]))] += 1
                            
                            st.write("**Pair Exposure:**")
                            for pair, count in pair_usage.items():
                                exposure = count / len(diversified) * 100
                                if exposure > max_pair_exposure * 100:
                                    st.warning(f"- {pair[0]} + {pair[1]}: {count}/{len(diversified)} lineups ({exposure:.1f}%) exceeds max pair exposure ({max_pair_exposure*100:.1f}%)")
                                else:
                                    st.write(f"- {pair[0]} + {pair[1]}: {count}/{len(diversified)} lineups ({exposure:.1f}%)")
                            
                            timestamp = pd.Timestamp.now().strftime('%Y-%m-%d')
                            csv_bytes = diversified.to_csv(index=False).encode("utf-8")
                            st.download_button("Download lineups CSV", csv_bytes, file_name=f"daily_lineups_{timestamp}.csv", mime="text/csv")
                        else:
                            st.error("❌ No valid lineups generated. Try relaxing constraints or checking CSV data.")
                    except Exception as e:
                        st.error(f"❌ Optimization failed: {e}")
                        print(f"Optimization error: {e}")
    except Exception as e:
        st.error(f"❌ Failed to read CSV: {e}")
        print(f"CSV error: {e}")
