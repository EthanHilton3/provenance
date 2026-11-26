"""Pick the duplicate-release threshold from evidence (S12).

A hand-labelled set of release pairs: "same" pairs are one release written two ways (spelling, punctuation, missing
words); "different" pairs are different releases, most of them the same work in another format or edition, which
must NOT be suggested as duplicates. Each release goes through the app's own canonical_text() and is embedded with
text-embedding-3-small at 512 dimensions (one batched call, about 1,000 tokens, about $0.00002). The script prints
the cosine distance of every pair and how well each threshold separates them, with and without the format rule
(a suggestion needs the same normalized format, or a format missing on one side), and writes the table to
docs/DUPLICATE_THRESHOLD.md.

    .venv/Scripts/python -I scripts/duplicate_threshold.py          # real call, needs OPENAI_API_KEY in .env
    .venv/Scripts/python -I scripts/duplicate_threshold.py --fake   # no network, to check the script itself

The pairs are written by hand, not taken from TMDB (its terms forbid using its content to validate AI systems).
"""
import argparse
import asyncio
import math
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.embeddings import FakeEmbeddings, OpenAIEmbeddings, canonical_text, norm_format  # noqa: E402

# (title, format, edition, year)
SAME = [
    (('Spirited Away', 'Blu-ray', 'Steelbook', 2001), ('spirited away', 'Blu-ray', 'steel book', 2001)),
    (('The Lord of the Rings: The Fellowship of the Ring', '4K UHD', 'Extended Edition', 2001),
     ('Lord of the Rings Fellowship of the Ring', '4K UHD', 'Extended', 2001)),
    (('Princess Mononoke', 'Blu-ray', 'Standard', 1997), ('Princess Mononoke (Mononoke-hime)', 'Blu-ray', None, 1997)),
    (('Star Wars: A New Hope', '4K UHD', 'Steelbook', 1977), ('Star Wars Episode IV - A New Hope', '4K Ultra HD', 'SteelBook', 1977)),
    (('The Legend of Zelda: Tears of the Kingdom', 'Switch', "Collector's Edition", 2023),
     ('Zelda Tears of the Kingdom', 'Nintendo Switch', 'Collectors Edition', 2023)),
    (("Harry Potter and the Philosopher's Stone", 'Hardcover', 'First edition', 1997),
     ("Harry Potter & the Philosopher's Stone", 'hardback', '1st edition', 1997)),
    (('Dune', 'Paperback', None, 1990), ('Dune', 'paperback', 'standard', 1990)),
    (('Avatar: The Last Airbender - The Complete Series', 'Blu-ray', None, 2018),
     ('Avatar The Last Airbender Complete Series', 'Blu-ray', 'Standard', 2018)),
    (('Nausicaa of the Valley of the Wind', 'Blu-ray', 'Limited Edition Steelbook', 1984),
     ('Nausicaä of the Valley of the Wind', 'Blu-ray', 'Steelbook (Limited)', 1984)),
    (('Super Smash Bros. Melee', 'GameCube', "Player's Choice", 2001), ('Super Smash Bros Melee', 'Nintendo GameCube', 'Players Choice', 2001)),
    (('One Piece Vol. 1', 'Paperback', None, 2003), ('One Piece, Volume 1', 'Paperback', None, 2003)),
    (('Breaking Bad: The Complete Series', 'Blu-ray', "Collector's Set", 2014), ('Breaking Bad Complete Series', 'Blu-ray', 'Collectors Set', 2014)),
    (('Spider-Man: Into the Spider-Verse', '4K UHD', None, 2018), ('Spiderman Into the Spiderverse', '4K', None, 2018)),
    (('The Hobbit', 'Hardcover', '75th Anniversary Edition', 2012), ('The Hobbit', 'Hardcover', '75th anniversary', 2012)),
    (('Mario Kart 8 Deluxe', 'Switch', None, 2017), ('Mario Kart 8 Deluxe', 'Nintendo Switch', 'Standard', 2017)),
    (('Code Geass: The Complete Series', 'Blu-ray', None, 2006), ('Code Geass Complete Series', 'Blu-ray', None, None)),
    (('Howl\'s Moving Castle', 'DVD', None, 2004), ('Howls Moving Castle', 'DVD', None, 2004)),
    (('The Dark Knight', 'Blu-ray', None, 2008), ('Dark Knight, The', 'Blu-ray', None, 2008)),
]

DIFFERENT = [
    # the same work in another format or edition: must not be suggested
    (('Spirited Away', 'Blu-ray', 'Steelbook', 2001), ('Spirited Away', 'DVD', None, 2001)),
    (('Spirited Away', 'Blu-ray', None, 2001), ('Spirited Away', 'Blu-ray', 'Steelbook', 2001)),
    (('Spirited Away', '4K UHD', None, 2001), ('Spirited Away', 'Blu-ray', None, 2001)),
    (('The Lord of the Rings: The Fellowship of the Ring', '4K UHD', 'Extended Edition', 2001),
     ('The Lord of the Rings: The Fellowship of the Ring', '4K UHD', 'Theatrical Edition', 2001)),
    (('The Lord of the Rings: The Fellowship of the Ring', 'Blu-ray', 'Extended Edition', 2001),
     ('The Lord of the Rings: The Fellowship of the Ring', 'DVD', 'Extended Edition', 2001)),
    (('Star Wars: A New Hope', '4K UHD', 'Steelbook', 1977), ('Star Wars: A New Hope', 'Blu-ray', 'Steelbook', 1977)),
    (('The Legend of Zelda: Tears of the Kingdom', 'Switch', "Collector's Edition", 2023),
     ('The Legend of Zelda: Tears of the Kingdom', 'Switch', None, 2023)),
    (("Harry Potter and the Philosopher's Stone", 'Hardcover', 'First edition', 1997),
     ("Harry Potter and the Philosopher's Stone", 'Paperback', None, 1997)),
    (('Dune', 'Paperback', None, 1990), ('Dune', 'Hardcover', 'Deluxe Edition', 2019)),
    (('Super Smash Bros. Melee', 'GameCube', "Player's Choice", 2001), ('Super Smash Bros. Melee', 'GameCube', None, 2001)),
    (('Nausicaa of the Valley of the Wind', 'Blu-ray', 'Limited Edition Steelbook', 1984),
     ('Nausicaa of the Valley of the Wind', 'DVD', None, 1984)),
    (('The Hobbit', 'Hardcover', '75th Anniversary Edition', 2012), ('The Hobbit', 'Paperback', None, 2012)),
    (('The Dark Knight', 'Blu-ray', None, 2008), ('The Dark Knight', '4K UHD', None, 2008)),
    (('Princess Mononoke', 'Blu-ray', None, 1997), ('Princess Mononoke', 'Blu-ray', 'Collector\'s Edition', 1997)),
    # the same series or a sequel
    (("Harry Potter and the Philosopher's Stone", 'Hardcover', None, 1997), ('Harry Potter and the Chamber of Secrets', 'Hardcover', None, 1998)),
    (('Mario Kart 8 Deluxe', 'Switch', None, 2017), ('Mario Kart 8', 'Wii U', None, 2014)),
    (('One Piece Vol. 1', 'Paperback', None, 2003), ('One Piece Vol. 2', 'Paperback', None, 2003)),
    (('Trigun Maximum Vol. 1', 'Paperback', None, 2004), ('Trigun Maximum Vol. 3', 'Paperback', None, 2004)),
    (('Breaking Bad: The Complete Series', 'Blu-ray', None, 2014), ('Breaking Bad: Season 1', 'Blu-ray', None, 2009)),
    (('Spider-Man: Into the Spider-Verse', '4K UHD', None, 2018), ('Spider-Man: Across the Spider-Verse', '4K UHD', None, 2023)),
    (('Star Wars: A New Hope', '4K UHD', None, 1977), ('Star Wars: The Empire Strikes Back', '4K UHD', None, 1980)),
    (('Avatar: The Last Airbender - The Complete Series', 'Blu-ray', None, 2018), ('Avatar', 'Blu-ray', None, 2009)),
    # unrelated
    (('Spirited Away', 'Blu-ray', None, 2001), ('Princess Mononoke', 'Blu-ray', None, 1997)),
    (('Dune', 'Paperback', None, 1990), ('Dune', 'Blu-ray', None, 2021)),
]


def cosine_distance(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return 1 - dot / (na * nb)


def same_format(a, b) -> bool:
    fa, fb = norm_format(a[1]).lower(), norm_format(b[1]).lower()
    return not fa or not fb or fa == fb


def label(r):
    return ' / '.join(str(x) for x in r if x not in (None, ''))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fake', action='store_true', help='fake vectors, no network')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'DUPLICATE_THRESHOLD.md'))
    args = ap.parse_args()

    pairs = [(a, b, True) for a, b in SAME] + [(a, b, False) for a, b in DIFFERENT]
    texts = sorted({canonical_text(*r) for a, b, _ in pairs for r in (a, b)})
    async with httpx.AsyncClient() as http:
        if args.fake:
            client = FakeEmbeddings()
        else:
            key = dotenv_values(ROOT / '.env').get('OPENAI_API_KEY') or ''
            if not key:
                raise SystemExit('OPENAI_API_KEY is not set in .env')
            client = OpenAIEmbeddings(http, key)
        vectors, usage = await client.embed(texts)
    vec = dict(zip(texts, vectors))
    print(f'{len(texts)} texts, {usage["tokens"]} tokens, ${usage["cost_usd"]:.8f} ({usage["model"]})')

    rows = []
    for a, b, same in pairs:
        d = cosine_distance(vec[canonical_text(*a)], vec[canonical_text(*b)])
        rows.append((d, same, same_format(a, b), a, b))
    rows.sort(key=lambda r: r[0])

    def score(t, rule):
        tp = sum(1 for d, s, f, *_ in rows if s and d <= t and (f or not rule))
        fp = sum(1 for d, s, f, *_ in rows if not s and d <= t and (f or not rule))
        return tp, fp

    candidates = sorted({round(r[0], 3) for r in rows})
    lines = ['# Duplicate release threshold (S12)', '',
             f'Measured with `scripts/duplicate_threshold.py`: {len(SAME)} pairs that are one release written two ways, '
             f'{len(DIFFERENT)} pairs of different releases (most of them the same work in another format or edition). '
             f'{len(texts)} texts, {usage["tokens"]} tokens, ${usage["cost_usd"]:.6f}, model {usage["model"]} at 512 dimensions. '
             'Each release is embedded as `canonical_text()` (backend/app/embeddings.py).', '',
             '## Every pair, by cosine distance', '',
             '| Distance | Label | Same format? | A | B |', '| --- | --- | --- | --- | --- |']
    for d, same, fmt, a, b in rows:
        lines.append(f'| {d:.3f} | {"same" if same else "different"} | {"yes" if fmt else "no"} | {label(a)} | {label(b)} |')
    lines += ['', '## Thresholds', '',
              '"Found" = same pairs suggested (of ' + str(len(SAME)) + '); "wrong" = different pairs suggested (of '
              + str(len(DIFFERENT)) + '). The format rule also requires the same normalized format.', '',
              '| Threshold | Found | Wrong | Found, with format rule | Wrong, with format rule |', '| --- | --- | --- | --- | --- |']
    for t in candidates:
        tp, fp = score(t, False)
        tp2, fp2 = score(t, True)
        lines.append(f'| {t:.3f} | {tp} | {fp} | {tp2} | {fp2} |')
    Path(args.out).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines).encode('ascii', 'replace').decode())


if __name__ == '__main__':
    asyncio.run(main())
