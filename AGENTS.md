# Repository Guidelines

## Project Structure & Module Organization

This repository is a small Django/React monorepo.

- `backend/config/`: Django settings, URL routing, and ASGI/WSGI entry points.
- `backend/fundflow/`: domain models, DRF serializers/views, aggregation and import services, migrations, and management commands.
- `frontend/src/`: React application code. API access belongs in `api/`, reusable UI in `components/`, and global styles in `index.css`.
- `docs/`: screenshots and supporting documentation assets.
- `沪深京A股.csv`: local stock/sector input consumed by `sync_sectors`.

Keep business logic in `backend/fundflow/services/`; keep views thin and avoid embedding data-fetching logic directly in React components.

## Build, Test, and Development Commands

Run backend commands from `backend/`:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py sync_sectors
python manage.py fetch_stock_fund_flow --force
python manage.py runserver 8000
python manage.py test fundflow
```

Run frontend commands from `frontend/`:

```bash
npm install          # install locked dependencies
npm run dev          # start Vite on port 5173
npm run lint         # run Oxlint React checks
npm run build        # create the production dist/ bundle
npm run preview      # serve the built bundle locally
```

## Coding Style & Naming Conventions

Use four-space indentation and `snake_case` for Python functions, modules, and management commands; use `PascalCase` for Django models. Follow existing Django conventions and keep migrations generated through `makemigrations`.

Use two-space indentation in JavaScript/JSX. Name React components and component files in `PascalCase` (for example, `SectorFlowChart.jsx`); use `camelCase` for functions and variables. Run `npm run lint` before submitting frontend changes.

## Testing Guidelines

Backend tests use Django’s `TestCase`. Add focused tests alongside the app in `fundflow/tests.py`, or split larger suites into `fundflow/tests/test_<feature>.py`. Cover service calculations, API responses, command behavior, and regression cases. No frontend test runner or coverage threshold is currently configured; at minimum, lint, build, and manually verify loading, empty, and error states.

## Commit & Pull Request Guidelines

The Git history currently contains only `init`, so no detailed convention is established. Use short, imperative commits with a clear scope, such as `backend: validate CSV rows` or `frontend: improve chart loading state`.

Pull requests should explain the change, list verification commands, link related issues, and call out migrations or configuration changes. Include screenshots for visible UI changes. Do not commit secrets, virtual environments, `node_modules/`, logs, or generated build output; treat `db.sqlite3` and imported market data as local development artifacts unless explicitly required.
