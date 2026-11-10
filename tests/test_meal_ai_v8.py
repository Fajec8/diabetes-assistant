"""All tests are local and must not contact paid AI or remote nutrition APIs."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.services import meal_ai_v8 as svc
from app.routers import meal_ai_v8 as route
from scripts.install_meal_ai_v8 import modify_files


def test_catalog_private_and_preparation_state():
    rows = svc.load_book_catalog()
    assert len(rows) >= 80
    assert all(r['source'] == 'private_book' and r['verified'] is False for r in rows)
    assert {'IMG_0177', 'IMG_0178', 'IMG_0180', 'IMG_0188'}.issubset({r['source_id'] for r in rows})
    cooked = svc.book_suggestions('rýže vařená', rows)
    assert cooked and cooked[0]['name'].startswith('rýže vařená')
    assert cooked[0]['carbs_per_100g'] == 20
    assert all('vařen' in r['name'] for r in cooked)


def test_book_first_no_external_call(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected paid or public network call')
    monkeypatch.setattr(svc, '_json_get', forbidden)
    result = svc.nutrition_suggestions('bramborový salát')
    assert result['source'] == 'private_book'
    assert result['candidates'][0]['carbs_per_100g'] == 13.33
    assert result['requires_confirmation']


def test_no_book_match_does_not_invent_value(monkeypatch):
    monkeypatch.setattr(svc, '_json_get', lambda url: {'foods': []})
    result = svc.nutrition_suggestions('velmi neznámý pokrm')
    assert result['candidates'] == []


def test_raw_rice_never_auto_claimed_as_cooked():
    rows = svc.load_book_catalog()
    matches = svc.book_suggestions('rýže vařená, dušená', rows)
    assert matches and matches[0]['carbs_per_100g'] == 20
    assert not any(row['name'].strip() == 'rýže' for row in matches)


def test_math_and_validation():
    assert svc.carbs_from_portion(200, 20) == 40
    assert svc.carbs_from_portion(300, 13) == 39
    with pytest.raises(ValueError):
        svc.carbs_from_portion(0, 20)
    with pytest.raises(ValueError):
        svc.carbs_from_portion(float('nan'), 20)
    with pytest.raises(ValueError):
        svc.carbs_from_portion(100, 150)


def test_ean_v2_and_missing_nutrients():
    d = {'status': 1, 'product': {'product_name_cs': 'Jogurt', 'nutriments': {'carbohydrates_100g': 12.4}}}
    row = svc.parse_off_product('8591234567890', d)
    assert row['carbs_per_100g'] == 12.4
    assert row['source'] == 'open_food_facts'
    assert 'EAN' not in row['source_detail'] or '8591234567890' in row['source_detail']
    with pytest.raises(ValueError):
        svc.parse_off_product('8591234567890', {'status': 1, 'product': {'nutriments': {}}})


def test_invalid_barcode_not_sent(monkeypatch):
    monkeypatch.setattr(svc, '_json_get', lambda *args: (_ for _ in ()).throw(AssertionError('called')))
    with pytest.raises(ValueError):
        svc.barcode_product('https://evil.example/path')
    with pytest.raises(ValueError):
        svc.barcode_product('abc')


def test_vision_schema_and_store_false():
    payload = svc.vision_request('data:image/jpeg;base64,TEST')
    assert payload['store'] is False
    assert payload['text']['format']['strict'] is True
    assert payload['input'][0]['content'][1]['detail'] == 'high'
    assert 'sacharidy' in payload['instructions']


def test_vision_parsing_alternatives_and_portion():
    answer = {'contains_food': True, 'question_for_user': 'Jaká je příloha?',
              'items': [{'name_cs': 'salátová směs', 'alternatives_cs': ['bramborový salát', 'těstovinový salát', 'rizoto'],
                         'portion_g_estimate': 200, 'portion_min_g': 120, 'portion_max_g': 350,
                         'portion_confidence': 'low', 'uncertainty': 'Bez váhy'}]}
    response = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(answer)}]}]}
    parsed = svc.parse_vision_response(response)
    assert len(parsed['items'][0]['alternatives_cs']) == 2
    assert parsed['items'][0]['portion_g_estimate'] == 200
    assert parsed['question_for_user']


def test_photo_strips_metadata_and_bounds():
    image = io.BytesIO()
    Image.new('RGB', (128, 128), 'blue').save(image, format='PNG')
    assert svc.prepare_photo(image.getvalue()).startswith('data:image/jpeg;base64,')
    with pytest.raises(ValueError):
        svc.prepare_photo(b'invalid')
    with pytest.raises(ValueError):
        svc.prepare_photo(b'a' * (svc.MAX_UPLOAD_BYTES + 1))


def client():
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def test_router_status_is_local():
    with client() as c:
        result = c.get('/meal-ai/api/status')
        assert result.status_code == 200
        assert result.json()['book_entries'] >= 80
        html = c.get('/meal-ai')
        assert html.status_code == 200
        assert 'EAN' in html.text and 'manualCarbs' in html.text
        banned = c.get('/meal-ai/api/status', headers={'host': 'prod.onrender.com'})
        assert banned.status_code == 403


def test_public_routes_no_remote_access():
    with client() as c:
        response = c.post('/meal-ai/api/analyze', data=b'not a photo', headers={'host': 'prod.onrender.com'})
        assert response.status_code == 403
        origin = c.post('/meal-ai/api/analyze', data=b'not a photo', headers={'origin':'https://malicious.example'})
        assert origin.status_code == 403


def test_router_ean_mocked(monkeypatch):
    monkeypatch.setattr(route.core, 'barcode_product', lambda code: {'name': 'Výrobek', 'carbs_per_100g': 10.0})
    with client() as c:
        assert c.get('/meal-ai/api/ean/8591234567890').json()['name'] == 'Výrobek'
        assert c.get('/meal-ai/api/ean/foobar').status_code == 422


def test_html_never_autosubmits_shadow_and_uses_same_origin():
    html = (Path(__file__).resolve().parents[1] / 'app/static/meal_ai_v8.html').read_text(encoding='utf-8')
    assert 'window.location.origin' in html
    assert 'diabetes-assistant-meal-v8' in html
    assert 'BarcodeDetector' in html
    assert '/decision-sessions' not in html


def test_installer_has_inert_feature_flag():
    readme = Path(__file__).resolve().parents[1] / 'scripts/install_meal_ai_v8.py'
    s = readme.read_text(encoding='utf-8')
    assert 'MEAL_AI_V8_LOCAL' in s
    assert 'shutil.copy2' in s
    assert 'mealAiItems' in s


def test_usda_missing_value_is_not_assumed_zero():
    assert svc.parse_usda({'foods': [{'fdcId': 456, 'description':'Food', 'foodNutrients': []}]}) == []
    row = svc.parse_usda({'foods': [{'fdcId': 456, 'description':'Food', 'foodNutrients': [{'nutrientId':1005, 'value': 20.1}]}]})
    assert row[0]['warning'] and row[0]['verified'] is False


def test_render_forbidden_even_when_host_is_loopback(monkeypatch):
    monkeypatch.setenv('RENDER','true')
    with client() as c:
        assert c.get('/meal-ai/api/status').status_code == 403


def test_installer_exact_anchor_and_idempotence():
    from scripts.install_meal_ai_v8 import modify_files
    base_main='app.include_router(\n    dexcom_router\n)\n'
    base_shadow='''<style></style><div>
            </div>
        </div>

        <hr class="separator">

        <h3>NovoRapid podaný před touto situací</h3>
<input id="mealCarbs" type="number" inputmode="decimal" min="0" step="1"
</div>
<script>
function clearForms() {
}
const carbs=22; const plannedMeal={
                items: []
            };
byId("decisionAt").value = localDateTimeValue();
restoreSameDayContext();
updateMealFields();
</script>'''
    main,shadow = modify_files(base_main, base_shadow)
    assert 'MEAL_AI_V8_LOCAL_INTEGRATION' in main
    assert 'mealAiFrame' in shadow and 'mealAiItems' in shadow
    assert modify_files(main,shadow) == (main,shadow)
    with pytest.raises(RuntimeError):
        modify_files(base_main, base_shadow.replace('items: []','items: not_allowed'))
