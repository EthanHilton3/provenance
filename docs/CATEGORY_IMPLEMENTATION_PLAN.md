# Category redesign: implementation plan

Written for Ethan. The design is settled in [CATEGORY_REDESIGN.md](CATEGORY_REDESIGN.md); this file is how to build it, in one long session. The last section is the prompt for that session. Nothing here is applied yet.

## What changes, in one paragraph

A new migration replaces the seeded tree (14 top-level and 19 children, 59 field definitions) with 19 top-level and 79 children, each with a description written for both people and the AI. Franchise, brand and signed-by become real columns on `items`. Field templates gain a **product** tag and a **show_if** condition. The item form learns those, plus the three new columns, and the grouped category dropdown becomes a search-as-you-type picker that also searches the descriptions. Existing items are re-pointed to the new categories so nothing is orphaned.

## Settled decisions

1. **Category descriptions: yes.** A `description` column on `categories`. It works like a tool's docstring: it tells a reader (the picker, and the AI intake prompt in S9) what belongs here and what doesn't. Format: one sentence of what it holds, examples, and "not for" pointers, e.g. *Battle toys: spinning-top and battle toys and toy weapons (Beyblade, Bakugan, Nerf, play swords). Not outdoor ride-ons (Outdoor play) or collectible figures (Figures).*
2. **Hidden values: kept while editing, wiped on save.** Only fields the template knows are wiped. Unknown keys stay as "other details".
3. **Franchise, brand and signed-by: real columns on `items`**, not JSON. They are on every item and are filtered across categories. Everything per-category stays in `attributes`.
4. **Schedule: all tonight, one session**, about 7 hours, with checkpoints.

## Out of scope for this work

- Showing a linked release's values read-only on the item form. There is no releases API or screen yet, so product fields stay editable and the tag is only recorded. The read-only behavior is built in S11 and S12.
- A screen for users to edit category templates.
- Single-card tracking for trading cards.

## Design

### Template field format

A field is `{key, label, type, options?}` today. It gains two optional keys:

| Key | Meaning | Example |
|---|---|---|
| `scope` | `"product"` for facts about the product. Absent means a fact about your copy. | `"scope": "product"` on `edition` |
| `show_if` | Show this field only when another field has a value. | `{"key": "format", "equals": "Vinyl"}` |

`show_if` supports one equality only. That covers Albums (format = Vinyl) and Board games (base_or_expansion = Expansion). `category_fields()` is unchanged: it already returns fields as stored, nearest definition first.

### New columns on `items`

`franchise`, `brand`, `signed_by` (all `text`, nullable). Add btree indexes on `(owner_id, franchise)` and `(owner_id, brand)` for "all my Zelda things". The item form shows them in a fixed, collapsed "More details" section, not through the template. `price_paid`, `location` and the like already live as columns, so this is the same pattern.

### Shared fields

There is no runtime library. Define each shared field once in a source file and let a script expand it into the migration. That keeps labels, types and options identical everywhere (for example the `completeness` choice list appears in 12 templates).

- Source of truth: `supabase/category_tree.json` (categories, descriptions, fields).
- A script, `scripts/build_category_migration.py`, reads it and writes the SQL.
- A DB test checks that the same key always has the same label and type across the tree.

### Hidden and extra values

- While editing, a hidden conditional field keeps its value in the form's state, so flipping Vinyl → CD → Vinyl loses nothing.
- On save, a pure helper `cleanForSave(fields, attributes)` removes values of fields that are in the template but currently hidden. Keys the template doesn't know are kept.
- `CategoryFields.vue` already shows unknown keys as "other details". Read-only rows skip hidden fields.

## Migration

New file: `supabase/migrations/20261125000000_category_redesign.sql` (the seed migration is not edited, since the cloud project already ran it). One transaction.

1. Recreate the check on `occasions.kind` with `inherited` added (Postgres named it, look it up).
2. Add `categories.description`.
3. Add `items.franchise`, `items.brand`, `items.signed_by` and the two indexes. Copy any existing `attributes` values for `brand`, `franchise` into the columns, then remove those keys from `attributes`.
4. **Rename in place where a row survives**, so its items keep their link and no re-pointing is needed:
   - Board Games & Puzzles → Games & Puzzles
   - Toys & Building Sets → Toys
   - Collectibles & Memorabilia → Memorabilia & Keepsakes
   - Clothing & Textiles → Clothing & Linens
   - Albums & Vinyl → Albums
   - Wall art & Frames → Wall art & Posters
   - Physical media → Discs
   - Manga & Comics → Manga
   - Drinkware & Dishes → Drinkware
5. **Insert the new categories** (about 60) and set every template and description.
6. **Re-point items** using the mapping table in [CATEGORY_REDESIGN.md](CATEGORY_REDESIGN.md):
   - Discs to VHS & tapes when `format` = VHS.
   - Toys to Building sets when `set_number` is filled.
   - Hand & Power tools to Hand tools when `power` = Manual, else Power tools.
   - Novels, and the Books, Home Decor and Electronics "Other" children, to their parent.
   - Tool sets to Tools.
7. **Attribute data**: `complete` and `complete_in_box` become `completeness` (true → "Complete in box", false → "Incomplete"). Other keys keep their names (`edition`, `format`, `model`), so nothing else needs touching. `numbered` stays as an "other detail", since parsing "3/100" is not worth it.
8. **Re-parent any user-owned category** whose built-in parent is about to be deleted.
9. **Delete the obsolete categories.** The `ON DELETE RESTRICT` foreign key is the safety net: if any item still points at one, the migration fails and nothing is applied.

### Backend and frontend for the new columns

- `backend/app/items.py`: add `franchise`, `brand`, `signed_by` to the create and patch models (they currently list the item columns by name). Update `backend/tests/test_api.py`.
- `frontend/src/components/ItemForm.vue`, `frontend/src/views/ItemDetailView.vue`, `frontend/src/lib/item.js`: add the three fields to the form, the detail view and the edit/409 comparison, with Node tests.

### Rollout to the cloud

1. The overnight run does this part read-only: counts items per category in the cloud project, lists user-owned categories, and checks every item against the mapping. It saves a data-only export to a gitignored folder.
2. It runs `npx supabase db reset` and the DB tests locally.
3. **You read `docs/CATEGORY_REDESIGN_REPORT.md` in the morning.** If the mapping covers your real items, approve the push and run `npx supabase db push`.
4. Run the live cloud test and look at the app.

## Work breakdown

Estimates are guesses; the project log records actual time.

| Part | What | Files | Est. |
|---|---|---|---|
| **A: database** | `category_tree.json`, the generator, the migration (columns, tree, re-pointing), DB tests | `supabase/category_tree.json`, `scripts/build_category_migration.py`, the new migration, `tests/db/` | 3 h |
| **B: backend and item form** | backend models for the new columns; `show_if`, `scope` and `cleanForSave` in a tested helper; the form and detail view | `backend/app/items.py`, `frontend/src/components/CategoryFields.vue`, `ItemForm.vue`, `ItemDetailView.vue`, new `frontend/src/lib/fields.js` and test | 2 h |
| **C: picker** | search-as-you-type picker with description search; check the items list with 79 children; phone check | `frontend/src/components/CategoryPicker.vue`, `frontend/src/views/ItemsView.vue`, `frontend/src/lib/categories.js` | 1.5 h |
| **D: ship** | local reset and the full test run, cloud rollout, docs and log | `docs/DESIGN.md`, `PROJECT_LOG.md` | 0.5 h |

**Order matters:** A before B, because B reads the new template keys and columns. C needs the descriptions from A. D last.

**Checkpoints (overnight run).** After each part the tests must pass, and then the run makes one commit on a new branch `category-redesign` (you authorize those four commits in the prompt; nothing goes to main and nothing is pushed). The cloud push is the only step that touches real data, and it is left for you to approve in the morning.

**Schedule.** The plan has S8 (category fields form) at 1.5 h on Wed Nov 25. This covers S8's scope too, since the item form is the same code; what remains of S8 is a quick check and the demo milestone. About 7 hours tonight is far more than S8's slot, so S9 on Sat Nov 28 is unaffected.

## Tests

- **Replace** `test_category_tree_matches_feasibility_list` in `tests/db/test_schema_extras.py`. It checks the tree's leaves against `intake.py` in the other repo (25 leaves). That list is now obsolete, so compare the DB to `supabase/category_tree.json` instead.
- **Update** `test_children_inherit_fields`. For Video Games › Games the keys become `region`, `platform`, `edition`, `completeness`. The `category_id` fixture in `tests/db/conftest.py` still finds Games and needs no change.
- **New DB tests:**
  - Same key means same label and type across the tree.
  - `show_if` always names a key defined in the same or an ancestor template.
  - Every category is reachable from a top-level one, and there are exactly 19 top-level and 79 children, each with a description.
  - A migration test with a pre-seeded item in each re-pointed category, checking it lands in the right new one.
  - `complete`/`complete_in_box` convert to `completeness`; `brand` and `franchise` move to columns.
  - The `inherited` occasion kind is accepted.
- **Backend tests**: the new columns round-trip through create, patch and the 409 rules.
- **Frontend tests** (Node, `npm test`): the visible-fields helper, `cleanForSave` (hidden known field wiped, unknown key kept, visible field kept), and the edit comparison with the new columns.

## Risks

- **AI intake accuracy.** The 85% result and the Luna prompt were measured against the old 25-leaf category list. With about 75 leaves the model has more ways to be wrong, and the S9 prompt must read its list (names and descriptions) from the database or it will drift from the app. S13 already logs accuracy on your 26 items; compare it against the old numbers there. The descriptions should help.
- **Picker usability.** 79 children in one grouped dropdown is hard on a phone, which is why Part C replaces it.
- **Review burden.** The migration is large. The generator keeps it reviewable: you review `category_tree.json`, not 500 lines of SQL.
- **Real data in the cloud.** Item counts per category are unknown until the read-only check. If items exist in categories I assumed were empty, the mapping needs another rule.
- **One long unattended session.** About 7 hours is a lot of context, and no one is watching. The per-part commits on the branch are the rollback points, and the report records every choice made without you.
- **Stalls.** A permission prompt, Windows sleeping or Docker not running would stop it silently. Set those up before you go to bed.

## Docs to update when done

- `docs/DESIGN.md`: the categories paragraph (template format, the new columns, descriptions), the ERD note, and the plan checkbox "Category review, before S8". It currently says brands are attributes. Brand is now a column, but "all my Nintendo things" is still one query.
- `PROJECT_LOG.md`: a row with the actual hours (ask me, don't copy the estimates).
- `README.md`: only if the commands change.

---

## Prompt for the overnight session

Before starting it: allowlist `npx supabase`, `pytest`, `npm`, `node`, `python` and `git` so no permission prompt stalls the run; keep the PC awake; start Docker Desktop. The run never asks you anything.

```text
Implement the category redesign for Provenance, unattended, to completion. I am asleep: do not ask me questions and do not stop for approval. When something is ambiguous, choose the conservative option, write the choice down in the report, and keep going.

Read first:
- docs/CATEGORY_REDESIGN.md (the settled design; do not change decisions)
- docs/CATEGORY_IMPLEMENTATION_PLAN.md (the plan: migration steps, tests, risks)
- supabase/migrations/20261117000000_initial_schema.sql (categories, category_fields, items)
- supabase/migrations/20261117000100_seed_categories.sql (the tree being replaced)
- backend/app/items.py and backend/tests/test_api.py
- frontend/src/components/CategoryFields.vue, CategoryPicker.vue, ItemForm.vue, frontend/src/views/ItemDetailView.vue, frontend/src/lib/categories.js, frontend/src/lib/item.js
- tests/db/conftest.py and tests/db/test_schema_extras.py

Work order: Part A (database), B (backend and item form), C (picker), D (ship, local only). Details are in the plan. Rules:
- Never edit an existing migration. Add supabase/migrations/20261125000000_category_redesign.sql.
- Define the tree once in supabase/category_tree.json (categories, descriptions, fields; shared fields defined once and referenced by key) and generate the migration with scripts/build_category_migration.py. Keep the generated SQL in the repo.
- Each category gets a description in the docstring style: what it holds, examples, and "not for" pointers to the right category.
- items gets franchise, brand, signed_by text columns (indexes on (owner_id, franchise) and (owner_id, brand)); move any attributes.brand / attributes.franchise into them. They are not template fields.
- Template fields may carry scope ("product") and show_if ({key, equals}). category_fields() stays as it is.
- Rename categories in place where a row survives so items keep their link; re-point the rest per the table in CATEGORY_REDESIGN.md; convert complete/complete_in_box to completeness; add the "inherited" occasion kind; re-parent user-owned categories under deleted built-ins; delete obsolete categories last (the RESTRICT foreign key is the safety net).
- Hidden conditional values stay in the form while editing and are removed on save by a pure cleanForSave helper in frontend/src/lib/fields.js (Node tests); keys the template does not know are kept and shown as other details.
- Keep CategoryFields.vue's contract (props categoryId, modelValue, editable; emits update:modelValue, fields).
- The picker is a search-as-you-type input that searches names and descriptions and shows "Parent › Child"; keep CategoryPicker's v-model contract (a category id).
- Replace test_category_tree_matches_feasibility_list with a comparison against category_tree.json; update test_children_inherit_fields; add the tests listed in the plan.
- Verify after each part: npx supabase db reset, then cd tests/db && ../../.venv/Scripts/python -m pytest -v; cd backend && ../.venv/Scripts/python -m pytest -q; cd frontend && npm test. A part is done only when its tests pass. Do not weaken or delete a test to make it pass, except the two the plan says to replace or update.

Autonomy rules:
- If the same failure survives three different fixes, stop work on that part, record what you tried in the report, and continue with whatever does not depend on it. If Docker or the local Supabase cannot start, do not fake results: write the report and stop.
- Never print or commit secrets (.env, keys, exports).

Git. I explicitly authorize exactly these git writes, for this one run, and nothing else:
- Create the branch category-redesign from main (git switch -c). Work only on it. Never commit to main.
- Four commits on that branch, one at the end of each part A, B, C, D, with short imperative messages. The first commit also includes docs/CATEGORY_REDESIGN.md and docs/CATEGORY_IMPLEMENTATION_PLAN.md (currently untracked). Commit only after that part's tests pass; if a part cannot be completed, commit what passes and say so in the message.
- No git push, no amend, no force, no rebase, no commits on any other branch, no git writes beyond these.
- No Co-Authored-By and no AI attribution in commit messages. Never commit data exports.

Cloud project: do NOT push the migration and do not write to the cloud project in any way. Read-only is allowed:
- Count items per category in the cloud project (SELECT only) and list any user-owned categories.
- Save a data-only export of items and categories to a gitignored folder (confirm it is gitignored first).
- Check every cloud item's category against the mapping. List any item whose category has no rule.

Part D (local): full local test run, update docs/DESIGN.md (categories paragraph, new columns, descriptions, ERD note, tick "Category review, before S8"). Do not edit PROJECT_LOG.md (the hours must be real; list it as pending).

Finish by writing docs/CATEGORY_REDESIGN_REPORT.md (uncommitted) with: what was done per part and the commit hashes; test results; every choice you made where something was ambiguous; anything that failed or was skipped; the cloud read-only findings; and the exact commands for me to run to push the migration (npx supabase db push) and to check the live cloud test. Then give the same summary as your final message.
```
