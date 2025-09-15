import streamlit as st
import pandas as pd
import re
import random
import tempfile
import os
from typing import Optional, Tuple, List
from collections import Counter
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, AfterEachExposureStrategy
from pydfs_lineup_optimizer.stacks import PositionsStack, GameStack, TeamStack
from pydfs_lineup_optimizer.fantasy_points_strategy import RandomFantasyPointsStrategy

st.set_page_config(page_title="The Betting Block DFS Optimizer", layout="wide")

# --- Config / mappings ---
SITE_MAP = {
    "DraftKings NFL": (Site.DRAFTKINGS, Sport.FOOTBALL),
    "FanDuel NFL": (Site.FANDUEL, Sport.FOOTBALL),
    "DraftKings NBA": (Site.DRAFTKINGS, Sport.BASKETBALL),
    "FanDuel NBA": (Site.FANDUEL, Sport.BASKETBALL),
}
NFL_POSITION_HINTS = {"QB", "RB", "WR", "TE", "K", "DST"}
NBA_POSITION_HINTS = {"PG", "SG", "SF", "PF", "C", "G", "F"}

# --- Helpers ---
def normalize_colname(c: str) -> str:
    return re.sub(r'[^a-z0-9]', '', c.lower())

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    for col in df.columns:
        for cand in candidates:
            if cand.lower().replace(' ', '') in col.lower().replace(' ', ''):
                return col
    return None

def guess_site_from_filename(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = name.lower()
    if "draftkings" in n or re.search(r'\bdk\b', n):
        return "DraftKings"
    if "fanduel" in n or re.search(r'\bfd\b', n):
        return "FanDuel"
    return None

def guess_sport_from_positions(series: pd.Series) -> Optional[str]:
    if series is None:
        return None
    try:
        all_pos = (
            series.dropna()
                  .astype(str)
                  .str.replace(' ', '')
                  .str.upper()
                  .str.split('/|,')
                  .explode()
                  .unique()
        )
        posset = set([str(p).strip() for p in all_pos if p])
        if posset & NFL_POSITION_HINTS:
            return "NFL"
        if posset & NBA_POSITION_HINTS:
            return "NBA"
    except Exception:
        pass
    return None

def parse_name_and_id_from_field(val: str) -> Tuple[str, Optional[str]]:
    s = str(val).strip()
    m = re.match(r'^(.*?)\s*\((\d+)\)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    m = re.match(r'^(.*?)\s*[-\|\/]\s*(\d+)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    m = re.match(r'^(.*\D)\s+(\d+)\s*$', s)
    if m: return m.group(1).strip(), m.group(2)
    return s, None

def parse_salary(s) -> Optional[float]:
    if pd.isna(s): return None
    try:
        t = str(s).replace('$','').replace(',','').strip()
        if t == '': return None
        return float(t)
    except: return None

def safe_float(x) -> Optional[float]:
    try:
        if pd.isna(x): return None
        return float(x)
    except:
        try: return float(str(x).replace(',', '').strip())
        except: return None

def player_display_name(p) -> str:
    fn = getattr(p, "first_name", None)
    ln = getattr(p, "last_name", None)
    if fn or ln: return f"{fn or ''} {ln or ''}".strip()
    full = getattr(p, "full_name", None)
    if full: return full
    return str(p)

# --- Diversification Logic ---
def diversify_lineups_wide(
    df_wide, salary_df,
    max_exposure=0.4,
    max_pair_exposure=0.6,
    randomness=0.15,
    salary_cap=50000,
    salary_min=49000
):
    diversified = df_wide.copy()
    total_lineups = len(diversified)
    
    # Build salary + projection lookup
    player_info = {}
    for _, row in salary_df.iterrows():
        try:
            fppg = float(row.get("AvgPointsPerGame", 0))
            if fppg < 0:
                fppg = 0
            player_info[row["Name"]] = {
                "team": str(row.get("TeamAbbrev", "")),
                "salary": float(row.get("Salary", 0)),
                "fppg": fppg,
                "position": str(row.get("Position", ""))
            }
        except (ValueError, TypeError):
            st.warning(f"Invalid data for {row['Name']}: {row.to_dict()}. Skipping.")
            continue
    
    # Initialize exposure counters
    exposure = Counter()
    pair_exposure = Counter()
    
    # Calculate initial exposures
    for i in range(total_lineups):
        lineup_players = []
        for col in diversified.columns:
            if col in ["TotalSalary", "ProjectedPoints"]:
                continue
            val = diversified.at[i, col]
            if isinstance(val, str):
                name = val.split("(")[0].strip()
                if name in player_info:
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
            if c not in ["TotalSalary", "ProjectedPoints"] and isinstance(diversified.at[lineup_idx, c], str)
            and diversified.at[lineup_idx, c].split("(")[0].strip() in player_info
        ]
        for col in diversified.columns:
            if col in ["TotalSalary", "ProjectedPoints"]:
                continue
            val = diversified.at[lineup_idx, col]
            if not isinstance(val, str):
                continue
            name = val.split("(")[0].strip()
            if name not in player_info:
                continue
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
                            if pos in ["TotalSalary", "ProjectedPoints"]:
                                continue
                            val2 = temp_lineup[pos]
                            if isinstance(val2, str):
                                nm = val2.split("(")[0].strip()
                                if nm in player_info:
                                    temp_players.append(nm)
                                    lineup_salary += player_info[nm]["salary"]
                                    lineup_points += player_info[nm]["fppg"]
                                    pos_counts[player_info[nm]["position"]] += 1
                        
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
                                diversified.at[lineup_idx, "TotalSalary"] = lineup_salary
                                diversified.at[lineup_idx, "ProjectedPoints"] = lineup_points
                                # Update exposures
                                exposure[name] -= 1
                                exposure[candidate] += 1
                                for pair in lineup_pairs:
                                    pair_exposure[pair] -= 1
                                for pair in new_pairs:
                                    pair_exposure[pair] += 1
                                break
    
    return diversified

# --- UI ---
st.title("The Betting Block DFS Optimizer")
st.write("Upload a salary CSV exported from DraftKings or FanDuel (NFL/NBA).")
uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])

if not uploaded_file:
    st.info("Upload a CSV (e.g. `Week_3_Salaries.csv`). The app will try to auto-detect site & sport.")
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("**Preview (first 10 rows):**")
st.dataframe(df.head(10))

# --- Detect columns ---
detected_site = guess_site_from_filename(getattr(uploaded_file, "name", None))
pos_col = find_column(df, ["position", "positions", "pos", "roster position", "rosterposition", "roster_pos"])
game_info_col = find_column(df, ["game info", "gameinfo", "game"])

guessed_sport = guess_sport_from_positions(df[pos_col]) if pos_col else None
auto_choice = f"{detected_site} {guessed_sport}" if detected_site and guessed_sport and f"{detected_site} {guessed_sport}" in SITE_MAP else None
st.markdown("### Auto-detect diagnostics")
st.write({
    "filename": getattr(uploaded_file, "name", None),
    "detected_site": detected_site,
    "pos_column": pos_col,
    "guessed_sport": guessed_sport,
})

site_choice = None
if auto_choice:
    st.success(f"Auto-detected: **{auto_choice}**")
    site_choice = st.selectbox("Site/sport", list(SITE_MAP.keys()), index=list(SITE_MAP.keys()).index(auto_choice))
else:
    st.warning("Could not auto-detect site+sport. Please choose manually.")
    site_choice = st.selectbox("Site/sport", list(SITE_MAP.keys()))

site, sport = SITE_MAP[site_choice]
optimizer = get_optimizer(site, sport)

# --- Load players ---
try:
    # Save uploaded file to temporary path
    with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name
    optimizer.load_players_from_csv(tmp_file_path)
    st.write(f"Loaded {len(optimizer.player_pool.players)} players")
    # Clean up temporary file
    os.unlink(tmp_file_path)
except Exception as e:
    st.error(f"Failed to load players from CSV: {e}")
    st.stop()

# --- Lineup settings ---
st.markdown("### Lineup Settings")
col1, col2 = st.columns(2)
with col1:
    num_lineups = st.slider("Number of lineups", 1, 200, 10)
    max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
with col2:
    min_salary = st.number_input("Minimum Salary", value=49000, step=500)
    game_stack_size = st.slider("Game Stack Size (Players)", 0, 5, 3)

use_advanced_constraints = st.checkbox("Use Advanced Constraints (QB+WR Stack, No Two RBs, DST Restrictions, WR Opp Stack)", value=True)
if use_advanced_constraints:
    col3, col4 = st.columns(2)
    with col3:
        qb_stack = st.checkbox("QB + WR Stack", value=True)
    with col4:
        no_two_rbs = st.checkbox("No Two RBs from Same Team", value=True)
        opp_stack = st.checkbox("WR Opposing Team Bringback", value=True)
        dst_restrictions = st.checkbox("Restrict DST vs QB/WR/RB/TE", value=True)
else:
    qb_stack = False
    no_two_rbs = False
    opp_stack = False
    dst_restrictions = False

optimizer.set_min_salary_cap(min_salary)
optimizer.set_max_repeating_players(2)
if qb_stack:
    optimizer.add_stack(PositionsStack(('QB', 'WR')))
if no_two_rbs:
    for team in df["TeamAbbrev"].unique():
        optimizer.restrict_positions_for_same_team(('RB', 'RB'))
if opp_stack:
    optimizer.force_positions_for_opposing_team(('WR', 'WR'))
if dst_restrictions:
    optimizer.restrict_positions_for_opposing_team(['DST'], ['QB', 'WR', 'RB', 'TE'])
if game_stack_size > 0:
    optimizer.add_stack(GameStack(game_stack_size))
    optimizer.add_stack(TeamStack(3))
optimizer.set_fantasy_points_strategy(RandomFantasyPointsStrategy(max_deviation=0.05))

# --- Generate lineups ---
gen_btn = st.button("Generate Lineups")
if gen_btn:
    try:
        with st.spinner("Generating..."):
            lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure, exposure_strategy=AfterEachExposureStrategy))
        st.success(f"Generated {len(lineups)} lineup(s)")
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
        lineups = []

    if lineups:
        # --- Map positions safely ---
        position_columns = {
            "QB": ["QB"],
            "RB": ["RB", "RB1"],
            "WR": ["WR", "WR1", "WR2"],
            "TE": ["TE"],
            "FLEX": ["FLEX"],
            "DST": ["DST"]
        }
        df_rows = []
        for lineup in lineups:
            row = {}
            pos_counter = {k: 0 for k in position_columns.keys()}
            for p in lineup.players:
                assigned = False
                for pos in p.positions or []:
                    if pos in position_columns and pos_counter[pos] < len(position_columns[pos]):
                        col = position_columns[pos][pos_counter[pos]]
                        row[col] = f"{player_display_name(p)} ({p.id})"
                        pos_counter[pos] += 1
                        assigned = True
                        break
                if not assigned:
                    if pos_counter["FLEX"] < 1:
                        row["FLEX"] = f"{player_display_name(p)} ({p.id})"
                        pos_counter["FLEX"] += 1
            # Ensure all columns exist
            for col in ["QB", "RB", "RB1", "WR", "WR1", "WR2", "TE", "FLEX", "DST"]:
                if col not in row:
                    row[col] = ""
            row["TotalSalary"] = lineup.salary_cost
            row["ProjectedPoints"] = lineup.fantasy_points
            df_rows.append(row)
        
        lineup_df = pd.DataFrame(df_rows)
        st.session_state["df_wide"] = lineup_df
        st.session_state["salary_df"] = df
        
        st.markdown("### Lineups (wide)")
        st.dataframe(lineup_df.style.format({
            "TotalSalary": "${:,.0f}",
            "ProjectedPoints": "{:.2f}"
        }))
        csv_bytes = lineup_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Lineups CSV", csv_bytes, file_name="dfs_lineups.csv", mime="text/csv")

# --- Diversify section ---
if "df_wide" in st.session_state and st.button("Diversify Lineups"):
    df_wide = st.session_state["df_wide"]
    salary_df = st.session_state["salary_df"]
    diversified = diversify_lineups_wide(
        df_wide,
        salary_df,
        max_exposure=max_exposure,
        max_pair_exposure=0.6,
        salary_cap=50000,
        salary_min=min_salary
    )
    st.markdown("### Diversified Lineups")
    if not diversified.empty:
        player_usage = Counter()
        for i in range(len(diversified)):
            for name in diversified[["QB", "RB", "RB1", "WR", "WR1", "WR2", "TE", "FLEX", "DST"]].iloc[i].values:
                if isinstance(name, str):
                    player_name = name.split(" (")[0]
                    player_usage[player_name] += 1
        
        st.dataframe(diversified.style.format({
            "TotalSalary": "${:,.0f}",
            "ProjectedPoints": "{:.2f}"
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
                for col in ["QB", "RB", "RB1", "WR", "WR1", "WR2", "TE", "FLEX", "DST"]
                if isinstance(diversified.iloc[i][col], str)
            ]
            for a in range(len(lineup_players)):
                for b in range(a + 1, len(lineup_players)):
                    pair_usage[tuple(sorted([lineup_players[a], lineup_players[b]]))] += 1
        
        st.write("**Pair Exposure:**")
        for pair, count in pair_usage.items():
            exposure = count / len(diversified) * 100
            if exposure > 60:
                st.warning(f"- {pair[0]} + {pair[1]}: {count}/{len(diversified)} lineups ({exposure:.1f}%) exceeds max pair exposure (60.0%)")
            else:
                st.write(f"- {pair[0]} + {pair[1]}: {count}/{len(diversified)} lineups ({exposure:.1f}%)")
        
        timestamp = pd.Timestamp.now().strftime('%Y-%m-%d')
        csv_bytes = diversified.to_csv(index=False).encode("utf-8")
        st.download_button("Download diversified CSV", csv_bytes, file_name=f"daily_lineups_{timestamp}.csv", mime="text/csv")
    else:
        st.error("❌ No valid lineups generated. Try relaxing constraints or checking CSV data.")
