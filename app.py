# app.py
import streamlit as st
import pandas as pd
import re
import io
from typing import Optional, Tuple, List

from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

st.set_page_config(page_title="PyDFS Streamlit Optimizer", layout="wide")


# --- Config / mappings -----------------------------------------------------
SITE_MAP = {
    "DraftKings NFL": (Site.DRAFTKINGS, Sport.FOOTBALL),
    "FanDuel NFL": (Site.FANDUEL, Sport.FOOTBALL),
    "DraftKings NBA": (Site.DRAFTKINGS, Sport.BASKETBALL),
    "FanDuel NBA": (Site.FANDUEL, Sport.BASKETBALL),
}

NFL_POSITION_HINTS = {"QB", "RB", "WR", "TE", "K", "DST"}
NBA_POSITION_HINTS = {"PG", "SG", "SF", "PF", "C", "G", "F"}


# --- helpers ---------------------------------------------------------------
def normalize_colname(c: str) -> str:
    """Normalize a column name for fuzzy matching."""
    return re.sub(r'[^a-z0-9]', '', c.lower())


def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Return the actual column name in df that matches any candidate (fuzzy)."""
    norm_map = {normalize_colname(c): c for c in df.columns}
    for cand in candidates:
        n = normalize_colname(cand)
        if n in norm_map:
            return norm_map[n]
    # try substring match
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
    # series expected to contain position strings like "QB", "RB/WR", "PG", "SG"
    if series is None:
        return None
    try:
        # explode slash-separated positions and uppercase
        all_pos = (
            series.dropna()
                  .astype(str)
                  .str.replace(' ', '')
                  .str.upper()
                  .str.split('/')
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
    """
    Try a few patterns in 'Name + ID' columns like:
      "Tom Brady - 12345", "Tom Brady (12345)", "Tom Brady | 12345"
    Return (name, id or None)
    """
    s = str(val).strip()
    # parentheses: "Tom Brady (1234)"
    m = re.match(r'^(.*?)\s*\((\d+)\)\s*$', s)
    if m:
        return m.group(1).strip(), m.group(2)
    # dash or pipe or slash at end: "Name - 1234" or "Name | 1234"
    m = re.match(r'^(.*?)\s*[-\|\/]\s*(\d+)\s*$', s)
    if m:
        return m.group(1).strip(), m.group(2)
    # trailing numeric token: "Name 12345"
    m = re.match(r'^(.*\D)\s+(\d+)\s*$', s)
    if m:
        return m.group(1).strip(), m.group(2)
    # fallback: no id
    return s, None


def parse_salary(s) -> Optional[float]:
    if pd.isna(s):
        return None
    try:
        t = str(s).replace('$', '').replace(',', '').strip()
        if t == '':
            return None
        return float(t)
    except Exception:
        return None


def safe_float(x) -> Optional[float]:
    try:
        if pd.isna(x): return None
        return float(x)
    except Exception:
        try:
            return float(str(x).replace(',', '').strip())
        except Exception:
            return None


def player_display_name(p) -> str:
    """Robust display for Player-like objects"""
    # Player object from pydfs may have first_name/last_name or full_name attributes
    fn = getattr(p, "first_name", None)
    ln = getattr(p, "last_name", None)
    if fn or ln:
        return f"{fn or ''} {ln or ''}".strip()
    full = getattr(p, "full_name", None)
    if full:
        return full
    # last resort
    return str(p)


# --- UI -------------------------------------------------------------------
st.title("PyDFS Streamlit Optimizer — improved auto-detect + CSV export")
st.write("Upload a salary CSV exported from DraftKings or FanDuel (NFL/NBA).")

uploaded_file = st.file_uploader("Upload salary CSV", type=["csv"], help="CSV exported from DK or FD salary tools")

if not uploaded_file:
    st.info("Upload a CSV (e.g. `DKSalaries.csv`). The app will try to auto-detect site & sport.")
    st.stop()

# read CSV (don't modify original columns; keep raw headers)
try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

st.markdown("**Preview (first 10 rows):**")
st.dataframe(df.head(10))


# --- intelligent detection -------------------------------------------------
detected_site = guess_site_from_filename(getattr(uploaded_file, "name", None))
# detect columns we care about (many variants supported)
id_col = find_column(df, ["id", "playerid", "player_id", "ID"])
name_plus_id_col = find_column(df, ["name + id", "name+id", "name_plus_id", "name_id", "nameandid"])
name_col = find_column(df, ["name", "full_name", "player"])
first_col = find_column(df, ["first_name", "firstname", "first"])
last_col = find_column(df, ["last_name", "lastname", "last"])
pos_col = find_column(df, ["position", "positions", "pos", "roster position", "rosterposition", "roster_pos"])
salary_col = find_column(df, ["salary", "salary_usd"])
team_col = find_column(df, ["team", "teamabbrev", "team_abbrev", "teamabbr"])
fppg_col = find_column(df, ["avgpointspergame", "avgpoints", "fppg", "projectedpoints", "proj"])

# if we have 'Name + ID' but no id column, we can extract
if not id_col and name_plus_id_col:
    # test parse on a sample row
    test_name, test_id = parse_name_and_id_from_field(df[name_plus_id_col].astype(str).iloc[0]) if len(df) > 0 else (None, None)
    if test_id:
        st.info("Detected `Name + ID` header — will extract ID from that field when ID column not present.")
        # we'll fill id from that parsing when building players

# guess sport from position column values if possible
guessed_sport = None
if pos_col:
    guessed_sport = guess_sport_from_positions(df[pos_col])

# Compose a recommended auto-choice (Site + Sport)
auto_choice = None
if detected_site and guessed_sport:
    auto_choice = f"{detected_site} {guessed_sport}"
    if auto_choice not in SITE_MAP:
        auto_choice = None  # unexpected combination

st.markdown("### Auto-detect diagnostics")
st.write({
    "filename": getattr(uploaded_file, "name", None),
    "detected_site_from_filename": detected_site,
    "pos_column": pos_col,
    "guessed_sport_from_positions": guessed_sport,
    "fppg_column": fppg_col,
    "salary_column": salary_col,
    "name_column": name_col or name_plus_id_col,
    "id_column": id_col,
})

# Let user confirm or override
if auto_choice:
    st.success(f"Auto-detected: **{auto_choice}**")
    site_choice = st.selectbox("Site/sport (detected — change if wrong)", list(SITE_MAP.keys()), index=list(SITE_MAP.keys()).index(auto_choice))
else:
    st.warning("Could not confidently auto-detect site+sport. Please choose manually.")
    site_choice = st.selectbox("Site/sport", list(SITE_MAP.keys()))


site, sport = SITE_MAP[site_choice]
optimizer = get_optimizer(site, sport)


# --- build Player objects -------------------------------------------------
players = []
skipped = 0
for idx, row in df.iterrows():
    try:
        # determine id
        player_id = None
        if id_col and not pd.isna(row[id_col]):
            player_id = str(row[id_col]).strip()
        elif name_plus_id_col and not pd.isna(row[name_plus_id_col]):
            _, extracted_id = parse_name_and_id_from_field(row[name_plus_id_col])
            if extracted_id:
                player_id = extracted_id
        else:
            # fallback to idx-based id to keep uniqueness; pydfs accepts string id
            player_id = f"r{idx}"

        # name fields
        if first_col and last_col:
            first_name = str(row[first_col]).strip()
            last_name = str(row[last_col]).strip()
        elif name_col:
            raw_name = str(row[name_col])
            parts = raw_name.split(" ", 1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts) > 1 else ""
        elif name_plus_id_col:
            parsed_name, _ = parse_name_and_id_from_field(row[name_plus_id_col])
            parts = parsed_name.split(" ", 1)
            first_name = parts[0].strip()
            last_name = parts[1].strip() if len(parts) > 1 else ""
        else:
            # not enough name info
            first_name = str(row.get(name_col, f"Player{idx}"))
            last_name = ""

        # positions (allow slashed multi-positions)
        raw_pos = None
        if pos_col and not pd.isna(row[pos_col]):
            raw_pos = str(row[pos_col]).strip()
        else:
            # fallback: Roster Position column name variant
            rp = find_column(df, ["roster position", "rosterposition", "rosterpos", "roster_pos"])
            raw_pos = str(row[rp]).strip() if rp and not pd.isna(row[rp]) else None

        # normalize to list
        if raw_pos and raw_pos != "nan":
            positions = [p.strip() for p in re.split(r'[\/\|,]', raw_pos) if p.strip()]
        else:
            positions = []

        # team
        team = str(row[team_col]).strip() if team_col and not pd.isna(row[team_col]) else None

        # salary & fppg
        salary = parse_salary(row[salary_col]) if salary_col else None
        fppg = safe_float(row[fppg_col]) if fppg_col else None

        # Skip players missing salary or position (depending on site rules)
        if salary is None:
            skipped += 1
            continue

        p = Player(player_id, first_name, last_name, positions or None, team, salary, fppg or 0.0)
        players.append(p)
    except Exception as e:
        skipped += 1
        st.warning(f"Skipping row #{idx} due to parse error: {e}")
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped} rows).")

if len(players) == 0:
    st.error("No valid players loaded. Check salary column and position column names/values.")
    st.stop()

# load into optimizer (future-safe API)
optimizer.player_pool.load_players(players)


# --- generate lineups -----------------------------------------------------
num_lineups = st.slider("Number of lineups to generate", 1, 50, 5)
gen_btn = st.button("Generate lineups")

if gen_btn:
    try:
        with st.spinner("Generating lineups..."):
            lineups = list(optimizer.optimize(n=num_lineups))
    except Exception as e:
        st.error(f"❌ Could not generate lineups: {e}")
        # show constraint error text if present
        st.stop()

    st.success(f"Generated {len(lineups)} lineup(s).")

    # Build a DataFrame for download: one row per player per lineup
    rows = []
    for li, lineup in enumerate(lineups, start=1):
        # lineup.players is typically a list of Player objects
        l_players = getattr(lineup, "players", None) or getattr(lineup, "_players", None) or list(lineup)
        # compute summary totals if present
        lineup_salary = getattr(lineup, "salary", None)
        lineup_fp = getattr(lineup, "fantasy_points", None)
        if lineup_salary is None:
            try:
                lineup_salary = sum([getattr(p, "salary", 0) for p in l_players])
            except Exception:
                lineup_salary = None
        if lineup_fp is None:
            try:
                lineup_fp = sum([safe_float(getattr(p, "fppg", 0)) for p in l_players])
            except Exception:
                lineup_fp = None

        for p in l_players:
            rows.append({
                "Lineup": li,
                "Player": player_display_name(p),
                "Position": "/".join(getattr(p, "positions", [])) if getattr(p, "positions", None) else getattr(p, "position", ""),
                "Salary": getattr(p, "salary", ""),
                "ProjectedPoints": getattr(p, "fppg", "") or "",
                "LineupSalary": lineup_salary,
                "LineupProjectedPoints": lineup_fp,
            })

    df_lineups = pd.DataFrame(rows)

    # show a compact view per lineup (grouped)
    st.markdown("### Lineups (grouped view)")
    grouped = df_lineups.groupby("Lineup").agg({
        "Player": lambda s: ", ".join(s),
        "Salary": "first",
        "LineupSalary": "first",
        "LineupProjectedPoints": "first"
    }).reset_index()
    grouped = grouped.rename(columns={"Player": "Players"})
    st.dataframe(grouped)

    # full table
    st.markdown("### Lineups (detailed)")
    st.dataframe(df_lineups)

    # CSV download
    csv_bytes = df_lineups.to_csv(index=False).encode("utf-8")
    st.download_button("Download lineups as CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
