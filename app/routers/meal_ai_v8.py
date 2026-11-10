"""Meal AI API: loopback development or token-guarded single-user beta.

This is NOT general patient authentication. Public deployment is permitted only
for a personal test, with a strong beta token and an independent API hard budget.
"""
from __future__ import annotations

import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.services import meal_ai_v8 as core
from app.services.meal_barcode_camera_v82 import MAX_BARCODE_BYTES, decode_ean_photo

router = APIRouter(prefix='/meal-ai', tags=['Meal AI – restricted beta'])
PAGE = Path(__file__).resolve().parents[1] / 'static' / 'meal_ai_v8.html'
_lock = threading.Lock()
_counter_day = ''
_calls_today = 0


def _on_render() -> bool:
    return os.getenv('RENDER', '').lower() not in ('', '0', 'false')


def _beta_enabled() -> bool:
    return _on_render() and os.getenv('MEAL_AI_BETA', '') == '1'


def _required_beta_token() -> str:
    token = os.getenv('MEAL_AI_BETA_TOKEN', '')
    if len(token) < 32:
        raise HTTPException(503, 'Meal AI beta není nakonfigurovaná. Chybí dlouhý přístupový token.')
    return token


def _access(request: Request, *, private: bool = True) -> str:
    """No anonymous paid or nutritional calls on the public Render instance."""
    if _on_render():
        if not _beta_enabled():
            raise HTTPException(403, 'Meal AI je pro veřejný server vypnuté.')
        _required_beta_token()
        mode = 'restricted_beta'
    else:
        mode = 'local_research'
        if request.url.hostname not in ('localhost', '127.0.0.1', 'testserver'):
            raise HTTPException(403, 'Lokální verze funguje pouze na tomto počítači.')

    # Same-origin gate for browser calls. Bearer token is required in addition.
    origin = request.headers.get('origin')
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http', 'https') or parsed.netloc.lower() != request.headers.get('host', '').lower():
            raise HTTPException(403, 'Nepovolený původ požadavku.')

    if mode == 'restricted_beta' and private:
        expected = _required_beta_token()
        auth = request.headers.get('authorization', '')
        if not auth.startswith('Bearer ') or not secrets.compare_digest(auth[7:], expected):
            raise HTTPException(401, 'Přístup zamítnut. Zkontroluj beta přístupový kód.', headers={'WWW-Authenticate': 'Bearer'})
    return mode


def _daily_cap() -> int:
    try:
        value = int(os.getenv('MEAL_AI_BETA_DAILY_LIMIT', '5'))
    except ValueError:
        value = 5
    return max(1, min(20, value))


def _reserve_call(mode: str) -> None:
    global _counter_day, _calls_today
    day = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        if day != _counter_day:
            _counter_day = day
            _calls_today = 0
        limit = _daily_cap() if mode == 'restricted_beta' else 8
        if _calls_today >= limit:
            raise HTTPException(429, 'Denní limit AI analýz dosažen. Další pokusy jsou zablokované.')
        _calls_today += 1


def _remaining(mode: str) -> int:
    day = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        used = _calls_today if day == _counter_day else 0
    return max(0, (_daily_cap() if mode == 'restricted_beta' else 8) - used)


@router.get('', include_in_schema=False)
@router.get('/', include_in_schema=False)
def meal_page(request: Request):
    _access(request, private=False)
    return FileResponse(PAGE, media_type='text/html', headers={'Cache-Control': 'no-store'})


@router.get('/api/status')
def status(request: Request):
    mode = _access(request, private=False)
    if mode == 'restricted_beta':
        # The status must not expose the key, image data, or personal food history.
        return {'mode': mode, 'authentication_required': True,
                'remaining_photo_calls_this_run': None,
                'book_entries': None,
                'photo_privacy': 'image not stored on disk; sent to OpenAI only after confirmation'}
    return {'mode': mode, 'authentication_required': False,
            'model': core.MODEL,
            'openai_key_set': bool(os.getenv('OPENAI_API_KEY', '').strip()),
            'remaining_photo_calls_this_run': _remaining(mode),
            'book_entries': len(core.load_book_catalog()),
            'photo_privacy': 'image not stored; paid API call only after clicking Analyze'}


@router.post('/api/analyze')
async def analyze(request: Request):
    mode = _access(request)
    length = request.headers.get('content-length')
    if length and length.isdigit() and int(length) > core.MAX_UPLOAD_BYTES:
        raise HTTPException(413, 'Maximální velikost fotografie je 10 MB.')
    raw_chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > core.MAX_UPLOAD_BYTES:
            raise HTTPException(413, 'Maximální velikost fotografie je 10 MB.')
        raw_chunks.append(chunk)
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        raise HTTPException(503, 'OpenAI klíč chybí v serverovém prostředí.')
    _reserve_call(mode)
    try:
        return await run_in_threadpool(core.analyze_photo, b''.join(raw_chunks), key, core.MODEL)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/api/nutrition')
async def nutrition(request: Request, name: str = Query(min_length=2, max_length=100), public: bool = True):
    _access(request)
    try:
        return await run_in_threadpool(core.nutrition_suggestions, name, None, public)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/api/ean/{code}')
async def ean(request: Request, code: str):
    _access(request)
    if not re.fullmatch(r'\d{8,14}', code):
        raise HTTPException(422, 'EAN/UPC musí mít 8 až 14 číslic.')
    try:
        return await run_in_threadpool(core.barcode_product, code)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None




@router.post('/api/scan-ean')
async def scan_ean(request: Request):
    """Read an EAN camera snapshot. Protected by the beta token, never persisted."""
    _access(request)
    length = request.headers.get('content-length')
    if length and length.isdigit() and int(length) > MAX_BARCODE_BYTES:
        raise HTTPException(413, 'Maximální velikost snímku EAN je 8 MB.')
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BARCODE_BYTES:
            raise HTTPException(413, 'Maximální velikost snímku EAN je 8 MB.')
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(422, 'Nebyla zaslána fotografie čárového kódu.')
    try:
        return await run_in_threadpool(decode_ean_photo, b''.join(chunks))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None

@router.get('/book/{page_id}', include_in_schema=False)
def book_page(request: Request, page_id: str):
    _access(request)
    # Never publicly serve the private book scans, even to beta users.
    if _on_render():
        raise HTTPException(404, 'Soukromé fotografie tabulek jsou dostupné pouze lokálně.')
    if not re.fullmatch(r'IMG_0(?:17[7-9]|18\d|19\d|20[0-4])', page_id):
        raise HTTPException(404, 'Neznámá stránka katalogu.')
    path = core.PRIVATE_IMAGES / (page_id + '.jpg')
    if not path.is_file():
        raise HTTPException(404, 'Fotografie stránky není na tomto zařízení.')
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'private, no-store'})
