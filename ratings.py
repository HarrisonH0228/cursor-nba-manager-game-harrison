MIN_GAMES_FOR_RATINGS = 20
STAT_WEIGHTS = {"ppg": 3.0, "rpg": 1.5, "apg": 1.5, "spg": 1.0, "bpg": 1.0}
STAT_COLUMNS = ("ppg", "rpg", "apg", "spg", "bpg")
DERIVED_STATS = ("overall",)
RANK_COLUMNS = STAT_COLUMNS + DERIVED_STATS
STAT_LABELS = {
    "ppg": "PPG",
    "rpg": "RPG",
    "apg": "APG",
    "spg": "SPG",
    "bpg": "BPG",
    "overall": "OVR",
}

ATTR_OVERALL_WEIGHTS = {
    "scoring": 3.0,
    "playmaking": 1.5,
    "rebounding": 1.5,
    "defense": 2.0,
    "efficiency": 1.0,
}
MIN_INTRINSIC_OVERALL = 25
MAX_INTRINSIC_OVERALL = 99


def rating_pool(players):
    return [player for player in players if (player.get("gp") or 0) >= MIN_GAMES_FOR_RATINGS]


def _competition_rank(value, pool_values):
    return 1 + sum(1 for pool_value in pool_values if pool_value > value)


def compute_stat_ranks(players):
    pool = rating_pool(players)
    ranks_by_id = {player["id"]: {} for player in players}

    for stat in RANK_COLUMNS:
        pool_values = [player[stat] for player in pool if player.get(stat) is not None]
        if not pool_values:
            continue

        for player in players:
            value = player.get(stat)
            if value is None:
                continue
            ranks_by_id[player["id"]][stat] = _competition_rank(value, pool_values)

    return ranks_by_id


def compute_stat_percentiles(players):
    pool = rating_pool(players)
    ranks_by_id = compute_stat_ranks(players)
    percentiles_by_id = {player["id"]: {} for player in players}

    for stat in STAT_COLUMNS:
        pool_size = sum(1 for player in pool if player.get(stat) is not None)
        if pool_size == 0:
            continue

        for player in players:
            rank = ranks_by_id[player["id"]].get(stat)
            if rank is not None:
                percentiles_by_id[player["id"]][stat] = (
                    100 * (pool_size - rank + 1) / pool_size
                )

    return percentiles_by_id


def compute_overall_ratings(players):
    percentiles_by_id = compute_stat_percentiles(players)
    overall_by_id = {}

    for player in players:
        player_percentiles = percentiles_by_id.get(player["id"], {})
        weighted_sum = 0.0
        weight_total = 0.0

        for stat, weight in STAT_WEIGHTS.items():
            percentile = player_percentiles.get(stat)
            if percentile is None:
                continue
            weighted_sum += weight * percentile
            weight_total += weight

        if weight_total > 0:
            overall_by_id[player["id"]] = round(weighted_sum / weight_total, 1)

    return overall_by_id


def apply_ratings(players):
    overall_by_id = compute_overall_ratings(players)
    for player in players:
        overall = overall_by_id.get(player["id"])
        if overall is not None:
            player["overall"] = overall
        else:
            player.pop("overall", None)
    return players


def compute_intrinsic_overall(player):
    """Absolute OVR from effective attributes (not league-relative percentiles)."""
    from attributes import effective_attributes

    attrs = player.get("attributes") or effective_attributes(player)
    weighted_sum = 0.0
    weight_total = 0.0
    for key, weight in ATTR_OVERALL_WEIGHTS.items():
        value = attrs.get(key)
        if value is None:
            continue
        weighted_sum += weight * value
        weight_total += weight
    if weight_total <= 0:
        return player.get("overall") or 50
    raw = weighted_sum / weight_total
    from attributes import ADMIN_ATTR_MAX

    max_ovr = ADMIN_ATTR_MAX if player.get("is_overclocked") else MAX_INTRINSIC_OVERALL
    return round(max(MIN_INTRINSIC_OVERALL, min(max_ovr, raw)), 1)


def needs_ratings(players):
    return any(player.get("overall") is None for player in players) or any(
        player.get("gp") is None for player in players
    )


TOP_PLAYERS_FOR_TEAM_OVERALL = 8
TOP_PLAYER_WEIGHT = 2.5
TOP_PLAYER_COUNT = 3
DEPTH_PLAYER_WEIGHT = 0.75
MIN_GAMES_FOR_TEAM_OVERALL = MIN_GAMES_FOR_RATINGS
MIN_QUALIFIED_PLAYERS_FOR_TEAM_OVERALL = 5
TEAM_GP_PENALTY_START = 20
PARTICIPATION_GP_RATIO = 0.5
PARTIAL_WEIGHT_MULTIPLIER = 1 / 3


def _resolve_team_gp(team_players, team_gp=None):
    if team_gp is not None:
        return team_gp
    if not team_players:
        return 0
    return max(player.get("gp") or 0 for player in team_players)


def _player_effective_gp(player, team_gp=None):
    season_gp = player.get("season_gp")
    if season_gp is not None and team_gp is not None and team_gp > 0:
        return season_gp
    return player.get("gp") or 0


def _player_meets_participation(player, team_gp):
    if team_gp is None or team_gp <= TEAM_GP_PENALTY_START:
        return True
    return _player_effective_gp(player, team_gp) >= team_gp * PARTICIPATION_GP_RATIO


def team_rating_pool(team_players, team_gp=None):
    team_gp = _resolve_team_gp(team_players, team_gp)
    return sorted(
        [
            player
            for player in team_players
            if player.get("overall") is not None
            and _player_effective_gp(player, team_gp) >= MIN_GAMES_FOR_TEAM_OVERALL
        ],
        key=lambda player: player["overall"],
        reverse=True,
    )


def build_team_top_players(pool, team_gp=None):
    team_gp = _resolve_team_gp(pool, team_gp)
    if len(pool) < MIN_QUALIFIED_PLAYERS_FOR_TEAM_OVERALL:
        return []

    selected = pool[:TOP_PLAYERS_FOR_TEAM_OVERALL]
    selected_ids = {player["id"] for player in selected}

    changed = True
    while changed:
        changed = False
        for index, player in enumerate(list(selected)):
            if _player_meets_participation(player, team_gp):
                continue

            replacement = None
            for candidate in pool:
                if candidate["id"] in selected_ids:
                    continue
                if not _player_meets_participation(candidate, team_gp):
                    continue
                if replacement is None or candidate["overall"] > replacement["overall"]:
                    replacement = candidate

            if replacement is None or replacement["overall"] <= player["overall"]:
                continue

            selected_ids.remove(player["id"])
            selected_ids.add(replacement["id"])
            selected[index] = replacement
            changed = True
            break

    top_players = sorted(selected, key=lambda player: player["overall"], reverse=True)
    return top_players[:TOP_PLAYERS_FOR_TEAM_OVERALL]


def _team_overall_weight(index, player, team_gp=None):
    weight = TOP_PLAYER_WEIGHT if index < TOP_PLAYER_COUNT else DEPTH_PLAYER_WEIGHT
    if not _player_meets_participation(player, team_gp):
        weight *= PARTIAL_WEIGHT_MULTIPLIER
    return weight


def compute_team_overall(team_players, team_gp=None):
    team_gp = _resolve_team_gp(team_players, team_gp)
    pool = team_rating_pool(team_players, team_gp)
    top_players = build_team_top_players(pool, team_gp)
    if len(top_players) < MIN_QUALIFIED_PLAYERS_FOR_TEAM_OVERALL:
        return None

    weighted_sum = sum(
        player["overall"] * _team_overall_weight(index, player, team_gp)
        for index, player in enumerate(top_players)
    )
    weight_total = sum(
        _team_overall_weight(index, player, team_gp) for index, player in enumerate(top_players)
    )
    if weight_total <= 0:
        return None
    return round(weighted_sum / weight_total, 1)


def build_team_summaries(players):
    teams_by_id = {}

    for player in players:
        team_id = player.get("team_id")
        if not team_id:
            continue

        if team_id not in teams_by_id:
            teams_by_id[team_id] = {
                "team_id": team_id,
                "team": player.get("team", "Unknown"),
                "players": [],
            }
        teams_by_id[team_id]["players"].append(player)

    summaries = []
    for team_data in teams_by_id.values():
        roster = team_data["players"]
        top_player = max(
            roster,
            key=lambda player: player.get("overall") or 0,
            default=None,
        )
        summaries.append(
            {
                "team_id": team_data["team_id"],
                "team": team_data["team"],
                "overall": compute_team_overall(roster),
                "roster_size": len(roster),
                "top_player_name": top_player.get("name") if top_player else None,
                "top_player_overall": top_player.get("overall") if top_player else None,
            }
        )

    return summaries


def compute_team_ranks(summaries):
    ranks_by_id = {summary["team_id"]: {} for summary in summaries}
    pool_values = [
        summary["overall"]
        for summary in summaries
        if summary.get("overall") is not None
    ]
    if not pool_values:
        return ranks_by_id

    for summary in summaries:
        overall = summary.get("overall")
        if overall is not None:
            ranks_by_id[summary["team_id"]]["overall"] = _competition_rank(
                overall, pool_values
            )

    return ranks_by_id
