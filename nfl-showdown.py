import streamlit as st
import pandas as pd
import re
from typing import Optional, Tuple, List
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

st.set_page_config(page_title="The Betting Block DFS Optimizer - Captain Mode", layout="wide")

# --- Config / mappings ---
SITE_MAP = {
    "DraftKings NFL Captain Mode": (Site.DRAFTKINGS_CAPTAIN_MODE, Sport.FOOTBALL),
}

NFL_CAPTAIN_POSITION_HINTS = {"CPT", "UTIL"}

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
        if posset & NFL_CAPTAIN_POSITION_HINTS:
            return "NFL Captain Mode"
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
st.title("The Betting Block DFS Optimizer - Captain Mode")
st.write("Upload a salary CSV exported from DraftKings for NFL Captain Mode.")
uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"])
if not uploaded_file:
    st.info("Upload a CSV (e.g. DKCaptainSalaries.csv). The app will try to auto-detect.")
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
    st.warning("Could not auto-detect. Please choose manually.")
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
max_repeating_players = st.slider("Max repeating players", 0, 5, 2)
min_salary = st.slider("Minimum Salary Cap", 40000, 50000, 49000)
optimizer.set_max_repeating_players(max_repeating_players)
optimizer.set_min_salary_cap(min_salary)
gen_btn = st.button("Generate lineups")

# --- generate lineups ---
if gen_btn:
    try:
        with st.spinner("Generating..."):
            lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure))
        st.success(f"Generated {len(lineups)} lineup(s)")
    except Exception as e:
        st.error(f"Error generating lineups: {e}")
        lineups = []
    if lineups:
        # --- map positions safely for Captain Mode ---
        position_columns = {
            "CPT": ["CPT"],
            "UTIL": ["UTIL1", "UTIL2", "UTIL3", "UTIL4", "UTIL5"],
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
            # ensure all columns exist
            for col in ["CPT", "UTIL1", "UTIL2", "UTIL3", "UTIL4", "UTIL5"]:
                if col not in row: row[col] = ""
            row["TotalSalary"] = sum(getattr(p,"salary",0) for p in lineup.players)
            row["ProjectedPoints"] = sum(safe_float(getattr(p,"fppg",0)) for p in lineup.players)
            df_rows.append(row)
        df_wide = pd.DataFrame(df_rows)
        st.markdown("### Lineups (wide)")
        st.dataframe(df_wide)
        csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
        st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
