import streamlit as st
import pandas as pd
import random
from collections import Counter

from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player


# ---------------- Helper Functions ---------------- #
def build_player_info(salary_df):
    """
    Build dictionary for quick salary + projection lookup.
    """
    info = {}
    for _, row in salary_df.iterrows():
        info[row["Name"]] = {
            "team": row.get("Team", ""),
            "salary": row.get("Salary", 0),
            "fppg": row.get("FPPG", 0),
        }
    return info


def calculate_lineup_totals(lineup_row, player_info, salary_cap=50000, salary_min=49500):
    """
    Recalculate total salary and projected points for a single lineup row.
    Returns (salary, points) or (None, None) if invalid.
    """
    total_salary, total_points = 0, 0
    used_players = set()

    for col, val in lineup_row.items():
        if col in ["Budget", "FPPG"]:
            continue
        if isinstance(val, str):
            name = val.split("(")[0].strip()
            if name in used_players:
                return None, None  # invalid: duplicate player
            used_players.add(name)

            total_salary += player_info.get(name, {}).get("salary", 0)
            total_points += player_info.get(name, {}).get("fppg", 0)

    if not (salary_min <= total_salary <= salary_cap):
        return None, None

    return total_salary, total_points


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
    player_info = build_player_info(salary_df)

    # Flatten exposures
    players, pairs = [], []
    for i in range(total_lineups):
        lineup_players = []
        for col in diversified.columns:
            if col in ["Budget", "FPPG"]:
                continue
            val = diversified.at[i, col]
            if isinstance(val, str):
                name = val.split("(")[0].strip()
                players.append(name)
                lineup_players.append(name)
        for a in range(len(lineup_players)):
            for b in range(a + 1, len(lineup_players)):
                pairs.append(tuple(sorted([lineup_players[a], lineup_players[b]])))

    exposure = Counter(players)
    pair_exposure = Counter(pairs)

    # Diversify
    for lineup_idx in range(total_lineups):
        for col in diversified.columns:
            if col in ["Budget", "FPPG"]:
                continue

            val = diversified.at[lineup_idx, col]
            if not isinstance(val, str):
                continue

            name = val.split("(")[0].strip()
            player_exp = exposure[name] / total_lineups

            # Get lineup players + pairs
            lineup_players = [
                diversified.at[lineup_idx, c].split("(")[0].strip()
                for c in diversified.columns
                if c not in ["Budget", "FPPG"] and isinstance(diversified.at[lineup_idx, c], str)
            ]
            lineup_pairs = [tuple(sorted([name, p])) for p in lineup_players if p != name]
            pair_flags = [pair_exposure[pair] / total_lineups > max_pair_exposure for pair in lineup_pairs]

            if player_exp > max_exposure or any(pair_flags):
                if random.random() < randomness:
                    # Try replacement
                    possible_replacements = [p for p in player_info.keys() if p != name]
                    random.shuffle(possible_replacements)

                    for candidate in possible_replacements:
                        temp_lineup = diversified.loc[lineup_idx].copy()
                        temp_lineup[col] = f"{candidate} ({player_info[candidate]['team']})"

                        # Recalculate totals
                        salary, points = calculate_lineup_totals(temp_lineup, player_info, salary_cap, salary_min)

                        if salary is not None:
                            # Accept replacement
                            diversified.loc[lineup_idx, col] = f"{candidate} ({player_info[candidate]['team']})"
                            diversified.at[lineup_idx, "Budget"] = salary
                            diversified.at[lineup_idx, "FPPG"] = points

                            # Update exposures
                            exposure[name] -= 1
                            exposure[candidate] += 1
                            for pair in lineup_pairs:
                                pair_exposure[pair] -= 1
                            new_pairs = [
                                tuple(sorted([a, b]))
                                for i, a in enumerate(lineup_players)
                                for b in lineup_players[i+1:]
                            ]
                            for pair in new_pairs:
                                pair_exposure[pair] += 1
                            break

    # Final recalc for all lineups
    for i in range(len(diversified)):
        salary, points = calculate_lineup_totals(diversified.loc[i], player_info, salary_cap, salary_min)
        diversified.at[i, "Budget"] = salary or 0
        diversified.at[i, "FPPG"] = points or 0

    return diversified


# ---------------- Streamlit App ---------------- #
st.title("DFS Lineup Optimizer (NFL Example)")

uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if uploaded_file:
    salary_df = pd.read_csv(uploaded_file)
    player_info = build_player_info(salary_df)

    # User Controls
    num_lineups = st.number_input("Number of lineups", min_value=1, max_value=150, value=10)
    max_exposure = st.slider("Max Player Exposure", 0.1, 1.0, 0.4, 0.05)
    max_pair_exposure = st.slider("Max Pair Exposure", 0.1, 1.0, 0.6, 0.05)
    salary_buffer = st.number_input("Min Salary (buffer)", min_value=40000, max_value=50000, value=49500, step=500)

    if st.button("Generate Lineups"):
        optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)

        # Add players
        for _, row in salary_df.iterrows():
            optimizer.add_player(Player(
                row["ID"], row["Name"], row["Position"], row["Team"],
                row["Salary"], row["FPPG"]
            ))

        # Optimize
        lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure))

        wide_rows = []
        for lineup in lineups:
            row = {}
            for player in lineup.players:
                row[player.position] = f"{player.full_name} ({player.team})"
            salary, points = calculate_lineup_totals(row, player_info, 50000, salary_buffer)
            row["Budget"] = salary or 0
            row["FPPG"] = points or 0
            wide_rows.append(row)

        df_wide = pd.DataFrame(wide_rows)
        st.session_state["df_wide"] = df_wide
        st.session_state["salary_df"] = salary_df

        st.markdown("### Lineups (wide)")
        st.dataframe(df_wide)

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
        salary_cap=50000,
        salary_min=salary_buffer
    )

    st.markdown("### Diversified Lineups")
    st.dataframe(diversified)

    csv_bytes = diversified.to_csv(index=False).encode("utf-8")
    st.download_button("Download diversified CSV", csv_bytes, file_name="lineups_diversified.csv", mime="text/csv")
