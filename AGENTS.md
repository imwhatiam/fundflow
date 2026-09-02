# Repository Guidelines

## Current Scope and Source of Truth

This Django/React monorepo monitors **Eastmoney third-level industry fund flow**. The current implementation and `README.md` take precedence over older session history.

- The runtime product is sector-only and third-level-industry-only. Do not reintroduce second-level industry filters, models, fields, APIs, UI controls, or compatibility branches without an explicit new requirement.
- The runtime product does not include stock workflows. Do not reintroduce stock models, stock fetch commands, stock APIs, CSV sector synchronization, or stock UI without an explicit new requirement.
- Migrations `0001`–`0009` contain applied history. Migration `0010_remove_secondary_industry` removes the temporary second-level data/schema. Do not edit or delete applied migrations—create a new migration instead.
- Keep `README.md` focused on the latest supported behavior. Do not restore removed pagination, browser caching, automatic polling, `--force`, stock-level workflows, or second-level-industry behavior.

## Project Structure and Responsibilities

- `backend/config/`: Django settings, routing, cache, CORS, and ASGI/WSGI entry points.
- `backend/fundflow/models.py`: third-level industry snapshots and per-tick ranking status.
- `backend/fundflow/services/eastmoney/`: request constants, interval planning, HTTP session handling, response parsing, and two-ranking orchestration.
- `backend/fundflow/services/snapshot_time.py`: trading-hour checks and snapshot-time alignment.
- `backend/fundflow/services/snapshot_collection.py`: fetch result plus snapshot-time collection; no database writes.
- `backend/fundflow/services/snapshot_writer.py`: atomic snapshot/status upsert and post-commit cache invalidation.
- `backend/fundflow/services/sector_intraday_queries.py`: read-only ORM queries.
- `backend/fundflow/services/sector_intraday_builders.py`: database rows to API payload transformation without ORM or cache access.
- `backend/fundflow/services/sector_intraday_service.py`: intraday use-case coordination and server-side cache access.
- `backend/fundflow/management/commands/fetch_sector_fund_flow.py`: CLI parsing and orchestration only.
- `backend/fundflow/views.py`: thin DRF parameter parsing and response views.
- `backend/fundflow/tests.py`: backend contract and regression tests.
- `frontend/src/api/`: all HTTP access; `features/sector-flow/`: page, request/selection hooks, and pure series helpers; `components/`: charts and ranking UI; `index.css`: global styling.

Keep views, management commands, and React components thin. Put upstream access, database reads, persistence, validation, time semantics, cache behavior, and payload aggregation in focused service modules.

## Eastmoney Data Contract and Request Discipline

The upstream API is unofficial and unstable. Preserve these verified semantics unless a fresh browser/network capture proves a change:

- Endpoint: `https://push2.eastmoney.com/api/qt/clist/get`.
- Request only third-level industries with `fs=m:90+s:8+f:!50`. Do not request second-level industries or the old mixed plate filter.
- Use `ut=8dec03ba335b81bf4ebdf7b29ec27d15`, `fid=f62`, `pn=1`, and `pz=50`.
- Fetch exactly two independent rankings: inflow with `po=1`, then outflow with `po=0`.
- Before the first HTTP request, generate the full interval plan: 10 random retry intervals (five possible retries for each ranking) plus one 120-second successful-ranking interval. Every retry interval must be at least 45 seconds and distinct; all planned intervals together must be at most 700 seconds.
- If the first ranking request succeeds, wait exactly 120 seconds before the outflow request. Do not add a post-request cooldown.
- On a failed initial request, retry that ranking at most five times using its precomputed retry intervals. Rebuild an owned session after a transport connection failure. A monotonic deadline strictly below 890 seconds must stop a fetch rather than shorten a required wait.
- Merge by `sector_code`; the later outflow response overwrites duplicate codes because it is newer.
- If one direction fails, preserve the other direction and record completeness in `EastmoneySectorFundFlowSnapshotStatus`. If both fail, do not write a snapshot.

Do **not** restore full live pagination: ranking movement between page requests caused duplicates and incomplete snapshots. Do not use aggressive concurrency, fake IP headers, or access-control bypasses. Real upstream tests may fail due to rate limiting; distinguish network instability from deterministic code failures.

## Trading Time, Persistence, Aggregation, and Cache

- Use `chinese-calendar` through `services/trading_calendar.py`, while always excluding weekends. Exchange-specific exceptional closures may require explicit maintenance.
- Use the 18 discrete 15-minute A-share ticks: `09:30`–`11:30`, then `13:00`–`15:00`. The chart must jump directly from `11:30` to `13:00`.
- Normal fetches run only during trading time and floor timestamps to the current 15-minute tick. `--latest` initializes/restores the most recent upstream tick outside trading hours. `--dry-run` performs real requests but never writes. `--force` was intentionally removed.
- Upsert `(sector_code, snapshot_time)` so retrying the same tick repairs partial data. Persist ranking status in the same transaction and invalidate the server cache only after a successful commit.
- Current Top N candidates must come from the selected direction's latest usable ranking. Earlier snapshots may only fill the history of already selected sectors.
- If the current tick lacks one direction, fall back strictly to the immediately previous trading tick for that direction and return `stale=true`. Missing ticks, incomplete status, or fallback also make the payload stale.
- Use server-side caching only. Development uses Django `FileBasedCache`; production must use a shared Redis-compatible cache across web workers and scheduled commands. Do not add browser result caching or automatic polling unless explicitly requested.

## Frontend Contract

The frontend displays only third-level industries. It requests up to 25 inflow and 25 outflow series, lists both Top 25 rankings, and initially selects five per direction for the chart. Preserve user checkbox selections during the same trade date. Use the fixed 18 discrete trading ticks as the chart category axis. Align API `time_points` into those ticks; future ticks remain empty, and the axis must jump directly from `11:30` to `13:00`.

Manually verify loading, empty, error, stale-data, checkbox, lunch-break-axis, and responsive states. The existing Vite large-bundle warning is known but is not a build failure.

## Build, Test, and Development Commands

Run backend commands from `backend/`:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py fetch_sector_fund_flow --dry-run
python manage.py fetch_sector_fund_flow --latest
python manage.py test fundflow
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

Before submitting, run backend tests/checks, migration drift detection, frontend lint/build, and `git diff --check`. Mock sleeps and network calls in unit tests; make live Eastmoney checks explicit, minimal, and read-only. Production scheduling should use a lock such as `flock` because one fetch can take several minutes.

## Coding, Security, and Change Discipline

Use four-space indentation and `snake_case` in Python; Django models use `PascalCase`. Use two-space indentation, `PascalCase` components, and `camelCase` variables in JavaScript/JSX. Prefer focused regression tests before changing request parameters, retry scheduling, fallback rules, cache invalidation, or time alignment.

Do not commit secrets, tokens, captured traffic, local databases, cache files, virtual environments, logs, `node_modules`, or generated bundles. Use concise imperative commits with a scope, such as `backend: schedule third-level sector retries` or `frontend: label third-level industries`. PRs must describe behavior changes, verification commands, migrations/deployment impact, and include screenshots for visible UI changes.
