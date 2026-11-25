# Category redesign: overnight run report

Run: Nov 24 to 25, 2026, unattended. Branch `category-redesign`, made from `main` at `a4aa37b`. Nothing was pushed, and the cloud project was only read from. (The migration was pushed afterwards with Ethan's approval; see the end of this file.)

## Result

All four parts are done and every suite passes. The migration is ready for you to push after you read this.

| Part | Commit | What |
|---|---|---|
| A: database | `bd8b9e3` | `supabase/category_tree.json` (19 top-level, 79 children, descriptions, shared field library), `scripts/build_category_migration.py`, generated `supabase/migrations/20261125000000_category_redesign.sql`, DB tests. Also adds the two design docs and `exports/` to `.gitignore`. |
| B: backend and item form | `9a19079` | `franchise`, `brand`, `signed_by` in the API models and in the form (collapsed "More details"), detail view and 409 diff. `show_if` in `CategoryFields.vue`; `cleanForSave` in `frontend/src/lib/fields.js`. `/api/categories` now returns `description`. |
| C: picker | `ccf8183` | `CategoryPicker.vue` is now a search-as-you-type combobox with the same v-model (a category id). The search is in `frontend/src/lib/categorySearch.js`. |
| D: docs | `c5321b5` | `docs/DESIGN.md` (categories paragraph, new columns, descriptions, ERD note, "Category review" ticked), `README.md` (the new generator command). |

## Test results (final run, after `npx supabase db reset`)

| Suite | Before | After |
|---|---|---|
| DB (`tests/db`) | 28 passed | **42 passed** |
| Backend (`backend`) | 57 passed, 2 skipped | **62 passed, 2 skipped** (the skips are the live tests, as before) |
| Frontend (`npm test`) | 19 passed | **41 passed** |

New DB tests:

- The tree matches `category_tree.json`: names, descriptions and templates.
- The committed SQL equals the generator's output.
- 19 top-level and 79 children, all reachable from the top and all described.
- The same key always has the same label and type.
- Every `show_if` names a field in the same or a parent template.
- `inherited` is accepted as an occasion kind.
- The new columns work under RLS.
- **Migration replay:** the test rebuilds the old tree inside a rolled-back transaction, puts one item in each of the 33 old categories (more where a rule splits), runs the migration again and checks where each item lands. It also covers `complete`/`complete_in_box` → `completeness`, brand and franchise moving to columns, re-parenting a user category, an unknown category with items stopping the migration (the RESTRICT safety net), and a second run changing nothing.

The two tests the plan named were replaced or updated:
- `test_category_tree_matches_feasibility_list` became `test_category_tree_matches_tree_file`.
- In `test_children_inherit_fields`, Games now has `region, platform, edition, completeness`.

One other existing test changed: the `createBody drops blanks` expectation in `item.test.js` now includes `franchise: null, brand: null, signed_by: null`. Keys were added and none removed, because the create body now carries the new columns. No test was weakened or deleted.

Extra checks beyond the suites:

- **Real local data.** I reset to the pre-redesign version, loaded your 52 local items, then applied only the new migration. 16 Novels went to Books, 17 Manga & Comics stayed on the same row (now Manga), 18 Games and 1 Physical media → Discs stayed. Their `platform` (`Switch`) and `format` (`4K UHD`) values are on the new pick lists.
- **Atomicity.** A throwaway migration that failed on its second statement left nothing behind, so the CLI applies a migration file as one transaction. The probe file was deleted.
- **Browser check** against the local stack, as a throwaway local user:
  - The search found Albums for "vinyl".
  - Format Vinyl showed the four vinyl-only fields.
  - Vinyl → CD → Vinyl kept the typed Pressing.
  - Saving as CD stored `{"format": "CD"}`: Pressing was dropped and Brand was saved to the column.
  - The edit screen opened "More details" because Brand was filled.
  - The items list grouped the item under "Music › Albums".

## Choices made without you

1. **`edition` is a product field everywhere, Controllers included.** The tree listing leaves Controllers' edition untagged, but rule 7 lists edition as a product fact and a shared field is defined once. The tag only records this for now; nothing behaves differently.
2. **Atari platforms are named "Atari 2600", "Atari 7800" and "Atari Jaguar"**, so they read clearly in a flat list. All other platform names are as approved.
3. **Labels for new fields.** The design doc gives keys, not labels, so I chose them:
   - `kind` "Movie or TV", `speed` "Speed (RPM)", `age_range` "Ages", `edition_number`/`edition_size` "Edition number"/"Edition size"
   - `base_or_expansion` "Base game or expansion", `issue_or_volume` "Issue or volume", `season` "Holiday / season" (the old label)
   - `color` is now plain "Color" everywhere; Consoles and Controllers used "Color / edition", and edition is now its own field.
4. **`completeness` is in 11 templates**, not the plan's "12": Games, Consoles, Board games, Card games, Puzzles, Building sets, Figures, Dolls & playsets, Audio, Cameras & photography, Model kits & miniatures. I followed the tree.
5. **Field library.** Every field used by two or more categories is in the library. A category may override only `options` and `show_if`, and `format` has no options in the library (Discs, Books and Albums each give their own). The generator refuses a field defined inline twice.
6. **Descriptions** do not repeat the category name. "Not for" pointers use "Parent › Child" when they point outside the parent.
7. **Old Board Games & Puzzles items go to Board games.** That follows the table in CATEGORY_REDESIGN.md, which plan step 6 left out. The cloud and local data had none.
8. **Old keys with no new home are kept as "other details", not renamed:** `player_count` (the new field is `players`), `numbered`, and `power: Manual` on items moved to Hand tools. Only `complete`/`complete_in_box` → `completeness` and brand/franchise → columns were converted, as specified. A `complete` value that isn't a yes/no stays as it is. If both flags exist, `complete_in_box` wins.
9. **Brand/franchise move:** blank values are dropped. If the column already has a different value (only possible on a re-run), the column keeps it and the attribute stays too.
10. **Obsolete built-ins are found generically.** Any built-in that is not in the tree file is deleted, children first. A final check in the migration confirms exactly 19 + 79 built-ins, all described. User categories under a deleted built-in move up to that built-in's parent; a clash with one of the user's own names would stop the migration (the cloud has no user categories).
11. **The migration is re-runnable.** Every step checks what is already there, and no explicit BEGIN/COMMIT is needed (confirmed above). It uses a session-local helper function and a temporary table, both dropped at the end.
12. **Item versions go up for rows the migration changes.** Locally that was the 16 Novels items. An edit open during the push would get the usual 409.
13. **`categories.description`** has a check that it is 1 to 1000 characters, or null. The three new item columns have no DB check, like `source` and `location`; the API caps them at 300 characters.
14. **Hidden values are wiped on save, including legacy ones.** Example: old Albums & Vinyl had an unconditional `pressing`. A CD album with a pressing value would lose it on its next save, since that field is now vinyl-only. None of your local or cloud items have this.
15. **`platform` is now a choice.** A saved value that isn't on the list still shows and stays selected (the existing `optionsFor` behavior).
16. **"More details"** starts collapsed and opens by itself when one of the three values is filled in.
17. **Picker behavior:**
    - Only the part of a description before its first "Not …" is searched, so "popcorn" finds Popcorn & snack ware and not Drinkware.
    - Plurals match ("mugs" finds "mug").
    - Accents are ignored ("pokemon" matches "Pokémon").
    - A name match ranks above a parent match, which ranks above a description match.
    - With nothing typed it lists the whole tree, with Other last.
    - When nothing matches it offers Other.
    - Under the field it shows what the chosen category holds.
    - The list sits in the page flow rather than floating, so on a phone it stays above the keyboard.
18. **Before the first reset I saved your local database** (52 items, 1 user, 1 photo) to `exports/local-before-redesign.sql`, because the planned `db reset` wipes it. At the end I restored it through the new migration, so your local stack has your items on the new tree. The one photo's database row is back. I did not check whether its file survived in local Storage.
19. **Added `exports/` to `.gitignore`** (checked with `git check-ignore`) for the exports.

## Failed or skipped

- **Nothing failed.** No part needed the three-fixes rule.
- **`PROJECT_LOG.md` is not updated**, as instructed. It needs a row with the real hours.
- **The ERD picture `docs/images/erd.png` was not regenerated.** The Mermaid text is updated, and DESIGN.md has a note saying the picture predates the redesign.
- **No real-phone check.** Resizing the Chrome window to phone width didn't take effect, so I checked in a desktop window, where the app's narrow column shows.
- **Not in scope and not done:** the read-only display of a linked release's product fields (S11/S12), and the S9 intake prompt reading category names and descriptions from the database.

## Cloud project (read-only)

These were REST GETs only, made with the service key from `.env`, which was never printed. Nothing was written.

- **Categories:** 33 built-ins (the 14 + 19 seed), **no user-owned categories**.
- **Items:** **1 item**, in **Video Games › Consoles**, with empty attributes. That row survives with the same name and id, so the item needs no rule. Nothing needs converting, and every cloud item is covered by the mapping.
- **Export:** `exports/cloud-categories.json` and `exports/cloud-items.json` (gitignored, not committed).

## Your steps in the morning

Read `supabase/category_tree.json` (the reviewable source). Then, from the repo root, on the `category-redesign` branch:

```sh
npx supabase db push --remote --dry-run   # should list only 20261125000000_category_redesign.sql
npx supabase db push --remote             # applies it to the cloud project (one transaction)
```

Correction: this CLI version pushes to the local stack unless `--remote` is given; the first version of this report left it out.

**Done on Nov 25, with Ethan's approval:** pushed with `--remote`. The cloud now has 19 top-level and 79 child categories, all with descriptions. The console item is unchanged (Video Games › Consoles, version 1). `tests/test_live_cloud.py` passed.

Then the live cloud test (PowerShell):

```powershell
cd backend
$env:PROVENANCE_LIVE = "1"; ..\.venv\Scripts\python -m pytest tests/test_live_cloud.py -v; Remove-Item Env:PROVENANCE_LIVE
```

(Git Bash: `cd backend && PROVENANCE_LIVE=1 ../.venv/Scripts/python -m pytest tests/test_live_cloud.py -v`.)

Then open the app and check your one console item. After that, merge the branch into main when you're happy (not done here) and add the `PROJECT_LOG.md` row with your real hours.
