import pandas as pd
from typing import List

def transpose_lineups_with_id(df_lineups: pd.DataFrame) -> pd.DataFrame:
    """
    Converts long-form lineup DataFrame to wide format:
    Columns: QB, RB, RB, WR, WR, WR, TE, FLEX, DST
    Each row: players in lineup, with IDs in parentheses.
    """
    POSITION_ORDER = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]
    
    output_rows: List[List[str]] = []

    for lineup_id, group in df_lineups.groupby("Lineup"):
        players = group.copy()
        lineup_row: List[str] = []
        used_players = set()

        for pos in POSITION_ORDER:
            if pos == "FLEX":
                flex_player = None
                for idx, row in players.iterrows():
                    if row["Player"] in used_players:
                        continue
                    if any(p in row["Position"] for p in ["RB", "WR", "TE"]):
                        flex_player = f'{row["Player"]}({row.get("ID","")})'
                        used_players.add(row["Player"])
                        break
                lineup_row.append(flex_player if flex_player else "")
            else:
                for idx, row in players.iterrows():
                    if row["Player"] in used_players:
                        continue
                    if pos in row["Position"]:
                        lineup_row.append(f'{row["Player"]}({row.get("ID","")})')
                        used_players.add(row["Player"])
                        break
        output_rows.append(lineup_row)

    return pd.DataFrame(output_rows, columns=POSITION_ORDER)


def save_csv(df: pd.DataFrame, filename: str = "lineups.csv"):
    """Save transposed DataFrame as CSV"""
    df.to_csv(filename, index=False)
