"""Scrape ESPN NFL expert picks and game results using browser-harness helpers.

Run from the repository root with:
  ./scripts/bh run < scripts/scrape_espn_picks.py
Optional environment: ESPN_FIRST_SEASON, ESPN_LAST_SEASON, ESPN_FIRST_WEEK,
ESPN_LAST_WEEK, ESPN_OUTPUT. This file is executed inside browser-harness' Python
runtime, where goto_url(), wait_for_load(), js(), list_tabs(), and switch_tab()
are preloaded.
"""
import datetime
import json
import os
from pathlib import Path

FIRST_SEASON = int(os.getenv("ESPN_FIRST_SEASON", "2023"))
LAST_SEASON = int(os.getenv("ESPN_LAST_SEASON", "2025"))
FIRST_WEEK = int(os.getenv("ESPN_FIRST_WEEK", "1"))
LAST_WEEK = int(os.getenv("ESPN_LAST_WEEK", "18"))
OUTPUT = Path(os.getenv("ESPN_OUTPUT", "data/espn-nfl-picks-2023-2025.jsonl"))
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

records = {}
if OUTPUT.exists():
    for line in OUTPUT.read_text().splitlines():
        try:
            row = json.loads(line)
            records[(row["season"], row["week"])] = row
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

# Reuse an existing ESPN work tab (or a blank tab); do not close other tabs.
tabs = list_tabs()
work = next((t for t in tabs if "www.espn.com/nfl/picks" in t.get("url", "")), None)
if work is None:
    work = next((t for t in tabs if t.get("url") == "about:blank"), None)
if work is None:
    raise RuntimeError("No ESPN picks tab or blank work tab is available")
switch_tab(work["targetId"])

EXTRACT = r'''(async (season, week) => {
  const tables = [...document.querySelectorAll("table")];
  const gameTable = tables.find(t => t.querySelector('a[href*="/gameId/"]'));
  const pickTable = tables.find(t => t.querySelector(".PassFailWrapper"));
  const title = document.title;
  const pageUrl = location.href;
  const headerCells = pickTable ? [...pickTable.rows[0].cells] : [];
  const experts = headerCells.map((cell, index) => ({
    column: index,
    name: cell.querySelector("div.headshot-container > div:last-child")?.innerText?.trim() || cell.innerText.trim(),
    fullName: cell.querySelector("img")?.alt || null,
    headshotUrl: cell.querySelector("img")?.src || null
  }));
  const games = gameTable ? [...gameTable.rows].flatMap(row => {
    const link = row.querySelector('a[href*="/gameId/"]');
    if (!link) return [];
    const gameId = row.id || link.href.match(/gameId\/(\d+)/)?.[1] || null;
    const pickRow = pickTable ? [...pickTable.rows].find(r => r.id === gameId) : null;
    const picks = experts.map((expert, i) => {
      const cell = pickRow?.cells[i];
      const img = cell?.querySelector("img");
      const imgUrl = img?.src || null;
      const imagePath = imgUrl ? decodeURIComponent(new URL(imgUrl).searchParams.get("img") || imgUrl) : "";
      const team = imagePath.match(/\/500\/([^/.]+)\.png/i)?.[1]?.toUpperCase() || null;
      const classes = cell?.querySelector(".PassFailWrapper")?.className || "";
      return { expert: expert.name, fullName: expert.fullName, pick: team,
        displayedCorrectness: classes.includes("is--correct") ? true : classes.includes("is--incorrect") ? false : null };
    });
    return [{ gameId, matchup: link.innerText.trim(), gameUrl: link.href,
      displayDate: row.querySelector(".competition-dates")?.innerText?.trim() || null, picks }];
  }) : [];

  async function fetchJson(url) {
    let lastError = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
      } catch (error) {
        lastError = String(error);
        await new Promise(resolve => setTimeout(resolve, 350 * (attempt + 1)));
      }
    }
    throw new Error(lastError || "request failed");
  }

  const scoreboardUrl = `https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=${season}&seasontype=2&week=${week}`;
  let scoreboard = null, scoreboardError = null;
  try { scoreboard = await fetchJson(scoreboardUrl); }
  catch (error) { scoreboardError = String(error); }
  const events = scoreboard?.events || [];
  const eventById = Object.fromEntries(events.map(event => [String(event.id), event]));
  const oddsById = {};
  // ESPN Core exposes archived book-level lines, including open/close where available.
  let next = 0;
  async function oddsWorker() {
    while (next < games.length) {
      const game = games[next++];
      const url = `https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/${encodeURIComponent(game.gameId)}/competitions/${encodeURIComponent(game.gameId)}/odds?limit=100`;
      try {
        const odds = await fetchJson(url);
        oddsById[game.gameId] = { source: "espn-core-odds", schemaVersion: 2, status: "ok", sourceUrl: url,
          providerCount: odds.count ?? null,
          markets: (odds.items || []).map(line => {
            const old = line.bettingOdds?.teamOdds || {};
            const home = line.homeTeamOdds || {};
            const away = line.awayTeamOdds || {};
            return {
              provider: line.provider?.name || null,
              providerId: line.provider?.id || null,
              details: line.details || null,
              spread: line.spread ?? old.preMatchSpreadHandicapHome?.value ?? null,
              total: line.overUnder ?? old.preMatchTotalHandicap?.value ?? null,
              home: {
                spread: home.close?.pointSpread?.american ?? home.current?.pointSpread?.american ?? old.preMatchSpreadHandicapHome?.value ?? null,
                spreadOdds: home.close?.spread?.american ?? home.current?.spread?.american ?? old.preMatchSpreadHome?.value ?? null,
                moneyline: home.close?.moneyLine?.american ?? home.current?.moneyLine?.american ?? old.preMatchMoneyLineHome?.value ?? null,
                open: home.open || null, close: home.close || null, current: home.current || null
              },
              away: {
                spread: away.close?.pointSpread?.american ?? away.current?.pointSpread?.american ?? old.preMatchSpreadHandicapAway?.value ?? null,
                spreadOdds: away.close?.spread?.american ?? away.current?.spread?.american ?? old.preMatchSpreadAway?.value ?? null,
                moneyline: away.close?.moneyLine?.american ?? away.current?.moneyLine?.american ?? old.preMatchMoneyLineAway?.value ?? null,
                open: away.open || null, close: away.close || null, current: away.current || null
              },
              open: line.open || null,
              close: line.close || null,
              current: line.current || null,
              preMatch: Object.fromEntries(Object.entries(old).filter(([key]) => /^(preMatchMoneyLine|preMatchSpread|preMatchTotal)/.test(key)).map(([key, value]) => [key, value.value ?? null]))
            };
          }) };
      } catch (error) { oddsById[game.gameId] = { source: "espn-core-odds", schemaVersion: 2, status: "error", sourceUrl: url, error: String(error), markets: [] }; }
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, games.length) }, () => oddsWorker()));

  const enrichedGames = games.map(game => {
    const event = eventById[String(game.gameId)];
    const competition = event?.competitions?.[0];
    const competitors = competition?.competitors || [];
    const home = competitors.find(c => c.homeAway === "home");
    const away = competitors.find(c => c.homeAway === "away");
    const winner = competitors.find(c => c.winner === true);
    const complete = competition?.status?.type?.completed === true || event?.status?.type?.completed === true;
    const actualWinner = winner?.team?.abbreviation || null;
    return { ...game,
      away: away?.team?.abbreviation || null,
      home: home?.team?.abbreviation || null,
      awayScore: away?.score == null ? null : Number(away.score),
      homeScore: home?.score == null ? null : Number(home.score),
      scheduledAt: competition?.date || event?.date || null,
      status: competition?.status?.type?.name || event?.status?.type?.name || "UNKNOWN",
      isFinal: complete,
      actualWinner,
      outcome: complete && !winner ? "tie_or_no_winner" : null,
      picks: game.picks.map(pick => ({ ...pick,
        correct: complete && actualWinner && pick.pick ? pick.pick === actualWinner : null
      })),
      odds: oddsById[String(game.gameId)] || { source: "espn-core-odds", status: "not_requested", markets: [] }
    };
  });
  const scoreboardSeason = scoreboard?.leagues?.[0]?.season?.year ?? null;
  const scoreboardWeek = scoreboard?.week?.number ?? null;
  const pageMatchesRequest = pageUrl.includes(`season=${season}`) && pageUrl.includes(`week=${week}`) && title.includes(String(season));
  const gameIds = new Set(games.map(g => String(g.gameId)));
  const eventIds = new Set(events.map(e => String(e.id)));
  return JSON.stringify({
    season, seasonType: 2, week,
    sourceUrl: pageUrl,
    canonicalUrl: window.__espnfitt__?.page?.meta?.canonical || null,
    pageTitle: title,
    retrievedAt: new Date().toISOString(),
    pageStatus: pageMatchesRequest && gameTable && pickTable ? "accepted" : "page_mismatch_or_missing_table",
    experts,
    gameCount: games.length,
    scoreboard: { sourceUrl: scoreboardUrl, season: scoreboardSeason, week: scoreboardWeek,
      eventCount: events.length, error: scoreboardError,
      matchesRequest: scoreboardSeason === season && scoreboardWeek === week,
      missingPageGameIds: [...eventIds].filter(id => !gameIds.has(id)),
      missingScoreboardGameIds: [...gameIds].filter(id => !eventIds.has(id)) },
    games: enrichedGames
  });
})'''

for season in range(FIRST_SEASON, LAST_SEASON + 1):
    for week in range(FIRST_WEEK, LAST_WEEK + 1):
        previous = records.get((season, week))
        if previous and previous.get("pageStatus") == "accepted" and previous.get("scoreboard", {}).get("matchesRequest") and all(g.get("odds", {}).get("source") == "espn-core-odds" and g.get("odds", {}).get("schemaVersion") == 2 and g.get("odds", {}).get("status") in ("ok", "empty") for g in previous.get("games", [])) and all(p.get("pick") is not None or p.get("correct") is None for g in previous.get("games", []) for p in g.get("picks", [])):
            print(f"SKIP {season} week {week}: complete cached record")
            continue
        url = f"https://www.espn.com/nfl/picks?season={season}&week={week}&seasontype=2"
        try:
            goto_url(url)
            wait_for_load()
            raw = js(f"{EXTRACT}({season},{week})")
            record = json.loads(raw)
        except Exception as error:
            record = {"season": season, "seasonType": 2, "week": week,
                      "sourceUrl": url, "retrievedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      "pageStatus": "error", "error": str(error), "experts": [], "games": []}
        records[(season, week)] = record
        temp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
        with temp.open("w") as out:
            for key in sorted(records):
                out.write(json.dumps(records[key], separators=(",", ":"), ensure_ascii=False) + "\n")
        temp.replace(OUTPUT)
        good_odds = sum(g.get("odds", {}).get("status") == "ok" for g in record.get("games", []))
        markets = sum(len(g.get("odds", {}).get("markets", [])) for g in record.get("games", []))
        print(f"{season} week {week}: {record.get('pageStatus')} games={record.get('gameCount', 0)} experts={len(record.get('experts', []))} scoreboard={record.get('scoreboard', {}).get('eventCount', 0)} odds={good_odds}/{len(record.get('games', []))} provider-markets={markets}")

selected = [records.get((season, week)) for season in range(FIRST_SEASON, LAST_SEASON + 1) for week in range(FIRST_WEEK, LAST_WEEK + 1)]
assert all(record and record.get("pageStatus") == "accepted" for record in selected), "one or more picks pages failed identity/table validation"
assert all(record.get("scoreboard", {}).get("matchesRequest") and not record["scoreboard"].get("missingPageGameIds") and not record["scoreboard"].get("missingScoreboardGameIds") for record in selected), "scoreboard season/week or game IDs do not match"
assert all(game.get("isFinal") for record in selected for game in record.get("games", [])), "one or more games lack a final result"
assert all(game.get("odds", {}).get("status") in ("ok", "empty") for record in selected for game in record.get("games", [])), "one or more game odds requests failed"
assert all(len({game["gameId"] for game in record.get("games", [])}) == len(record.get("games", [])) for record in selected), "duplicate game ID within a week"
print(f"AUDIT OK: {len(selected)} weeks, {sum(len(r['games']) for r in selected)} final games; odds fetches succeeded")