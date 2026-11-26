"""A stand-in for TMDB and Open Library, for walking the catalog flow locally without calling them:

    python -m uvicorn app.fake_catalog:app --port 8003
    TMDB_URL=http://127.0.0.1:8003/3   OPENLIBRARY_URL=http://127.0.0.1:8003/ol   (for the backend)

It answers in their JSON shapes (only the fields the backend reads) from a small list of real titles, matching any
title that shares a word with the query, like a loose search does. Two shows are both called "Avatar: The Last
Airbender" (2005 and 2024), as on TMDB, so a search without a year is ambiguous. A query containing:
* "ratelimit": 429 with Retry-After: 30;
* "servererror": a 500;
* "slow": no answer for 10 s (the backend gives up after 6, retries once, then reports unavailable).
"""
import asyncio
import re

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

MOVIES = [
    (129, 'Spirited Away', '千と千尋の神隠し', '2001-07-20', 90.0),
    (128, 'Princess Mononoke', 'もののけ姫', '1997-07-12', 23.0),
    (81, 'Nausicaä of the Valley of the Wind', '風の谷のナウシカ', '1984-03-11', 30.0),
    (120, 'The Lord of the Rings: The Fellowship of the Ring', None, '2001-12-18', 120.0),
    (122, 'The Lord of the Rings: The Return of the King', None, '2003-12-01', 110.0),
    (11, 'Star Wars', None, '1977-05-25', 80.0),
    (155, 'The Dark Knight', None, '2008-07-16', 100.0),
]
SHOWS = [
    (246, 'Avatar: The Last Airbender', None, '2005-02-21', 35.0),
    (82452, 'Avatar: The Last Airbender', None, '2024-02-22', 39.0),
    (31724, 'Code Geass: Lelouch of the Rebellion', 'コードギアス 反逆のルルーシュ', '2006-10-06', 20.0),
    (1396, 'Breaking Bad', None, '2008-01-20', 200.0),
]
BOOKS = [
    ('OL27482W', 'The Hobbit', ['J.R.R. Tolkien'], 1937, 482, ['9780547928227', '9780261102217']),
    ('OL893415W', 'Dune', ['Frank Herbert'], 1965, 300, ['9780441172719']),
    ('OL82563W', "Harry Potter and the Philosopher's Stone", ['J. K. Rowling'], 1997, 400, ['9780747532699']),
]
STOP = {'the', 'of', 'a', 'and', 'to', 'in'}

app = FastAPI(title='Fake TMDB and Open Library')


def words(s: str) -> set[str]:
    return set(re.findall(r'[a-z0-9]+', s.lower())) - STOP


def special(query: str):
    q = query.lower()
    if 'ratelimit' in q:
        return JSONResponse({'status_message': 'Too many requests'}, 429, headers={'Retry-After': '30'})
    if 'servererror' in q:
        return JSONResponse({'status_message': 'error'}, 500)
    return None


def matches(query: str, title: str, original: str | None = None) -> int:
    return max(len(words(query) & words(title)), len(words(query) & words(original or '')))


@app.get('/3/search/{kind}')
async def tmdb_search(kind: str, query: str = '', year: int | None = None, first_air_date_year: int | None = None):
    if r := special(query):
        return r
    if 'slow' in query.lower():
        await asyncio.sleep(10)
    rows = MOVIES if kind == 'movie' else SHOWS
    y = year or first_air_date_year
    hits = sorted((r for r in rows if matches(query, r[1], r[2]) and (not y or r[3].startswith(str(y)))),
                  key=lambda r: -matches(query, r[1], r[2]))
    key, okey, dkey = ('title', 'original_title', 'release_date') if kind == 'movie' else ('name', 'original_name', 'first_air_date')
    return {'page': 1, 'total_results': len(hits),
            'results': [{'id': i, key: t, okey: o or t, dkey: d, 'popularity': p} for i, t, o, d, p in hits]}


@app.get('/3/{kind}/{tmdb_id}')
async def tmdb_details(kind: str, tmdb_id: int):
    rows = MOVIES if kind == 'movie' else SHOWS
    for i, t, o, d, p in rows:
        if i == tmdb_id:
            if kind == 'movie':
                return {'id': i, 'title': t, 'original_title': o or t, 'release_date': d, 'popularity': p}
            return {'id': i, 'name': t, 'original_name': o or t, 'first_air_date': d, 'popularity': p}
    return JSONResponse({'status_code': 34, 'status_message': 'not found'}, 404)


def ol_doc(b):
    return {'key': f'/works/{b[0]}', 'title': b[1], 'author_name': b[2], 'first_publish_year': b[3], 'edition_count': b[4]}


@app.get('/ol/search.json')
async def ol_search(q: str = '', title: str = '', limit: int = Query(8)):
    if r := special(q or title):
        return r
    if q.startswith('isbn:'):
        isbn = q[5:]
        docs = [ol_doc(b) for b in BOOKS if isbn in b[5]]
    else:
        docs = [ol_doc(b) for b in sorted(BOOKS, key=lambda b: -matches(title, b[1])) if matches(title, b[1])]
    return {'numFound': len(docs), 'docs': docs[:limit]}


@app.get('/ol/works/{key}.json')
async def ol_work(key: str):
    for b in BOOKS:
        if b[0] == key:
            return {'key': f'/works/{key}', 'title': b[1], 'first_publish_date': str(b[3])}
    return JSONResponse({'error': 'notfound'}, 404)
