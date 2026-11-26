# Duplicate release threshold (S12)

Measured with `scripts/duplicate_threshold.py`: 18 pairs that are one release written two ways, 24 pairs of different releases (most of them the same work in another format or edition). 62 texts, 1484 tokens, $0.000030, model text-embedding-3-small at 512 dimensions. Each release is embedded as `canonical_text()` (backend/app/embeddings.py).

## Every pair, by cosine distance

| Distance | Label | Same format? | A | B |
| --- | --- | --- | --- | --- |
| 0.000 | same | yes | Dune / Paperback / 1990 | Dune / paperback / standard / 1990 |
| 0.000 | same | yes | Mario Kart 8 Deluxe / Switch / 2017 | Mario Kart 8 Deluxe / Nintendo Switch / Standard / 2017 |
| 0.005 | same | yes | The Hobbit / Hardcover / 75th Anniversary Edition / 2012 | The Hobbit / Hardcover / 75th anniversary / 2012 |
| 0.008 | same | yes | Super Smash Bros. Melee / GameCube / Player's Choice / 2001 | Super Smash Bros Melee / Nintendo GameCube / Players Choice / 2001 |
| 0.012 | same | yes | Avatar: The Last Airbender - The Complete Series / Blu-ray / 2018 | Avatar The Last Airbender Complete Series / Blu-ray / Standard / 2018 |
| 0.013 | same | yes | The Dark Knight / Blu-ray / 2008 | Dark Knight, The / Blu-ray / 2008 |
| 0.014 | same | yes | Princess Mononoke / Blu-ray / Standard / 1997 | Princess Mononoke (Mononoke-hime) / Blu-ray / 1997 |
| 0.015 | same | yes | Breaking Bad: The Complete Series / Blu-ray / Collector's Set / 2014 | Breaking Bad Complete Series / Blu-ray / Collectors Set / 2014 |
| 0.017 | same | yes | Harry Potter and the Philosopher's Stone / Hardcover / First edition / 1997 | Harry Potter & the Philosopher's Stone / hardback / 1st edition / 1997 |
| 0.020 | same | yes | The Lord of the Rings: The Fellowship of the Ring / 4K UHD / Extended Edition / 2001 | Lord of the Rings Fellowship of the Ring / 4K UHD / Extended / 2001 |
| 0.020 | same | yes | Spider-Man: Into the Spider-Verse / 4K UHD / 2018 | Spiderman Into the Spiderverse / 4K / 2018 |
| 0.022 | same | yes | Howl's Moving Castle / DVD / 2004 | Howls Moving Castle / DVD / 2004 |
| 0.023 | same | yes | One Piece Vol. 1 / Paperback / 2003 | One Piece, Volume 1 / Paperback / 2003 |
| 0.024 | same | yes | Star Wars: A New Hope / 4K UHD / Steelbook / 1977 | Star Wars Episode IV - A New Hope / 4K Ultra HD / SteelBook / 1977 |
| 0.032 | different | yes | The Lord of the Rings: The Fellowship of the Ring / 4K UHD / Extended Edition / 2001 | The Lord of the Rings: The Fellowship of the Ring / 4K UHD / Theatrical Edition / 2001 |
| 0.033 | same | yes | Nausicaa of the Valley of the Wind / Blu-ray / Limited Edition Steelbook / 1984 | Nausicaä of the Valley of the Wind / Blu-ray / Steelbook (Limited) / 1984 |
| 0.037 | different | yes | Trigun Maximum Vol. 1 / Paperback / 2004 | Trigun Maximum Vol. 3 / Paperback / 2004 |
| 0.037 | same | yes | The Legend of Zelda: Tears of the Kingdom / Switch / Collector's Edition / 2023 | Zelda Tears of the Kingdom / Nintendo Switch / Collectors Edition / 2023 |
| 0.040 | different | yes | Super Smash Bros. Melee / GameCube / Player's Choice / 2001 | Super Smash Bros. Melee / GameCube / 2001 |
| 0.044 | different | yes | Princess Mononoke / Blu-ray / 1997 | Princess Mononoke / Blu-ray / Collector's Edition / 1997 |
| 0.050 | different | yes | The Legend of Zelda: Tears of the Kingdom / Switch / Collector's Edition / 2023 | The Legend of Zelda: Tears of the Kingdom / Switch / 2023 |
| 0.051 | same | yes | Spirited Away / Blu-ray / Steelbook / 2001 | spirited away / Blu-ray / steel book / 2001 |
| 0.070 | different | no | The Lord of the Rings: The Fellowship of the Ring / Blu-ray / Extended Edition / 2001 | The Lord of the Rings: The Fellowship of the Ring / DVD / Extended Edition / 2001 |
| 0.070 | same | yes | Code Geass: The Complete Series / Blu-ray / 2006 | Code Geass Complete Series / Blu-ray |
| 0.073 | different | yes | Spirited Away / Blu-ray / 2001 | Spirited Away / Blu-ray / Steelbook / 2001 |
| 0.076 | different | yes | One Piece Vol. 1 / Paperback / 2003 | One Piece Vol. 2 / Paperback / 2003 |
| 0.076 | different | no | Star Wars: A New Hope / 4K UHD / Steelbook / 1977 | Star Wars: A New Hope / Blu-ray / Steelbook / 1977 |
| 0.080 | different | no | Harry Potter and the Philosopher's Stone / Hardcover / First edition / 1997 | Harry Potter and the Philosopher's Stone / Paperback / 1997 |
| 0.096 | different | no | The Dark Knight / Blu-ray / 2008 | The Dark Knight / 4K UHD / 2008 |
| 0.098 | different | no | Spirited Away / 4K UHD / 2001 | Spirited Away / Blu-ray / 2001 |
| 0.105 | different | no | Mario Kart 8 Deluxe / Switch / 2017 | Mario Kart 8 / Wii U / 2014 |
| 0.117 | different | yes | Spider-Man: Into the Spider-Verse / 4K UHD / 2018 | Spider-Man: Across the Spider-Verse / 4K UHD / 2023 |
| 0.122 | different | no | The Hobbit / Hardcover / 75th Anniversary Edition / 2012 | The Hobbit / Paperback / 2012 |
| 0.124 | different | no | Nausicaa of the Valley of the Wind / Blu-ray / Limited Edition Steelbook / 1984 | Nausicaa of the Valley of the Wind / DVD / 1984 |
| 0.134 | different | yes | Star Wars: A New Hope / 4K UHD / 1977 | Star Wars: The Empire Strikes Back / 4K UHD / 1980 |
| 0.137 | different | yes | Breaking Bad: The Complete Series / Blu-ray / 2014 | Breaking Bad: Season 1 / Blu-ray / 2009 |
| 0.139 | different | no | Spirited Away / Blu-ray / Steelbook / 2001 | Spirited Away / DVD / 2001 |
| 0.188 | different | no | Dune / Paperback / 1990 | Dune / Hardcover / Deluxe Edition / 2019 |
| 0.226 | different | yes | Harry Potter and the Philosopher's Stone / Hardcover / 1997 | Harry Potter and the Chamber of Secrets / Hardcover / 1998 |
| 0.227 | different | yes | Spirited Away / Blu-ray / 2001 | Princess Mononoke / Blu-ray / 1997 |
| 0.242 | different | yes | Avatar: The Last Airbender - The Complete Series / Blu-ray / 2018 | Avatar / Blu-ray / 2009 |
| 0.316 | different | no | Dune / Paperback / 1990 | Dune / Blu-ray / 2021 |

## Thresholds

"Found" = same pairs suggested (of 18); "wrong" = different pairs suggested (of 24). The format rule also requires the same normalized format.

| Threshold | Found | Wrong | Found, with format rule | Wrong, with format rule |
| --- | --- | --- | --- | --- |
| 0.000 | 1 | 0 | 1 | 0 |
| 0.005 | 3 | 0 | 3 | 0 |
| 0.008 | 3 | 0 | 3 | 0 |
| 0.012 | 5 | 0 | 5 | 0 |
| 0.013 | 6 | 0 | 6 | 0 |
| 0.014 | 7 | 0 | 7 | 0 |
| 0.015 | 7 | 0 | 7 | 0 |
| 0.017 | 8 | 0 | 8 | 0 |
| 0.020 | 10 | 0 | 10 | 0 |
| 0.022 | 12 | 0 | 12 | 0 |
| 0.023 | 12 | 0 | 12 | 0 |
| 0.024 | 14 | 0 | 14 | 0 |
| 0.032 | 14 | 1 | 14 | 1 |
| 0.033 | 14 | 1 | 14 | 1 |
| 0.037 | 15 | 1 | 15 | 1 |
| 0.040 | 16 | 3 | 16 | 3 |
| 0.044 | 16 | 3 | 16 | 3 |
| 0.050 | 16 | 5 | 16 | 5 |
| 0.051 | 17 | 5 | 17 | 5 |
| 0.070 | 17 | 6 | 17 | 5 |
| 0.073 | 18 | 7 | 18 | 6 |
| 0.076 | 18 | 8 | 18 | 7 |
| 0.080 | 18 | 10 | 18 | 7 |
| 0.096 | 18 | 11 | 18 | 7 |
| 0.098 | 18 | 11 | 18 | 7 |
| 0.105 | 18 | 13 | 18 | 7 |
| 0.117 | 18 | 13 | 18 | 7 |
| 0.122 | 18 | 14 | 18 | 8 |
| 0.124 | 18 | 15 | 18 | 8 |
| 0.134 | 18 | 17 | 18 | 9 |
| 0.137 | 18 | 18 | 18 | 10 |
| 0.139 | 18 | 18 | 18 | 10 |
| 0.188 | 18 | 19 | 18 | 10 |
| 0.226 | 18 | 21 | 18 | 11 |
| 0.227 | 18 | 22 | 18 | 12 |
| 0.242 | 18 | 23 | 18 | 13 |
| 0.316 | 18 | 23 | 18 | 13 |

## Decision

**Suggest an existing release when the cosine distance is at most 0.028 and the formats do not differ.**

- Same releases written two ways sit at 0.000 to 0.024 for 14 of 18 pairs. The other four are further out: a diacritic (Nausicaä, 0.033), a shortened title (Zelda, 0.037), "steel book" in lower case (0.051) and a missing year (0.070).
- Different editions of the same film or game sit right among them: Extended vs Theatrical at 0.032, Player's Choice vs standard at 0.040, Collector's vs standard at 0.044 and 0.050, and volume 1 vs 3 at 0.037. No threshold finds all duplicates without also suggesting a different edition.
- Different formats start at 0.070, and the format rule (both formats known and different: never suggested) removes them at any threshold.
- 0.028 is midway between the last clean same pair (0.024) and the first different pair (0.032): 14 of 18 duplicates found, 0 of 24 different releases suggested. A miss costs a second shared release that moderation can merge later; a wrong suggestion invites linking the wrong edition, which is what this check must not do. The owner still decides every suggestion; nothing is merged automatically.
- 42 hand-written pairs is a small set: the margin between 0.024 and 0.032 is thin. Re-run the script with real releases once users have created some, and change `DUPLICATE_MAX_DISTANCE` (backend config) if the evidence moves.
