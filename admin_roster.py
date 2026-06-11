"""Admin roster operations — bypass phase and roster-size limits."""

from attributes import admin_apply_career_overrides, admin_apply_attribute_overrides
from custom_players import (
    build_prospect_from_template,
    get_custom_player,
    mark_custom_player_drafted,
)
from roster import _sync_free_agents
from season import league_lookup, team_name


def list_season_teams(season):
    teams = []
    for team_id_str, record in season.get("standings", {}).items():
        teams.append(
            {
                "team_id": int(team_id_str),
                "team_name": record.get("team_name", team_id_str),
            }
        )
    teams.sort(key=lambda row: row["team_name"])
    return teams


def _store_player(season, player):
    season.setdefault("players", {})[str(player["id"])] = player


def admin_assign_to_team(season, player, team_id):
    player_id = int(player["id"])
    team_id = int(team_id)

    if player.get("team_id"):
        old_roster = season.get("rosters", {}).get(str(player["team_id"]), [])
        if player_id in old_roster:
            old_roster.remove(player_id)

    roster = season.setdefault("rosters", {}).setdefault(str(team_id), [])
    if player_id not in roster:
        roster.append(player_id)

    player["team_id"] = team_id
    player["team"] = team_name(season, team_id)
    _store_player(season, player)
    _sync_free_agents(season)
    return player


def admin_release_player(season, team_id, player_id):
    player_id = int(player_id)
    team_id = int(team_id)
    lookup = league_lookup(season)
    player = lookup.get(player_id)
    if not player or player.get("team_id") != team_id:
        return False, "Player is not on that roster."

    roster = season.get("rosters", {}).get(str(team_id), [])
    if player_id in roster:
        roster.remove(player_id)

    player["team_id"] = None
    player["team"] = "Free Agent"
    _sync_free_agents(season)
    return True, f"Released {player.get('name', player_id)} to free agency."


def admin_sign_free_agent(season, team_id, player_id):
    player_id = int(player_id)
    lookup = league_lookup(season)
    player = lookup.get(player_id)
    if not player:
        return False, "Player not found."
    if player.get("team_id"):
        return False, "Player is already on a team."

    admin_assign_to_team(season, player, team_id)
    return True, f"Signed {player.get('name', player_id)}."


def admin_move_player(season, player_id, dest_team_id):
    player_id = int(player_id)
    dest_team_id = int(dest_team_id)
    lookup = league_lookup(season)
    player = lookup.get(player_id)
    if not player:
        return False, "Player not found."

    admin_assign_to_team(season, player, dest_team_id)
    return True, f"Moved {player.get('name', player_id)} to {team_name(season, dest_team_id)}."


def admin_place_custom_on_team(season, custom_id, team_id, rng=None):
    template = get_custom_player(custom_id)
    if not template:
        return False, None, "Custom player not found."

    prospect = build_prospect_from_template(season, template, rng=rng, career=template.get("career"))
    admin_assign_to_team(season, prospect, team_id)
    mark_custom_player_drafted(season, custom_id)
    return True, prospect, f"Added {prospect['name']} to {team_name(season, team_id)}."


def admin_update_league_player(season, player_id, career=None, attributes=None):
    lookup = league_lookup(season)
    player = lookup.get(int(player_id))
    if not player:
        return False, "Player not found."

    if attributes:
        admin_apply_attribute_overrides(player, attributes)
    if career:
        admin_apply_career_overrides(player, career=career)

    _store_player(season, player)
    return True, f"Updated {player.get('name', player_id)}."
