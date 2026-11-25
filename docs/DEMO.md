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
- **No AI intake, barcode scan, collections or occasions yet** (S9 onward).
- **Not covered by this run:** the phone camera button, HEIC photos from a real phone, and the layout at phone width. The walk used a desktop browser and generated JPEGs through the file picker. The phone was checked in S7, before the category redesign.
