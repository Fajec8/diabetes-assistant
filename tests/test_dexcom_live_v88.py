"""Offline tests. No Dexcom requests, no real passwords, no patient data."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import dexcom_live_v88 as route
from app.routers import meal_ai_v8
from app.services import dexcom_share_live_v88 as live

SECRET = 'v88-test-only-' + 'Z' * 34


def app_client():
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def enable_beta(monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('MEAL_AI_BETA', '1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN', SECRET)


def auth_headers():
    cookie = meal_ai_v8._session_cookie_value(SECRET)
    return {'Cookie': 'meal_ai_beta_session=' + cookie}


def sample_record(now, mins, value=126):
    when = now - timedelta(minutes=mins)
    class Reading:
        pass
    obj = Reading()
    obj.value = value
    obj.json = {'ST': 'Date(' + str(int(when.timestamp() * 1000)) + ')'}
    obj.trend_direction = 'Flat'
    obj.trend_arrow = '→'
    return obj


def test_anonymous_request_denied_without_calling_upstream(monkeypatch):
    enable_beta(monkeypatch)
    monkeypatch.setenv('DEXCOM_SHARE_ENABLED', '1')
    monkeypatch.setenv('DEXCOM_SHARE_USERNAME', 'example@example.invalid')
    monkeypatch.setenv('DEXCOM_SHARE_PASSWORD', 'dummy')
    monkeypatch.setattr(live, 'get_snapshot', lambda: pytest.fail('Network called before auth'))
    with app_client() as c:
        assert c.get('/meal-ai/api/live-dexcom').status_code == 401
        page = c.get('/meal-ai/live-dexcom')
        assert page.status_code == 200  # the public HTML shell
        assert '/meal-ai/api/live-dexcom' in page.text
        assert 'dummy' not in page.text  # no credentials in HTML


def test_private_cookie_can_read_only_configured_data(monkeypatch):
    enable_beta(monkeypatch)
    monkeypatch.setenv('DEXCOM_SHARE_ENABLED', '1')
    monkeypatch.setenv('DEXCOM_SHARE_USERNAME', 'example@example.invalid')
    monkeypatch.setenv('DEXCOM_SHARE_PASSWORD', 'dummy')
    now = datetime.now(timezone.utc)
    data = live._normalize_reading(sample_record(now, 5), now)
    monkeypatch.setattr(live, 'get_snapshot', lambda: {'available': True, 'latest': data})
    with app_client() as c:
        response = c.get('/meal-ai/api/live-dexcom', headers=auth_headers())
        assert response.status_code == 200
        assert response.json()['latest']['value_mmol_l'] == 7.0
        assert 'dummy' not in response.text
        assert c.get('/meal-ai/live-dexcom', headers=auth_headers()).status_code == 200


def test_cross_origin_denied_even_with_cookie(monkeypatch):
    enable_beta(monkeypatch)
    with app_client() as c:
        response = c.get('/meal-ai/api/live-dexcom', headers={**auth_headers(), 'Origin':'https://evil.invalid'})
    assert response.status_code == 403


def test_not_configured_fails_closed(monkeypatch):
    enable_beta(monkeypatch)
    monkeypatch.delenv('DEXCOM_SHARE_USERNAME', raising=False)
    with app_client() as c:
        assert c.get('/meal-ai/api/live-dexcom', headers=auth_headers()).status_code == 503


def test_normalized_timestamp_and_units(monkeypatch):
    now = datetime.now(timezone.utc)
    result = live._normalize_reading(sample_record(now, 4, 90), now)
    assert result['value_mg_dl'] == 90
    assert result['value_mmol_l'] == 5.0
    assert result['trend_arrow'] == '→'
    assert abs((datetime.fromisoformat(result['system_time'])-now).total_seconds() + 240) < 1


def test_unknown_timestamp_or_unsafe_value_never_fabricated():
    now = datetime.now(timezone.utc)
    class Bad:
        value = 2500
        json = {}
        datetime = datetime(2026, 1, 1)  # naive timezone ambiguous
    assert live._normalize_reading(Bad(), now) is None
    b = sample_record(now, 5, 2500)
    assert live._normalize_reading(b, now) is None


def test_freshness_and_historical_values(monkeypatch):
    now = datetime.now(timezone.utc)
    samples = [sample_record(now, minutes, 108 + minutes) for minutes in (2,17,32,62)]
    class Fake:
        def get_glucose_readings(self, max_count, minutes):
            assert 1 <= max_count <= 20 and 60 <= minutes <= 100
            return samples
    monkeypatch.setattr(live, '_get_client', lambda: Fake())
    payload = live._uncached_snapshot(now)
    assert payload['available']
    assert payload['fresh']
    assert payload['history']['15']['value_mg_dl'] == 125
    assert payload['history']['30']['value_mg_dl'] == 140
    assert payload['history']['60']['value_mg_dl'] == 170
    assert len(payload['readings']) == 4


def test_stale_readings_cannot_claim_fresh(monkeypatch):
    now = datetime.now(timezone.utc)
    class Fake:
        def get_glucose_readings(self, **kwargs):
            return [sample_record(now, 35)]
    monkeypatch.setattr(live, '_get_client', lambda: Fake())
    assert live._uncached_snapshot(now)['fresh'] is False


def test_no_records_do_not_create_fake_glucose(monkeypatch):
    class Fake:
        def get_glucose_readings(self, **kwargs):
            return []
    monkeypatch.setattr(live, '_get_client', lambda: Fake())
    data = live._uncached_snapshot(datetime.now(timezone.utc))
    assert data['available'] is False
    assert data['latest'] is None


def test_cached_fetch_only_once(monkeypatch):
    monkeypatch.setenv('DEXCOM_SHARE_ENABLED', '1')
    monkeypatch.setenv('DEXCOM_SHARE_USERNAME', 'example')
    monkeypatch.setenv('DEXCOM_SHARE_PASSWORD', 'dummy')
    monkeypatch.setenv('DEXCOM_SHARE_REGION', 'ous')
    calls = []
    now = datetime.now(timezone.utc)
    def fake(now_arg):
        calls.append(now_arg)
        latest = live._normalize_reading(sample_record(now, 2), now_arg)
        return {'available': True, 'latest': latest, 'fresh': True, 'age_minutes': 2}
    monkeypatch.setattr(live, '_uncached_snapshot', fake)
    monkeypatch.setattr(live, '_cached_snapshot', None)
    live.get_snapshot();live.get_snapshot()
    assert len(calls) == 1


def test_project_ui_does_not_auto_dose_or_copy_reading_to_shadow():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    page = (root/'app/static/dexcom_live_v88.html').read_text('utf-8')
    assert '/meal-ai/api/live-dexcom' in page
    assert 'setInterval' in page
    assert 'Pouze zobrazení' in page
    assert 'postMessage(' not in page
    assert '/decision-sessions' not in (root/'app/routers/dexcom_live_v88.py').read_text('utf-8')
