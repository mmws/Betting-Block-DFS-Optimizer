import streamlit as st
import pandas as pd
import random
from collections import Counter
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

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
                        
                        # Recalculate totals and validate position counts
                        lineup_salary, lineup_points = 0, 0
                        temp_players = []
                        pos_counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "DST": 0}
                        for pos in diversified.columns:
                            if pos in ["Budget", "FPPG"]:
                                continue
                            val2 = temp_lineup[pos]
                            if isinstance(val2, str):
                                nm = val2.split("(")[0].strip()
                                temp_players.append(nm)
                                lineup_salary += player_info.get(nm, {}).get("salary", 0)
                                lineup_points += player_info.get(nm, {}).get("fppg", 0)
                                pos_counts[player_info.get(nm, {}).get("position", "")] += 1
                        
                        # Check salary and position constraints
                        valid_positions = (
                            pos_counts["QB"] == 1 and
                            2 <= pos_counts["RB"] <= 3 and
                            3 <= pos_counts["WR"] <= 4 and
                            pos_counts["TE"] == 1 and
                            pos_counts["DST"] == 1
                        )
                        if salary_min <= lineup_salary <= salary_cap and valid_positions:
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
uploaded_file = st.file_uploader("Upload DraftKings Salaries CSV", type=["csv"])

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

                if st.button("Generate Lineups"):
                    optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
                    # Add players
                    for _, row in salary_df.iterrows():
                        try:
                            name_parts = str(row['Name']).split(" ", 1)
                            first_name = name_parts[0]
                            last_name = name_parts[1] if len(name_parts) > 1 else ""
                            optimizer.add_player(Player(
                                player_id=str(row["ID"]),
                                first_name=first_name,
                                last_name=last_name,
                                positions=str(row["Position"]).split("/"),
                                team=str(row["TeamAbbrev"]),
                                salary=float(row["Salary"]),
                                fppg=float(row["AvgPointsPerGame"])
                            ))
                        except Exception as e:
                            st.warning(f"Skipping player {row['Name']} due to error: {e}")
                    
                    # Optimize
                    lineups = []
                    for lineup in optimizer.optimize(n=num_lineups, max_exposure=max_exposure):
                        lineup_data = {
                            "qb": "", "rb": "", "rb": "", "wr": "", "wr": "", "wr": "",
                            "te": "", "flex": "", "dst": "", "Budget": 0, "FPPG": 0
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
                            lineup_data["qb"] = f"{qb[0].full_name} ({qb[0].id})"
                        rb_slots = [k for k in lineup_data.keys() if k == "rb"]
                        for i in range(min(2, len(rbs))):
                            lineup_data[rb_slots[i]] = f"{rbs[i].full_name} ({rbs[i].id})"
                        wr_slots = [k for k in lineup_data.keys() if k == "wr"]
                        for i in range(min(3, len(wrs))):
                            lineup_data[wr_slots[i]] = f"{wrs[i].full_name} ({wrs[i].id})"
                        if tes:
                            lineup_data["te"] = f"{tes[0].full_name} ({tes[0].id})"
                        if dst:
                            lineup_data["dst"] = f"{dst[0].full_name} ({dst[0].id})"
                        if len(rbs) == 3:
                            lineup_data["flex"] = f"{rbs[2].full_name} ({rbs[2].id})"
                        elif len(wrs) == 4:
                            lineup_data["flex"] = f"{wrs[3].full_name} ({wrs[3].id})"
                        elif len(tes) == 2:
                            lineup_data["flex"] = f"{tes[1].full_name} ({tes[1].id})"

                        lineups.append(pd.DataFrame([lineup_data]))
                    
                    df_wide = pd.concat(lineups, ignore_index=True)
                    st.session_state["df_wide"] = df_wide
                    st.session_state["salary_df"] = salary_df
                    st.markdown("### Lineups (wide)")
                    st.dataframe(df_wide.style.format({
                        "Budget": "${:,.0f}",
                        "FPPG": "{:.2f}"
                    }))
                    csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
                    st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
                
                # Diversify section
                if "df_wide" in st.session_state and st.button("Diversify Lineups"):
                    df_wide = st.session_state["df_wide"]
                    salary_df = st.session_state["salary_df"]
                    diversified = diversify_lineups_wide(
                        df_wide,
                        salary_df,
                        max_exposure=max_exposure,
                        max_pair_exposure=max_pair_exposure,
                        salary_cap=salary_cap,
                        salary_min=min_salary
                    )
                    st.markdown("### Diversified Lineups")
                    if not diversified.empty:
                        player_usage = Counter()
                        for i in range(len(diversified)):
                            for name in diversified[["qb", "rb", "rb", "wr", "wr", "wr", "te", "flex", "dst"]].iloc[i].values:
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
                                for col in ["qb", "rb", "rb", "wr", "wr", "wr", "te", "flex", "dst"]
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
                        st.download_button("Download diversified CSV", csv_bytes, file_name=f"daily_lineups_{timestamp}.csv", mime="text/csv")
                    else:
                        st.error("❌ No valid lineups generated. Try relaxing constraints or checking CSV data.")
    except Exception as e:
        st.error(f"❌ Failed to read CSV: {e}")
        print(f"CSV error: {e}")
