# Put this function into your app.py (replace old diversify function)
import re
import random
from collections import Counter

def _extract_base_name(s: str) -> str:
    """Strip trailing numeric ID in parentheses and whitespace: 'Joe Burrow (12345)' -> 'Joe Burrow'."""
    if s is None:
        return ""
    s = str(s).strip()
    # Remove trailing "(12345)" or " (12345)"
    return re.sub(r'\s*\(\s*\d+\s*\)\s*$', '', s).strip()

def _extract_id_from_string(s: str) -> str:
    m = re.search(r'\((\d+)\)', str(s))
    return m.group(1) if m else ""

def _detect_cols(df):
    """Return guessed column names for name, id, salary, fppg, team (or None)."""
    cols = {c.lower(): c for c in df.columns}
    def find(poss):
        for p in poss:
            if p.lower() in cols:
                return cols[p.lower()]
        return None
    name_col = find(["Name", "Player", "Full Name", "full_name", "player", "name"])
    id_col = find(["ID", "Id", "id", "player_id", "playerid"])
    salary_col = find(["Salary", "salary", "salary_usd", "Salary_usd"])
    fppg_col = find(["FPPG", "fppg", "Proj", "ProjectedPoints", "projectedpoints", "proj"])
    team_col = find(["Team", "team", "team_abbrev", "teamabbr", "teamabbrev"])
    return name_col, id_col, salary_col, fppg_col, team_col

def build_player_info_from_salary_df(salary_df):
    """Return mapping base_name -> {id, salary, fppg, team} using best-effort column detection."""
    name_col, id_col, salary_col, fppg_col, team_col = _detect_cols(salary_df)
    player_info = {}
    for _, r in salary_df.iterrows():
        raw_name = r[name_col] if name_col and name_col in r else (r.iloc[0] if len(r)>0 else "")
        base = _extract_base_name(raw_name)
        pid = ""
        if id_col and id_col in r and not pd.isna(r[id_col]):
            pid = str(r[id_col])
        else:
            pid = _extract_id_from_string(raw_name)
        try:
            sal = float(r[salary_col]) if salary_col and salary_col in r and not pd.isna(r[salary_col]) else 0.0
        except Exception:
            sal = 0.0
        try:
            fppg = float(r[fppg_col]) if fppg_col and fppg_col in r and not pd.isna(r[fppg_col]) else 0.0
        except Exception:
            fppg = 0.0
        team = r[team_col] if team_col and team_col in r and not pd.isna(r[team_col]) else ""
        player_info[base] = {"id": str(pid) if pid else "", "salary": sal, "fppg": fppg, "team": str(team)}
    return player_info

def diversify_lineups_wide(
    df_wide: pd.DataFrame,
    salary_df: pd.DataFrame,
    max_exposure: float = 0.4,
    max_pair_exposure: float = 0.6,
    randomness: float = 0.12,
    salary_min: float = 0.0,
    salary_cap: float = 50000.0
) -> pd.DataFrame:
    """
    Diversify wide-format lineups (df_wide) using player info from salary_df.
    - df_wide: columns are positions (QB,RB1,RB2,WR1,...) and Budget / FPPG (or you can have different names).
    - salary_df: original uploaded salary table (must contain player names and salary/FPPG).
    Returns a NEW DataFrame with updated Budget and FPPG.
    """
    if df_wide is None or len(df_wide) == 0:
        return df_wide

    # make copies
    diversified = df_wide.copy().reset_index(drop=True)
    player_info = build_player_info_from_salary_df(salary_df)

    # build flat list of player names (base name without id)
    total_lineups = len(diversified)
    players_flat = []
    pairs_flat = []

    # detect which columns are position columns vs total columns (common names)
    total_cols = set([c.lower() for c in diversified.columns])
    # consider Budget, TotalSalary, FPPG, ProjectedPoints as totals to skip when iterating players
    totals_to_skip = set([c for c in diversified.columns if c.lower() in {"budget", "totalsalary", "fppg", "projectedpoints", "totalprojectedpoints"}])

    pos_columns = [c for c in diversified.columns if c not in totals_to_skip]

    # initial exposures
    for idx in range(total_lineups):
        lineup_players = []
        for col in pos_columns:
            val = diversified.at[idx, col]
            if isinstance(val, str) and val.strip() != "":
                base = _extract_base_name(val)
                lineup_players.append(base)
                players_flat.append(base)
        # pairs
        for i in range(len(lineup_players)):
            for j in range(i+1, len(lineup_players)):
                pairs_flat.append(tuple(sorted((lineup_players[i], lineup_players[j]))))

    exposure = Counter(players_flat)
    pair_exposure = Counter(pairs_flat)

    # helper to recompute totals for a given lineup index
    def recompute_lineup_totals(idx):
        budget = 0.0
        fppg_total = 0.0
        for col in pos_columns:
            val = diversified.at[idx, col]
            if isinstance(val, str) and val.strip() != "":
                name = _extract_base_name(val)
                info = player_info.get(name)
                if info:
                    budget += float(info.get("salary", 0.0))
                    fppg_total += float(info.get("fppg", 0.0))
        # write back (use consistent column names if present)
        # prefer existing name "Budget" or "TotalSalary" for salary
        if "Budget" in diversified.columns:
            diversified.at[idx, "Budget"] = budget
        elif "TotalSalary" in diversified.columns:
            diversified.at[idx, "TotalSalary"] = budget
        else:
            diversified.at[idx, "Budget"] = budget
        # prefer "FPPG" or "ProjectedPoints"
        if "FPPG" in diversified.columns:
            diversified.at[idx, "FPPG"] = fppg_total
        elif "ProjectedPoints" in diversified.columns:
            diversified.at[idx, "ProjectedPoints"] = fppg_total
        else:
            diversified.at[idx, "FPPG"] = fppg_total

    # try diversify: loop through lineups and positions and attempt replacements
    all_player_names = list(player_info.keys())

    for idx in range(total_lineups):
        # recompute lineup players each iteration (they may change)
        current_players = []
        for col in pos_columns:
            val = diversified.at[idx, col]
            if isinstance(val, str) and val.strip() != "":
                current_players.append(_extract_base_name(val))

        for col in pos_columns:
            val = diversified.at[idx, col]
            if not (isinstance(val, str) and val.strip()):
                continue
            base_name = _extract_base_name(val)
            # current exposures
            player_exp = (exposure.get(base_name, 0) / total_lineups) if total_lineups > 0 else 0.0

            # check pair exposure for current player with others in same lineup
            pair_violates = False
            for other in current_players:
                if other == base_name:
                    continue
                pair = tuple(sorted((base_name, other)))
                if (pair_exposure.get(pair, 0) / total_lineups) > max_pair_exposure:
                    pair_violates = True
                    break

            # decide whether to try replace
            if player_exp > max_exposure or pair_violates:
                if random.random() >= randomness:
                    continue  # skip replacement attempt this time

                # candidate pool: players not already in current lineup (base names)
                candidates = [p for p in all_player_names if p not in current_players]
                random.shuffle(candidates)

                replaced = False
                for cand in candidates:
                    info = player_info.get(cand)
                    if not info:
                        continue
                    # Tentatively place candidate in copy, compute new totals
                    old_val = diversified.at[idx, col]
                    old_base = base_name

                    diversified.at[idx, col] = cand + (f" ({info['id']})" if info.get("id") else f" ({info.get('team','')})")
                    # recompute totals
                    recompute_lineup_totals(idx)
                    # read totals
                    # Salary column name detection
                    salary_now = None
                    if "Budget" in diversified.columns:
                        salary_now = float(diversified.at[idx, "Budget"])
                    elif "TotalSalary" in diversified.columns:
                        salary_now = float(diversified.at[idx, "TotalSalary"])
                    else:
                        salary_now = float(diversified.at[idx, "Budget"])

                    # If salary within bounds, accept
                    if salary_min <= salary_now <= salary_cap:
                        # update exposures: decrement old, increment new
                        exposure[old_base] = max(0, exposure.get(old_base, 0) - 1)
                        exposure[cand] = exposure.get(cand, 0) + 1
                        # update pair exposures: remove pairs involving old_base, add pairs for cand
                        # recompute current_players for pair accounting
                        new_players = []
                        for ccol in pos_columns:
                            v = diversified.at[idx, ccol]
                            if isinstance(v, str) and v.strip():
                                new_players.append(_extract_base_name(v))
                        # rebuild pair exposures for this lineup: first remove old pairs then add new pairs
                        # remove old pairs:
                        for a in range(len(current_players)):
                            for b in range(a+1, len(current_players)):
                                pair = tuple(sorted((current_players[a], current_players[b])))
                                pair_exposure[pair] = max(0, pair_exposure.get(pair, 0) - 1)
                        # add new pairs:
                        for a in range(len(new_players)):
                            for b in range(a+1, len(new_players)):
                                pair = tuple(sorted((new_players[a], new_players[b])))
                                pair_exposure[pair] = pair_exposure.get(pair, 0) + 1

                        # update current_players for next col iterations
                        current_players = new_players
                        replaced = True
                        break
                    else:
                        # revert and try next candidate
                        diversified.at[idx, col] = old_val
                        recompute_lineup_totals(idx)

                # end candidates loop
                if not replaced:
                    # no replacement found, ensure totals are correct for original
                    recompute_lineup_totals(idx)

    # After all attempts: make a final pass to ensure all totals are consistent numeric values
    for idx in range(len(diversified)):
        recompute_lineup_totals(idx)

    return diversified
