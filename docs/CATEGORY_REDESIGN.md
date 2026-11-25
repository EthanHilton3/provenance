# Category redesign (proposal for review)

Status: **reviewed and settled with Ethan on 2026-11-24, nothing applied yet.** When it looks right, it becomes a new migration (not an edit to `20261117000100_seed_categories.sql`, because the cloud project already ran it).

Today: 14 top-level categories, 19 children, 59 field definitions.
Proposed: 19 top-level categories, 79 children.

## Rules the tree follows

1. **One axis: what the thing physically is.** Franchise, theme, occasion, brand and platform are attributes or collections, not categories.
2. **Domain accessories stay in their domain.** A Switch case is Video Games › Accessories, a tuner is Music › Instrument gear, a camera bag is Cameras. Bags & Cases is for general bags, luggage, purses and backpacks.
3. **Function wins over theme.** A movie-theater cup is Kitchen › Drinkware. A signed poster is a poster with "signed by" filled in.
4. **A category earns its place** by having its own fields or a list you would actually browse. Otherwise it is a field value or a collection.
5. **No child "Other".** An item that fits no child sits in the parent itself (the picker shows it as "(general)"). One top-level **Other** remains as the escape hatch.
6. **One item per physical piece.** A coin binder is a collection of coin items, not one item with a quantity.
7. **Product vs copy.** Fields that describe the product (edition, format, region, publisher, ISBN, packaging, disc count, pressing, variant, set number) are tagged **[P]**. With a release linked, they show the release's values read-only. With no release, they are editable on the item. Untagged fields are about your copy.
8. **Played where decides games.** Played seated, at a table, is Games & Puzzles. Played standing or outdoors (cornhole, Kan Jam, Spikeball) is Sports & outdoors.
9. **Platform means which software it runs, not the hardware.** Hardware variants (Game Boy Pocket, GBA SP, DSi XL, New 2DS XL) are the `model` of an item in Consoles.

## Fields on every item, and shared fields (defined once, included by key)

Three fields are **real columns on `items`**, not template fields: franchise / series, brand / maker, and signed by (anything can be signed: a card, jersey, book, poster, coin). They are on every item and are searched across categories. The item form shows them in a collapsed "More details" section.

The rest are a field library so labels and types stay the same everywhere. A category lists which ones it includes.

| Field | Type | On |
|---|---|---|
| Franchise / series | text column | **Every item** |
| Brand / maker | text column | **Every item** |
| Signed by | text column | **Every item** |
| `completeness` | choice: Complete in box, Complete no box, Incomplete, Loose item | Categories marked ◆ |
| `material`, `color`, `dimensions`, `size` | text | Where listed below |
| `piece_count`, `scale`, `model` | number / text / text | Where listed below |
| `edition_number`, `edition_size` | number | Figures, Memorabilia, Wall art & Posters |

Not universal: model (hardware only). No collectible flag; use collections.

Notation: `key` (type), **[P]** = product fact, **◆** = has `completeness`.

---

## The tree

### Video Games
- Parent fields: `region` (text) **[P]**
- **Games** ◆: `platform` (choice), `edition` **[P]**
- **Consoles** ◆: `model` (text), `color`, `edition` **[P]**, `storage`. No `platform`: the console is the platform.
- **Controllers**: `platform` (choice), `model`, `color`, `edition`
- **Accessories**: `platform` (choice)
- **Platform pick list (approved; split by which game cards/discs run on it):**
  - Nintendo home: NES, Super Nintendo, Nintendo 64, GameCube, Wii, Wii U, Switch, Switch 2
  - Nintendo handheld: Game Boy, Game Boy Color, Game Boy Advance, Nintendo DS (DS, DS Lite, DSi), Nintendo 3DS (3DS, 2DS and the New models)
  - Sony: PlayStation, PS2, PS3, PS4, PS5, PSP, PS Vita
  - Microsoft: Xbox, Xbox 360, Xbox One, Xbox Series X|S
  - Sega: Master System, Genesis, Sega CD, Saturn, Dreamcast, Game Gear
  - Atari: 2600, 7800, Jaguar
  - Other: Neo Geo, TurboGrafx-16, PC, Other
- Why Game Boy is three entries: original Game Boy games run on all of them, Game Boy Color games (the clear, color-only ones) do not run on the original, and Game Boy Advance cartridges are physically a different shape and only fit the Advance family. DS cards play on the 3DS family but not the other way round, so DS and 3DS stay separate. 2DS plays the same 3DS cards, so 2DS and 3DS share one entry.

### Movies & TV
- Parent fields: `kind` (choice: Movie, TV, Other) **[P]**
- **Discs**: `format` (choice: 4K UHD, Blu-ray, DVD, HD DVD, Other) **[P]**, `edition` **[P]**, `packaging` (choice: Standard case, Steelbook, Slipcover, Box set, Other) **[P]**, `disc_count` (number) **[P]**, `region` **[P]**
- **VHS & tapes**: `edition` **[P]**, `video_standard` (choice: NTSC, PAL) **[P]**, `ex_rental` (boolean)

### Books
- Parent fields: `author`, `isbn` **[P]**, `publisher` **[P]**, `format` (choice: Hardcover, Paperback, Mass market, Other) **[P]**, `edition` **[P]**, `genre` (text)
- **Manga**: `volume` (number)
- **Comics & graphic novels**: `issue_or_volume` (text), `creators` (text)
- **Children's books**: `age_range` (text)
- **Textbooks**: `course` (text, e.g. "CS 452 Database"), `term` (text, e.g. "Fall 2025")
- Everything else sits in Books (general).

### Music
- **Albums**: `artist` (text), `format` (choice: Vinyl, CD, Cassette, Other) **[P]**
  - Only when format = Vinyl: `record_size` (choice: 12", 10", 7"), `speed` (choice: 33, 45, 78), `pressing` **[P]**, `variant` **[P]**
  - Needs conditional fields (see "What the app needs").
- **Instruments**: `type` (text, e.g. trumpet), `model`
- **Instrument gear & accessories** (tuners, stands, amps, pedals, straps, cases): `for_instrument` (text), `model`
- **Sheet music & lesson books** (your lesson books and fun songbooks like Star Wars or James Bond for trumpet): `instrument` (text), `purpose` (choice: Lessons, Songs for fun, Ensemble or duets, Other), `level` (choice: Beginner, Intermediate, Advanced)

### Games & Puzzles (non-video; lawn and yard games are in Sports & outdoors)
- Parent fields: `publisher` **[P]**
- **Board games** ◆: `players` (text, e.g. "2 to 4"), `play_time` (text), `age_range` (text), `edition` **[P]**, `base_or_expansion` (choice: Base game, Expansion), `expansion_for` (text; only when Expansion)
- **Card games** ◆: `players`, `play_time`, `age_range`, `edition` **[P]**
- **Trading card games**: `game` (text), `product_type` (choice: Booster pack, Booster box, Pre-constructed deck, Tin or bundle, Other), `set_name` (text), `language` (text). Sealed product and accessories only, no single cards.
- **Puzzles** ◆: `piece_count` (number), `finished_size` (text)
- **Game accessories**: `for_game` (text) (dice, playmats, sleeves, deck boxes, tins)

### Toys
- **Building sets** ◆: `set_number` **[P]**, `piece_count`
- **Figures** ◆: `scale`, `edition_number`, `edition_size`
- **Plush**: `size` (text)
- **Vehicles**: `scale`
- **Dolls & playsets** ◆ (Barbie, dollhouse, Little People playset, play storefront)
- **Battle toys** (Beyblade, Bakugan, Nerf, play swords)
- **Electronic toys** (Tamagotchi, Furby, Tiger handhelds, Teddy Ruxpin, View-Master)
- **Classic toys** (yo-yo, Slinky, Rubik's cube, Magic 8-Ball)
- **Creative toys** (Play-Doh, Lite-Brite, Etch A Sketch)
- Outdoor toys (ride-ons, kites, water guns) moved to Sports & outdoors › Outdoor play.

### Memorabilia & Keepsakes
- Parent fields: `edition_number`, `edition_size`
- **Pins, buttons & patches**
- **Tickets & programs**: `event`, `event_date` (text)
- **Props & replicas** (anime katana, Master Sword, lightsaber, helmets)
- For things with no other function. A signed photo goes here; a signed poster goes under Wall art & Posters.

### Coins & Currency
- Parent fields: `country`, `year` (number), `denomination`, `grade` (text)
- **Coins**: `mint_mark`, `metal`
- **Paper money**: `serial_number`
- **Tokens & medals**: `issuer`
- **Stamps**: `mint_or_used` (choice: Mint, Used)

### Home Decor
- Parent fields: `dimensions`
- **Wall art & Posters**: `artist`, `medium`, `edition_number`, `edition_size`
- **Frames & photo displays**: `material`
- **Candles & Fragrance**: `scent`, `size`
- **Decorative objects** (vases, figurines, lamps, clocks, bookends): `material`
- **Seasonal** (decorations only, scarecrows included): `season`
- **Rugs, curtains & cushions**: `material`, `color`

### Furniture
- Parent fields: `material`, `color`, `dimensions`
- **Seating**, **Tables & desks**, **Storage & shelving**, **Bedroom**

### Kitchen
- Parent fields: `material`
- **Appliances**: `model`, `color`
- **Cookware & bakeware** (pots, pans, baking sheets, mixing bowls)
- **Utensils & cutlery**: `piece_count`
- **Drinkware** (mugs, cups, pitchers): `piece_count`
- **Dishes & serveware** (plates, serving bowls): `piece_count`
- **Popcorn & snack ware** (popcorn bowls, popcorn tins, movie-theater popcorn buckets, candy dishes, chip-and-dip sets)
- **Containers & storage**: lidded storage, canisters, jars, bread bins, spice and fruit racks (other tins, like a cookie tin, go here)

### Bags & Cases
- `color`, `material`. No children.

### Clothing & Linens (was Clothing & Textiles)
- Parent fields: `size`, `color`, `material`
- **Clothing**, **Shoes**, **Jewelry & watches**
- **Bedding**: sheets, pillowcases, comforters, duvets, mattress pads
- **Blankets, throws & quilts**: wherever they are used (bed, sofa, wall, picnic)
- **Towels & washcloths**: bath, hand and kitchen towels, washcloths
- **Table linens**: tablecloths, napkins, placemats
- Split rule: sheets and pillowcases and the layers made for a bed are Bedding. Anything blanket-like is Blankets, throws & quilts. If it dries or cleans you or a dish, it's Towels. If it covers a table, it's Table linens. Floor, window and sofa pieces (rugs, curtains, cushions) are in Home Decor.

### Tools
- **Hand tools**: `model`
- **Power tools**: `model`, `power` (choice: Corded, Cordless, Other)
- **Tool storage & accessories**
- A tool set is an item that contains tools (containment), not a category.

### Electronics
- Parent fields: `model`
- **Computers & tablets**: `storage`
- **Phones & wearables**: `storage`
- **Audio** ◆, **Cameras & photography** ◆, **TVs & home theater**, **Cables, chargers & accessories**, **Smart home**

### Sports & outdoors
- **Sports equipment** (balls, bats, gloves, weights, yoga mats, bikes and helmets): `sport` (text)
- **Camping & hiking**, **Fishing**
- **Lawn & yard games** (cornhole, Kan Jam, Spikeball, ladder toss)
- **Outdoor play** (ride-ons, kites, water guns, bubbles, sidewalk chalk)

### Craft & hobby
- **Sewing, yarn & fabric**, **Art supplies**
- **Model kits & miniatures** ◆: `scale`, `built` (boolean)

### Family photos & documents
- **Photos & albums**: `year` (number), `people` (text)
- **Documents & letters**: `year` (number), `written_by` (text)
- Heirlooms are not a category. Grandma's quilt is a quilt (Bedding); its story lives on the item as the giver plus a new occasion kind, **Inherited**. (Quilts are in Blankets, throws & quilts.)

### Other
- No fields. The general escape hatch.

---

## Where the old categories go

| Old | New |
|---|---|
| Video Games › Games, Consoles, Controllers, Accessories | Same names. `platform` moves from the parent to Games, Controllers, Accessories. |
| Movies & TV › Physical media | Discs, or VHS & tapes when format = VHS |
| Books › Novels, Other | Books (general) |
| Books › Manga & Comics | Manga by default; move comics by hand |
| Board Games & Puzzles | Games & Puzzles › Board games by default; puzzles by hand |
| Toys & Building Sets | Toys › Building sets when `set_number` is filled, else Toys (general) |
| Music › Albums & Vinyl | Music › Albums |
| Collectibles & Memorabilia | Memorabilia & Keepsakes; most items will need a better home |
| Home Decor › Wall art & Frames | Wall art & Posters |
| Home Decor › Other | Home Decor (general) |
| Kitchen › Drinkware & Dishes | Drinkware or Dishes & serveware, by hand |
| Clothing & Textiles | Clothing & Linens (general) until sorted |
| Tools › Tool sets | Tools (general) |
| Tools › Hand & Power tools | Hand tools when `power` = Manual, else Power tools |
| Electronics › Other | Electronics (general) |

Existing items must be re-pointed first, because deleting a category that has items is blocked.

## What the app needs for this

- **Conditional fields** (Albums, Board games): a template entry like `"show_if": {"key": "format", "equals": "Vinyl"}`, honored by the item form. Decide what happens to a vinyl-only value if the format later changes (keep, or clear).
- **Product/copy tags** on template fields, and the form logic in rule 7. The shared releases table is written only by the backend, so "edit release" has to mean "suggest a correction".
- **Shared field library**: define a field once in `category_tree.json` and have categories include it by key; a script expands it into the migration. `franchise`, `brand` and `signed_by` are columns on `items`, not part of this.
- **Category descriptions**: a `description` column on `categories` (what it holds, examples, "not for" pointers), searched by the picker and used by the intake prompt.
- **A searchable category picker.** The picker is a grouped dropdown. With 19 groups and 79 children it will be hard to scan on a phone, so S8 should replace it with a search-as-you-type picker.
- **Occasion kind**: add `inherited` to the `occasions.kind` check constraint.
- **Tests**: `tests/db/conftest.py` looks up Video Games › Games, and `tests/db/test_schema_extras.py` expects the field keys `['platform', 'region', 'edition', 'complete_in_box']`. Both change.
- Field keys stay the same where they exist today (`brand`, `edition`, `format`, `model`), so existing attribute data keeps working. `complete` and `complete_in_box` need a small data migration into `completeness`.

## Open questions

None. Settled in the review: popcorn tins have their own Kitchen child; Blankets, throws & quilts is its own child of Clothing & Linens; Lawn & yard games and Outdoor play are separate; the platform list is approved; the katana is under Props & replicas; completeness applies to Figures, Dolls & playsets, Audio and Cameras & photography; the searchable picker goes into S8.

Next step: the implementation plan and prompt, then the migration.
