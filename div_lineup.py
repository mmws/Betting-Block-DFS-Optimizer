import streamlit as st
import pandas as pd
import random
from collections import Counter

# -----------------------------
# Diversify function
# -----------------------------
def diversify_lineups_wide(df_wide, salary_dict, points_dict, max_salary=50000, max_exposure=0.4, randomness=0.1):
    """
    Diversify lineups by limiting max player exposure, ensuring salary cap,
    avoiding duplicates, and recalculating totals.
    """
    diversified = df_wide.copy()
    total_lineups = len(diversified)

    # Flatten all players for exposure count
    players = []
    for col in diversified.columns:
        if col not in ["TotalSalary", "TotalPoints"]:
            for val in diversified[col]:
                if isinstance(val, str):
                    name = val.split("(")[0].strip()
                    players.append(name)
    exposure = Counter(players)

    # Loop lineups
    for i in diversified.index:
        seen_players = set()
        lineup_salary = 0
        lineup_points = 0

        for col in diversified.columns:
            if col in ["TotalSalary", "TotalPoints"]:
                continue
            val = diversified.at[i, col]
            if not isinstance(val, str):
                continue

            name = val.split("(")[0].strip()
            player_exp = exposure[name] / total_lineups

            # If over exposure or duplicate, attempt replacement
            if player_exp > max_exposure or name in seen_players:
                replacements = list(salary_dict.keys())
                random.shuffle(replacements)

                for rep in replacements:
                    if rep == name:
                        continue
                    if rep in seen_players:
                        continue

                    # Recalculate if valid replacement
                    new_salary = (lineup_salary - salary_dict.get(name, 0)) + salary_dict.get(rep, 0)
                    if new_salary > max_salary:
                        continue

                    diversified.at[i, col] = rep
                    name = rep
                    break

            seen_players.add(name)
            lineup_salary += salary_dict.get(name, 0)
            lineup_points += points_dict.get(name, 0)

        # Update totals
        diversified.at[i, "TotalSalary"] = lineup_salary
        diversified.at[i, "TotalPoints"] = lineup_points

    return diversified


# -----------------------------
# Streamlit App
# -----------------------------
st.title("DFS Optimizer with Diversification")

# Upload salary file
uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if uploaded_file:
    salary_df = pd.read_csv(uploaded_file)

    # Example: expecting Player, Salary, FPPG columns
    salary_dict = dict(zip(salary_df["Player"], salary_df["Salary"]))
    points_dict = dict(zip(salary_df["Player"], salary_df["FPPG"]))

    # Fake generated lineups (replace with optimizer output)
    wide_rows = [
        {
            "QB": "Joe Burrow(123)",
            "RB1": "Christian McCaffrey(456)",
            "RB2": "Breece Hall(789)",
            "WR1": "CeeDee Lamb(321)",
            "WR2": "Tee Higgins(654)",
            "WR3": "Calvin Ridley(987)",
            "TE": "Mark Andrews(741)",
            "FLEX": "James Cook(852)",
            "DST": "Bills(963)"
        }
        for _ in range(10)
    ]

    # Add totals to wide rows
    for row in wide_rows:
        total_salary = sum(salary_dict.get(p.split("(")[0].strip(), 0) for p in row.values())
        total_points = sum(points_dict.get(p.split("(")[0].strip(), 0) for p in row.values())
        row["TotalSalary"] = total_salary
        row["TotalPoints"] = total_points

    df_wide = pd.DataFrame(wide_rows)

    # Show generated lineups
    st.markdown("### Lineups (wide)")
    st.dataframe(df_wide)

    # Diversify button
    if st.button("Diversify Lineups"):
        diversified = diversify_lineups_wide(
            df_wide, salary_dict, points_dict,
            max_salary=50000, max_exposure=0.4, randomness=0.3
        )
        st.markdown("### Diversified Lineups")
        st.dataframe(diversified)

        csv_bytes = diversified.to_csv(index=False).encode("utf-8")
        st.download_button("Download Diversified CSV", csv_bytes, file_name="lineups_diversified.csv", mime="text/csv")
    else:
        # Default export
        csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
        st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
