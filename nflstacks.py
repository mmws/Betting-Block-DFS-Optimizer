import streamlit as st
import pandas as pd
import re
import random
from typing import Optional, Tuple, List
from collections import Counter
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player, AfterEachExposureStrategy
from pydfs_lineup_optimizer.stacks import PositionsStack, GameStack
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

# --- UI ---
st.title("The Betting Block DFS Optimizer")
st.write("Upload a salary CSV exported from DraftKings or FanDuel (NFL/NBA).")
uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])

if not uploaded_file:
    st.info("Upload a CSV (e.g. `DKSalaries.csv`). The app will try to auto-detect site & sport.")
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
id_col = find_column(df, ["id", "playerid", "player_id", "ID"])
name_plus_id_col = find_column(df, ["name + id", "name+id", "name_plus_id", "name_id", "nameandid"])
name_col = find_column(df, ["name", "full_name", "player"])
first_col = find_column(df, ["first_name", "firstname", "first"])
last_col = find_column(df, ["last_name", "lastname", "last"])
pos_col = find_column(df, ["position", "positions", "pos", "roster position", "rosterposition", "roster_pos"])
salary_col = find_column(df, ["salary", "salary_usd"])
team_col = find_column(df, ["team", "teamabbrev", "team_abbrev", "teamabbr"])
fppg_col = find_column(df, ["avgpointspergame", "avgpoints", "fppg", "projectedpoints", "proj"])
game_info_col = find_column(df, ["game info", "gameinfo", "game"])

guessed_sport = guess_sport_from_positions(df[pos_col]) if pos_col else None
auto_choice = f"{detected_site} {guessed_sport}" if detected_site and guessed_sport and f"{detected_site} {guessed_sport}" in SITE_MAP else None
st.markdown("### Auto-detect diagnostics")
st.write({
    "filename": getattr(uploaded_file, "name", None),
    "detected_site": detected_site,
    "pos_column": pos_col,
    "guessed_sport": guessed_sport,
    "name_column": name_col or name_plus_id_col,
    "id_column": id_col,
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

# --- Build players ---
players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        player_id = str(row[id_col]).strip() if id_col and not pd.isna(row[id_col]) else None
        if not player_id and name_plus_id_col:
            _, player_id = parse_name_and_id_from_field(row[name_plus_id_col])
        if not player_id: player_id = f"r{idx}"
        if first_col and last_col:
            first_name = str(row[first_col]).strip()
            last_name = str(row[last_col]).strip()
        elif name_col:
            parts = str(row[name_col]).split(" ", 1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts) > 1 else "" if row[pos_col] != "DST" else row[name_col]
        elif name_plus_id_col:
            parsed_name, _ = parse_name_and_id_from_field(row[name_plus_id_col])
            parts = parsed_name.split(" ", 1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts) > 1 else "" if row[pos_col] != "DST" else parsed_name
        else:
            first_name = str(row.get(name_col, f"Player{idx}"))
            last_name = ""
        raw_pos = str(row[pos_col]).strip() if pos_col and not pd.isna(row[pos_col]) else None
        positions = [p.strip() for p in re.split(r'[\/\|,]', raw_pos)] if raw_pos else []
        team = str(row[team_col]).strip() if team_col and not pd.isna(row[team_col]) else None
        salary = parse_salary(row[salary_col]) if salary_col else None
        fppg = safe_float(row[fppg_col]) if fppg_col else None
        game_info = str(row[game_info_col]).strip() if game_info_col and not pd.isna(row[game_info_col]) else None
        if salary is None or not team or not positions:
            skipped += 1
            continue
        players.append(Player(
            player_id=player_id,
            first_name=first_name,
            last_name=last_name,
            positions=positions,
            team=team,
            salary=salary,
            fppg=fppg or 0.0,
            game_info=game_info
        ))
    except Exception:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if len(players) == 0:
    st.error("No valid players loaded! Check CSV data.")
    st.stop()

optimizer.player_pool.load_players(players)

# --- Lineup settings ---
st.markdown("### Lineup Settings")
col1, col2 = st.columns(2)
with col1:
    num_lineups = st.slider("Number of lineups", 1, 200, 10)
    max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
    max_repeating_players = st.slider("Max repeating players", 0, len(players), 2)
with col2:
    min_salary = st.number_input("Minimum Salary", value=49500, step=500)
    max_players_per_team = st.number_input("Max Players per Team", value=4, step=1)
    game_stack_size = st.slider("Game Stack Size (Players)", 0, 5, 3)

use_qb_stack = st.checkbox("QB + Skill Player Stack", value=True)

optimizer.set_min_salary_cap(min_salary)
optimizer.set_max_players_from_team(max_players_per_team)
optimizer.set_max_repeating_players(max_repeating_players)

# --- Apply stacking rules ---
if use_qb_stack:
    optimizer.add_stack(PositionsStack(('QB', 'WR')))
    optimizer.add_stack(PositionsStack(('QB', 'TE')))
    optimizer.add_stack(PositionsStack(('QB', 'RB')))
if game_stack_size > 0:
    optimizer.add_stack(GameStack(game_stack_size))

optimizer.set_fantasy_points_strategy(RandomFantasyPointsStrategy(max_deviation=0.05))

# --- Generate lineups ---
gen_btn = st.button("Generate Lineups")
if gen_btn:
    try:
        with st.spinner("Generating..."):
            lineups = list(optimizer.optimize(
                n=num_lineups,
                max_exposure=max_exposure,
                exposure_strategy=AfterEachExposureStrategy
            ))
        st.success(f"Generated {len(lineups)} lineup(s)")
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
        lineups = []

    if lineups:
        df_rows = []
        for lineup in lineups:
            row = {}
            for p in lineup.players:
                row[p.positions[0]] = f"{player_display_name(p)} ({p.id})"
            row["TotalSalary"] = lineup.salary_costs
            row["ProjectedPoints"] = lineup.fantasy_points
            df_rows.append(row)
        result_df = pd.DataFrame(df_rows)
        st.dataframe(result_df)
        st.download_button("Download Lineups CSV", result_df.to_csv(index=False), "lineups.csv")
