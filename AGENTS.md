# Repository Guidelines

## Current Scope and Source of Truth

This Django/React monorepo monitors intraday A-share **sector** fund flow from two independent upstream sources. The current implementation and `README.md` take precedence over older session history.

- **Eastmoney (`fundflow`)** covers only third-level industries using `fs=m:90+s:8+f:!50`. Do not reintroduce second-level industry filters, models, fields, APIs, UI controls, or compatibility branches without an explicit new requirement.
- **Kaipanla (`kaipanla`)** covers the upstream App's mixed industry/concept sector universe through `ZhiShuRanking.RealRankingInfo`. It is intentionally separate from Eastmoney and must not be normalized into an Eastmoney-shaped source.
- The runtime product has no stock workflow. Do not reintroduce stock models, commands, APIs, CSV synchronization, or UI without an explicit new requirement.
- `fundflow` migrations `0001`–`0010` and `kaipanla` migration `0001` are applied history. In particular, `fundflow` migration `0010_remove_secondary_industry` removes the temporary second-level schema/data. Never edit or delete applied migrations; create a new migration.
- Keep `README.md` focused on the two current sector sources. Do not restore removed full live Eastmoney pagination, browser result caching, automatic polling, `--force`, stock workflows, or second-level Eastmoney behavior.

## Architecture and Responsibilities

### Shared project configuration

- `backend/config/`: Django settings, API routing, CORS, cache, logging, and ASGI/WSGI entry points.
- The project runs in `Asia/Shanghai`; `chinese-calendar` plus an explicit weekend exclusion determines A-share trading days.
- Development uses default SQLite (`backend/db.sqlite3`) plus `FileBasedCache`. `kaipanla` models use the independently routed `backend/kaipanla.sqlite3` database through `kaipanla.db_router.KaipanlaRouter`.
- Production must use a shared Redis-compatible cache across web workers and scheduled commands. Do not add browser caching or automatic polling unless explicitly requested.

### Eastmoney app (`backend/fundflow/`)

- `models.py`: third-level industry snapshots and two-ranking status per tick.
- `services/eastmoney/`: request constants, interval planning, HTTP session handling, parsing, and the two-ranking orchestration.
- `services/snapshot_time.py`: trading-hour checks and source-time alignment.
- `services/snapshot_collection.py`: fetch result plus snapshot-time collection; no database writes.
- `services/snapshot_writer.py`: atomic snapshot/status upsert and post-commit cache invalidation.
- `services/sector_intraday_queries.py`: read-only ORM queries.
- `services/sector_intraday_builders.py`: database rows to API payload transformation without ORM or cache access.
- `services/sector_intraday_service.py`: intraday use-case coordination and server-side cache access.
- `management/commands/fetch_sector_fund_flow.py`: CLI parsing and orchestration only.
- `views.py`: thin DRF parameter parsing and response views.
- `tests.py`: contract and regression tests.

### Kaipanla app (`backend/kaipanla/`)

- `models.py`: Kaipanla snapshot fields and one full-fetch status per tick. Preserve the upstream-native field set; do not invent Eastmoney-only values.
- `db_router.py`: keeps all Kaipanla reads, writes, and migrations in the `kaipanla` database.
- `services/http_client.py`: form POST and response decoding only.
- `services/ranking_fetcher.py`: sequential pagination, retry, parse orchestration, and code-level deduplication.
- `services/parser.py`: maps the upstream fixed-position row array into real supported fields only.
- `services/snapshot_*.py`: snapshot-time selection, collection, atomic persistence, and post-commit cache invalidation.
- `services/intraday_queries.py`, `intraday_builders.py`, `intraday_service.py`, `intraday_cache.py`: the read-only query, pure payload, use-case, and cache layers.
- `management/commands/fetch_kaipanla_sector_fund_flow.py`: CLI parsing and orchestration only.
- `views.py`, `urls.py`, `tests.py`: independent DRF API contract and regression suite.

### Frontend (`frontend/src/`)

- `api/client.js`: all HTTP access. It owns `/eastmoney-api/` and `/kaipanla-api/` requests and applies `VITE_API_BASE` only as the host base.
- `features/sector-flow/`: Eastmoney page, data/selection hooks, constants, and pure series helpers.
- `features/kaipanla-flow/`: corresponding Kaipanla feature slice. Keep it independent rather than adding source conditionals through the Eastmoney slice.
- `components/SectorFlowChart.jsx` and `components/SectorRankingList.jsx`: source-agnostic display components.
- `App.jsx`: source tab selection; default tab is Eastmoney. `index.css`: global and responsive styling.

Keep views, management commands, and React components thin. Put upstream access, database reads, persistence, validation, time semantics, cache behavior, and payload aggregation in focused service modules.

## Eastmoney Data Contract and Request Discipline

The upstream API is unofficial and unstable. Preserve these verified semantics unless a fresh browser/network capture proves a change:

- Endpoint: `https://push2.eastmoney.com/api/qt/clist/get`.
- Request only third-level industries with `fs=m:90+s:8+f:!50`. Do not request second-level industries or the old mixed plate filter.
- Use `ut=8dec03ba335b81bf4ebdf7b29ec27d15`, `fid=f62`, `pn=1`, and `pz=50`.
- Fetch exactly two independent rankings: inflow with `po=1`, then outflow with `po=0`.
- Before the first HTTP request, generate the full interval plan: 10 random retry intervals (five possible retries for each ranking) plus one 120-second successful-ranking interval. Every retry interval must be at least 45 seconds and distinct; all planned intervals together must be at most 700 seconds.
- If the first ranking request succeeds, wait exactly 120 seconds before the outflow request. Do not add a post-request cooldown.
- On a failed initial request, retry that ranking at most five times using its precomputed retry intervals. Rebuild an owned session after a transport connection failure. A monotonic 889-second deadline must stop a fetch rather than shorten a required wait.
- Merge by `sector_code`; the later outflow response overwrites duplicate codes because it is newer.
- If one direction fails, preserve the other direction and persist completeness in `EastmoneySectorFundFlowSnapshotStatus`. If both fail, do not write a snapshot.

Do **not** restore full live pagination: ranking movement between page requests caused duplicates and incomplete snapshots. Do not use aggressive concurrency, fake IP headers, or access-control bypasses. Real upstream tests may fail due to rate limiting; distinguish network instability from deterministic code failures.

## Kaipanla Data Contract and Credential Discipline

The Kaipanla upstream is also unofficial and relies on App-style credentials. Treat it as a separate integration with stricter secret handling.

- POST to `https://apphwshhq.longhuvip.com/w1/api/index.php` using `c=ZhiShuRanking`, `a=RealRankingInfo`, `Type=1`, `ZSType=7`, `Order=1`, and the current fixed App metadata in `services/constants.py`.
- Fetch sequential pages of 30 rows: start `Index=0`, increment by 30, and stop once the upstream `Count` is covered. Deduplicate only by `sector_code`.
- Each page gets at most three total attempts with a 1.5-second delay between failed attempts. If a page cannot be fetched, returns a nonzero `errcode`, or the final result has no valid rows, do not write a snapshot.
- Read `KPL_USER_ID`, `KPL_TOKEN`, and `KPL_DEVICE_ID` only from environment variables. Never hardcode them, add them to fixtures, echo them in tests, or commit captured HTTP traffic.
- The upstream records are fixed-position arrays. Preserve the current parser mapping and ignore duplicate strength/change fields. Keep only fields actually returned: name/code, change percentage, main net inflow/buy/sell, large-order net inflow, volume ratio, turnover, float market cap, and total market cap.
- Do not add fabricated Eastmoney fields (index, main-net-inflow ratio, or super/large/medium/small split) to Kaipanla models or APIs without verified upstream data and an explicit requirement.

## Trading Time, Persistence, Aggregation, and Cache

- Use the 18 discrete 15-minute A-share ticks: `09:30`–`11:30`, then `13:00`–`15:00`. The chart must jump directly from `11:30` to `13:00`.
- Normal fetches run only during trading time and floor timestamps to the current 15-minute tick. `--latest` initializes/restores the most recent upstream tick outside trading hours. `--dry-run` performs real requests but never writes. `--force` is intentionally unsupported.
- Both sources upsert `(sector_code, snapshot_time)` so retrying the same tick repairs its snapshot. Persist status in the same transaction and invalidate the corresponding cache only after a successful commit.
- Eastmoney current Top N candidates must come from the selected direction's current usable ranking. If it is unavailable, fall back strictly to the immediately previous trading tick for that direction; earlier snapshots only fill history for already selected sectors.
- Kaipanla uses one full ranking. If the current tick is absent or failed, use the nearest previous usable snapshot as the current candidate source.
- Missing ticks, incomplete status, or fallback make the payload `stale=true`.
- API date parsing accepts an ISO date. Missing or invalid dates fall back to the source database's latest stored trade date, then to today's local date. `inflow_top` and `outflow_top` default to 5 and are clamped to 0–30.
- API payloads use `trade_date`, `time_points`, `series`, and `stale`; series values are in 亿元. Historical dates receive all 18 ticks; the current date receives only elapsed ticks. The frontend aligns both onto the complete 18-tick display axis.

## Frontend Contract

The frontend has an Eastmoney and a Kaipanla tab, defaulting to Eastmoney. Each active page makes one request on mount; it does not cache browser results or poll automatically.

- Both feature slices request up to 25 inflow and 25 outflow series, list both Top 25 rankings, and initially select five per direction for the chart.
- Preserve manual checkbox choices throughout the same `trade_date`; reset to default only when a populated new date arrives.
- Treat upstream names as untrusted in the chart tooltip: retain HTML escaping.
- Manually verify loading, empty, error, stale-data, checkbox, tab-switching, lunch-break-axis, and responsive states. The Vite large-bundle warning is known but is not a build failure.

## Build, Test, and Development Commands

Run backend commands from `backend/`:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py migrate --database=kaipanla
python manage.py fetch_sector_fund_flow --dry-run
python manage.py fetch_kaipanla_sector_fund_flow --dry-run
python manage.py fetch_sector_fund_flow --latest
python manage.py fetch_kaipanla_sector_fund_flow --latest
python manage.py test fundflow kaipanla
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py runserver 8000
```

Run frontend commands from `frontend/`:

```bash
npm install
npm run dev
npm run lint
npm run build
npm run preview
```

Before submitting, run backend tests/checks, migration drift detection, frontend lint/build, and `git diff --check`. Mock sleeps and network calls in unit tests; make live upstream checks explicit, minimal, and read-only. Production scheduling should use independent locks (such as `flock`) to prevent overlapping runs of each several-minute fetch command.

## Coding, Security, and Change Discipline

Use four-space indentation and `snake_case` in Python; Django models use `PascalCase`. Use two-space indentation, `PascalCase` components, and `camelCase` variables in JavaScript/JSX. Prefer focused regression tests before changing request parameters, retry scheduling, pagination, fallback rules, cache invalidation, source-time alignment, or fixed-axis behavior.

Do not commit secrets, tokens, captured traffic, local databases, cache files, virtual environments, logs, `node_modules`, or generated bundles. The API currently has no built-in authentication; production work must restrict its exposure through deployment configuration or add an explicit, reviewed authentication requirement.

Use concise imperative commits with a scope, such as `backend: retry kaipanla ranking page` or `frontend: preserve source tab selections`. PRs must describe behavior changes, verification commands, migrations/deployment impact, upstream-contract changes, and include screenshots for visible UI changes.
