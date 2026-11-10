"""Regression tests: invalid Unicode bearer credentials must never cause HTTP 500."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.routers.meal_ai_v8 import _access


def request_with_auth(value: bytes | None = None) -> Request:
    headers = [(b'host', b'testserver')]
    if value is not None:
        headers.append((b'authorization', value))
    return Request({
        'type': 'http',
        'method': 'POST',
        'scheme': 'https',
        'path': '/meal-ai/api/scan-ean',
        'raw_path': b'/meal-ai/api/scan-ean',
        'query_string': b'',
        'headers': headers,
        'server': ('testserver', 443),
        'client': ('127.0.0.1', 10000),
        'http_version': '1.1',
    })


@pytest.fixture(autouse=True)
def render_beta(monkeypatch):
    monkeypatch.setenv('RENDER', '1')
    monkeypatch.setenv('MEAL_AI_BETA', '1')
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN', 'Q' * 44)


def assert_http_error(request: Request, expected_code: int):
    with pytest.raises(HTTPException) as error:
        _access(request)
    assert error.value.status_code == expected_code


def test_valid_ascii_beta_token_is_accepted():
    assert _access(request_with_auth(b'Bearer ' + b'Q' * 44)) == 'restricted_beta'


def test_missing_beta_token_returns_401():
    assert_http_error(request_with_auth(), 401)


def test_incorrect_ascii_beta_token_returns_401():
    assert_http_error(request_with_auth(b'Bearer ' + b'R' * 44), 401)


def test_nonascii_beta_token_from_browser_returns_401_not_500():
    # ASGI HTTP headers are raw bytes. Starlette decodes them as Latin-1.
    # Previously this triggered TypeError in secrets.compare_digest(str, str).
    assert_http_error(request_with_auth(b'Bearer ' + b'Q' * 43 + b'\xe1'), 401)


def test_nonascii_server_configuration_returns_503_not_500(monkeypatch):
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN', 'ž' * 44)
    assert_http_error(request_with_auth(b'Bearer ' + b'Q' * 44), 503)


def test_short_server_configuration_returns_503(monkeypatch):
    monkeypatch.setenv('MEAL_AI_BETA_TOKEN', 'too-short')
    assert_http_error(request_with_auth(b'Bearer ' + b'Q' * 44), 503)


def test_status_access_still_does_not_require_beta_token():
    assert _access(request_with_auth(), private=False) == 'restricted_beta'
