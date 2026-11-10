from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services.meal_barcode_camera_v82 import decode_ean_photo, gtin_checksum_ok


def _png_bytes():
    buffer=io.BytesIO()
    Image.new('RGB', (60, 60), 'white').save(buffer, format='PNG')
    return buffer.getvalue()


def test_gtin_checksums():
    # GTIN-13 known textbook example, valid last digit 7.
    assert gtin_checksum_ok('4006381333931')
    assert not gtin_checksum_ok('4006381333930')
    assert not gtin_checksum_ok('not a code')


def test_photo_decode_returns_code(monkeypatch):
    fake=SimpleNamespace(read_barcodes=lambda image: [SimpleNamespace(text='4006381333931',format='EAN13')])
    monkeypatch.setitem(sys.modules,'zxingcpp',fake)
    assert decode_ean_photo(_png_bytes()) == {'code':'4006381333931','format':'EAN13'}


def test_invalid_format_not_accepted(monkeypatch):
    fake=SimpleNamespace(read_barcodes=lambda image: [SimpleNamespace(text='4006381333931',format='QRCode')])
    monkeypatch.setitem(sys.modules,'zxingcpp',fake)
    with pytest.raises(ValueError,match='nebyl nalezen'):
        decode_ean_photo(_png_bytes())


def test_bad_uploads_rejected():
    with pytest.raises(ValueError):decode_ean_photo(b'not an image')
    with pytest.raises(ValueError):decode_ean_photo(b'')
    with pytest.raises(ValueError):decode_ean_photo(b'X'*(8*1024*1024+1))


def test_mobile_ui_has_two_photo_options():
    root=Path(__file__).resolve().parents[1]
    page=(root/'app/static/meal_ai_v8.html').read_text('utf-8-sig')
    assert 'id="mealCameraInput" class="visually-hidden-file" type="file" accept="image/*" capture="environment"' in page
    assert 'id="imageInput" class="visually-hidden-file" type="file"' in page
    assert 'id="eanCameraInput" class="visually-hidden-file" type="file" accept="image/*" capture="environment"' in page
    assert '/meal-ai/api/scan-ean' in page
    assert 'state.photoFile' in page


def test_new_route_is_guarded(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.meal_ai_v8 import router
    app=FastAPI();app.include_router(router)
    client=TestClient(app)
    monkeypatch.setenv('RENDER','1')
    monkeypatch.setenv('MEAL_AI_BETA','1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN','a'*36)
    assert client.post('/meal-ai/api/scan-ean',content=_png_bytes(),headers={'content-type':'image/png'}).status_code==401


def test_scan_api_reads_code(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.routers.meal_ai_v8 as routes
    app=FastAPI();app.include_router(routes.router)
    client=TestClient(app)
    monkeypatch.setenv('RENDER','1')
    monkeypatch.setenv('MEAL_AI_BETA','1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN','a'*36)
    monkeypatch.setattr(routes,'decode_ean_photo',lambda raw:{'code':'4006381333931','format':'EAN13'})
    rsp=client.post('/meal-ai/api/scan-ean',content=_png_bytes(),headers={'Authorization':'Bearer '+'a'*36,'Content-Type':'image/png'})
    assert rsp.status_code==200
    assert rsp.json()['code']=='4006381333931'


def test_large_payload_rejected_before_decode(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.routers.meal_ai_v8 as routes
    app=FastAPI();app.include_router(routes.router)
    client=TestClient(app)
    monkeypatch.setenv('RENDER','1')
    monkeypatch.setenv('MEAL_AI_BETA','1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN','a'*36)
    rsp=client.post('/meal-ai/api/scan-ean',content=b'',headers={'Authorization':'Bearer '+'a'*36,'Content-Length':str(9*1024*1024)})
    assert rsp.status_code==413
