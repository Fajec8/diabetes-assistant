"""Offline regression tests for secure, optional 14-day Meal AI beta sign-in.

No internet, private patient data or paid OpenAI request is needed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import meal_ai_v8 as routes

SECRET = 'v87-test-secret-' + 'A' * 40


@pytest.fixture(autouse=True)
def beta(monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('MEAL_AI_BETA', '1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN', SECRET)


def client() -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    # HTTPS because Secure cookies are intentionally never sent over HTTP.
    return TestClient(app, base_url='https://testserver')


def login(c: TestClient, remember: bool = True):
    return c.post('/meal-ai/api/session?remember=' + ('1' if remember else '0'),
                  headers={'Authorization': 'Bearer ' + SECRET})


def test_anonymous_cannot_access_private_apis_or_create_cookie():
    with client() as c:
        r = c.get('/meal-ai/api/session')
        assert r.status_code == 200
        assert r.json()['authenticated'] is False
        assert SECRET not in r.text
        assert c.get('/meal-ai/api/nutrition?name=jogurt').status_code == 401
        r = c.post('/meal-ai/api/session?remember=1')
        assert r.status_code == 401
        assert 'set-cookie' not in r.headers


def test_remember_session_has_secure_cookie_and_access(monkeypatch):
    monkeypatch.setattr(routes.core, 'nutrition_suggestions',
                        lambda name, book, public: {'candidates': [], 'source': name})
    with client() as c:
        r = login(c)
        assert r.status_code == 200
        assert r.json() == {'authenticated': True, 'remembered': True, 'remember_days': 14}
        cookie = r.headers['set-cookie']
        assert 'meal_ai_beta_session=' in cookie
        assert 'httponly' in cookie.lower()
        assert 'secure' in cookie.lower()
        assert 'samesite=strict' in cookie.lower()
        assert 'path=/meal-ai' in cookie.lower()
        assert 'max-age=1209600' in cookie.lower()
        assert SECRET not in cookie
        assert c.get('/meal-ai/api/session').json()['authenticated'] is True
        r = c.get('/meal-ai/api/nutrition?name=jogurt')
        assert r.status_code == 200 and r.json()['source'] == 'jogurt'


def test_session_only_has_no_persistent_max_age():
    with client() as c:
        r = login(c, remember=False)
        assert r.status_code == 200
        assert r.json()['remembered'] is False
        assert 'max-age=' not in r.headers['set-cookie'].lower()
        assert c.get('/meal-ai/api/session').json()['authenticated'] is True


def test_wrong_bearer_cannot_create_remembered_session():
    with client() as c:
        r = c.post('/meal-ai/api/session?remember=1',
                   headers={'Authorization': 'Bearer wrong-code-' + 'X' * 40})
        assert r.status_code == 401
        assert 'set-cookie' not in r.headers
        assert c.get('/meal-ai/api/session').json()['authenticated'] is False


def test_logout_revokes_browser_cookie():
    with client() as c:
        assert login(c).status_code == 200
        assert c.get('/meal-ai/api/session').json()['authenticated'] is True
        out = c.post('/meal-ai/api/session/logout')
        assert out.status_code == 200
        assert out.json()['authenticated'] is False
        assert c.get('/meal-ai/api/session').json()['authenticated'] is False
        assert c.get('/meal-ai/api/nutrition?name=jogurt').status_code == 401


def test_token_rotation_invalidates_existing_cookies(monkeypatch):
    with client() as c:
        assert login(c).status_code == 200
        monkeypatch.setenv('MEAL_AI_BETA_TOKEN', 'R' * 45)
        assert c.get('/meal-ai/api/session').json()['authenticated'] is False
        assert c.get('/meal-ai/api/nutrition?name=jogurt').status_code == 401


def test_signed_cookie_expires_after_14_days(monkeypatch):
    tick = [1_800_000_000]
    monkeypatch.setattr(routes.time, 'time', lambda: tick[0])
    with client() as c:
        assert login(c).status_code == 200
        assert c.get('/meal-ai/api/session').json()['authenticated'] is True
        # Cookie may be removed by client-side expiry. Either way the server rejects it.
        tick[0] += routes.SESSION_SECONDS + 10
        assert c.get('/meal-ai/api/session').json()['authenticated'] is False


def test_signed_cookie_cannot_be_tampered_with():
    with client() as c:
        assert login(c).status_code == 200
        raw = c.cookies['meal_ai_beta_session']

    tampered = raw[:-1] + ('A' if raw[-1] != 'A' else 'B')
    assert tampered != raw
    assert not routes._valid_session_cookie(tampered, SECRET)

    # Fresh client avoids competing valid cookies in the cookie jar.
    with client() as stranger:
        headers = {'Cookie': 'meal_ai_beta_session=' + tampered}
        assert stranger.get('/meal-ai/api/session', headers=headers).json()['authenticated'] is False
        assert stranger.get('/meal-ai/api/nutrition?name=jogurt', headers=headers).status_code == 401


def test_foreign_origin_does_not_gain_session_or_access():
    with client() as c:
        bad = c.post('/meal-ai/api/session?remember=1',
                     headers={'Authorization': 'Bearer ' + SECRET,
                              'Origin': 'https://evil.example'})
        assert bad.status_code == 403
        assert login(c).status_code == 200
        assert c.get('/meal-ai/api/nutrition?name=jogurt',
                     headers={'Origin': 'https://evil.example'}).status_code == 403


def test_ui_keeps_beta_secret_out_of_local_storage():
    html = (Path(__file__).resolve().parents[1] / 'app/static/meal_ai_v8.html').read_text(encoding='utf-8-sig')
    assert 'MEAL_AI_V87_SECURE_DEVICE_SESSION_UI' in html
    assert 'mealBetaRemember' in html
    assert 'mealBetaLogout' in html
    assert 'localStorage.setItem' not in html
    assert 'sessionStorage.setItem(betaSessionKey' not in html
    assert 'Authorization' in html and 'Bearer ' in html
    assert 'diabetes-assistant-meal-v8' in html
