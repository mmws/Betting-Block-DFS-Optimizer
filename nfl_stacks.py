# app.py
import streamlit as st
import pandas as pd
import re
from collections import Counter
from typing import Optional, Tuple, List

from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player
from pydfs_lineup_optimizer.stacks import GameStack, TeamStack, PositionsStack


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

# --- helpers ---
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
    st.info("Upload a CSV (e.g. DKSalaries.csv). The app will try to auto-detect site & sport.")
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("**Preview (first 10 rows):**")
st.dataframe(df.head(10))

# --- detect columns ---
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
game = find_column(df, ["Game Info"]  # e.g. "LV@IND 10/05/2025 01:00PM ET"
opponent = game.split(' ')[0].split('@')[1]  # take part after '@'
game_info = f"{team}@{opponent}

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

# --- build players ---
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
            parts = str(row[name_col]).split(" ",1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts)>1 else ""
        elif name_plus_id_col:
            parsed_name,_ = parse_name_and_id_from_field(row[name_plus_id_col])
            parts = parsed_name.split(" ",1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts)>1 else ""
        else:
            first_name = str(row.get(name_col, f"Player{idx}"))
            last_name = ""

        raw_pos = str(row[pos_col]).strip() if pos_col and not pd.isna(row[pos_col]) else None
        positions = [p.strip() for p in re.split(r'[\/\|,]', raw_pos)] if raw_pos else []

        team = str(row[team_col]).strip() if team_col and not pd.isna(row[team_col]) else None
        salary = parse_salary(row[salary_col]) if salary_col else None
        fppg = safe_float(row[fppg_col]) if fppg_col else None

        if salary is None:
            skipped += 1
            continue

        players.append(Player(player_id, first_name, last_name, positions or None, team, salary, fppg or 0.0))
    except:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if len(players)==0: st.error("No valid players!"); st.stop()

optimizer.player_pool.load_players(players)

# --- lineup settings ---
num_lineups = st.slider("Number of lineups", 1, 200, 5)
max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
max_repeating_players = st.slider("Max repeating players", 0, 6, 2)
optimizer.set_max_repeating_players(max_repeating_players)

# --- stacking options ---
st.markdown("### Stacking Options")
enable_qb_wr = st.checkbox("QB + WR stack", value=True)
enable_qb_rb = st.checkbox("QB + RB stack", value=False)
enable_qb_te = st.checkbox("QB + TE stack", value=False)
enable_qb_rb_wr = st.checkbox("QB + RB + WR Stack", value=False)
enable_qb_rb_te = st.checkbox("QB + RB + TE Stack", value=False)
enable_qb_wr_wr = st.checkbox("QB + WR + WR Stack", value=False)
enable_qb_te_wr = st.checkbox("QB + WR + TE Stack", value=False)
enable_team_stack = st.checkbox("Team stack (3 players: QB/WR/TE)", value=True)
enable_game_stack = st.checkbox("Game stack (3 players, min 1 from opponent)", value=False)
no_double_rb = st.checkbox("Restrict 2 RBs from same team", value=True)
no_dst_vs_offense = st.checkbox("No DST vs offensive players", value=False)
# enable_runback = st.checkbox("Enable Runback", value=False)
# Streamlit dropdown for minimum salary (scalable by 100, max 50000)
min_salary_options = list(range(48000, 50001, 100))  # starts at 40000, ends at 50000
min_salary = st.selectbox("Select Minimum Salary for Lineups", min_salary_options, index=len(min_salary_options)-1)



gen_btn = st.button("Generate")  # define first

if gen_btn:
    st.write("Generating lineups...")
    # your lineup generation code here
    try:
        # Apply stacking rules before optimization
        if enable_qb_wr:
            optimizer.add_stack(PositionsStack(['QB', 'WR']))
        if enable_qb_rb:
            optimizer.add_stack(PositionsStack(['QB', 'RB']))
        if enable_qb_rb_wr:
            optimizer.add_stack(PositionsStack(['QB', 'RB', 'WR']))
        if enable_qb_rb_te:
            optimizer.add_stack(PositionsStack(['QB', 'RB', 'TE']))    
        if enable_qb_wr_wr:
            optimizer.add_stack(PositionsStack(['QB', 'WR', 'WR']))  
        if enable_qb_te_wr:
            optimizer.add_stack(PositionsStack(['QB', 'TE', 'WR'])) 
        if enable_qb_te:
            optimizer.add_stack(PositionsStack(['QB', 'TE']))
        if enable_team_stack:
            optimizer.add_stack(TeamStack(3, for_positions=['QB', 'WR', 'TE']))
        if enable_game_stack:
            optimizer.add_stack(GameStack(3, min_from_team=1))
        if no_double_rb:
            optimizer.restrict_positions_for_same_team(("RB", "RB"))
        if no_dst_vs_offense:
             # DST cannot be on a team against any offensive players in the lineup
            optimizer.restrict_positions_for_opposing_team(['DST'], ['QB', 'WR', 'RB', 'TE'])
            # if enable_runback:
            # Apply runback stack
            # optimizer.force_positions_for_opposing_team expects a tuple of positions
            # optimizer.force_positions_for_opposing_team(('QB','WR'))
        if min_salary:
            optimizer.set_min_salary_cap(min_salary)

        with st.spinner("Generating..."):
            lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure))
        st.success(f"Generated {len(lineups)} lineup(s)")
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
        lineups = []

    if lineups:
        # --- map positions safely ---
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
                        row[col] = f"{player_display_name(p)}({p.id})"
                        pos_counter[pos] += 1
                        assigned = True
                        break
                if not assigned:
                    if pos_counter["FLEX"] < 1:
                        row["FLEX"] = f"{player_display_name(p)}({p.id})"
                        pos_counter["FLEX"] += 1

            for col in ["QB","RB","RB1","WR","WR1","WR2","TE","FLEX","DST"]:
                if col not in row: row[col] = ""

            row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
            row["ProjectedPoints"] = sum(safe_float(getattr(p,"fppg",0)) for p in lineup.players)
            df_rows.append(row)

        df_wide = pd.DataFrame(df_rows)
        st.markdown("### Lineups (wide)")
        st.dataframe(df_wide)

        csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
        st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
