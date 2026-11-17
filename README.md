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

No code yet. Once it exists, this section will cover:

1. Copy `.env.example` to `.env` and fill in the Supabase and API keys (never commit `.env`).
2. Backend: create a `.venv`, install requirements, start FastAPI.
3. Frontend: `npm install`, then `npm run dev`.
