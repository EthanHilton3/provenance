"""ONE real photo through Luna (single item) and ONE group photo through Sol. Costs real money: about $0.03 in all.

Opt in twice (it is skipped by default, and by PROVENANCE_LIVE alone):
  PROVENANCE_LIVE=1 PROVENANCE_LIVE_AI=1 pytest tests/test_live_ai.py -s
Uses OPENAI_API_KEY from .env (or the environment) and reads the built-in categories from SUPABASE_URL (local or cloud;
read only). Photos: PROVENANCE_AI_SINGLE_PHOTO and PROVENANCE_AI_GROUP_PHOTO, or else the first photo of each
feasibility test in the CS-452 Database repo next to this one. Each photo goes through the upload cleaner first
(EXIF and GPS stripped, 2048 px), the same as a real upload. Nothing is written to the database.
"""
import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

from app.ai import MODES, OpenAIClient, propose
from app.config import get_settings
from app.db import service_db
from app.images import clean_photo
from app.worker import load_categories

pytestmark = pytest.mark.skipif(not (os.environ.get('PROVENANCE_LIVE') and os.environ.get('PROVENANCE_LIVE_AI')),
                                reason='real OpenAI calls: set PROVENANCE_LIVE=1 and PROVENANCE_LIVE_AI=1')

CS452 = Path(__file__).resolve().parents[3] / 'CS-452 Database'
# Feasibility costs per photo: Luna 768 px about $0.0003 (plus about 4,000 prompt tokens of category descriptions,
# about $0.0005 uncached); Sol whole photo at 2048 px about $0.027.
ESTIMATE = {'single': 0.001, 'group': 0.03}


def first_photo(env_var: str, folder: str) -> Path:
    if os.environ.get(env_var):
        return Path(os.environ[env_var])
    found = sorted((CS452 / folder / 'photos' / 'jpg').glob('*.jpg'))
    if not found:
        pytest.skip(f'set {env_var} to a photo')
    return found[0]


def test_one_luna_card_and_one_sol_scene():
    key = get_settings().openai_api_key.get_secret_value()
    assert key and not key.startswith('sk-test'), 'needs the real OPENAI_API_KEY'
    photos = {'single': first_photo('PROVENANCE_AI_SINGLE_PHOTO', '26-11-16 collection intake feasibility'),
              'group': first_photo('PROVENANCE_AI_GROUP_PHOTO', '26-11-23 group photo feasibility')}
    print(f'\nEstimated cost: about ${sum(ESTIMATE.values()):.2f} '
          f'(Luna ${ESTIMATE["single"]:.3f} for {photos["single"].name}, Sol ${ESTIMATE["group"]:.3f} for {photos["group"].name})')

    async def run():
        async with httpx.AsyncClient(timeout=30) as http:
            categories = await load_categories(service_db(http))
            ai = OpenAIClient(http, key)
            out = {}
            for mode, path in photos.items():
                jpeg = clean_photo(path.read_bytes()).jpeg
                out[mode] = await propose(ai, mode, jpeg, categories)
            return out, categories

    out, categories = asyncio.run(run())
    card, single = out['single']
    scene, group = out['group']
    # Reaching here means both replies were HTTP 200, status 'completed', and passed validation: a rejected strict
    # schema is an HTTP 400 and would have raised AIError (OpenAI's message is in the captured WARNING log).
    print('Both calls: HTTP 200, status completed, strict schema accepted, answer validated')
    print('\nLuna card:\n' + json.dumps(card, indent=2, ensure_ascii=False))
    print(f'\nSol scene: {len(scene["items"])} items, {scene["visible_but_unidentifiable"]} unidentified, notes: {scene["notes"]}')
    for n, i in enumerate(scene['items']):
        print(f'  {n}. {i["name"]} | {i["kind"]} | {i["confidence"]} | {i["position"]} | read: {i["text_read_on_item"]}')
    for mode, u in (('single', single), ('group', group)):
        print(f'{mode}: {u["model"]} {u["input_tokens"]} in ({u["cached_tokens"]} cached), {u["output_tokens"]} out '
              f'({u["reasoning_tokens"]} reasoning), ${u["cost_usd"]:.6f}, {u["latency_ms"]} ms')
    print(f'Actual cost: ${single["cost_usd"] + group["cost_usd"]:.4f}')

    assert single['model'] == MODES['single'].model and group['model'] == MODES['group'].model
    assert card['category_id'] == categories.ids[card['category']] and card['name']
    assert scene['items'] and all(i['name'] for i in scene['items'])
