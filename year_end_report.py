"""End-of-season awards and stat leaders for the year-end newspaper report."""

from season import league_lookup, roster_players, standings_table, team_name

MIN_AWARD_GP = 41


def _player_line(player):
    parts = []
    if player.get("ppg") is not None:
        parts.append(f"{player['ppg']:.1f} PPG")
    if player.get("rpg") is not None:
        parts.append(f"{player['rpg']:.1f} RPG")
    if player.get("apg") is not None:
        parts.append(f"{player['apg']:.1f} APG")
    if player.get("spg") is not None:
        parts.append(f"{player['spg']:.1f} SPG")
    if player.get("bpg") is not None:
        parts.append(f"{player['bpg']:.1f} BPG")
    return " · ".join(parts) if parts else ""


def _winner_entry(player, team_id, season=None, value=None, note=None):
    tid = int(team_id) if team_id else None
    if season and tid:
        tname = team_name(season, tid)
    else:
        tname = player.get("team", "—")
    return {
        "player_id": player.get("id"),
        "name": player.get("name", "Unknown"),
        "team_id": tid,
        "team_name": tname,
        "overall": player.get("overall"),
        "age": player.get("age"),
        "gp": player.get("season_gp") or player.get("gp") or 0,
        "line": _player_line(player),
        "value": value,
        "note": note,
    }


def _qualified_players(season, lookup, min_gp=MIN_AWARD_GP):
    qualified = []
    for player in season.get("players", {}).values():
        if not player.get("team_id"):
            continue
        gp = int(player.get("season_gp") or player.get("gp") or 0)
        if gp < min_gp:
            continue
        qualified.append(player)
    return qualified


def _team_win_pct(season, team_id):
    record = season.get("standings", {}).get(str(team_id), {})
    gp = record.get("gp", 0) or (record.get("w", 0) + record.get("l", 0))
    if gp <= 0:
        return 0.5
    return record.get("w", 0) / gp


def _mvp_score(season, player):
    team_id = player.get("team_id")
    ppg = float(player.get("ppg") or 0)
    overall = float(player.get("overall") or 50)
    win_pct = _team_win_pct(season, team_id)
    return ppg * 1.2 + win_pct * 18 + overall * 0.15


def _dpoy_score(player):
    defense = float((player.get("attributes") or {}).get("defense") or 50)
    spg = float(player.get("spg") or 0)
    bpg = float(player.get("bpg") or 0)
    overall = float(player.get("overall") or 50)
    return defense * 0.45 + spg * 12 + bpg * 14 + overall * 0.08


def _is_rookie_candidate(player, season_year):
    if player.get("is_rookie"):
        return True
    drafted = player.get("drafted")
    if drafted and int(drafted) == int(season_year):
        return True
    age = player.get("age") or 25
    gp = int(player.get("season_gp") or player.get("gp") or 0)
    return age <= 22 and gp >= 20


def _sixth_man_candidates(season, lookup, qualified):
    qualified_ids = {p["id"] for p in qualified}
    candidates = []
    for team_id_str in season.get("rosters", {}):
        team_id = int(team_id_str)
        roster = roster_players(season, team_id, lookup)
        if len(roster) < 6:
            continue
        sorted_by_ppg = sorted(roster, key=lambda p: float(p.get("ppg") or 0), reverse=True)
        starters = {p["id"] for p in sorted_by_ppg[:5]}
        for player in roster:
            if player["id"] in starters:
                continue
            overall = player.get("overall") or 0
            if overall < 65 or overall > 86:
                continue
            if player["id"] not in qualified_ids:
                continue
            candidates.append(player)
    return candidates


def _coach_of_year(season):
    east = standings_table(season, conference="East")
    west = standings_table(season, conference="West")
    if not east and not west:
        return None
    non_playoff = []
    for group in (east, west):
        for row in group[8:]:
            non_playoff.append(row)
    if not non_playoff:
        non_playoff = rows[16:30] if len(rows) > 16 else rows[8:]
    if not non_playoff:
        return None
    best = max(non_playoff, key=lambda row: row.get("win_pct", 0))
    return {
        "team_id": best["team_id"],
        "team_name": best["team_name"],
        "record": f"{best['w']}-{best['l']}",
        "win_pct": round(best.get("win_pct", 0) * 100, 1),
        "note": "Best record among non-playoff teams",
    }


def build_year_end_report(season, lookup=None):
    """Compute awards and leaders; store on season['year_end_report']."""
    lookup = lookup or league_lookup(season)
    season_year = season.get("season_year", 2026)
    qualified = _qualified_players(season, lookup)

    playoffs = season.get("playoffs") or {}
    champion = {
        "team_id": playoffs.get("champion_id"),
        "team_name": playoffs.get("champion_name"),
    }

    for player in qualified:
        if player.get("team_id"):
            player["_team_name"] = team_name(season, player["team_id"])

    mvp_sorted = sorted(qualified, key=lambda p: _mvp_score(season, p), reverse=True)
    dpoy_sorted = sorted(qualified, key=_dpoy_score, reverse=True)
    rookie_pool = [p for p in qualified if _is_rookie_candidate(p, season_year)]
    rookie_sorted = sorted(
        rookie_pool,
        key=lambda p: float(p.get("ppg") or 0) + float(p.get("overall") or 0) * 0.1,
        reverse=True,
    )
    mip_sorted = sorted(
        qualified,
        key=lambda p: float(p.get("season_form") or 1.0) * float(p.get("ppg") or 0),
        reverse=True,
    )
    sixth_pool = _sixth_man_candidates(season, lookup, qualified)
    sixth_sorted = sorted(sixth_pool, key=lambda p: float(p.get("ppg") or 0), reverse=True)

    def award_block(key, title, sorted_players, value_fn=None, min_pool=1):
        if len(sorted_players) < min_pool:
            return None
        winner = sorted_players[0]
        val = value_fn(winner) if value_fn else None
        runners = []
        for runner in sorted_players[1:4]:
            runners.append(
                _winner_entry(
                    runner,
                    runner.get("team_id"),
                    season,
                    value_fn(runner) if value_fn else None,
                )
            )
        return {
            "key": key,
            "title": title,
            "winner": _winner_entry(winner, winner.get("team_id"), season, val),
            "runners_up": runners,
        }

    awards = []
    for block in (
        award_block("mvp", "Most Valuable Player", mvp_sorted, lambda p: round(_mvp_score(season, p), 1)),
        award_block("dpoy", "Defensive Player of the Year", dpoy_sorted, lambda p: round(_dpoy_score(p), 1)),
        award_block(
            "roy",
            "Rookie of the Year",
            rookie_sorted,
            lambda p: float(p.get("ppg") or 0),
            min_pool=1 if rookie_sorted else 99,
        ),
        award_block(
            "mip",
            "Most Improved Player",
            mip_sorted,
            lambda p: round(float(p.get("season_form") or 1.0), 2),
        ),
        award_block(
            "sixth_man",
            "Sixth Man of the Year",
            sixth_sorted,
            lambda p: float(p.get("ppg") or 0),
            min_pool=1 if sixth_sorted else 99,
        ),
    ):
        if block:
            awards.append(block)

    stat_leaders = {}
    for stat, label in (
        ("ppg", "Points Per Game"),
        ("rpg", "Rebounds Per Game"),
        ("apg", "Assists Per Game"),
        ("spg", "Steals Per Game"),
        ("bpg", "Blocks Per Game"),
    ):
        leaders = sorted(
            qualified,
            key=lambda p, s=stat: float(p.get(s) or 0),
            reverse=True,
        )[:5]
        stat_leaders[stat] = {
            "label": label,
            "leaders": [
                _winner_entry(p, p.get("team_id"), season, float(p.get(stat) or 0))
                for p in leaders
            ],
        }

    all_nba_sorted = sorted(qualified, key=lambda p: _mvp_score(season, p), reverse=True)
    all_nba_first = [
        _winner_entry(p, p.get("team_id"), season) for p in all_nba_sorted[:5]
    ]
    all_nba_second = [
        _winner_entry(p, p.get("team_id"), season) for p in all_nba_sorted[5:10]
    ]

    all_defense_sorted = sorted(qualified, key=_dpoy_score, reverse=True)
    all_defense_first = [
        _winner_entry(p, p.get("team_id"), season) for p in all_defense_sorted[:5]
    ]

    standings_rows = standings_table(season)
    top_records = [
        {
            "team_name": row["team_name"],
            "w": row["w"],
            "l": row["l"],
            "win_pct": round(row.get("win_pct", 0) * 100, 1),
        }
        for row in standings_rows[:10]
    ]

    report = {
        "season_year": season_year,
        "champion": champion,
        "awards": awards,
        "coach_of_year": _coach_of_year(season),
        "stat_leaders": stat_leaders,
        "all_nba_first": all_nba_first,
        "all_nba_second": all_nba_second,
        "all_defense_first": all_defense_first,
        "all_rookie": [
            _winner_entry(p, p.get("team_id"), season) for p in rookie_sorted[:5]
        ],
        "top_records": top_records,
    }
    season["year_end_report"] = report
    try:
        from news import append_news

        mvp = next((a for a in awards if a["key"] == "mvp"), None)
        if mvp:
            append_news(
                season,
                "year_end",
                mvp=mvp["winner"]["name"],
                team=mvp["winner"]["team_name"],
            )
    except ImportError:
        pass
    return report


def get_year_end_report(season, lookup=None):
    """Return cached report or build if season is complete."""
    report = season.get("year_end_report")
    if report:
        return report
    if season.get("phase") not in {"complete", "draft", "offseason"}:
        return None
    return build_year_end_report(season, lookup)
