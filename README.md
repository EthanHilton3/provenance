# Provenance

A web app for cataloging the specific things you own, down to the exact edition and release, with AI photo intake doing most of the typing. Photograph an item and the app proposes a card (what it is, which edition, format, condition, details worth keeping) for you to confirm or fix.

It tracks **releases, not titles**: not "I own A New Hope" but "the 4K steelbook, opened, bought on Prime Day 2021."

CS 452 final project. Design, ERD, system diagram and daily goals: [docs/DESIGN.md](docs/DESIGN.md). Work log: [PROJECT_LOG.md](PROJECT_LOG.md).

## Stack

- Frontend: Vue 3 + Vite, installable web app
- Backend: FastAPI (Python)
- Database, photo storage and sign-in: Supabase (Postgres with row-level security, Storage, Auth)
- AI: OpenAI GPT-6 Luna for photo intake
- Catalogs: UPC lookup, TMDB, Open Library, IGDB

## How to run

### Database (local)

The schema lives in [supabase/migrations/](supabase/migrations/): 15 tables with row-level security, the starter category tree, and the `claim_intake_job()` queue function. Needs Docker Desktop running.

```sh
npx supabase start          # first run pulls images; applies the migrations
npx supabase db reset       # rebuild from the migrations at any time

py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -r tests/requirements.txt
cd tests/db && ../../.venv/Scripts/python -m pytest -v
```

The tests cover: one user can't read or write another's items, concurrent workers never claim the same intake job, simultaneous scans of a new barcode make one release (`ON CONFLICT`), optimistic locking, and the share link hiding price and location.

### Backend

```sh
cp .env.example .env        # fill in the Supabase keys (never commit .env)
.venv/Scripts/python -m pip install -r backend/requirements.txt
cd backend && ../.venv/Scripts/python -m pytest -q                       # unit tests, no network
PROVENANCE_LIVE=1 ../.venv/Scripts/python -m pytest tests/test_live_cloud.py   # real cloud project, throwaway users
../.venv/Scripts/python -m uvicorn app.main:app --reload                 # http://localhost:8000/docs
```

API so far: `/api/health`, `/api/me`, `/api/categories`, `/api/categories/{id}/fields`, `/api/items` (list with keyset paging, get, create, patch with `version`, delete).

### Frontend

Not built yet: `npm install`, then `npm run dev`.
