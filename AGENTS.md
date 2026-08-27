# Repository Guidelines

## Current Scope and Source of Truth

This Django/React monorepo monitors **Eastmoney industry-sector fund flow**. The current implementation and `README.md` take precedence over older session history.

- The runtime product is sector-only. Do not reintroduce stock models, stock fetch commands, stock APIs, CSV sector synchronization, or stock UI without an explicit new requirement.
- Migrations `0001`–`0006` contain legacy schema history; `0007` removes the legacy stock tables. Do not edit or delete applied migrations—create a new migration instead.
- Keep `README.md` focused on the latest supported behavior. Do not restore documentation for removed pagination, browser caching, 30-second polling, `--force`, or stock-level workflows.

## Project Structure and Responsibilities

- `backend/config/`: Django settings, routing, cache, CORS, and ASGI/WSGI entry points.
- `backend/fundflow/models.py`: Eastmoney sector snapshots and per-tick ranking status.
- `backend/fundflow/services/`: upstream requests, trading calendar/time logic, caching, fallback, ranking, and aggregation.
- `backend/fundflow/management/commands/fetch_sector_fund_flow.py`: orchestration and persistence only.
- `backend/fundflow/views.py`: thin DRF parameter parsing and response views.
- `backend/fundflow/tests.py`: backend contract and regression tests.
- `frontend/src/api/`: all HTTP access; `components/`: charts and ranking UI; `index.css`: global styling.

Keep views and React components thin. Put retrieval, validation, time semantics, cache behavior, and aggregation in service modules.

## Eastmoney Data Contract and Request Discipline

The upstream API is unofficial and unstable. Preserve these verified semantics unless a fresh browser/network capture proves a change:

- Endpoint: `https://push2.eastmoney.com/api/qt/clist/get`.
- Industry page filter: `fs=m:90+s:4` (roughly 128 industries), not `m:90+t:2` (the old mixed set of roughly 496 plates).
- Use `ut=8dec03ba335b81bf4ebdf7b29ec27d15`, `fid=f62`, `pn=1`, and `pz=50`.
- Fetch two independent rankings: inflow with `po=1`, then outflow with `po=0`.
- Wait 60 seconds between the two rankings. After a successful second request, retain the 10-second cooldown. Preserve bounded retries, exponential backoff, and session rebuilding on transport failure.
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

The frontend requests up to 25 inflow and 25 outflow series, lists both Top 25 rankings, and initially selects five per direction for the chart. Preserve user checkbox selections during the same trade date. Use the API's discrete `time_points` as a category axis; future ticks remain empty rather than being fabricated or connected across lunch.

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

Before submitting, run backend tests/checks, migration drift detection, frontend lint/build, and `git diff --check`. Mock sleeps and network calls in unit tests; make live Eastmoney checks explicit, minimal, and read-only. Production scheduling should use a lock such as `flock` because one fetch can exceed one minute.

## Coding, Security, and Change Discipline

Use four-space indentation and `snake_case` in Python; Django models use `PascalCase`. Use two-space indentation, `PascalCase` components, and `camelCase` variables in JavaScript/JSX. Prefer focused regression tests before changing request parameters, fallback rules, cache invalidation, or time alignment.

Do not commit secrets, tokens, captured traffic, local databases, cache files, virtual environments, logs, `node_modules`, or generated bundles. Use concise imperative commits with a scope, such as `backend: preserve partial sector rankings` or `frontend: use discrete trading ticks`. PRs must describe behavior changes, verification commands, migrations/deployment impact, and include screenshots for visible UI changes.
