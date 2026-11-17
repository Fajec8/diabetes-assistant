"""Offline, isolated tests. Never call Dexcom Share or expose patient readings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.services import dexcom_outcome_v90 as outcome
from app.services import dexcom_share_live_v88 as live
from app.routers import dexcom_live_v88 as router
from app.routers import meal_ai_v8

TOKEN = 'test-only-secure-token-' + 'Q' * 36


def enable_beta(monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('MEAL_AI_BETA', '1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN', TOKEN)
    monkeypatch.setenv('DEXCOM_SHARE_ENABLED', '1')
    monkeypatch.setenv('DEXCOM_SHARE_USERNAME', 'fake@example.invalid')
    monkeypatch.setenv('DEXCOM_SHARE_PASSWORD', 'dummy')
    monkeypatch.setenv('DEXCOM_SHARE_REGION', 'ous')


def client():
    app = FastAPI()
    app.include_router(router.router)
    return TestClient(app)


def cookie():
    return {'Cookie': 'meal_ai_beta_session=' + meal_ai_v8._session_cookie_value(TOKEN)}


class FakeReading:
    def __init__(self, at: datetime, value=126):
        self.value = value
        self.json = {'ST': 'Date(' + str(int(at.timestamp() * 1000)) + ')'}
        self.trend_arrow = '→'
        self.trend_direction = 'Flat'


def fake_share(monkeypatch, rows, call_history):
    class FakeClient:
        def get_glucose_readings(self, minutes, max_count):
            call_history.append((minutes, max_count))
            return rows
    monkeypatch.setattr(live, '_get_client', lambda: FakeClient())


def test_matching_five_horizons_and_window_over_90_minutes(monkeypatch):
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=188)
    rows = [FakeReading(start + timedelta(minutes=h), 100+h//5) for h in outcome.HORIZONS]
    calls = []
    fake_share(monkeypatch, rows, calls)
    monkeypatch.setenv('DEXCOM_SHARE_ENABLED', '1')
    monkeypatch.setenv('DEXCOM_SHARE_USERNAME', 'fake')
    monkeypatch.setenv('DEXCOM_SHARE_PASSWORD', 'fake')
    data = outcome.get_outcome_snapshot(start.isoformat())
    assert data['matched_count'] == 5
    assert set(data['fields']) == {'30','60','90','120','180'}
    assert data['fields']['180']['value_mmol_l'] == round(136/18, 1)
    assert calls[0][0] >= 210 and calls[0][1] > 20
    assert 'rows' not in data and 'password' not in repr(data).lower()


def test_future_horizons_not_fabricated(monkeypatch):
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=64)
    rows = [FakeReading(start + timedelta(minutes=h)) for h in (30,60)]
    calls = []
    fake_share(monkeypatch, rows, calls)
    monkeypatch.setenv('DEXCOM_SHARE_ENABLED', '1')
    monkeypatch.setenv('DEXCOM_SHARE_USERNAME', 'fake')
    monkeypatch.setenv('DEXCOM_SHARE_PASSWORD', 'fake')
    data = outcome.get_outcome_snapshot(start.isoformat())
    assert data['fields']['30'] is not None
    assert data['fields']['60'] is not None
    assert all(data['fields'][str(h)] is None for h in (90,120,180))


def test_nearest_within_six_minutes_not_from_wrong_horizon():
    now = datetime.now(timezone.utc)
    target = now - timedelta(minutes=25)
    row = {'system_time': (target + timedelta(minutes=5)).isoformat(), 'value_mmol_l': 6.2}
    assert outcome._nearest([row], target, now)['value_mmol_l'] == 6.2
    row['system_time'] = (target + timedelta(minutes=7)).isoformat()
    assert outcome._nearest([row], target, now) is None
    assert outcome._nearest([row], now + timedelta(minutes=30), now) is None


def test_invalid_dates_rejected_before_upstream(monkeypatch):
    now = datetime.now(timezone.utc)
    for value in ('2026-11-17T10:00:00', 'not-a-time',
                  (now - timedelta(hours=24)).isoformat(),
                  (now + timedelta(hours=1)).isoformat()):
        with pytest.raises(ValueError):
            outcome._parse_decision_at(value, now)


def test_anonymous_outcome_endpoint_denied(monkeypatch):
    enable_beta(monkeypatch)
    monkeypatch.setattr(outcome, 'get_outcome_snapshot', lambda *_: pytest.fail('Unauthenticated upstream call'))
    with client() as c:
        r = c.post('/meal-ai/api/live-dexcom/outcome', json={'decision_at': datetime.now(timezone.utc).isoformat()})
    assert r.status_code == 401


def test_authenticated_lookup_only_returns_five_fields(monkeypatch):
    enable_beta(monkeypatch)
    called = []
    def fake(when):
        called.append(when)
        return {'source': 'dexcom_share_unofficial','matched_count': 0,
                'fields': {str(h): None for h in outcome.HORIZONS}}
    monkeypatch.setattr(outcome, 'get_outcome_snapshot', fake)
    moment = datetime.now(timezone.utc).isoformat()
    with client() as c:
        resp = c.post('/meal-ai/api/live-dexcom/outcome', json={'decision_at': moment}, headers=cookie())
    assert resp.status_code == 200
    assert called == [moment]
    assert len(resp.json()['fields']) == 5
    assert resp.headers.get('cache-control') == 'no-store'


def test_malformed_request_and_cross_origin_denied(monkeypatch):
    enable_beta(monkeypatch)
    with client() as c:
        assert c.post('/meal-ai/api/live-dexcom/outcome', json={'decision_at': 42}, headers=cookie()).status_code == 400
        assert c.post('/meal-ai/api/live-dexcom/outcome', data='x'*600, headers=cookie()).status_code == 400
        assert c.post('/meal-ai/api/live-dexcom/outcome', json={'decision_at': datetime.now(timezone.utc).isoformat()},
                      headers={**cookie(), 'Origin': 'https://evil.invalid'}).status_code == 403


def test_frontend_opt_in_only_and_overlapping_session_guards():
    text = (Path(__file__).resolve().parents[1] / 'app/static/shadow.html').read_text('utf-8-sig')
    assert text.count('id="dexcomOutcomeV90"') == 1
    assert 'id="dexcomOutcomeV90Fetch"' in text
    assert 'id="dexcomOutcomeV90Apply"' in text
    js = text.split('// DEXCOM_OUTCOME_V90:',1)[1].split('// DEXCOM_LIVE_V89_SHADOW_BRIDGE',1)[0]
    before = js.split('async function dexcomOutcomeV90Apply()',1)[0]
    assert 'byId(edit.id).value' not in before
    assert 'session.status !== "WAITING_OUTCOME"' in js
    assert 'reading.targetMs >= nextMs' in js
    assert 'byId(id).disabled' in js
    assert 'Date.parse(session.decision_at)' in js
    assert 'Math.abs(when - targetMs) > 6 * 60000' in js
    assert 'for (const edit of edits) byId(edit.id).value = edit.value' in js
    assert 'saveOutcome(' not in js
    assert 'baseline").value' not in js
    assert 'insulin' not in js.lower().replace('no insulin logic', '')
