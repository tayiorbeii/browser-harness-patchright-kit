#!/usr/bin/env python3
"""Simulate 16-point NFL confidence pools from the archived ESPN picks dataset."""
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/espn-nfl-picks-2023-2025.jsonl"
WEEKLY_JSONL = ROOT / "data/espn-confidence-simulation-2023-2025.jsonl"
WEEKLY_CSV = ROOT / "data/espn-confidence-weekly-scores-2023-2025.csv"
FINAL_CSV = ROOT / "data/espn-confidence-final-standings-2023-2025.csv"
MAX_POINTS = 16


def number(value):
    try:
        return float(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return None


def implied_probability(value):
    """Handle American or fractional moneyline values from ESPN's archived odds."""
    if value is None:
        return None
    text = str(value).strip().replace("−", "-")
    if "/" in text:
        try:
            numerator, denominator = map(float, text.split("/", 1))
            return denominator / (numerator + denominator)
        except (ValueError, ZeroDivisionError):
            return None
    odds = number(text)
    if odds is None or odds == 0:
        return None
    return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)


def provider_lines(game):
    candidates = []
    for market in game["odds"].get("markets", []):
        home = market.get("home", {})
        away = market.get("away", {})
        home_spread, away_spread = number(home.get("spread")), number(away.get("spread"))
        if home_spread is None or away_spread is None:
            continue
        candidates.append({
            "provider": market.get("provider") or "unknown",
            "homeSpread": home_spread,
            "awaySpread": away_spread,
            "homeProbability": implied_probability(home.get("moneyline")),
            "awayProbability": implied_probability(away.get("moneyline")),
        })
    return candidates


def choose_market(game):
    """Consensus first, ESPN BET second; otherwise median unique non-live books."""
    candidates = provider_lines(game)
    for preferred in ("consensus", "espn bet"):
        hit = next((m for m in candidates if m["provider"].casefold() == preferred), None)
        if hit:
            return {"source": hit["provider"], "providers": [hit["provider"]],
                    "homeSpread": hit["homeSpread"], "awaySpread": hit["awaySpread"],
                    "homeProbability": hit["homeProbability"], "awayProbability": hit["awayProbability"]}

    # Regional editions of the same sportsbook are one source; live feeds aren't
    # pre-game confidence signals. Use one line per distinct book in the fallback.
    unique = {}
    for market in candidates:
        name = market["provider"]
        if "live" in name.casefold():
            continue
        base = re.sub(r"\s*\([^)]*\)$", "", name).strip()
        key = base.casefold()
        if key not in unique or name.casefold() == key:
            unique[key] = market
    selected = list(unique.values())
    source = "median_non_live_books"
    if not selected and candidates:
        # A few archived events expose only ESPN's live-feed market. Keep it as
        # an explicitly marked last resort rather than dropping that game.
        selected = candidates
        source = "live_only_fallback"
    if not selected:
        raise ValueError(f"no usable spread market for {game['gameId']}")

    def median(field):
        values = [m[field] for m in selected if m[field] is not None]
        return statistics.median(values) if values else None

    home_spread = median("homeSpread")
    away_spread = median("awaySpread")
    if home_spread is None or away_spread is None:
        raise ValueError(f"fallback market has no paired spread for {game['gameId']}")
    names = sorted(m["provider"] for m in selected)
    return {"source": source, "providers": names,
            "homeSpread": home_spread, "awaySpread": away_spread,
            "homeProbability": median("homeProbability"), "awayProbability": median("awayProbability")}


def main():
    weeks = [json.loads(line) for line in INPUT.read_text().splitlines() if line.strip()]
    assert len(weeks) == 54 and len({(w["season"], w["week"]) for w in weeks}) == 54
    score_history = defaultdict(lambda: {"points": 0, "wins": 0, "losses": 0, "ties": 0, "noPicks": 0})
    outputs = []
    weekly_rows = []
    final_rows = []

    for week in sorted(weeks, key=lambda w: (w["season"], w["week"])):
        season, week_num = week["season"], week["week"]
        games = week["games"]
        n = len(games)
        assert n and all(g["isFinal"] for g in games)
        markets = {g["gameId"]: choose_market(g) for g in games}
        expert_names = [expert["name"] for expert in week["experts"]]
        game_by_expert = {
            expert: [
                {"game": game,
                 "pick": next((p for p in game["picks"] if p["expert"] == expert), None),
                 "market": markets[game["gameId"]]}
                for game in games
            ]
            for expert in expert_names
        }
        expert_scores = []
        assigned_by_game = defaultdict(list)

        for expert in expert_names:
            entries = game_by_expert[expert]

            def order(entry):
                pick = entry["pick"] or {}
                team = pick.get("pick")
                market = entry["market"]
                if team == entry["game"].get("home"):
                    spread, probability = market["homeSpread"], market["homeProbability"]
                elif team == entry["game"].get("away"):
                    spread, probability = market["awaySpread"], market["awayProbability"]
                else:
                    return (3, 0, 0, entry["game"]["gameId"])
                if spread < -0.001:
                    return (0, spread, -(probability or 0), entry["game"]["gameId"])
                if spread > 0.001:
                    # Smaller underdogs are the more confident upset selections.
                    return (2, spread, -(probability or 0), entry["game"]["gameId"])
                return (1, 0, -(probability or 0), entry["game"]["gameId"])

            ordered = sorted(entries, key=order)
            weekly = {"points": 0, "wins": 0, "losses": 0, "ties": 0, "noPicks": 0}
            for index, entry in enumerate(ordered):
                game, pick, market = entry["game"], entry["pick"] or {}, entry["market"]
                confidence_points = MAX_POINTS - index
                selected_team = pick.get("pick")
                is_correct = pick.get("correct") is True
                if not selected_team:
                    result = "no_pick"
                    weekly["noPicks"] += 1
                elif game.get("actualWinner") is None:
                    result = "tie"
                    weekly["ties"] += 1
                elif is_correct:
                    result = "correct"
                    weekly["wins"] += 1
                    weekly["points"] += confidence_points
                else:
                    result = "incorrect"
                    weekly["losses"] += 1
                if selected_team == game.get("home"):
                    picked_spread = market["homeSpread"]
                elif selected_team == game.get("away"):
                    picked_spread = market["awaySpread"]
                else:
                    picked_spread = None
                assigned_by_game[game["gameId"]].append({
                    "expert": expert,
                    "pick": selected_team,
                    "confidenceRank": index + 1,
                    "confidencePoints": confidence_points,
                    "pickedTeamSpread": picked_spread,
                    "marketSource": market["source"],
                    "marketProviders": market["providers"],
                    "result": result,
                    "pointsEarned": confidence_points if is_correct else 0,
                })
            history = score_history[(season, expert)]
            for key in weekly:
                history[key] += weekly[key]
            expert_scores.append({"expert": expert, **weekly,
                                  "possiblePoints": sum(range(MAX_POINTS - n + 1, MAX_POINTS + 1))})

        # Ranking within the week is by earned confidence points; names make tied
        # display order stable without changing their shared rank.
        weekly_sorted = sorted(expert_scores, key=lambda row: (-row["points"], row["expert"]))
        rank = 0
        prior_points = None
        for i, row in enumerate(weekly_sorted, 1):
            if row["points"] != prior_points:
                rank = i
                prior_points = row["points"]
            row["rank"] = rank
            cumulative = score_history[(season, row["expert"])]
            row["seasonToDatePoints"] = cumulative["points"]
            row["seasonToDateWins"] = cumulative["wins"]

        cumulative_sorted = sorted(expert_names, key=lambda name: (-score_history[(season, name)]["points"], name))
        cumulative_rank = {}
        rank, prior = 0, None
        for i, name in enumerate(cumulative_sorted, 1):
            points = score_history[(season, name)]["points"]
            if points != prior:
                rank = i
                prior = points
            cumulative_rank[name] = rank

        for row in weekly_sorted:
            weekly_rows.append({"season": season, "week": week_num, "games": n,
                                "pointsAvailable": row["possiblePoints"], "weeklyRank": row["rank"],
                                "expert": row["expert"], "weeklyPoints": row["points"],
                                "seasonToDateRank": cumulative_rank[row["expert"]],
                                "seasonToDatePoints": row["seasonToDatePoints"],
                                "correct": row["wins"], "incorrect": row["losses"],
                                "ties": row["ties"], "noPicks": row["noPicks"]})

        output_games = []
        for game in games:
            output_games.append({key: game.get(key) for key in (
                "gameId", "matchup", "scheduledAt", "away", "awayScore", "home", "homeScore",
                "actualWinner", "status", "isFinal") } | {
                "market": markets[game["gameId"]],
                "expertAssignments": assigned_by_game[game["gameId"]],
            })
        outputs.append({"season": season, "week": week_num, "gameCount": n,
                        "confidenceValues": list(range(MAX_POINTS, MAX_POINTS - n, -1)),
                        "marketPolicy": "consensus; else ESPN BET; else median of unique non-live book spreads; moneyline implied probability breaks spread ties",
                        "expertScores": weekly_sorted, "games": output_games})

    for season in (2023, 2024, 2025):
        experts = sorted(name for (year, name) in score_history if year == season)
        ordered = sorted(experts, key=lambda name: (-score_history[(season, name)]["points"], name))
        prior_points, rank = None, 0
        for i, expert in enumerate(ordered, 1):
            totals = score_history[(season, expert)]
            if totals["points"] != prior_points:
                rank, prior_points = i, totals["points"]
            possible = sum(row["pointsAvailable"] for row in weekly_rows if row["season"] == season and row["expert"] == expert)
            decisions = totals["wins"] + totals["losses"]
            final_rows.append({"season": season, "rank": rank, "expert": expert,
                               "totalPoints": totals["points"], "pointsAvailable": possible,
                               "pointsPct": round(100 * totals["points"] / possible, 3) if possible else 0,
                               "correct": totals["wins"], "incorrect": totals["losses"],
                               "ties": totals["ties"], "noPicks": totals["noPicks"],
                               "decisionAccuracyPct": round(100 * totals["wins"] / decisions, 3) if decisions else 0})

    assert sum(len(w["games"]) for w in outputs) == 816
    assert all(len(g["expertAssignments"]) == len(w["expertScores"]) for w in outputs for g in w["games"])
    with WEEKLY_JSONL.open("w") as out:
        for row in outputs:
            out.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    for path, rows, fields in (
        (WEEKLY_CSV, weekly_rows, ["season", "week", "games", "pointsAvailable", "weeklyRank", "expert", "weeklyPoints", "seasonToDateRank", "seasonToDatePoints", "correct", "incorrect", "ties", "noPicks"]),
        (FINAL_CSV, final_rows, ["season", "rank", "expert", "totalPoints", "pointsAvailable", "pointsPct", "correct", "incorrect", "ties", "noPicks", "decisionAccuracyPct"]),
    ):
        with path.open("w", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    print(f"Simulated {len(outputs)} weeks / {sum(len(w['games']) for w in outputs)} games")
    print("FINAL STANDINGS")
    for row in final_rows:
        print(f"{row['season']} {row['rank']:>2}. {row['expert']:<12} {row['totalPoints']:>4} points; {row['correct']}-{row['incorrect']}")
    print(f"Wrote {WEEKLY_JSONL.relative_to(ROOT)}, {WEEKLY_CSV.relative_to(ROOT)}, and {FINAL_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
