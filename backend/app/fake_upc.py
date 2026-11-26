"""A stand-in for UPCitemdb, for walking the barcode flow locally without spending the real ~100 lookups a day:

    python -m uvicorn app.fake_upc:app --port 8002
    UPCITEMDB_URL=http://127.0.0.1:8002/prod/trial/lookup   (for the backend)

It answers like the trial endpoint (same JSON shape and rate headers) with the products the barcode test found
(titles, brands and categories as UPCitemdb returned them, including its odd categories), and:
* the two Switch 2 controllers from the test, and any other code: a miss (200, code OK, no items);
* 200000004293: 429 with Retry-After: 30;
* 200000005009: a 500;
* 200000008888: no answer for 10 s (the backend gives up after 8).
"""
import asyncio

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

PRODUCTS = {
    '883929704736': ('The Lord of the Rings: Motion Picture Trilogy (Extended & Theatrical)(4K/UHD)', 'Warner', 'Media > DVDs & Videos'),
    '826663208511': ('Nausicaa Of The Valley Of The Wind (Limited Edition Steelbook) (Blu-ray + DVD)', 'SDS', 'Media > DVDs & Videos'),
    '032429348128': ('Star Trek: Stardate Collection (Blu-ray + Digital Copy) [Blu-ray]', 'Paramount Home Video', 'Media > DVDs & Videos'),
    '191329209448': ('The Ultimate Aang & Korra Blu-ray Collection: Avatar: The Last Airbender: The Complete Series / Legend of Korra Complete Series', 'Paramount', 'Media > DVDs & Videos'),
    '704400025105': ('Code Geass: The Complete Series [Blu-ray]', 'Funimation', 'Electronics > Video > Televisions'),
    '704400015601': ('Dragon Ball Z: Seasons 1-9 Collection (Amazon Exclusive) [Blu-ray] (B075KZBHD6)', 'Funimation',
                     'Electronics > Video > Video Players & Recorders > DVD & Blu-ray Players'),
    '045496960070': ('Restored Super Smash Bros Melee', 'Nintendo GameCube', 'Software > Video Game Software'),
    '045496906788': ('Nintendo� The Legend of Zelda: Ocarina of Time - Nintendo Switch 2', 'Nintendo', ''),
}
RATE_LIMITED, SERVER_ERROR, SLOW = '200000004293', '200000005009', '200000008888'

app = FastAPI(title='Fake UPCitemdb')
remaining = {'n': 100}


def _headers() -> dict:
    remaining['n'] = max(remaining['n'] - 1, 0)
    return {'X-RateLimit-Limit': '100', 'X-RateLimit-Remaining': str(remaining['n']), 'X-RateLimit-Reset': '1795636139'}


@app.get('/prod/trial/lookup')
async def lookup(upc: str = Query('')):
    code = upc[1:] if len(upc) == 13 and upc.startswith('0') else upc
    if code == RATE_LIMITED:
        return JSONResponse({'code': 'TOO_FAST', 'message': 'Exceeded limit'}, 429, headers={**_headers(), 'Retry-After': '30'})
    if code == SERVER_ERROR:
        return JSONResponse({'code': 'INTERNAL_ERROR'}, 500)
    if code == SLOW:
        await asyncio.sleep(10)
    if code in PRODUCTS:
        title, brand, category = PRODUCTS[code]
        item = {'ean': '0' + code, 'title': title, 'brand': brand, 'category': category, 'model': '',
                'description': 'Canned answer from app.fake_upc.', 'images': [], 'offers': []}
        return JSONResponse({'code': 'OK', 'total': 1, 'offset': 0, 'items': [item]}, headers=_headers())
    return JSONResponse({'code': 'OK', 'total': 0, 'offset': 0, 'items': []}, headers=_headers())
