import streamlit as st
import pandas as pd
import re
import random
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

# --- Diversification logic ---
def diversify_lineups_wide(df_wide, salary_df, max_exposure=0.4, max_pair_exposure=0.6,
                           randomness=0.15, salary_cap=50000, salary_min=49500):
    diversified = df_wide.copy()
    total_lineups = len(diversified)
    player_info = {}
    for _, row in salary_df.iterrows():
        try:
            fppg = float(row.get("AvgPointsPerGame", 0))
            if fppg < 0: fppg = 0
            player_info[row["Name"]] = {
                "team": str(row.get("TeamAbbrev", "")),
                "salary": float(row.get("Salary", 0)),
                "fppg": fppg,
                "position": str(row.get("Position", ""))
            }
        except: continue
    exposure = Counter()
    pair_exposure = Counter()
    for i in range(total_lineups):
        lineup_players = []
        for col in diversified.columns:
            if col in ["TotalSalary", "ProjectedPoints"]: continue
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
            if col in ["TotalSalary", "ProjectedPoints"]: continue
            val = diversified.at[lineup_idx, col]
            if not isinstance(val, str): continue
            name = val.split("(")[0].strip()
            if name not in player_info: continue
            player_exp = exposure[name] / total_lineups
            lineup_pairs = [tuple(sorted([name, p])) for p in lineup_players if p != name]
            pair_flags = [pair_exposure[pair] / total_lineups > max_pair_exposure for pair in lineup_pairs]
            if player_exp > max_exposure or any(pair_flags):
                if random.random() < randomness:
                    current_pos = player_info[name]["position"]
                    possible_replacements = [p for p in player_info.keys() if p != name and player_info[p]["position"] == current_pos]
                    random.shuffle(possible_replacements)
                    for candidate in possible_replacements:
                        temp_lineup = diversified.loc[lineup_idx].copy()
                        temp_lineup[col] = f"{candidate} ({player_info[candidate]['team']})"
                        lineup_salary, lineup_points = 0, 0
                        temp_players = []
                        pos_counts = {"QB":0,"RB":0,"WR":0,"TE":0,"DST":0}
                        for pos in diversified.columns:
                            if pos in ["TotalSalary","ProjectedPoints"]: continue
                            val2 = temp_lineup[pos]
                            if isinstance(val2,str):
                                nm = val2.split("(")[0].strip()
                                if nm in player_info:
                                    temp_players.append(nm)
                                    lineup_salary += player_info[nm]["salary"]
                                    lineup_points += player_info[nm]["fppg"]
                                    pos_counts[player_info[nm]["position"]] += 1
                        valid_positions = (pos_counts["QB"]==1 and 2<=pos_counts["RB"]<=3 and 3<=pos_counts["WR"]<=4 and pos_counts["TE"]==1 and pos_counts["DST"]==1)
                        if salary_min <= lineup_salary <= salary_cap and valid_positions:
                            new_pairs = [tuple(sorted([a,b])) for i,a in enumerate(temp_players) for b in temp_players[i+1:]]
                            if all((pair_exposure[pair]+1)/total_lineups <= max_pair_exposure for pair in new_pairs):
                                diversified.loc[lineup_idx, col] = f"{candidate} ({player_info[candidate]['team']})"
                                diversified.at[lineup_idx,"TotalSalary"] = lineup_salary
                                diversified.at[lineup_idx,"ProjectedPoints"] = lineup_points
                                exposure[name] -= 1
                                exposure[candidate] += 1
                                for pair in lineup_pairs: pair_exposure[pair] -=1
                                for pair in new_pairs: pair_exposure[pair] +=1
                                break
    return diversified

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
id_col = find_column(df, ["id","playerid","player_id","ID"])
name_plus_id_col = find_column(df, ["name + id","name+id","name_plus_id","name_id","nameandid"])
name_col = find_column(df, ["name","full_name","player"])
first_col = find_column(df, ["first_name","firstname","first"])
last_col = find_column(df, ["last_name","lastname","last"])
pos_col = find_column(df, ["position","positions","pos","roster position","rosterposition","roster_pos"])
salary_col = find_column(df, ["salary","salary_usd"])
team_col = find_column(df, ["team","teamabbrev","team_abbrev","teamabbr"])
fppg_col = find_column(df, ["avgpointspergame","avgpoints","fppg","projectedpoints","proj"])
game_info_col = find_column(df, ["game info","gameinfo","game"])

guessed_sport = guess_sport_from_positions(df[pos_col]) if pos_col else None
auto_choice = f"{detected_site} {guessed_sport}" if detected_site and guessed_sport and f"{detected_site} {guessed_sport}" in SITE_MAP else None

st.markdown("### Auto-detect diagnostics")
st.write({
    "filename": getattr(uploaded_file,"name",None),
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
for idx,row in df.iterrows():
    try:
        player_id = str(row[id_col]).strip() if id_col and not pd.isna(row[id_col]) else None
        if not player_id and name_plus_id_col:
            _, player_id = parse_name_and_id_from_field(row[name_plus_id_col])
        if not player_id: player_id = f"r{idx}"
        if first_col and last_col:
            first_name = str(row[first_col]).strip()
            last_name = str(row[last_col]).strip()
        elif name_col:
            parts = str(row[name_col]).split(" ",1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts)>1 else "" if row[pos_col]!="DST" else row[name_col]
        elif name_plus_id_col:
            parsed_name,_ = parse_name_and_id_from_field(row[name_plus_id_col])
            parts = parsed_name.split(" ",1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts)>1 else "" if row[pos_col]!="DST" else parsed_name
        else:
            first_name = str(row.get(name_col,f"Player{idx}"))
            last_name = ""
        raw_pos = str(row[pos_col]).strip() if pos_col and not pd.isna(row[pos_col]) else None
        positions = [p.strip() for p in re.split(r'[\/\|,]',raw_pos)] if raw_pos else []
        team = str(row[team_col]).strip() if team_col and not pd.isna(row[team_col]) else None
        salary = parse_salary(row[salary_col]) if salary_col else None
        fppg = safe_float(row[fppg_col]) if fppg_col else None
        from pydfs_lineup_optimizer.players import Game
        raw_game_info = str(row[game_info_col]).strip() if game_info_col and not pd.isna(row[game_info_col]) else None
        game_info = None
        if raw_game_info:
        try:
            m = re.match(r"(\w+)@(\w+)", raw_game_info)
        if m:
            away, home = m.groups()
            game_info = Game(home_team=home.strip(), away_team=away.strip())
        except:
            game_info = None  # fallback if parsing fails

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
    except: skipped+=1; continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if len(players)==0:
    st.error("No valid players loaded! Check CSV data.")
    st.stop()

optimizer.player_pool.load_players(players)

# --- Lineup settings ---
st.markdown("### Lineup Settings")
col1,col2 = st.columns(2)
with col1:
    num_lineups = st.slider("Number of lineups",1,200,10)
    max_exposure = st.slider("Max exposure per player",0.0,1.0,0.3)
with col2:
    min_salary = st.number_input("Minimum Salary",value=49500,step=500)
    max_players_per_team = st.number_input("Max Players per Team",value=4,step=1)
    game_stack_size = st.slider("Game Stack Size (Players)",0,5,0)

use_advanced_constraints = st.checkbox("Use Advanced Constraints (QB+WR/TE/RB Stack, No Two RBs, WR/TE/RB Opp Stack)", value=True)
qb_stack = no_two_rbs = opp_stack = False
if use_advanced_constraints:
    col3,col4 = st.columns(2)
    with col3:
        qb_stack = st.checkbox("QB + WR/TE/RB Stack", value=True)
    with col4:
        no_two_rbs = st.checkbox("No Two RBs from Same Team", value=True)
        opp_stack = st.checkbox("WR/TE/RB Opposing Team Bringback", value=True)

optimizer.set_min_salary_cap(min_salary)
optimizer.set_max_repeating_players(2)
optimizer.set_fantasy_points_strategy(RandomFantasyPointsStrategy(max_deviation=0.05))

# --- Stacks & team constraints ---
if qb_stack:
    optimizer.add_stack(PositionsStack(('QB','WR')))
    optimizer.add_stack(PositionsStack(('QB','TE')))
    optimizer.add_stack(PositionsStack(('QB','RB')))
if no_two_rbs:
    for team in df["TeamAbbrev"].unique():
        optimizer.restrict_positions_for_same_team(('RB','RB'))
if opp_stack:
    optimizer.force_positions_for_opposing_team(('WR','WR'))
    optimizer.force_positions_for_opposing_team(('WR','TE'))
    optimizer.force_positions_for_opposing_team(('WR','RB'))
if game_stack_size>0:
    optimizer.add_stack(GameStack(game_stack_size))
if max_players_per_team>0:
    optimizer.add_stack(TeamStack(max_players_per_team))

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
        position_columns = {"QB":["QB"],"RB":["RB","RB1"],"WR":["WR","WR1","WR2"],"TE":["TE"],"FLEX":["FLEX"],"DST":["DST"]}
        df_rows = []
        for lineup in lineups:
            row = {}
            pos_counter = {k:0 for k in position_columns.keys()}
            for p in lineup.players:
                assigned=False
                for pos in p.positions or []:
                    if pos in position_columns and pos_counter[pos]<len(position_columns[pos]):
                        col = position_columns[pos][pos_counter[pos]]
                        row[col] = f"{player_display_name(p)} ({p.id})"
                        pos_counter[pos]+=1
                        assigned=True
                        break
                if not assigned:
                    if pos_counter["FLEX"]<1:
                        row["FLEX"] = f"{player_display_name(p)} ({p.id})"
                        pos_counter["FLEX"]+=1
            row["TotalSalary"] = lineup.salary_cost
            row["ProjectedPoints"] = lineup.fantasy_points
            df_rows.append(row)
        lineup_df = pd.DataFrame(df_rows)
        st.dataframe(lineup_df)
        st.markdown("### Export CSV")
        csv = lineup_df.to_csv(index=False)
        st.download_button("Download Lineups CSV", data=csv, file_name="dfs_lineups.csv", mime="text/csv")


