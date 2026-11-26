"""A stand-in for OpenAI, for walking the intake flow locally without cost:  python -m app.worker --fake

It answers with canned proposals that pass the real schemas, chosen from the photo's average colour so a walk is
repeatable:
* single mode: mostly red -> a Switch game (sure); mostly green -> a film on disc (unsure, asks "4K or Blu-ray?",
  can't tell if sealed); mostly blue or anything else -> a mug (low confidence).
* group mode: always the same shelf of six items, two of them unidentifiable.
* a nearly black photo -> an AI error, so the retry and failed states can be seen (3 attempts, then failed).

Never used unless --fake is passed, and the worker refuses --fake against anything but a local Supabase.
"""
import base64
import io

from PIL import Image, ImageStat
from pydantic import BaseModel

from .ai import AIError, ModeConfig, Scene

GAME = {'item_count': 1, 'category': 'Video Games > Games', 'name': 'The Legend of Zelda: Tears of the Kingdom',
        'brand_or_maker': 'Nintendo', 'franchise_or_series': 'The Legend of Zelda', 'edition_or_model': None,
        'platform_or_format': 'Switch', 'attributes': [{'key': 'Region', 'value': 'US'}], 'condition': 'opened / used',
        'bundle_contents': [], 'catalog': 'igdb_game', 'catalog_query': 'Tears of the Kingdom', 'confidence': 'high',
        'ask_user': None}
DISC = {'item_count': 1, 'category': 'Movies & TV > Discs', 'name': 'Spirited Away', 'brand_or_maker': 'GKIDS',
        'franchise_or_series': 'Studio Ghibli', 'edition_or_model': None, 'platform_or_format': None,
        'attributes': [{'key': 'disc count', 'value': '2'}, {'key': 'packaging', 'value': 'steelbook'}],
        'condition': 'cannot tell', 'bundle_contents': [], 'catalog': 'tmdb_movie', 'catalog_query': 'Spirited Away',
        'confidence': 'medium', 'ask_user': 'Is this the 4K UHD or the Blu-ray release?'}
MUG = {'item_count': 1, 'category': 'Kitchen > Drinkware', 'name': 'Blue diner mug', 'brand_or_maker': None,
       'franchise_or_series': None, 'edition_or_model': None, 'platform_or_format': None,
       'attributes': [{'key': 'material', 'value': 'ceramic'}, {'key': 'color', 'value': 'blue'}],
       'condition': 'opened / used', 'bundle_contents': [], 'catalog': 'none', 'catalog_query': 'blue diner mug',
       'confidence': 'low', 'ask_user': 'What brand is printed on the bottom?'}


def _found(name, kind, confidence, position, sealed=None, maker=None, series=None, volumes=None, edition=None,
           text=None):
    return {'name': name, 'creator_or_maker': maker, 'kind': kind, 'series_or_franchise': series,
            'volumes_or_count': volumes, 'edition_or_format': edition, 'text_read_on_item': text or name.upper(),
            'confidence': confidence, 'position': position, 'sealed': sealed}


SHELF = {
    'items': [
        _found('One Piece', 'manga or comic volume', 'high', 'top shelf, left', maker='Eiichiro Oda', series='One Piece',
               volumes='vols 1-3', text='ONE PIECE 1 2 3'),
        _found('Trigun Maximum', 'manga or comic volume', 'medium', 'top shelf, middle', maker='Yasuhiro Nightow',
               series='Trigun', volumes='vols 1 and 2', edition='Deluxe'),
        _found('Spirited Away', 'movie or TV disc set', 'high', 'middle shelf, left', sealed=False, maker='GKIDS',
               series='Studio Ghibli', edition='Blu-ray'),
        _found('Final Fantasy Pixel Remaster', 'box set or slipcase set', 'low', 'middle shelf, right',
               series='Final Fantasy', text='FINAL FANTASY ... REMASTER (partly hidden)'),
        _found('Super Mario Odyssey', 'video game', 'high', 'bottom shelf, left', sealed=True, maker='Nintendo',
               series='Super Mario', edition='Switch'),
        _found('Link amiibo', 'amiibo or figure', 'medium', 'bottom shelf, right', maker='Nintendo',
               series='The Legend of Zelda', text='amiibo'),
    ],
    'visible_but_unidentifiable': 2,
    'notes': 'Fake model: a canned shelf.',
}


def _photo_colour(content: list[dict]) -> tuple[float, float, float]:
    for part in content:
        if part.get('type') == 'input_image':
            data = base64.b64decode(part['image_url'].split(',', 1)[1])
            with Image.open(io.BytesIO(data)) as im:
                return tuple(ImageStat.Stat(im.convert('RGB').resize((32, 32))).mean)
    return (0.0, 0.0, 255.0)


class FakeAIClient:
    """Same `parse` as ai.OpenAIClient; no network."""

    async def parse(self, cfg: ModeConfig, system: str, content: list[dict], schema: type[BaseModel]):
        usage = {'model': f'fake-{cfg.model}', 'input_tokens': 0, 'cached_tokens': 0, 'output_tokens': 0,
                 'reasoning_tokens': 0, 'cost_usd': 0.0, 'latency_ms': 0}
        r, g, b = _photo_colour(content)
        if max(r, g, b) < 24:
            raise AIError('The fake AI was told to fail (an all-black photo)', usage)
        if schema is Scene:
            return Scene.model_validate(SHELF), usage
        card = GAME if r >= max(g, b) else DISC if g >= b else MUG
        allowed = set(schema.model_fields['category'].annotation.__args__)
        if card['category'] not in allowed:  # a category renamed since this file was written
            card = {**card, 'category': 'Other' if 'Other' in allowed else sorted(allowed)[0]}
        return schema.model_validate(card), usage
