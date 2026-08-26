# Repository Guidelines

## Project Structure & Module Organization

This Django/React monorepo monitors Eastmoney industry-sector fund flow.

- `backend/config/`: Django settings, routing, and ASGI/WSGI entry points.
- `backend/fundflow/`: sector snapshot model, DRF views, aggregation services, calendar helpers, migrations, and the fetch command.
- `backend/fundflow/services/`: Eastmoney request handling, 15-minute time logic, trading-day checks, caching, and aggregation.
- `frontend/src/`: React application. Keep HTTP access in `api/`, UI in `components/`, and global styles in `index.css`.
- `docs/`: documentation assets.

Keep views thin. Put data retrieval, validation, and aggregation logic in `backend/fundflow/services/`.

## Build, Test, and Development Commands

Run backend commands from `backend/`:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py fetch_sector_fund_flow
python manage.py fetch_sector_fund_flow --latest
python manage.py runserver 8000
python manage.py test fundflow
```

Run frontend commands from `frontend/`:

```bash
npm install
npm run dev
npm run lint
npm run build
npm run preview
```

## Coding Style & Naming Conventions

Use four-space indentation and `snake_case` for Python modules, functions, and management commands. Use `PascalCase` for Django models. Keep migrations generated through `makemigrations` unless a reviewed data-removal migration is required.

Use two-space indentation in JavaScript/JSX. React component files and exports use `PascalCase` (for example, `SectorFlowChart.jsx`); functions and variables use `camelCase`.

## Testing Guidelines

Backend tests live in `backend/fundflow/tests.py` and use Django `SimpleTestCase` or `TestCase`. Cover pagination completeness, retries, time alignment, trading-day behavior, command persistence, and API responses. Run `python manage.py test fundflow` and `python manage.py check` before submitting.

No frontend test runner is configured. At minimum run `npm run lint`, `npm run build`, and manually verify loading, empty, error, and stale-data states.

## Commit & Pull Request Guidelines

Use concise, imperative commits with a scope, such as `backend: validate sector pages` or `frontend: clarify stale data`. PRs should explain behavior changes, list verification commands, identify migrations or deployment changes, and include screenshots for UI changes. Do not commit secrets, virtual environments, logs, or generated bundles.
