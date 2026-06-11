"""Roster size limits, releases, and free-agent signings."""

from season import can_trade, league_lookup, team_name

MAX_ROSTER = 15
MIN_ROSTER = 10


def _normalize_team_id(team_id):
    if team_id is None:
        return None
    return int(team_id)


def _player_team_id(player):
    raw = player.get("team_id")
    if raw is None:
        return None
    return int(raw)


def roster_size(season, team_id):
    return len(season.get("rosters", {}).get(str(team_id), []))


def can_add_player(season, team_id):
    return roster_size(season, team_id) < MAX_ROSTER


def can_remove_player(season, team_id):
    return roster_size(season, team_id) > MIN_ROSTER


def free_agent_ids(season):
    return list(season.get("free_agents", []))


def free_agent_players(season, lookup=None):
    lookup = lookup or league_lookup(season)
    players = []
    for player_id in free_agent_ids(season):
        player = lookup.get(int(player_id))
        if player and not player.get("team_id"):
            players.append(player)
    return players


def validate_roster_sizes_after_trade(
    season,
    user_team_id,
    partner_team_id,
    outgoing_players,
    incoming_players,
    check_partner_max=True,
):
    user_size = roster_size(season, user_team_id)
    partner_size = roster_size(season, partner_team_id)
    user_after = user_size - len(outgoing_players) + len(incoming_players)
    partner_after = partner_size - len(incoming_players) + len(outgoing_players)

    if user_after > MAX_ROSTER:
        return False, f"Trade would exceed roster limit ({MAX_ROSTER} players)."
    if check_partner_max and partner_after > MAX_ROSTER:
        return False, "Trade would exceed partner roster limit."
    if user_after < MIN_ROSTER:
        return False, f"Trade would drop below minimum roster ({MIN_ROSTER} players)."
    if partner_after < MIN_ROSTER:
        return False, "Trade would drop partner below minimum roster."
    return True, None


def repair_roster_sync(season, team_id=None):
    """Fix team_id on players listed in a team's roster array."""
    lookup = league_lookup(season)
    if team_id is not None:
        team_ids = [_normalize_team_id(team_id)]
    else:
        team_ids = [_normalize_team_id(key) for key in season.get("rosters", {}).keys()]

    for tid in team_ids:
        roster_ids = season.get("rosters", {}).get(str(tid), [])
        label = team_name(season, tid)
        for player_id in roster_ids:
            player = lookup.get(int(player_id))
            if player and _player_team_id(player) != tid:
                player["team_id"] = tid
                player["team"] = label


def _sync_free_agents(season):
    pool = []
    for key, player in season.get("players", {}).items():
        if not player.get("team_id"):
            pool.append(player.get("id", int(key)))
    season["free_agents"] = sorted(set(pool))


def ensure_draft_roster_room(season, team_id, lookup=None):
    """CPU draft helper: release lowest-OVR players until there is roster room."""
    lookup = lookup or league_lookup(season)
    while not can_add_player(season, team_id) and can_remove_player(season, team_id):
        roster_ids = season.get("rosters", {}).get(str(team_id), [])
        candidates = [lookup[pid] for pid in roster_ids if pid in lookup]
        if not candidates:
            break
        worst = min(candidates, key=lambda player: player.get("overall") or 0)
        release_player(season, team_id, worst["id"])


def release_worst_players(season, team_id, count, lookup=None):
    """Release the lowest-OVR players from a team roster."""
    lookup = lookup or league_lookup(season)
    team_id = _normalize_team_id(team_id)
    count = max(0, int(count))
    released = []
    for _ in range(count):
        if not can_remove_player(season, team_id):
            break
        roster_ids = season.get("rosters", {}).get(str(team_id), [])
        candidates = [lookup[pid] for pid in roster_ids if pid in lookup]
        if not candidates:
            break
        worst = min(candidates, key=lambda player: player.get("overall") or 0)
        ok, _ = release_player(season, team_id, worst["id"], force=True)
        if ok:
            released.append(worst)
        else:
            break
    return released


def release_player(season, team_id, player_id, force=False):
    if not force and not can_trade(season):
        return False, "Roster moves are not available in this phase."

    team_id = _normalize_team_id(team_id)
    player_id = int(player_id)
    if not force and not can_remove_player(season, team_id):
        return False, f"Cannot drop below {MIN_ROSTER} players."

    lookup = league_lookup(season)
    player = lookup.get(player_id)
    roster = season.get("rosters", {}).get(str(team_id), [])
    on_roster = player_id in roster
    player_team = _player_team_id(player) if player else None

    if not player or (not on_roster and player_team != team_id):
        return False, "Player is not on your roster."

    roster_list = season["rosters"].setdefault(str(team_id), [])
    if player_id in roster_list:
        roster_list.remove(player_id)

    player["team_id"] = None
    player["team"] = "Free Agent"
    _sync_free_agents(season)
    return True, f"Released {player.get('name', player_id)} to free agency."


def sign_free_agent(season, team_id, player_id):
    if not can_trade(season):
        return False, "Free-agent signings are not available in this phase."

    player_id = int(player_id)
    if not can_add_player(season, team_id):
        return False, f"Roster is full ({MAX_ROSTER} players). Release someone first."

    lookup = league_lookup(season)
    player = lookup.get(player_id)
    if not player:
        return False, "Player not found."
    if player.get("team_id"):
        return False, "Player is already on a team."
    if player_id not in season.get("free_agents", []):
        return False, "Player is not a free agent."

    roster = season["rosters"].setdefault(str(team_id), [])
    if player_id not in roster:
        roster.append(player_id)

    player["team_id"] = team_id
    player["team"] = team_name(season, team_id)
    _sync_free_agents(season)
    return True, f"Signed {player.get('name', player_id)}."
