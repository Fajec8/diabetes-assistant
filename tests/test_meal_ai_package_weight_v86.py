"""Meal AI V8.6: test known packaging weight; offline, no OpenAI calls."""
from pathlib import Path
import pytest
from app.services import meal_ai_v8 as svc

EAN = '8594033402358'

def product(q=None, unit=None, text=None, carbs=12.4, serving=None):
    p = {'product_name_cs':'Jogurt', 'nutriments':{'carbohydrates_100g': carbs}}
    if q is not None:p['product_quantity'] = q
    if unit is not None:p['product_quantity_unit'] = unit
    if text is not None:p['quantity'] = text
    if serving is not None:p['serving_size'] = serving
    return p

@pytest.mark.parametrize('data,expected', [
    (product(150,'g','150 g'),150.0),
    (product('150','g'),150.0),
    (product('0,15','kg'),150.0),
    (product(text='150g'),150.0),
    (product(text='0,15 kg'),150.0),
    (product(text='150 g ℮'),150.0),
    (product(200,'g','200 g',serving='50 g'),200.0),
    (product(150,'ml','150 ml'),None),
    (product(text='150 ml'),None),
    (product(500,'g','4 x 125 g'),None),
    (product(500,'g','4×125g'),None),
    (product(serving='150 g'),None),
    (product(10000,'g'),None),
    (product(-100,'g'),None),
    (product('nan','g'),None),
    (product(True,'g'),None),
    (product(text='100 g + 50 g'),None),
    (product(150,None,'150 g'),150.0),
    (product(150,'ml','150 g'),None),
    (product(500,'g','150 g'),None),
    (product(150,'g','150 ml'),None),
])
def test_only_explicit_single_package_mass(data, expected):
    assert svc._off_package_weight_g(data) == expected


def test_known_product_package_autofill(monkeypatch):
    def fake_get(url):
        assert 'product_quantity' in url and 'product_quantity_unit' in url and 'quantity' in url
        return {'status':1,'product':product(150,'g','150 g')}
    monkeypatch.setattr(svc,'_json_get',fake_get)
    data = svc.barcode_product(EAN)
    assert data['carbs_per_100g'] == 12.4
    assert data['package_weight_g'] == 150
    assert data['package_quantity'] == '150 g'
    assert data['verified'] is False


def test_off_fallback_keeps_verified_package_size_but_not_carbs(monkeypatch):
    p = product(150,'g','150 g')
    p['nutriments'] = {}
    monkeypatch.setattr(svc,'_json_get',lambda url: {'status':1,'product':p})
    result=svc.barcode_product(EAN)
    assert result['requires_manual'] is True
    assert result['package_weight_g'] == 150
    assert result['carbs_per_100g'] is None
    assert result['source_detail'] == ''


def test_missing_off_record_never_invents_weight(monkeypatch):
    monkeypatch.setattr(svc,'_json_get',lambda url: {'status':0})
    result=svc.barcode_product(EAN)
    assert result['package_weight_g'] is None
    assert result['carbs_per_100g'] is None


def test_other_types_do_not_use_serving_or_ml():
    assert svc._off_package_weight_g(product(150,'ml','150 ml',serving='150 g')) is None
    assert svc._off_package_weight_g(product(serving='150g')) is None


def test_frontend_binds_off_weight_to_portion_and_warns():
    html=(Path(__file__).resolve().parents[1]/'app/static/meal_ai_v8.html').read_text('utf-8-sig')
    assert 'MEAL_AI_V86_PACKAGE_WEIGHT' in html
    assert "portion:data.package_weight_g??''" in html
    assert 'packageWeightG:data.package_weight_g??null' in html
    assert 'Předvyplněná hmotnost CELÉHO balení' in html
    assert 'Pokud nesníš celé balení' in html
    assert 'item.portion=portion.value' in html
    assert 'state.items.push(newItem(data.name' in html
    assert 'needsLabelEntry:missing' in html
