"""Private, read-only Dexcom LIVE page. Requires the Meal AI V8.7 beta session."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.routers.meal_ai_v8 import _access
from app.services import dexcom_share_live_v88 as source

router = APIRouter(prefix='/meal-ai', tags=['Private Dexcom LIVE research beta'])
PAGE = Path(__file__).resolve().parents[1] / 'static' / 'dexcom_live_v88.html'


@router.get('/live-dexcom', include_in_schema=False)
def live_page(request: Request):
    _access(request)
    return FileResponse(PAGE, media_type='text/html', headers={
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
    })


@router.get('/api/live-dexcom')
async def live_data(request: Request):
    _access(request)
    if not source.live_configured():
        raise HTTPException(503, 'Dexcom LIVE není nastavený. Zkontroluj soukromé proměnné Renderu.')
    try:
        return await run_in_threadpool(source.get_snapshot)
    except source.DexcomLiveError as exc:
        raise HTTPException(503, str(exc)) from None
