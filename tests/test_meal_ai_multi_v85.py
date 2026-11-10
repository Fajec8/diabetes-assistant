"""Static regression guards for combined Meal AI V8.5 workflow.

No public API, image analysis or paid AI call in these tests.
"""
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / 'app' / 'static' / 'meal_ai_v8.html'


def test_shared_basket_and_photo_append():
    page = HTML.read_text(encoding='utf-8-sig')
    assert 'MEAL_AI_V85_COMBINED_MEAL' in page
    assert 'state.items.push(...recognized)' in page
    assert 'for(const item of recognized)lookupFood(item)' in page
    assert 'state.items=data.recognition.items.map(' not in page
    assert 'state.items=[];renderFoods();invalidate();' not in page
    assert '$("recognizedSection").hidden=false' in page


def test_manual_added_to_same_basket():
    page = HTML.read_text(encoding='utf-8-sig')
    assert 'id="manualAdd"' in page
    assert 'manual:true,manualCarbs:String(carbs)' in page
    assert 'if(item.manual)' in page
    assert 'state.items.push(newItem(data.name,' in page  # barcode product addition
    assert 'state.items.map(item=>' in page  # combined submit
    assert 'diabetes-assistant-meal-v8' in page
    assert 'window.location.origin' in page


def test_no_shadow_or_api_changed():
    page = HTML.read_text(encoding='utf-8-sig')
    assert '/decision-sessions' not in page
    assert 'api/analyze' in page
    assert 'api/ean' in page
    assert 'api/scan-ean' in page
    assert 'window.confirm(' in page
