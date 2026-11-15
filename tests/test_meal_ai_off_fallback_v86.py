"""Local tests for missing products in Open Food Facts. No external API calls."""
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services import meal_ai_v8 as svc
from app.routers import meal_ai_v8 as routes

EAN = '8594033402358'


def test_missing_product_http_404_is_editable(monkeypatch):
    def not_found(url):
        raise ValueError('Nutriční databáze odpověděla HTTP 404.')
    monkeypatch.setattr(svc, '_json_get', not_found)
    row = svc.barcode_product(EAN)
    assert row['requires_manual'] is True
    assert row['found'] is False
    assert row['code'] == EAN
    assert row['carbs_per_100g'] is None
    assert row['source_detail'] == ''
    assert row['verified'] is False


def test_product_status_zero_is_editable(monkeypatch):
    monkeypatch.setattr(svc, '_json_get', lambda url: {'status': 0})
    row = svc.barcode_product(EAN)
    assert row['requires_manual'] and row['carbs_per_100g'] is None


def test_missing_carbs_retains_product_name(monkeypatch):
    monkeypatch.setattr(svc, '_json_get', lambda url: {
        'status': 1, 'product': {'product_name_cs': 'Jahodový jogurt', 'nutriments': {}}
    })
    row = svc.barcode_product(EAN)
    assert row['requires_manual'] and row['name'] == 'Jahodový jogurt'
    assert row['carbs_per_100g'] is None


def test_other_database_errors_not_hidden(monkeypatch):
    def server_error(url):
        raise ValueError('Nutriční databáze odpověděla HTTP 503.')
    monkeypatch.setattr(svc, '_json_get', server_error)
    with pytest.raises(ValueError, match='HTTP 503'):
        svc.barcode_product(EAN)


def test_existing_product_unchanged(monkeypatch):
    monkeypatch.setattr(svc, '_json_get', lambda url: {
        'status': 1, 'product': {'product_name_cs': 'Jogurt',
                                 'nutriments': {'carbohydrates_100g': 12.4}}
    })
    row = svc.barcode_product(EAN)
    assert row['name'] == 'Jogurt'
    assert row['carbs_per_100g'] == 12.4
    assert not row.get('requires_manual', False)


def test_ean_router_returns_pending_http_200(monkeypatch):
    monkeypatch.setattr(svc, '_json_get', lambda url: {'status': 0})
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.get('/meal-ai/api/ean/' + EAN)
    assert response.status_code == 200
    assert response.json()['requires_manual'] is True


def test_combined_meal_keeps_missing_ean_editable():
    html = (Path(__file__).resolve().parents[1] / 'app/static/meal_ai_v8.html').read_text(encoding='utf-8-sig')
    assert 'MEAL_AI_V85_COMBINED_MEAL' in html
    assert 'MEAL_AI_V86_OFF_MANUAL_FALLBACK' in html
    assert 'state.items.push(newItem(data.name||' in html
    assert 'needsLabelEntry:missing' in html
    assert 'if(item.needsLabelEntry)edit.open=true' in html
    assert 'state.items.push(...recognized)' in html
    assert 'state.items=[];renderFoods();invalidate();' not in html
    assert 'carbs_per_100g' in html
