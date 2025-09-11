# nfl.py
import streamlit as st
import pandas as pd
import random
from collections import Counter
from typing import Dict, Optional

from pydfs_lineup_optimizer import get_optimizer, Site, Sport, Player

st.set_page_config(page_title="NFL DFS Optimizer", layout="wide")
st.title("NFL DFS Optimizer — Generate + Diversify Lineups")

# ---------------- Helpers ----------------
def parse_salary(x):
    try:
        return float(str(x).replace("$", "").replace(",", ""))
    except:
        return 0

def safe_float(x):
    try:
        return float(x)
    except:
        return 0.0

def name_key(cell):
    """Extract name from cell like 'Joe Burrow(12345)' or 'Joe Burrow (TEAM)'"""
    if not isinstance(cell, str):
        return str(cell)
    return cell.split("(")[0].strip()

def player_display_name(p):
    fn = getattr(p, "first_name", None)
    ln = getattr(p, "last_name", None)
    if fn or ln:
        return f"{fn or ''} {ln or ''}".strip()
    full = getattr(p, "full_name", None)
    if full:
        return full
    name_alt = getattr(p, "name", None) or getattr(p, "fullName", None)
    if name_alt:
        return str(name_alt)
    return str(p)

# ---------------- Diversification ----------------
SLOT_TO_ALLOWED_POS = {
    "QB": ["QB"],
    "RB1": ["RB"],
    "RB2": ["RB"],
    "WR1": ["WR"],
    "WR2": ["WR"],
    "WR3": ["WR"],
    "TE": ["TE"],
    "FLEX": ["RB", "WR", "TE"],
    "DST": ["DST"],
}

def build_player_info(df: pd.DataFrame, name_col, pos_col, team_col, salary_col, fppg_col, id_col=None):
    info = {}
    for _, r in df.iterrows():
        name = str(r.get(name_col) or "").strip()
        pid = str(r.get(id_col)) if id_col and not pd.isna(r.get(id_col)) else None
        positions = [str(p).upper() for p in str(r.get(pos_col) or "").split("/") if p]
        team = str(r.get(team_col) or "")
        salary = parse_salary(r.get(salary_col))
        fppg = safe_float(r.get(fppg_col))
        info[name] = {"id": pid, "positions": positions, "team": team, "salary": salary, "fppg": fppg}
    return info

def compute_exposures(df):
    total = len(df)
    players = []
    pairs = []
    slot_cols = [c for c in df.columns if c not in ("TotalSalary", "ProjectedPoints")]
    for i in df.index:
        line_players = []
        for col in slot_cols:
            val = df.at[i, col]
            if isinstance(val, str) and val.strip():
                n = name_key(val)
                line_players.append(n)
                players.append(n)
        for a in range(len(line_players)):
            for b in range(a+1, len(line_players)):
                pairs.append(tuple(sorted([line_players[a], line_players[b]])))
    return Counter(players), Counter(pairs)

def diversify_lineups(df, player_info: Dict, max_exp=0.4, max_pair=0.6, randomness=0.15, salary_cap=50000, salary_min=49500):
    df = df.copy().reset_index(drop=True)
    total_lineups = len(df)
    if total_lineups == 0: 
        return df

    slot_cols = [c for c in df.columns if c not in ("TotalSalary", "ProjectedPoints")]
    exposure, pair_exp = compute_exposures(df)

    # Precompute candidates by slot
    candidates_by_slot = {}
    for slot, allowed in SLOT_TO_ALLOWED_POS.items():
        candidates_by_slot[slot] = [name for name, info in player_info.items() if any(p in allowed for p in info.get("positions", []))]

    for li in range(total_lineups):
        current_names = [name_key(df.at[li, c]) for c in slot_cols if isinstance(df.at[li, c], str)]
        for col in slot_cols:
            cell = df.at[li, col]
            if not isinstance(cell, str) or not cell.strip():
                continue
            name = name_key(cell)
            player_exp = exposure.get(name, 0)/total_lineups
            lineup_pairs = [tuple(sorted([name, other])) for other in current_names if other != name]
            pair_flag = any(pair_exp.get(p,0)/total_lineups > max_pair for p in lineup_pairs)

            if player_exp <= max_exp and not pair_flag:
                continue
            if random.random() > randomness:
                continue

            candidates = candidates_by_slot.get(col, [])
            random.shuffle(candidates)
            orig_name = name
            for cand in candidates:
                if cand == orig_name or cand in current_names:
                    continue
                # simulate replacement
                sim_players = [n for n in current_names if n != orig_name] + [cand]
                sim_salary = sum(player_info.get(n, {}).get("salary", 0) for n in sim_players)
                sim_points = sum(player_info.get(n, {}).get("fppg", 0) for n in sim_players)
                if not (salary_min <= sim_salary <= salary_cap):
                    continue
                # check pair exposure
                violates = False
                for a in range(len(sim_players)):
                    for b in range(a+1, len(sim_players)):
                        p = tuple(sorted([sim_players[a], sim_players[b]]))
                        prospective = pair_exp.get(p,0)
                        if p not in lineup_pairs:
                            prospective +=1
                        if prospective/total_lineups > max_pair:
                            violates = True
                            break
                    if violates: break
                if violates:
                    continue
                # accept replacement
                pid = player_info.get(cand, {}).get("id")
                team = player_info.get(cand, {}).get("team")
                new_cell = f"{cand}({pid})" if pid else f"{cand} ({team})" if team else cand
                df.at[li, col] = new_cell
                # update exposure
                exposure[orig_name] = max(0, exposure.get(orig_name,0)-1)
                exposure[cand] = exposure.get(cand,0)+1
                for other in current_names:
                    if other==orig_name: continue
                    old_pair = tuple(sorted([orig_name,other]))
                    new_pair = tuple(sorted([cand,other]))
                    pair_exp[old_pair] = max(0,pair_exp.get(old_pair,0)-1)
                    pair_exp[new_pair] = pair_exp.get(new_pair,0)+1
                # recalc totals
                current_names = [name_key(df.at[li, c]) for c in slot_cols if isinstance(df.at[li,c],str)]
                df.at[li,"TotalSalary"] = sum(player_info.get(n,{}).get("salary",0) for n in current_names)
                df.at[li,"ProjectedPoints"] = sum(player_info.get(n,{}).get("fppg",0) for n in current_names)
                break

    return df

# ---------------- Upload + Build ----------------
uploaded_file = st.file_uploader("Upload Salary CSV", type=["csv"])
if not uploaded_file:
    st.info("Upload salary CSV with columns: Name, Position, Team, Salary, FPPG")
    st.stop()

salary_df = pd.read_csv(uploaded_file)

name_col = "Name"
pos_col = "Position"
team_col = "Team"
salary_col = "Salary"
fppg_col = "FPPG"
id_col = None

player_info = build_player_info(salary_df, name_col, pos_col, team_col, salary_col, fppg_col, id_col)

# ---------------- Optimizer ----------------
optimizer = get_optimizer(Site.DRAFTKINGS, Sport.FOOTBALL)
players=[]
for idx,row in salary_df.iterrows():
    raw_name = str(row.get(name_col)).strip()
    positions = [row.get(pos_col).upper()] if pos_col else []
    team = str(row.get(team_col) or "")
    salary = parse_salary(row.get(salary_col))
    fppg = safe_float(row.get(fppg_col))
    pid = f"r{idx}"
    players.append(Player(pid, raw_name, "", positions, team, salary, fppg))
optimizer.player_pool.load_players(players)

# ---------------- UI ----------------
num_lineups = st.slider("Number of lineups", 1, 150, 10)
max_exposure = st.slider("Max player exposure", 0.0,1.0,0.4,0.05)
salary_min_buffer = st.number_input("Min lineup salary", 0, 50000, 49500, step=100)
salary_cap_ui = st.number_input("Max lineup salary",0,100000,50000, step=100)

if st.button("Generate Lineups"):
    lineups = list(optimizer.optimize(n=num_lineups, max_exposure=max_exposure))
    slot_order=["QB","RB1","RB2","WR1","WR2","WR3","TE","FLEX","DST"]
    wide_rows=[]
    for lineup in lineups:
        slot_map={s:"" for s in slot_order}
        assigned=set()
        for p in lineup.players:
            positions=[str(x).upper() for x in getattr(p,"positions",[])]
            pname = player_display_name(p)
            pid = getattr(p,"id","")
            pname_id = f"{pname}({pid})" if pid else pname
            if "QB" in positions and not slot_map["QB"]:
                slot_map["QB"]=pname_id; assigned.add(pname)
            elif "DST" in positions and not slot_map["DST"]:
                slot_map["DST"]=pname_id; assigned.add(pname)
            elif "TE" in positions and not slot_map["TE"]:
                slot_map["TE"]=pname_id; assigned.add(pname)
        # fill RB/WR/FLEX
        for p in lineup.players:
            pname = player_display_name(p)
            if pname in assigned: continue
            positions=[str(x).upper() for x in getattr(p,"positions",[])]
            if "RB" in positions:
                if not slot_map["RB1"]: slot_map["RB1"]=pname; assigned.add(pname); continue
                elif not slot_map["RB2"]: slot_map["RB2"]=pname; assigned.add(pname); continue
            if "WR" in positions:
                for s in ["WR1","WR2","WR3"]:
                    if not slot_map[s]: slot_map[s]=pname; assigned.add(pname); break
        # FLEX
        for p in lineup.players:
            pname = player_display_name(p)
            if pname in assigned: continue
            slot_map["FLEX"]=pname; assigned.add(pname)
        names_assigned = [name_key(slot_map[s]) for s in slot_order if slot_map[s]]
        total_salary=sum(player_info.get(n,{}).get("salary",0) for n in names_assigned)
        total_points=sum(player_info.get(n,{}).get("fppg",0) for n in names_assigned)
        row={s: slot_map[s] for s in slot_order}
        row["TotalSalary"]=total_salary
        row["ProjectedPoints"]=total_points
        wide_rows.append(row)
    df_wide = pd.DataFrame(wide_rows,columns=slot_order+["TotalSalary","ProjectedPoints"])
    st.session_state["df_wide_original"]=df_wide
    st.session_state["player_info"]=player_info
    st.dataframe(df_wide)
    st.download_button("Download Lineups CSV", df_wide.to_csv(index=False).encode("utf-8"), file_name="lineups.csv", mime="text/csv")

# ---------------- Diversify ----------------
if "df_wide_original" in st.session_state:
    st.markdown("---")
    st.header("Diversify Generated Lineups")
    max_exp_ui=st.slider("Max player exposure",0.05,1.0,0.4,0.05)
    max_pair_ui=st.slider("Max pair exposure",0.05,1.0,0.6,0.05)
    randomness_ui=st.slider("Diversify randomness",0.0,1.0,0.15,0.05)
    salary_min_ui=st.number_input("Min lineup salary (diversify)",0,50000,salary_min_buffer,step=100)
    salary_cap_ui2=st.number_input("Max lineup salary (diversify)",0,100000,salary_cap_ui,step=100)
    if st.button("Diversify Lineups"):
        df_wide = st.session_state["df_wide_original"].copy()
        info = st.session_state["player_info"]
        diversified = diversify_lineups(df_wide, info, max_exp_ui,max_pair_ui,randomness_ui,salary_cap_ui2,salary_min_ui)
        st.session_state["df_wide_diversified"]=diversified
        st.dataframe(diversified)
        st.download_button("Download Diversified CSV", diversified.to_csv(index=False).encode("utf-8"), file_name="lineups_diversified.csv", mime="text/csv")
