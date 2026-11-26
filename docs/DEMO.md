# Core demo script (S8 milestone)

About five minutes: add, browse, edit, photos. Written from a real run of the app against local Supabase.

## Before the demo

1. Docker Desktop running, then `npx supabase start` in the repo root (or use the cloud project, see the README).
2. Backend: `cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --port 8001` (the port in `frontend/.env.local`).
3. Frontend: `cd frontend && npm run dev`, then open http://localhost:5174 (on a phone: the same page through the computer's address).
4. Have three photos ready (an item, an album cover, a mug). Use a fresh email so the list starts empty.

## Steps

1. **Sign up.** Create account with an email and a password of 6+ characters. You land on an empty "Nothing catalogued yet" screen with an Add button.
2. **Add a game.** Name it "Zelda: Tears of the Kingdom". In Category type `video game` and pick Video Games › Games. The form now shows Region (inherited from the parent Video Games), Platform, Edition and Completeness (the category's own). Set Platform to Switch, add a photo, Save. *Point out: the picker searches names and descriptions, and the fields change with the category.*
3. **Add an album.** Name it "Rumours", category `album` → Music › Albums. Set Format to Vinyl and Record size, Speed and Pressing appear; switch Format to CD and they disappear (and come back with their values if you switch back). Add a photo, Save.
4. **Add a mug.** Name "Blue diner mug", category `mug` → Kitchen › Drinkware (Material, Pieces). Open "More details" and set Brand to Pyrex. Add a photo, Save. *Point out: franchise, brand and signed by are on every item, whatever the category.*
5. **Browse.** Back on My things, the three items are grouped by category with thumbnails. Fold a group by tapping its header (it is remembered on this device).
6. **Open and edit.** Open the game: read-only rows for its fields, then Edit, change Platform to Switch 2 and Condition to Like new, Save. The "Saved." banner shows and the list now carries "Like new".
7. **Change a photo.** On the game, Choose photos to add a second, tap the first, Delete photo, confirm. One photo remains and becomes the thumbnail.
8. **Category change keeps your data.** Edit the album, change its category to Kitchen › Drinkware. Artist and Format are kept under "Other details" instead of being thrown away. Cancel (or Save if you mean it).
9. **Delete.** Open the mug, Delete, and read the confirmation ("the item and its 1 photo will be gone for good"). Confirm; the list now has two items in two categories.
10. **Two devices (optional, strongest moment).** Open the same item in two tabs, save an edit in one, then save in the other: the "changed since you loaded it" panel shows what changed and lets you use theirs or save yours on top.

## Known rough edges

Said out loud if asked; none of these block the flow.

- **Whole-number fields take decimals.** Pieces accepts 12.5, and so do Year and Edition number. The field library has no integer flag. Fixing it means a schema change (`category_tree.json`, the migration and the DB tests).
- **No date, unit or "required" field types.** The library has text, number, yes/no and choice. Dates are only the item's own "Acquired" field.
- **The backend checks that a field value is one plain value but not that its key belongs to the category.** That is deliberate (an old category's values must survive), so a wrong-category key is kept, not rejected.
- **Category fields from a previous category show as "Other details"**, with a label made from the key ("Piece count"), not the original label ("Pieces").
- **No search or filter on My things**, and no "all Video Games" roll-up: groups are the leaf categories only. The API can already filter by category.
- **The first photo is the thumbnail**; there is no reorder or "make cover".
- **Deleting is permanent** (no trash). On the hosted project a photo you already viewed can keep loading for a short while after deleting it (CDN cache; see the README).
- **No barcode scan, collections or occasion views yet** (S11 onward). AI intake from photos is below (S10).
- **Not covered by this run:** the phone camera button, HEIC photos from a real phone, and the layout at phone width. The walk used a desktop browser and generated JPEGs through the file picker. The phone was checked in S7, before the category redesign.

# AI intake demo (S10)

About five minutes: a batch of single photos, one shelf photo, the follow-up questions, and saving twice from two tabs. Written from a run against local Supabase with the fake model, so it costs nothing and is repeatable.

## Before the demo

1. Local Supabase running (`npx supabase start`) with every migration applied (`npx supabase migration up`).
2. Point everything at the local stack, not the cloud project in `.env`: export `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` from `npx supabase status -o env` (`API_URL`, `ANON_KEY`, `SERVICE_ROLE_KEY`), the same two as `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`, and `API_TARGET=http://127.0.0.1:8001`. Environment variables win over the `.env` files.
3. Backend: `cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --port 8001`.
4. Worker, fake model: `cd backend && ../.venv/Scripts/python -m app.worker --fake`. It refuses to start unless Supabase is local. For the real model, leave out `--fake` (it needs `OPENAI_API_KEY`; about $0.0003 a single photo with Luna, about $0.03 a shelf with Sol).
5. Frontend: `cd frontend && npm run dev`, open http://localhost:5174.
6. Photos. The fake model answers by the photo's main colour: **red** = a Switch game (sure), **green** = a film on disc (unsure, asks "4K UHD or Blu-ray?"), **blue** = a mug (low confidence), **nearly black** = the AI fails (3 tries, about 90 seconds). In "Many items" mode any photo gives the same six-item shelf. Any plain coloured JPEG, PNG or HEIC works.

## Steps

1. **Batch.** My things › Add from photos. Choose a red, a green, a blue and a black photo. Keep "One item". In "All from an occasion" pick "+ New occasion…", type Christmas 2025, Add occasion. Upload and read 4 photos. *Point out: one job per photo; the list checks for progress on its own and stops checking once nothing is waiting.*
2. **The sure card.** Review the game. The photo sits beside the form; Platform is already Switch, Region US. Tap "Complete in box" in the question box. Sealed shows Opened with "AI guess": sealed is never shown as certain. The occasion is Christmas 2025. Save item: the next card opens.
3. **The unsure card.** On the mug, the name is marked "The AI was not sure what this is", and the AI's own question is shown as written. Change the name: the mark goes away.
4. **Two tabs.** Open the same mug card in a second tab, Save there, then Save in the first: "Already saved" with a link to the one item. Nothing is duplicated.
5. **Follow-ups and leaving.** On the film, the AI asks "4K UHD or Blu-ray?" and under it are one-tap Sealed and Format answers. Tap Opened and Blu-ray, go back to Photos, open the card again: the answers are still there (kept on this device until you save or discard). Save.
6. **Failed photo.** The black photo ends "Gave up after 3 tries" with Try again, Add by hand and Discard. Add by hand opens a blank card with the photo; name it, pick a category, Save.
7. **Shelf.** Switch to "Many items", upload one photo, Review. Six rows, each with a category from what kind of thing it is (manga → Books › Manga, game → Video Games › Games…), "Check volumes", "Check edition" and "Check title" marks, and one-tap Sealed answers. "The AI also saw 2 things it couldn't identify".
   - The box set row says "Pick a category" and is left out until you choose one: tap it, search `video game`, pick Games.
   - Untick the amiibo. Open Trigun: Volumes says "vols 1 and 2"; correct it. Add an item the AI missed: a cologne bottle in Other.
   - Save the selected items. Each item gets its own copy of the shelf photo.
8. **Discard.** Upload another shelf, Review, Discard: the photo is deleted and the list moves on.

## Group-photo kind → category

| The model's kind | Category (changeable per row) |
| --- | --- |
| novel or book, art book or guide | Books (general) |
| manga or comic volume | Books › Manga |
| video game | Video Games › Games |
| movie or TV disc set | Movies & TV › Discs |
| amiibo or figure | Toys › Figures |
| trading card or card product | Games & Puzzles › Trading card games |
| board game or puzzle | Games & Puzzles › Board games |
| toy or building set | Toys (general) |
| wall art or decor | Home Decor (general) |
| electronics or accessory | Electronics (general) |
| box set or slipcase set | none: you choose |
| other | Other |

## Known rough edges (S10)

- **A run of volumes stays one item.** "vols 1-3" is kept as text in a Volumes detail beside the number field Volume; splitting a run into one item per volume is not built.
- **Photos uploaded together appear in any order** in the waiting list: a batch's jobs share one creation time.
- **After a tap, the next question moves under your finger**, so a fast double tap can answer two questions.
- **Photos that never became jobs** (the job request failed and you left before Try again) stays stored with no item and no job; nothing shows or deletes it yet.
- **Single photos can't go to a general category** such as "Books (general)" for a novel: the S9 single-item prompt offers leaf categories only. Group rows can.
- **Not covered by the S10 walk:** a real phone (the 390 px layout was checked in a desktop browser), the camera button, a real iPhone HEIC (a HEIC generated by pillow-heif uploaded and converted fine), light mode, and the real model.

# Barcode demo (S11)

About four minutes: a scan that finds the release with no AI call, a miss handed to the AI or to the form, and what happens when the catalog says no. Written from a run against local Supabase and the fake catalog, so it costs nothing and never spends the real UPCitemdb lookups (about 100 a day for the whole app).

## Before the demo

1. Local Supabase with every migration applied, environment pointed at it, as in the S10 demo above.
2. Fake catalog: `cd backend && ../.venv/Scripts/python -m uvicorn app.fake_upc:app --port 8002`. It answers with the products the barcode test found. Point the backend at it with `UPCITEMDB_URL=http://127.0.0.1:8002/prod/trial/lookup` (leave it unset for the real UPCitemdb).
3. Backend (port 8001) and frontend as before. For the AI path, run the fake worker too.
4. **Phone camera:** the camera needs https. In `frontend`, run Vite with `TUNNEL=1` set, then `cloudflared tunnel --url http://localhost:5174` and open the `https://….trycloudflare.com` address it prints on the phone. While it runs, anyone with that address can reach the dev app; stop it (Ctrl+C) when done. Without the tunnel the phone can still type the number and pick a photo, but not use the live camera.

## Barcodes to type (from the barcode test)

| Type this | What happens |
| --- | --- |
| `883929704736` | Lord of the Rings 4K: found; Format 4K UHD (marked "from the store listing"); edition answers "Extended & Theatrical" or Standard |
| `826663208511` | Nausicaa steelbook: found; Blu-ray; edition answer "Limited Edition Steelbook" |
| `045496960070` | Smash Bros Melee: found as a game; Platform GameCube |
| `045496906788` | Ocarina of Time: found as a game; Platform Switch 2; no edition words, so only Standard |
| `045496884796` | Switch 2 controller: not in the catalog |
| `045496600397` | IMG_9427 as the model misread it: refused by the check digit, nothing is looked up |
| `200000004293` | fake catalog only: a 429; every lookup then pauses for 30 s |
| `200000008888` | fake catalog only: no answer; the backend gives up after 8 s |

## Steps

1. **Scan.** My things › Scan a barcode. Tap Scan with camera (on the phone) and hold the Lord of the Rings box in the frame, or type `883929704736` and Look up. The card appears straight away: "Found by barcode and added to the shared catalog". *Point out: no AI call; the first person to scan a barcode adds it to the shared catalog for everyone.*
2. **The edition is a question, not a guess.** Tap "Extended & Theatrical" and Opened. Format is already 4K UHD, marked to check. Save item: "Saved … Scan the next one."
3. **Second scan is free.** Type `0883929704736` (the EAN-13 spelling of the same box). "Found by barcode in the shared catalog": answered from `releases`, no outside call, the same release.
4. **Misread.** Type `045496600397`: "Those digits don't pass the barcode's check digit". *Point out: this is the misread the barcode test caught.*
5. **Miss, by hand.** Type `045496884796`: "This barcode isn't in the catalog yet", with Photograph the box and Add by hand. Add by hand: "Barcode 045496884796 is saved with this item"; name it, pick Video Games › Controllers, Save. The item shows Barcode under Other details.
6. **Miss, by photo.** Scan the controller again (answered from the cache this time), Photograph the box. The intake page says the barcode is kept with one photo; Many items is locked and choosing two photos is refused. Upload one, review the AI's card: the barcode is on it.
7. **Pick a photo.** Pick a photo of the barcode instead of the camera. A photo with no barcode in it says so and suggests a closer one.
8. **When the catalog says no.** Type `200000004293`: "The barcode catalog is busy". Type any other new code within 30 s: "The catalog asked us to slow down". Nothing is cached, so the same codes are asked again later.

## How it decides (for questions)

- Lookup order: `releases` by barcode → `catalog_cache` (hits 30 days, misses 7) → UPCitemdb. A 429, timeout or server error is never cached.
- Budget, shared by everyone (`catalog_calls`, `begin_catalog_call()`): 90 lookups in 24 h for the app (10 of the 100 left for testing by hand), 20 per user, 5 a minute, and a pause for as long as a 429 asks.
- Releases are written only by the backend (`release_from_catalog()`, `INSERT … ON CONFLICT DO NOTHING`): two people scanning at once get one release, and a later answer never changes it. Edition and format stay empty on the release; your answers go on your item.

## Known rough edges

- **The barcode on an item is stored as EAN-13** (`0883929704736`), one more digit than the UPC-A printed on most boxes. The scan page shows the printed form.
- **A miss doesn't make a shared release yet.** The barcode stays on your item (or the intake job) until S12's user-created releases.
- **Two people scanning the same new code at the same moment can spend two lookups.** They still get one release.
- **No release view on the item page** yet; the link is there (`items.release_id`) but nothing shows it.
- **Not covered by the S11 walk:** a real phone camera (the live scan was driven by a drawn barcode fed in as a fake camera stream, through the same WASM decoder iPhone uses), iPhone Safari itself, the tunnel, the phone-width layout of the card, real photos from the barcode test (generated photos only), and the real UPCitemdb (`PROVENANCE_LIVE_UPC=1 pytest tests/test_live_barcode.py -s`, one lookup, not run).

# Catalog match and shared releases demo (S12)

About five minutes: a photo card that finds its film, saving it to the shared catalog, the "this looks like an existing release" question, a barcode release getting its film, and what happens when the catalog says no. Written from a run against local Supabase with the fake model, a fake TMDB and Open Library, and fake embeddings, so it costs nothing and calls nobody.

## Before the demo

1. Local Supabase with every migration applied, environment pointed at it, as in the S10 demo.
2. Fake catalogs: `cd backend && ../.venv/Scripts/python -m uvicorn app.fake_catalog:app --port 8003` (TMDB and Open Library in one) and the fake UPCitemdb from S11. Point the backend at them: `TMDB_URL=http://127.0.0.1:8003/3`, `OPENLIBRARY_URL=http://127.0.0.1:8003/ol`, `UPCITEMDB_URL=http://127.0.0.1:8002/prod/trial/lookup`.
3. `EMBEDDINGS_FAKE=true` for the backend: word-overlap vectors instead of OpenAI. The backend refuses it unless Supabase is local. For the real duplicate check leave it unset (it needs `OPENAI_API_KEY`; about $0.0000004 a release).
4. Backend, fake worker and frontend as before. Photos: **green** = a film on disc (Spirited Away), **red** = a Switch game.

## Steps

1. **The match.** Add from photos, one green photo, Review. Under the form: "Which film is this?" with **Spirited Away (2001)**, its Japanese title, TMDB, and **Best match**, already chosen. *Point out: the AI's search text was cleaned in code; the year in it is a hint, not part of the title.*
2. **Share it.** "Add this release to the shared catalog" is ticked, and the line under it says what is shared (title, format, edition, barcode; the film's title, year and kind) and what stays private. Tap Opened and Blu-ray, type a note ("Gift from grandma"), Save. The item is linked to a new shared release, linked to the TMDB film. The note is only on your item.
3. **Use it?** Upload another green photo. Set Packaging to Standard case, Blu-ray, Save: "This looks like a release that's already in the shared catalog. Use it?" with Spirited Away · Blu-ray · Standard edition · 2001. Use this one: the item links to that release; nothing new is made.
4. **Not a duplicate.** A third green photo, left as Steelbook, Blu-ray, Save: no question, because a steelbook is a different release. It gets its own release under the same film.
5. **No, mine is different.** Two red photos (Zelda, a game: no catalog search, just the shared-catalog box). Save the first. Save the second: the question appears; No, mine is different makes a second release, and both share one game work. *Point out: you decide; nothing is merged for you.*
6. **A barcode release gets its film.** Scan a barcode, type `826663208511` (Nausicaä steelbook). The store's long title still finds **Nausicaä of the Valley of the Wind (1984)** as Best match (the search drops "(Limited Edition Steelbook) (Blu-ray + DVD)"). Save: the release is linked. Type the code again: "In the shared catalog as Nausicaä of the Valley of the Wind (1984)", and no search.
7. **A weak match is never chosen for you.** Type `032429348128` (Star Trek: Stardate Collection). The only result is Star Wars (1977), listed but not chosen: "Nothing is linked until you choose."
8. **The catalog says no.** In "Search for", type `Star Trek ratelimit` and Search: "The catalog can't be reached right now; you can still save." Save works. Every TMDB search pauses for 30 s after that 429, and nothing was cached.
9. **Credits.** About (top right): the TMDB logo and notice, Open Library and UPCitemdb.

## How it decides (for questions)

- **Catalogs:** Movies & TV → TMDB (film, show, or both when the card doesn't say), Books → Open Library, Video Games › Games → no catalog (no IGDB yet) but can be shared, everything else → no catalog and no sharing.
- **Fallbacks:** ISBN (books) → the title with the year hint → the title with format, platform, edition words and brackets removed, no year → nothing ("None of these" makes a user work).
- **Strong or weak:** strong only for an exact title the year confirms, or the only exact title when there is no year. TMDB has two shows called "Avatar: The Last Airbender" (2005 and 2024): without a year that is weak, so nothing is chosen.
- **Cache and limits:** `catalog_cache` keeps results 30 days and empty answers 7; 429s, timeouts and errors are never cached. TMDB 6 s timeout, Open Library 10 s (it took 5.3 s in the smoke test), one retry after a short backoff. Per-user and per-minute caps through `begin_catalog_call()`, and a pause as long as a 429 asks.
- **Duplicate check:** releases without a barcode embed "title | format | edition | year" with text-embedding-3-small at 512 dimensions. An existing release is offered when the cosine distance is at most 0.028 and the formats don't differ ([evidence](DUPLICATE_THRESHOLD.md): 14 of 18 duplicates found, 0 of 24 different editions or formats offered). A barcode decides by its unique index instead.
- **Two people at once:** creating a release takes an advisory lock and re-runs the check inside it, so the second person is asked "use it?" about the first's release instead of making a twin. One work per catalog entry (unique `catalog_ref`, ON CONFLICT), and a release keeps the first work it was linked to.
- **Privacy:** the API accepts only catalog facts for a shared release. `created_by` on releases and works is hidden from users by column grants, so nobody can list what another user has added.

## Known rough edges

- **The group-photo grid doesn't match or share yet.** Its rows save as before (decided for S12).
- **Some real duplicates are missed:** a diacritic (Nausicaä), a shortened title, "steel book" spelled apart, a missing year. A miss makes a second shared release; there is no merge tool for moderation yet.
- **UPCitemdb releases have no embedding**, so a photographed box isn't matched against a release someone made by scanning.
- **An ISBN that UPCitemdb doesn't know** goes to the photo or the form; Open Library isn't asked to make the release.
- **The barcode card's "Search for" box shows the store's full title**; the search itself drops the edition and format words.
- **If saving the item fails after the release was made**, the shared release stays (it holds catalog facts only).
- **User-made works are merged only by exact title, kind and year.**
- **TMDB's terms need a separate agreement for commercial use**, which the Pro plan would be.
- **Not covered by the S12 walk:** a real phone and the phone-width layout, the real vision model, the real TMDB, Open Library and OpenAI in the browser (each was called directly from the backend code in a smoke test instead: Princess Mononoke strong, the two Avatars weak, The Hobbit by ISBN, one real embedding through PostgREST into pgvector), light mode, and the cloud project (the migration is applied locally only).
