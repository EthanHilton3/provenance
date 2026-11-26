"""ONE real UPCitemdb lookup, to check the live API still answers the way upc.py reads it. Free, but it spends one
of the app's roughly 100 trial lookups for the day (shared by everyone on this network address).

Skipped by default. Opt in:  PROVENANCE_LIVE_UPC=1 pytest tests/test_live_barcode.py -s
Needs no keys and no database: it calls the client directly, not through the budget. Code: PROVENANCE_UPC_CODE, or
the Lord of the Rings 4K set from the barcode test (a known hit).
"""
import asyncio
import os

import httpx
import pytest

from app.gtin import parse
from app.upc import UpcItemDb, hints

pytestmark = pytest.mark.skipif(not os.environ.get('PROVENANCE_LIVE_UPC'),
                                reason='real UPCitemdb lookup: set PROVENANCE_LIVE_UPC=1')


def test_one_real_lookup():
    code = parse(os.environ.get('PROVENANCE_UPC_CODE', '883929704736'))

    async def go():
        async with httpx.AsyncClient() as http:
            return await UpcItemDb(http).lookup(code)

    result = asyncio.run(go())
    print(f'\n{code.code}: {result.outcome} HTTP {result.http_status} {result.headers}')
    if result.product:
        print(f"  {result.product['title']!r} by {result.product.get('brand')!r}; hints {hints(result.product, code.kind)}")
    assert result.outcome in ('hit', 'miss'), result.reason
    if 'PROVENANCE_UPC_CODE' not in os.environ:
        assert result.outcome == 'hit' and 'Lord of the Rings' in result.product['title']
