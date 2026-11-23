# Project Log

Hours start from active working time measured in my Claude Code session timestamps (pauses over 15 minutes removed), then are rounded up to the next quarter hour. The round-up covers time outside those sessions: thinking through the design, testing, photographing items, and dashboard setup.

| Date | What | Hours |
|---|---|---|
| 11/14/2026 | Brainstormed final project ideas against my other class projects | 0.5 |
| 11/15/2026 | Spoiler Shield feasibility test (an earlier idea; LLM spoiler classifier + extension probe). [Details](https://github.com/EthanHilton3/CS-452-Database/tree/main/26-11-15%20spoiler%20shield%20feasibility) | 0.75 |
| 11/16/2026 | Collection intake feasibility test (26 photos, 4 model setups, my answer key, scoring). [Details](https://github.com/EthanHilton3/CS-452-Database/blob/main/26-11-16%20collection%20intake%20feasibility/README.md) | 0.5 |
| 11/16/2026 | Initial design doc: ERD, system design, build plan, business model, naming | 1.25 |
| 11/17/2026 | Repo setup, project log, design export | 0.25 |
| 11/17/2026 | Database schema as a Supabase migration: 15 tables, RLS (private vs shared), composite same-owner keys, seeded category tree, `claim_intake_job()` with SKIP LOCKED, barcode upsert, pgvector(512). Ran it locally (Supabase CLI + Docker); 18 tests pass, and breaking SKIP LOCKED or RLS on purpose makes them fail. [Migration](supabase/migrations/), [tests](tests/db/) | 0.25 |
| 11/19/2026 | ERD and tech stack diagrams, screen designs, Initial Design submission and pitch | 1.0 |
| 11/22/2026 | Created the Supabase cloud project, connected the CLI, set up keys and `.env` | 0.5 |
| 11/22/2026 | FastAPI backend with Supabase auth and the items API (tests included), then a code review and fixes on 11/23. [Backend](backend/) | 0.5 |
| 11/23/2026 | Progress tracker: checked the plan against the repo, reconstructed hours from session timestamps | 0.5 |
| **Total** | | **6.0** |
