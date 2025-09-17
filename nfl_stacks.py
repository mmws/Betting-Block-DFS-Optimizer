import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Tuple, Generator, Union
from pulp import LpProblem, LpMaximize, LpVariable, LpBinary, lpSum, LpStatusInfeasible
import pytz
import re

@dataclass(frozen=True)
class Player:
    id: str
    full_name: str
    positions: List[str]
    team: str
    salary: float
    fppg: float
    opponent: Optional[str] = None  # Added for game stacks
    game_id: Optional[str] = None   # Added for game stacks
    max_exposure: Optional[float] = None
    min_exposure: Optional[float] = None
    projected_ownership: Optional[float] = None
    injured: bool = False

@dataclass
class Lineup:
    players: List[Player]
    total_fppg: float = field(init=False)
    total_salary: float = field(init=False)

    def __post_init__(self):
        self.total_fppg = sum(p.fppg for p in self.players)
        self.total_salary = sum(p.salary for p in self.players)

    def __str__(self):
        return "\n".join([f"{p.full_name} ({p.positions[0]}, {p.team} vs {p.opponent}): {p.fppg} FPPG, ${p.salary}" for p in self.players]) + f"\nTotal: {self.total_fppg} FPPG, ${self.total_salary}"

@dataclass
class Settings:
    site: str
    sport: str
    budget: float
    positions: List[Tuple[str, int]]
    total_players: int = 8
    max_from_team: Optional[int] = None
    csv_importer: Optional[Callable] = None
    scoring_func: Optional[Callable] = None

DFS_CONFIGS = {
    'YAHOO': {
        'BASKETBALL': {
            'budget': 200,
            'positions': [('PG',1), ('SG',1), ('SF',1), ('PF',1), ('C',1), ('G',1), ('F',1), ('UTIL',1)],
            'total_players': 8,
            'max_from_team': 4,
        },
        'FOOTBALL': {
            'budget': 200,
            'positions': [('QB',1), ('RB',2), ('WR',3), ('TE',1), ('FLEX',1), ('DST',1)],
            'total_players': 9,
            'max_from_team': None,
        },
    },
    'DRAFTKINGS': {
        'BASKETBALL': {
            'budget': 50000,
            'positions': [('PG',1), ('SG',1), ('SF',1), ('PF',1), ('C',1), ('G',1), ('F',1), ('UTIL',1)],
            'total_players': 8,
            'max_from_team': None,
        },
        'FOOTBALL': {
            'budget': 50000,
            'positions': [('QB',1), ('RB',2), ('WR',3), ('TE',1), ('FLEX',1), ('DST',1)],
            'total_players': 9,
            'max_from_team': None,
            'modes': {'captain': {'multiplier': 1.5, 'slots': [('CPT',1), ('UTIL',5)]}},
        },
    },
    'FANDUEL': {
        'BASKETBALL': {
            'budget': 60000,
            'positions': [('PG',2), ('SG',2), ('SF',2), ('PF',2), ('C',1)],
            'total_players': 9,
        },
        'FOOTBALL': {
            'budget': 60000,
            'positions': [('QB',1), ('RB',2), ('WR',3), ('TE',1), ('FLEX',1), ('DST',1)],
            'total_players': 9,
        },
    },
}

class SleekOptimizer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.players_df = pd.DataFrame()
        self.rules: List[Callable] = []
        self.exposure_strategy: Callable = lambda used, total, max_exp: used / total <= (max_exp or 1.0)
        self.max_repeating_players: Optional[int] = None
        self.games_map: Dict[str, Tuple[str, str]] = {}  # e.g., {'GSW@LAL': ('GSW', 'LAL')}

    def load_players_from_csv(self, filename: str, games_map: Optional[Dict[str, Tuple[str, str]]] = None):
        df = pd.read_csv(filename)
        df['positions'] = df.get('Position', '').str.split(r'[\/|,]').apply(lambda x: [p.strip() for p in x] if isinstance(x, list) else [])
        if games_map:
            self.games_map = games_map
            df['game_id'] = df['Team'].map({team: gid for gid, (t1, t2) in games_map.items() for team in (t1, t2)})
            df['opponent'] = df.apply(lambda row: next(t for t in games_map.get(row['game_id'], ('', '')) if t != row['Team']), axis=1)
        else:
            # Try parsing game info from 'Game' column (e.g., 'GSW@LAL')
            if 'Game' in df.columns:
                self.games_map = {row['Game']: tuple(row['Game'].split('@')) for _, row in df.iterrows() if pd.notna(row['Game'])}
                df['game_id'] = df['Game']
                df['opponent'] = df['Game'].apply(lambda g: g.split('@')[1] if pd.notna(g) and '@' in g else None)
        self.players_df = df.assign(
            id=df.get('ID', df.index.map(lambda i: f'r{i}')),
            full_name=df.get('Name', 'Unknown'),
            team=df.get('Team', ''),
            salary=df.get('Salary', 0).apply(self._parse_salary),
            fppg=df.get('FPPG', 0).apply(self._safe_float),
            max_exposure=df.get('Max Exposure', None).apply(self._parse_percent),
            min_exposure=df.get('Min Exposure', None).apply(self._parse_percent),
            projected_ownership=df.get('Projected Ownership', None).apply(self._parse_percent),
            injured=df.get('Injury Status', False).apply(lambda x: x == 'INJ'),
            opponent=df.get('opponent', None),
            game_id=df.get('game_id', None)
        ).dropna(subset=['salary'])

    @staticmethod
    def _parse_salary(val):
        if pd.isna(val): return None
        try:
            return float(str(val).replace('$', '').replace(',', '').strip())
        except:
            return None

    @staticmethod
    def _safe_float(val):
        try:
            return float(str(val).replace(',', '').strip()) if pd.notna(val) else 0.0
        except:
            return 0.0

    @staticmethod
    def _parse_percent(val):
        if pd.isna(val): return None
        val = str(val).replace('%', '').strip()
        try:
            return float(val) / 100 if float(val) > 1 else float(val)
        except:
            return None

    def set_max_repeating_players(self, max_repeating: int):
        self.max_repeating_players = max_repeating
        self.add_rule(self._max_repeating_players_rule())

    def _max_repeating_players_rule(self):
        def rule_func(prob, vars_dict, df, context):
            if self.max_repeating_players is not None:
                for pid in vars_dict:
                    used = context['player_uses'].get(pid, 0)
                    if used >= self.max_repeating_players:
                        prob += vars_dict[pid] == 0, f"NoRepeat_{pid}"
        return rule_func

    def restrict_positions_for_same_team(self, positions: Tuple[str, str]):
        def rule_func(prob, vars_dict, df, context):
            for team in df.team.unique():
                team_players = df[df.team == team]
                pos1_players = team_players[team_players.positions.apply(lambda ps: positions[0] in ps)]
                pos2_players = team_players[team_players.positions.apply(lambda ps: positions[1] in ps)]
                for p1 in pos1_players.itertuples():
                    for p2 in pos2_players.itertuples():
                        if p1.id != p2.id:
                            prob += vars_dict[p1.id] + vars_dict[p2.id] <= 1, f"RestrictSame_{team}_{p1.id}_{p2.id}"
        self.rules.append(rule_func)

    def restrict_positions_for_opposing_team(self, positions1: List[str], positions2: List[str]):
        def rule_func(prob, vars_dict, df, context):
            for gid, (t1, t2) in self.games_map.items():
                t1_players = df[df.team == t1]
                t2_players = df[df.team == t2]
                pos1_players = t1_players[t1_players.positions.apply(lambda ps: any(p in positions1 for p in ps))]
                pos2_players = t2_players[t2_players.positions.apply(lambda ps: any(p in positions2 for p in ps))]
                for p1 in pos1_players.itertuples():
                    for p2 in pos2_players.itertuples():
                        prob += vars_dict[p1.id] + vars_dict[p2.id] <= 1, f"RestrictOpp_{gid}_{p1.id}_{p2.id}"
                # Symmetric restriction
                pos1_players_t2 = t2_players[t2_players.positions.apply(lambda ps: any(p in positions1 for p in ps))]
                pos2_players_t1 = t1_players[t1_players.positions.apply(lambda ps: any(p in positions2 for p in ps))]
                for p1 in pos1_players_t2.itertuples():
                    for p2 in pos2_players_t1.itertuples():
                        prob += vars_dict[p1.id] + vars_dict[p2.id] <= 1, f"RestrictOpp_{gid}_{p1.id}_{p2.id}"
        self.rules.append(rule_func)

    def force_positions_for_opposing_team(self, position_pairs: Union[Tuple[str, str], List[Tuple[str, str]]]):
        if isinstance(position_pairs, tuple):
            position_pairs = [position_pairs]
        def rule_func(prob, vars_dict, df, context):
            for gid, (t1, t2) in self.games_map.items():
                t1_players = df[df.team == t1]
                t2_players = df[df.team == t2]
                for pos1, pos2 in position_pairs:
                    pos1_t1 = t1_players[t1_players.positions.apply(lambda ps: pos1 in ps)]
                    pos2_t2 = t2_players[t2_players.positions.apply(lambda ps: pos2 in ps)]
                    pos1_t2 = t2_players[t2_players.positions.apply(lambda ps: pos1 in ps)]
                    pos2_t1 = t1_players[t1_players.positions.apply(lambda ps: pos2 in ps)]
                    # Require at least one valid pair (OR logic)
                    prob += lpSum(vars_dict[p.id] for p in pos1_t1.itertuples()) + lpSum(vars_dict[p.id] for p in pos2_t2.itertuples()) >= 2, f"ForceOpp_{gid}_{pos1}_{pos2}"
                    prob += lpSum(vars_dict[p.id] for p in pos1_t2.itertuples()) + lpSum(vars_dict[p.id] for p in pos2_t1.itertuples()) >= 2, f"ForceOpp_{gid}_{pos2}_{pos1}"
        self.rules.append(rule_func)

    def add_stack(self, stack: Union['TeamStack', 'GameStack']):
        if isinstance(stack, TeamStack):
            self.rules.append(self._team_stack_rule(stack.size, stack.for_positions))
        elif isinstance(stack, GameStack):
            self.rules.append(self._game_stack_rule(stack.size, stack.min_from_team))

    def _team_stack_rule(self, size: int, for_positions: Optional[List[str]] = None):
        def rule_func(prob, vars_dict, df, context):
            for team in df.team.unique():
                team_players = df[df.team == team]
                if for_positions:
                    team_players = team_players[team_players.positions.apply(lambda ps: any(p in for_positions for p in ps))]
                prob += lpSum(vars_dict[row.id] for row in team_players.itertuples()) >= size, f"TeamStack_{team}"
        return rule_func

    def _game_stack_rule(self, size: int, min_from_team: int):
        def rule_func(prob, vars_dict, df, context):
            for gid in df.game_id.unique():
                game_players = df[df.game_id == gid]
                teams = self.games_map.get(gid, (None, None))
                if not all(teams): continue
                t1_players = game_players[game_players.team == teams[0]]
                t2_players = game_players[game_players.team == teams[1]]
                prob += lpSum(vars_dict[row.id] for row in game_players.itertuples()) >= size, f"GameStack_{gid}"
                prob += lpSum(vars_dict[row.id] for row in t1_players.itertuples()) >= min_from_team, f"MinTeam1_{gid}"
                prob += lpSum(vars_dict[row.id] for row in t2_players.itertuples()) >= min_from_team, f"MinTeam2_{gid}"
        return rule_func

    def add_rule(self, rule_func: Callable):
        self.rules.append(rule_func)

    def optimize(self, n: int = 1, max_exposure: Optional[float] = None, with_injured: bool = False, randomness: bool = False) -> Generator[Lineup, None, None]:
        df = self.players_df[~self.players_df.injured] if not with_injured else self.players_df
        if randomness:
            df['fppg'] = df['fppg'] * (1 + pd.np.random.uniform(-0.12, 0.12, len(df)))

        context = {'lineups_generated': 0, 'player_uses': {p.id: 0 for p in df.itertuples()}}
        for _ in range(n):
            prob = LpProblem("DFS_Optimizer", LpMaximize)
            player_vars = {row.id: LpVariable(f"player_{row.id}", cat=LpBinary) for row in df.itertuples()}

            prob += lpSum(row.fppg * player_vars[row.id] for row in df.itertuples())
            prob += lpSum(player_vars.values()) == self.settings.total_players, "Total_Players"
            prob += lpSum(row.salary * player_vars[row.id] for row in df.itertuples()) <= self.settings.budget, "Budget"

            for pos, count in self.settings.positions:
                pos_players = df[df.positions.apply(lambda ps: pos in ps)]
                prob += lpSum(player_vars[row.id] for row in pos_players.itertuples()) == count, f"Pos_{pos}"

            if self.settings.max_from_team:
                for team in df.team.unique():
                    team_players = df[df.team == team]
                    prob += lpSum(player_vars[row.id] for row in team_players.itertuples()) <= self.settings.max_from_team, f"Team_{team}"

            for rule in self.rules:
                rule(prob, player_vars, df, context)

            for row in df.itertuples():
                if row.max_exposure is not None:
                    used = context['player_uses'].get(row.id, 0)
                    if not self.exposure_strategy(used, context['lineups_generated'] + 1, row.max_exposure):
                        prob += player_vars[row.id] == 0, f"Exposure_{row.id}"

            status = prob.solve()
            if status == LpStatusInfeasible:
                raise ValueError("Infeasible solution; check constraints.")

            selected_ids = [var.name.split('_')[1] for var in prob.variables() if var.value() == 1]
            selected_players = [Player(**df.loc[sid][['id', 'full_name', 'positions', 'team', 'salary', 'fppg', 'opponent', 'game_id', 'max_exposure', 'min_exposure', 'projected_ownership', 'injured']].to_dict()) for sid in selected_ids]
            lineup = Lineup(selected_players)
            yield lineup

            context['lineups_generated'] += 1
            for p in selected_players:
                context['player_uses'][p.id] += 1

@dataclass
class TeamStack:
    size: int
    for_positions: Optional[List[str]] = None

@dataclass
class GameStack:
    size: int
    min_from_team: int

def get_optimizer(site: str, sport: str, mode: Optional[str] = None):
    if site not in DFS_CONFIGS or sport not in DFS_CONFIGS[site]:
        raise ValueError(f"Unsupported site-sport: {site}-{sport}")
    config = DFS_CONFIGS[site][sport].copy()
    if mode and mode in config.get('modes', {}):
        mode_config = config['modes'][mode]
        config['positions'] = mode_config.get('slots', config['positions'])
    return SleekOptimizer(Settings(site=site, sport=sport, **config))
