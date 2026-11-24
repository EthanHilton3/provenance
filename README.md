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

`tests/test_live_photos.py` runs the photo flow against a real Storage service. Against the local stack (no cloud needed), set `PROVENANCE_LIVE=1` and export `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` from `npx supabase status -o env` (`API_URL`, `ANON_KEY`, `SERVICE_ROLE_KEY`). Against the cloud project it needs the photos migration pushed first.

Known limit of signed URLs on the hosted project: its CDN caches a photo once a signed URL has been fetched, and can keep serving that same URL after the photo is deleted (observed for a few seconds up to the cache lifetime, which is up to an hour; local Supabase has no CDN). A URL nobody fetched before the delete stops working at once, and the database row and file are gone either way. `Cache-Control: max-age=0` on upload did not fix this reliably, so it is not used.

API so far: `/api/health`, `/api/me`, `/api/categories`, `/api/categories/{id}/fields`, `/api/items` (list with keyset paging, get, create, patch with `version`, delete) and photos: `POST /api/items/{id}/photos` and `POST /api/photos` (multipart `file`: JPEG, PNG or HEIC up to 15 MB; stored as an upright, metadata-free JPEG of at most 2048 px in a private bucket, date taken kept in the row), `GET /api/items/{id}/photos` (signed URLs, valid 1 hour), `DELETE /api/photos/{id}`.

### Frontend

Not built yet: `npm install`, then `npm run dev`.
