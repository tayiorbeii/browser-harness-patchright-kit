# ESPN NFL expert picks (regular season, 2023–2025)

`espn-nfl-picks-2023-2025.jsonl` contains one JSON object per season/week (54 records total). Each record has the expert roster and game list; each game contains the experts' picks, final score/result, and available ESPN odds-provider markets.

## Fields and interpretation

- Week-level `season`, `seasonType` (`2` = regular season), `week`, `sourceUrl`, `canonicalUrl`, `pageTitle`, `retrievedAt`, and `pageStatus` identify and audit the picks page.
- `experts` includes the displayed name, headshot alt/full name, headshot URL, and column index. Rosters vary by season.
- Each `game` includes ESPN `gameId`, teams, schedule date, status, final scores, actual winner, and linked game page.
- Each game's `picks` array has one row per expert: selected team abbreviation, ESPN's displayed correctness class, and `correct` recomputed from the scoreboard result. `correct` is null for a game without a unique winner; an absent pick stays null.
- `scoreboard` records the ESPN scoreboard request and identity checks. `matchesRequest` and the two missing-ID arrays should pass before using a week.
- `odds.markets` preserves available ESPN Core provider records. Each market includes provider identity, spread/total, home/away prices, and provider `open`/`close`/`current` data when supplied. Older records may instead expose `preMatch` values. These are provider-specific snapshots, **not a guaranteed consensus line at the moment each expert made a pick**; compare like-for-like providers and line fields.

## Collection and validation

Run from the repository root with the isolated project browser:

```sh
./scripts/bh run < scripts/scrape_espn_picks.py
```

The script resumes complete week records and atomically rewrites the JSONL after each week. Optional `ESPN_FIRST_SEASON`, `ESPN_LAST_SEASON`, `ESPN_FIRST_WEEK`, `ESPN_LAST_WEEK`, and `ESPN_OUTPUT` environment variables scope or redirect a run. It asserts page identity, scoreboard/game-ID agreement, final scores, successful odds requests, and unique game IDs for the selected range.

## Coverage notes

- 54/54 weeks and 816/816 regular-season games were captured; all scoreboard season/week and game-ID checks passed, and every game was final.
- ESPN's displayed correctness agreed with the scoreboard-derived result for every pick with a unique outcome.
- One pick is blank: Matt Bowen, 2023 Week 10, TEN at TB. Green Bay–Dallas ended in a 40–40 tie in 2025 Week 4; its winner and all experts' `correct` values are null.
- Spread data is present for all 816 games, but available providers and historical fields differ by game. Where an explicit `open`/`close` pair is absent, do not interpret `preMatch` or a provider's current field as a closing line without additional source verification.
