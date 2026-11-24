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
| 11/23/2026 | Group photo feasibility test: 15 photos that each show many items (shelves, displays). Built a harness that returns every distinct item in a photo and ran it on Luna (1024 and 2048 px) and Sol; built a blind judging page and hand-judged 4 photos (about 280 listed items across 5 setups). Then tested tiling: 4 overlapping tiles per photo plus a merge step. Results: Sol 98-100% right-or-close with 0-2% made-up items, Luna 86-88% with 12-14% made-up. Tiling cost 3-4x more and did not help, so the design uses one whole-photo Sol call and a confirmation grid. Updated the design doc and build plan with the conclusion | 1.5 |
| 11/24/2026 | Barcode feasibility test: 15 photos, zxing decoder with retries and a model fallback, UPCitemdb lookup with disk cache, check-digit gating, judged by hand. 8/15 end to end right-or-close, 8/8 of hits right-or-close, 7/15 needed the AI. [Details](https://github.com/EthanHilton3/CS-452-Database/blob/main/26-11-24%20barcode%20test/README.md) | 1.0 |
| 11/24/2026 | Photo upload (S6): private storage bucket with RLS on the owner's id prefix; upload endpoints that accept JPEG, PNG and HEIC, keep the date taken, strip all metadata including GPS, apply orientation and resize to a 2048 px JPEG; signed-URL read; delete that removes file and row with no silent orphans. 57 backend and 28 DB tests, a live test against real Storage, and a real HTTP upload with my own photos. Ran everything on the cloud project too, which found that its CDN can keep serving an already-fetched signed URL briefly after a delete (documented). [Backend](backend/), [migration](supabase/migrations/) | 0.75 |
| **Total** | | **9.25** |
