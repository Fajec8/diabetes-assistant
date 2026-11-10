"""Offline checks for the single-user token-guarded Render beta."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import meal_ai_v8 as routes
from app.services import meal_ai_v8 as svc
from scripts.prepare_meal_ai_render_beta import change

SECRET = 'test-only-0123456789abcdefghijklmnopqrstuvwxyz'


def client():
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def enable_beta(monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('MEAL_AI_BETA', '1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN', SECRET)


def test_beta_fail_closed_without_long_token(monkeypatch):
    monkeypatch.setenv('RENDER','true')
    monkeypatch.setenv('MEAL_AI_BETA','1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN','short')
    with client() as c:
        assert c.get('/meal-ai/api/status').status_code == 503
        assert c.get('/meal-ai').status_code == 503


def test_beta_no_anonymous_api_access(monkeypatch):
    enable_beta(monkeypatch)
    with client() as c:
        status = c.get('/meal-ai/api/status')
        assert status.status_code == 200
        assert status.json()['authentication_required'] is True
        assert status.json()['book_entries'] is None
        assert SECRET not in status.text
        assert c.get('/meal-ai').status_code == 200
        assert c.get('/meal-ai/api/nutrition?name=ryze').status_code == 401
        assert c.get('/meal-ai/api/ean/8591234567890').status_code == 401
        assert c.post('/meal-ai/api/analyze', content=b'mocked photo').status_code == 401
        assert c.get('/meal-ai/book/IMG_0188').status_code == 401
        assert c.get('/meal-ai/api/nutrition?name=ryze',headers={'Authorization':'Bearer bad'}).status_code == 401


def test_beta_authorized_nutrition_and_blocked_origin(monkeypatch):
    enable_beta(monkeypatch)
    monkeypatch.setattr(routes.core,'nutrition_suggestions',lambda name, book, public: {'name': name,'count':2})
    auth={'Authorization':'Bearer '+SECRET}
    with client() as c:
        good=c.get('/meal-ai/api/nutrition?name=ryze',headers=auth)
        assert good.status_code == 200 and good.json()['name']=='ryze'
        bad=c.get('/meal-ai/api/nutrition?name=ryze',headers={**auth,'Origin':'https://evil.example'})
        assert bad.status_code == 403
        assert c.get('/meal-ai/book/IMG_0188',headers=auth).status_code == 404


def test_beta_photo_call_requires_token_before_cost(monkeypatch):
    enable_beta(monkeypatch)
    monkeypatch.setenv('OPENAI_API_KEY','test-uncallable')
    counter={'calls':0}
    def fake_analyze(*args):
        counter['calls']+=1
        return {'recognition':{'contains_food':False,'items':[]},'usage':{}}
    monkeypatch.setattr(routes.core,'analyze_photo',fake_analyze)
    auth={'Authorization':'Bearer '+SECRET}
    with client() as c:
        assert c.post('/meal-ai/api/analyze',content=b'example').status_code == 401
        assert counter['calls']==0
        monkeypatch.setenv('MEAL_AI_BETA_DAILY_LIMIT','1')
        monkeypatch.setattr(routes,'_counter_day','')
        monkeypatch.setattr(routes,'_calls_today',0)
        assert c.post('/meal-ai/api/analyze',content=b'example',headers=auth).status_code==200
        assert c.post('/meal-ai/api/analyze',content=b'example',headers=auth).status_code==429
        assert counter['calls']==1


def test_no_book_secret_in_git_and_external_override(monkeypatch,tmp_path):
    local = tmp_path/'private.json'
    local.write_text('{"vj_g_carbs":10,"rows":[{"name_cs":"Rýže vařená", "exchange_units":1, "weight_g":50,"page_id":"IMG_0188"}]}',encoding='utf-8')
    monkeypatch.setattr(svc,'PRIVATE_CATALOG',local)
    assert svc.load_book_catalog()[0]['carbs_per_100g']==20
    assert (Path(__file__).resolve().parents[1] / 'app/static/meal_ai_v8.html').is_file()


def test_html_token_stays_out_of_url_and_postmessage():
    s=(Path(__file__).resolve().parents[1]/'app/static/meal_ai_v8.html').read_text('utf-8')
    assert 'sessionStorage' in s
    assert 'Authorization' in s and 'Bearer ' in s
    assert 'apiFetch' in s
    assert 'Bearer '+SECRET not in s
    assert "fetch('/meal-ai/api/analyze'" not in s


def test_prepare_patches_flag_and_dependencies():
    original='if _meal_ai_os.getenv("MEAL_AI_V8_LOCAL", "0") == "1":\n'
    main, req=change(original,'fastapi==0.142.2\n')
    assert 'MEAL_AI_BETA' in main
    assert 'Pillow>=' in req
    assert change(main,req)==(main,req)
    with pytest.raises(RuntimeError): change('not a valid V8 app','fastapi')
