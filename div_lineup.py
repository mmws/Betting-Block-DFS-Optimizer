import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player
from itertools import combinations
from collections import Counter

st.set_page_config(page_title="DFS Optimizer")

# --- helpers ---------------------------------------------------------------
def parse_salary(s):
    try:
        return float(str(s).replace('$', '').replace(',', '').strip())
    except:
        return None

def safe_float(x):
    try:
        return float(x) if not pd.isna(x) else 0.0
    except:
        return 0.0

def player_display_name(p):
    return f"{p.first_name} {p.last_name} ({p.id})".strip()

# --- UI -------------------------------------------------------------------
st.title("DFS Optimizer")
uploaded_file = st.file_uploader("Upload DraftKings NFL CSV (Name + ID, Roster Position, Salary, TeamAbbrev, AvgPointsPerGame)", type=["csv"])
if not uploaded_file:
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Error reading CSV: {e}")
    st.stop()

# --- build players --------------------------------------------------------
players = []
skipped = 0
for _, row in df.iterrows():
    try:
        player_id = str(row.get("ID", row.get("Name + ID", "r" + str(_))))
        name = str(row.get("Name + ID", "Unknown")).split(" (")[0].split(" ", 1)
        first_name = name[0]
        last_name = name[1] if len(name) > 1 else ""
        positions = [p.strip() for p in str(row.get("Roster Position", "")).split("/")]
        team = str(row.get("TeamAbbrev", ""))
        salary = parse_salary(row.get("Salary"))
        fppg = safe_float(row.get("AvgPointsPerGame"))
        if salary is None or not positions or positions == [""]:
            skipped += 1
            continue
        players.append(Player(player_id, first_name, last_name, positions, team, salary, fppg))
    except:
        skipped += 1
        continue

st.write(f"Loaded {len(players)} players (skipped {skipped})")
if not players:
    st.error("No valid players!")
    st.stop()

optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
optimizer.player_pool.load_players(players)

# --- generate lineups ------------------------------------------------------
num_lineups = st.slider("Number of lineups", 1, 150, 150)
max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
min_salary = st.number_input("Min salary", value=49000, min_value=0, max_value=50000)
max_salary = st.number_input("Max salary", value=50000, min_value=0, max_value=50000)
max_player_pairs = st.slider("Max player pair appearances", 1, num_lineups, 5)

if st.button("Generate"):
    with st.spinner("Generating..."):
        try:
            generate_n = min(num_lineups * 5, 1500)
            lineups = list(optimizer.optimize(n=generate_n, max_exposure=max_exposure))
            st.write(f"Initially generated {len(lineups)} lineups")
            
            # Filter by salary range
            salary_filtered = [lineup for lineup in lineups if min_salary <= sum(p.salary for p in lineup.players) <= max_salary]
            st.write(f"{len(salary_filtered)} lineups after salary filter ({min_salary}-{max_salary})")
            
            # Filter by max player pairs
            filtered_lineups = salary_filtered
            if max_player_pairs < num_lineups:
                pair_counts = {}
                selected_lineups = []
                for lineup in sorted(salary_filtered, key=lambda x: sum(p.fppg for p in x.players), reverse=True):
                    players = lineup.players
                    pairs = list(combinations([p.id for p in players], 2))
                    temp_counts = pair_counts.copy()
                    for pair in pairs:
                        temp_counts[pair] = temp_counts.get(pair, 0) + 1
                    if all(count <= max_player_pairs for count in temp_counts.values()):
                        selected_lineups.append(lineup)
                        pair_counts = temp_counts
                    if len(selected_lineups) >= num_lineups:
                        break
                filtered_lineups = selected_lineups[:num_lineups]
            st.write(f"{len(filtered_lineups)} lineups after pair filter (max {max_player_pairs})")
            
            # Summarize top player pairs
            pair_counts_display = Counter()
            for lineup in filtered_lineups:
                players = lineup.players
                pairs = list(combinations([player_display_name(p) for p in players], 2))
                pair_counts_display.update(pairs)
            if pair_counts_display:
                st.write("Most common player pairs:")
                for pair, count in pair_counts_display.most_common(5):
                    st.write(f"{pair[0]} & {pair[1]}: {count} times")
        except Exception as e:
            st.error(f"Error generating lineups: {e}")
            st.stop()

    st.success(f"Generated {len(filtered_lineups)} lineup(s)")
    if len(filtered_lineups) < num_lineups:
        st.warning(f"Only {len(filtered_lineups)} lineups generated (requested {num_lineups}). Try increasing max player pairs or widening salary range.")

    # --- convert to wide format ------------------------------------------------
    wide_rows = []
    position_order = ["QB", "RB", "RB_1", "WR", "WR_1", "WR_2", "TE", "FLEX", "DST"]
    for lineup in filtered_lineups:
        lineup_players = lineup.players
        row = {}
        assigned_players = []
        qb = [p for p in lineup_players if "QB" in p.positions]
        rb = [p for p in lineup_players if "RB" in p.positions]
        wr = [p for p in lineup_players if "WR" in p.positions]
        te = [p for p in lineup_players if "TE" in p.positions]
        dst = [p for p in lineup_players if "DST" in p.positions]
        flex = [p for p in lineup_players if any(pos in p.positions for pos in ["RB", "WR", "TE"])]

        if len(qb) >= 1 and len(rb) >= 2 and len(wr) >= 3 and len(te) >= 1 and len(dst) >= 1 and len(flex) >= 1:
            row["QB"] = player_display_name(qb[0])
            assigned_players.append(qb[0])
            row["RB"] = player_display_name(rb[0])
            row["RB_1"] = player_display_name(rb[1])
            assigned_players.extend(rb[:2])
            row["WR"] = player_display_name(wr[0])
            row["WR_1"] = player_display_name(wr[1])
            row["WR_2"] = player_display_name(wr[2])
            assigned_players.extend(wr[:3])
            row["TE"] = player_display_name(te[0])
            assigned_players.append(te[0])
            for p in flex:
                if p not in assigned_players:
                    row["FLEX"] = player_display_name(p)
                    assigned_players.append(p)
                    break
            row["DST"] = player_display_name(dst[0])
            row["TotalSalary"] = sum(p.salary for p in lineup_players)
            row["ProjectedPoints"] = sum(p.fppg for p in lineup_players)
            wide_rows.append(row)

    if not wide_rows:
        st.error("No lineups match constraints! Check CSV data or relax salary/pair limits.")
        st.stop()

    df_wide = pd.DataFrame(wide_rows, columns=position_order + ["TotalSalary", "ProjectedPoints"])
    st.markdown("### Lineups")
    st.dataframe(df_wide)
    csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")
