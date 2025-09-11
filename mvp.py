import streamlit as st
import pandas as pd
from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player
from itertools import combinations

st.set_page_config(page_title="DFS Optimizer", layout="wide")

# --- helpers ---------------------------------------------------------------
def parse_salary(s) -> float:
    try:
        return float(str(s).replace('$', '').replace(',', '').strip())
    except:
        return None

def safe_float(x) -> float:
    try:
        return float(x) if not pd.isna(x) else 0.0
    except:
        return 0.0

def player_display_name(p) -> str:
    return f"{p.first_name} {p.last_name} ({p.id})".strip()

# --- UI -------------------------------------------------------------------
st.title("DFS Optimizer")
st.write("Upload a DraftKings NFL salary CSV with columns: Name, Position, Salary, Team, avgpointspergame")
uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded_file:
    st.stop()

try:
    df = pd.read_csv(uploaded_file)
except Exception as e:
    st.error(f"Error reading CSV: {e}")
    st.stop()

# --- build players --------------------------------------------------------
players = []
for _, row in df.iterrows():
    try:
        player_id = str(row.get("ID", row.get("Name", "r" + str(_))))
        name = str(row.get("Name", "Unknown")).split(" ", 1)
        first_name = name[0]
        last_name = name[1] if len(name) > 1 else ""
        positions = [p.strip() for p in str(row.get("Position", "")).split("/")]
        team = str(row.get("Team", ""))
        salary = parse_salary(row.get("Salary"))
        fppg = safe_float(row.get("avgpointspergame"))
        if salary is None:
            continue
        players.append(Player(player_id, first_name, last_name, positions, team, salary, fppg))
    except:
        continue

if not players:
    st.error("No valid players in CSV!")
    st.stop()

optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
optimizer.player_pool.load_players(players)

# --- generate lineups ------------------------------------------------------
num_lineups = st.slider("Number of lineups", 1, 150, 50)
max_exposure = st.slider("Max exposure per player", 0.0, 1.0, 0.3)
min_salary = st.number_input("Min total salary", value=49000, min_value=0, max_value=50000)
max_salary = st.number_input("Max total salary", value=50000, min_value=0, max_value=50000)
max_player_pairs = st.slider("Max times any two players appear together", 1, num_lineups, min(15, num_lineups))

if st.button("Generate lineups"):
    with st.spinner("Generating..."):
        try:
            # Generate more lineups initially
            generate_n = min(num_lineups * 5, 1500)
            lineups = list(optimizer.optimize(n=generate_n, max_exposure=max_exposure))
            
            # Filter by salary range
            salary_filtered = [
                lineup for lineup in lineups
                if min_salary <= sum(p.salary for p in lineup.players) <= max_salary
            ]
            
            # Filter by max player pairs
            filtered_lineups = salary_filtered
            if max_player_pairs < num_lineups:
                pair_counts = {}
                selected_lineups = []
                sorted_lineups = sorted(salary_filtered, key=lambda x: sum(p.fppg for p in x.players), reverse=True)
                for lineup in sorted_lineups:
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
        qb_players = [p for p in lineup_players if "QB" in p.positions]
        rb_players = [p for p in lineup_players if "RB" in p.positions]
        wr_players = [p for p in lineup_players if "WR" in p.positions]
        te_players = [p for p in lineup_players if "TE" in p.positions]
        dst_players = [p for p in lineup_players if "DST" in p.positions]
        flex_players = [p for p in lineup_players if any(pos in p.positions for pos in ["RB", "WR", "TE"])]

        if qb_players:
            row["QB"] = player_display_name(qb_players[0])
            assigned_players.append(qb_players[0])
        if len(rb_players) >= 2:
            row["RB"] = player_display_name(rb_players[0])
            row["RB_1"] = player_display_name(rb_players[1])
            assigned_players.extend(rb_players[:2])
        if len(wr_players) >= 3:
            row["WR"] = player_display_name(wr_players[0])
            row["WR_1"] = player_display_name(wr_players[1])
            row["WR_2"] = player_display_name(wr_players[2])
            assigned_players.extend(wr_players[:3])
        if te_players:
            row["TE"] = player_display_name(te_players[0])
            assigned_players.append(te_players[0])
        if flex_players:
            for p in flex_players:
                if p not in assigned_players:
                    row["FLEX"] = player_display_name(p)
                    assigned_players.append(p)
                    break
        if dst_players:
            row["DST"] = player_display_name(dst_players[0])
            assigned_players.append(dst_players[0])

        if len(row) != len(position_order):
            continue

        row["TotalSalary"] = sum(p.salary for p in lineup_players)
        row["ProjectedPoints"] = sum(p.fppg for p in lineup_players)
        wide_rows.append(row)

    if not wide_rows:
        st.error("No lineups match the constraints! Try widening salary range or increasing max player pairs.")
        st.stop()

    df_wide = pd.DataFrame(wide_rows, columns=position_order + ["TotalSalary", "ProjectedPoints"])
    st.markdown("### Lineups")
    st.dataframe(df_wide)
    csv_bytes = df_wide.to_csv(index=False).encode("utf-8")
    st.download_button("Download lineups CSV", csv_bytes, file_name="lineups.csv", mime="text/csv")