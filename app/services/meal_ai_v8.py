"""Meal AI V8 - local research service, never an insulin dosing component.

Nutrition lookup prioritizes a user's PRIVATE book catalogue. All rows are
unverified references, not clinical nutrition measurements. No photos stored.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[2]
# On Render a private beta may use /etc/secrets/meal_private_catalog.json.
# This source is NEVER embedded in the GitHub repository.
PRIVATE_CATALOG = Path(os.getenv('MEAL_AI_PRIVATE_CATALOG_PATH') or (ROOT / 'data' / 'meal_photo_private_sources' / 'catalog_v8.json'))
PRIVATE_IMAGES = ROOT / 'data' / 'meal_photo_private_sources' / 'book_pages'
API_URL = 'https://api.openai.com/v1/responses'
OFF_URL = 'https://world.openfoodfacts.org/api/v2/product/'
USDA_URL = 'https://api.nal.usda.gov/fdc/v1/foods/search'
MODEL = os.getenv('MEAL_AI_MODEL', 'gpt-4o-mini')
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def normalize_name(value: str) -> str:
    raw = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(re.findall(r'[a-z0-9]+', ''.join(c for c in raw if not unicodedata.combining(c))))


def finite_float(value, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError('Číslo chybí nebo není platné.')
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Číslo chybí nebo není platné.') from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f'Hodnota musí být v rozsahu {minimum}–{maximum}.')
    return number


def carbs_from_portion(portion_g, carbs_per_100g) -> float:
    """Deterministic calculation; never derive carbohydrates from image pixels."""
    p = Decimal(str(finite_float(portion_g, 0.1, 3000)))
    c = Decimal(str(finite_float(carbs_per_100g, 0, 100)))
    return float((p * c / 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def load_book_catalog(path: Path | None = None) -> list[dict]:
    if path is None:
        path = PRIVATE_CATALOG
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding='utf-8'))
    if raw.get('vj_g_carbs') != 10:
        raise ValueError('Nepodporovaná definice VJ v katalogu.')
    foods: list[dict] = []
    for item in raw.get('rows', []):
        try:
            name = str(item['name_cs']).strip()
            vj = finite_float(item['exchange_units'], 0.1, 20)
            mass = finite_float(item['weight_g'], 1, 5000)
            per100 = round(1000 * vj / mass, 2)
            if len(name) < 2 or per100 > 100:
                continue
            page_id = str(item['page_id'])
            if not re.fullmatch(r'IMG_0(?:17[7-9]|18\d|19\d|20[0-4])', page_id):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        foods.append({
            'name': name,
            'carbs_per_100g': per100,
            'preparation_state': str(item.get('preparation_state', 'neuvedeno')),
            'source': 'private_book',
            'source_id': page_id,
            'source_detail': f'{page_id}: {vj:g} VJ = {mass:g} g',
            'source_url': f'/meal-ai/book/{page_id}',
            'warning': 'Soukromá fototabulka: kontroluj konkrétní řádek a stav přípravy. Přepis není klinicky ověřen.',
            'verified': False,
        })
    return foods


def book_suggestions(query: str, catalog: list[dict] | None = None, limit: int = 6) -> list[dict]:
    """No hidden substitution cooked <-> dry. Ambiguous matches stay visible."""
    q = normalize_name(query)
    if len(q) < 2:
        return []
    if catalog is None:
        catalog = load_book_catalog()
    cooking = {'varena', 'varene', 'vareny', 'varena dusena', 'dusena', 'smazene', 'smazena', 'pecene', 'pecena', 'syrova', 'syrove', 'syrovy'}
    q_tokens = set(q.split())
    q_prep = q_tokens.intersection(cooking)
    scored = []
    for food in catalog:
        n = normalize_name(food['name'])
        name_prep = set(n.split()).intersection(cooking)
        # Explicitly cooked food MUST NOT match generic raw/unspecified item.
        if q_prep and not (q_prep & name_prep):
            continue
        if n == q:
            score = 1.0
        elif n.startswith(q + ' ') or q.startswith(n + ' '):
            score = 0.87
        else:
            score = SequenceMatcher(None, q, n).ratio() * 0.83
        if score < 0.77:
            continue
        scored.append({**food, 'score': round(score, 3)})
    scored.sort(key=lambda x: (-x['score'], x['name']))
    return scored[:limit]


def _json_get(url: str, timeout: int = 12) -> dict:
    request = Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'DiabetesAssistantResearch/0.8 (local private test; product lookup)',
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read(1_500_001)
            if len(content) > 1_500_000:
                raise ValueError('Příliš velká odpověď databáze.')
    except HTTPError as exc:
        raise ValueError(f'Nutriční databáze odpověděla HTTP {exc.code}.') from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('Nutriční databáze je dočasně nedostupná.') from None
    return json.loads(content)


def parse_off_product(barcode: str, data: dict) -> dict:
    if data.get('status') not in (1, '1', 'success') or not isinstance(data.get('product'), dict):
        raise ValueError('Výrobek s tímto EAN nebyl nalezen.')
    product = data['product']
    value = (product.get('nutriments') or {}).get('carbohydrates_100g')
    if value is None:
        raise ValueError('Výrobek nemá údaj sacharidů na 100 g/ml.')
    carbs = finite_float(value, 0, 100)
    name = str(product.get('product_name_cs') or product.get('product_name') or 'Výrobek ' + barcode).strip()[:120]
    return {
        'name': name, 'carbs_per_100g': carbs,
        'source': 'open_food_facts', 'source_id': barcode,
        'source_url': f'https://world.openfoodfacts.org/product/{barcode}',
        'source_detail': f'Open Food Facts, kód {barcode}',
        'preparation_state': 'ověř konkrétní balení', 'score': 1,
        'warning': 'Komunitní záznam: ověř etiketu; u nápojů se údaj může vztahovat ke 100 ml.',
        'verified': False,
    }


def barcode_product(barcode: str) -> dict:
    if not re.fullmatch(r'\d{8,14}', barcode):
        raise ValueError('EAN/UPC musí mít 8 až 14 číslic.')
    query = urlencode({'fields': 'product_name,product_name_cs,nutriments'})
    return parse_off_product(barcode, _json_get(f'{OFF_URL}{barcode}?{query}'))


TRANSLATIONS = {
    'bramborovy salat': 'potato salad',
    'smazene maso': 'breaded cutlet',
    'kureci rizek': 'breaded chicken cutlet',
    'veprovy rizek': 'breaded pork cutlet',
    'ryze varena': 'cooked rice',
    'ryze varena dusena': 'cooked rice',
    'brambory varene': 'boiled potatoes',
    'testoviny varene': 'cooked pasta',
    'kuskus vareny': 'cooked couscous',
}


def parse_usda(data: dict) -> list[dict]:
    out = []
    for item in data.get('foods', [])[:8]:
        nutrient = next((f for f in item.get('foodNutrients', [])
                         if f.get('nutrientId') == 1005 or f.get('nutrientNumber') == '205'), None)
        if nutrient is None or nutrient.get('value') is None:
            continue
        try:
            carbs = finite_float(nutrient['value'], 0, 100)
        except ValueError:
            continue
        fdc_id = str(item.get('fdcId', ''))
        if not fdc_id.isdigit():
            continue
        out.append({
            'name': str(item.get('description', 'USDA potravina'))[:120],
            'carbs_per_100g': carbs,
            'source': 'usda', 'source_id': fdc_id,
            'source_url': 'https://fdc.nal.usda.gov/food-details/' + fdc_id + '/nutrients',
            'source_detail': 'USDA FDC ' + fdc_id,
            'preparation_state': str(item.get('dataType', 'neuvedeno')),
            'score': 0.45,
            'warning': 'USDA carbohydrate by difference může zahrnovat vlákninu. Nezaměňuj za CZ/EU sacharidy bez ověření; recepty se liší.',
            'verified': False,
        })
    return out[:4]


def nutrition_suggestions(name: str, book: list[dict] | None = None,
                          public: bool = True) -> dict:
    q = name.strip()
    if not 2 <= len(q) <= 100:
        raise ValueError('Zadej název potraviny (2–100 znaků).')
    private = book_suggestions(q, book)
    if private:
        return {'candidates': private, 'source': 'private_book', 'fallback_error': '',
                'requires_confirmation': True}
    if not public:
        return {'candidates': [], 'source': 'none', 'fallback_error': '', 'requires_confirmation': True}
    try:
        text = TRANSLATIONS.get(normalize_name(q), q)
        key = os.getenv('FDC_API_KEY', 'DEMO_KEY')
        url = USDA_URL + '?' + urlencode({'api_key': key, 'query': text, 'pageSize': 8})
        found = parse_usda(_json_get(url))
        return {'candidates': found, 'source': 'usda', 'fallback_error': '', 'requires_confirmation': True}
    except (ValueError, json.JSONDecodeError) as exc:
        return {'candidates': [], 'source': 'none', 'fallback_error': str(exc), 'requires_confirmation': True}


VISION_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'contains_food': {'type': 'boolean'},
        'items': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'name_cs': {'type': 'string'},
                'alternatives_cs': {'type': 'array', 'items': {'type': 'string'}},
                'portion_g_estimate': {'type': ['number', 'null']},
                'portion_min_g': {'type': ['number', 'null']},
                'portion_max_g': {'type': ['number', 'null']},
                'portion_confidence': {'type': 'string', 'enum': ['low', 'medium', 'high']},
                'uncertainty': {'type': 'string'},
            },
            'required': ['name_cs', 'alternatives_cs', 'portion_g_estimate', 'portion_min_g',
                         'portion_max_g', 'portion_confidence', 'uncertainty'],
        }},
        'question_for_user': {'type': 'string'},
    },
    'required': ['contains_food', 'items', 'question_for_user'],
}

VISION_PROMPT = (
    'Jsi VÝZKUMNÝ rozpoznávač jídla, česky, striktně podle JSON schématu. '
    'Z fotografie odděl potraviny a přílohy, odhadni přibližnou gramáž a rozmezí, '
    'ale přiznej velkou nejistotu. Pokud chybí měřítko, nedělej falešně přesné odhady. '
    'U nejasné položky nabídni nejvýše dvě skutečně pravděpodobné alternativy, '
    'například bramborový salát vs. těstovinový salát. '
    'Rozlišuj vařenou a suchou přílohu a neodhaduj skryté suroviny ani recepturu. '
    'Nikdy nepočítej sacharidy ani dávku inzulínu. Žádná další soukromá data nemáš.'
)


def prepare_photo(raw: bytes) -> str:
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError('Fotografie musí mít nejvýše 10 MB.')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('JPEG', 'PNG', 'WEBP') or im.width * im.height > 25_000_000:
                raise ValueError('Podporujeme JPG, PNG a WebP do 25 MP.')
            im = ImageOps.exif_transpose(im)
            im.thumbnail((1536, 1536))
            if im.mode == 'RGBA':
                canvas = Image.new('RGB', im.size, 'white')
                canvas.paste(im, mask=im.getchannel('A'))
                im = canvas
            else:
                im = im.convert('RGB')
            output = io.BytesIO()
            im.save(output, 'JPEG', quality=82)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError('Fotografii nelze přečíst.') from exc
    return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')


def vision_request(data_url: str, model: str = MODEL) -> dict:
    return {
        'model': model, 'store': False,
        'instructions': VISION_PROMPT,
        'input': [{'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'Popiš viditelné části jídla a nabídni přibližné hmotnosti.'},
            {'type': 'input_image', 'image_url': data_url, 'detail': 'high'},
        ]}],
        'text': {'format': {'type': 'json_schema', 'name': 'meal_ai_v8', 'strict': True, 'schema': VISION_SCHEMA}},
        'max_output_tokens': 1600,
    }


def parse_vision_response(data: dict) -> dict:
    if data.get('status') != 'completed':
        raise ValueError('Rozpoznání nebylo dokončeno.')
    texts = [part['text'] for message in data.get('output', []) if message.get('type') == 'message'
             for part in message.get('content', []) if part.get('type') == 'output_text' and isinstance(part.get('text'), str)]
    if not texts:
        raise ValueError('AI nevrátila odpověď.')
    parsed = json.loads('\n'.join(texts))
    foods = []
    for item in parsed.get('items', [])[:12]:
        name = str(item.get('name_cs') or '').strip()[:120]
        if len(name) < 2:
            continue
        alternatives = []
        for choice in item.get('alternatives_cs', [])[:6]:
            option = str(choice).strip()[:120]
            if len(option) >= 2 and normalize_name(option) not in {normalize_name(name), *[normalize_name(a) for a in alternatives]}:
                alternatives.append(option)
            if len(alternatives) >= 2:
                break
        def portion(value):
            try:
                return finite_float(value, 1, 3000)
            except ValueError:
                return None
        foods.append({
            'name_cs': name, 'alternatives_cs': alternatives,
            'portion_g_estimate': portion(item.get('portion_g_estimate')),
            'portion_min_g': portion(item.get('portion_min_g')),
            'portion_max_g': portion(item.get('portion_max_g')),
            'portion_confidence': item.get('portion_confidence') if item.get('portion_confidence') in ('low', 'medium', 'high') else 'low',
            'uncertainty': str(item.get('uncertainty') or '')[:250],
        })
    return {'contains_food': bool(parsed.get('contains_food')),
            'items': foods, 'question_for_user': str(parsed.get('question_for_user') or '')[:250]}


def analyze_photo(raw: bytes, api_key: str, model: str = MODEL) -> dict:
    data_url = prepare_photo(raw)
    request = Request(API_URL,
                      data=json.dumps(vision_request(data_url, model)).encode('utf-8'),
                      headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
                      method='POST')
    try:
        with urlopen(request, timeout=90) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise ValueError(f'Obrazové AI odmítlo požadavek: HTTP {exc.code}. Ověř klíč a kredit.') from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('Obrazové AI je dočasně nedostupné.') from None
    recognition = parse_vision_response(result)
    return {'recognition': recognition, 'model': model,
            'usage': {'input_tokens': (result.get('usage') or {}).get('input_tokens'),
                      'output_tokens': (result.get('usage') or {}).get('output_tokens')}}
