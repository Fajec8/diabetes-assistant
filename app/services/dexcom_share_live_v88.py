"""Read-only Dexcom Share snapshot for a single-user restricted research beta.

The Dexcom Share protocol is unofficial. Never use this adapter for automated
insulin decisions or clinical alerts. Passwords only come from server env vars.
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

_cache_lock = threading.Lock()
_cache_at = 0.0
_cached_snapshot: dict[str, Any] | None = None
_client = None
_client_params: tuple[str, str, str] | None = None
CACHE_SECONDS = 55
FRESH_MINUTES = 15


class DexcomLiveError(RuntimeError):
    pass


def live_configured() -> bool:
    return (
        os.getenv('DEXCOM_SHARE_ENABLED') == '1'
        and bool(os.getenv('DEXCOM_SHARE_USERNAME', '').strip())
        and bool(os.getenv('DEXCOM_SHARE_PASSWORD', ''))
        and os.getenv('DEXCOM_SHARE_REGION', 'ous').lower() in ('us', 'ous', 'jp')
    )


def _get_client():
    global _client, _client_params
    cfg = (
        os.environ['DEXCOM_SHARE_USERNAME'].strip(),
        os.environ['DEXCOM_SHARE_PASSWORD'],
        os.getenv('DEXCOM_SHARE_REGION', 'ous').strip().lower(),
    )
    if _client is None or _client_params != cfg:
        try:
            from pydexcom import Dexcom
        except ImportError as exc:
            raise DexcomLiveError('Chybí knihovna pydexcom na serveru.') from exc
        _client = Dexcom(username=cfg[0], password=cfg[1], region=cfg[2])
        _client_params = cfg
    return _client


def _timestamp_from_reading(reading: Any) -> datetime | None:
    # Dexcom Share's ST is a Unix epoch in milliseconds, independent of local TZ.
    raw = getattr(reading, 'json', None)
    if isinstance(raw, dict):
        stamp = str(raw.get('ST') or raw.get('WT') or '')
        match = re.search(r'Date\((\d{12,13})(?:[+-]\d{4})?\)', stamp)
        if match:
            try:
                return datetime.fromtimestamp(int(match.group(1)) / 1000, timezone.utc)
            except (ValueError, OverflowError, OSError):
                return None
    # Do not silently interpret a naive datetime as UTC or local timezone.
    dt = getattr(reading, 'datetime', None)
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    return None


def _normalize_reading(reading: Any, now: datetime) -> dict | None:
    observed = _timestamp_from_reading(reading)
    if observed is None:
        return None
    age = (now - observed).total_seconds() / 60
    if age < -2 or age > 1440:  # no future or implausibly old dates
        return None
    try:
        mgdl = int(getattr(reading, 'value'))
    except (ValueError, TypeError, OverflowError):
        return None
    if not (39 <= mgdl <= 401):
        return None
    arrow = getattr(reading, 'trend_arrow', '')
    if arrow not in ('', '↑↑', '↑', '↗', '→', '↘', '↓', '↓↓', '?', '-'):
        arrow = '?'
    trend = str(getattr(reading, 'trend_direction', '') or '')
    if trend not in ('DoubleUp','SingleUp','FortyFiveUp','Flat',
                     'FortyFiveDown','SingleDown','DoubleDown','None',
                     'NotComputable','RateOutOfRange'):
        trend = 'Unknown'
    return {
        'system_time': observed.isoformat(),
        'value_mg_dl': mgdl,
        'value_mmol_l': round(mgdl / 18.0, 1),
        'trend': trend,
        'trend_arrow': arrow,
    }


def _nearest(readings: list[dict], time_unix: float, delta_minutes: int) -> dict | None:
    target = time_unix - delta_minutes * 60
    nearest = min(readings, key=lambda item: abs(datetime.fromisoformat(item['system_time']).timestamp() - target), default=None)
    if nearest is None:
        return None
    difference = abs(datetime.fromisoformat(nearest['system_time']).timestamp() - target)
    return nearest if difference <= 7 * 60 else None


def _uncached_snapshot(now: datetime) -> dict:
    global _client, _client_params
    try:
        rows = _get_client().get_glucose_readings(max_count=18, minutes=90)
    except Exception as exc:
        # Never return raw upstream error strings: some could contain account details.
        _client, _client_params = None, None
        raise DexcomLiveError('Dexcom Share je nedostupný nebo odmítl přihlášení. Zkontroluj připojení Share a účet na Renderu.') from None

    records = []
    for row in rows or []:
        parsed = _normalize_reading(row, now)
        if parsed is not None:
            records.append(parsed)
    records.sort(key=lambda item: item['system_time'], reverse=True)
    # Stable de-duplication by observation timestamp.
    seen = set()
    unique = []
    for item in records:
        if item['system_time'] not in seen:
            unique.append(item)
            seen.add(item['system_time'])
    if not unique:
        return {'source': 'dexcom_share_unofficial', 'available': False,
                'reason': 'Dexcom Share nevrátil platná měření.', 'latest': None,
                'age_minutes': None, 'fresh': False, 'readings': [],
                'history': {'15': None, '30': None, '60': None}}
    latest = unique[0]
    latest_time = datetime.fromisoformat(latest['system_time'])
    age_minutes = round((now - latest_time).total_seconds() / 60, 1)
    latest_unix = latest_time.timestamp()
    return {
        'source': 'dexcom_share_unofficial', 'available': True,
        'latest': latest, 'age_minutes': age_minutes,
        'fresh': 0 <= age_minutes <= FRESH_MINUTES,
        'readings': list(reversed(unique)),
        'history': {
            '15': _nearest(unique, latest_unix, 15),
            '30': _nearest(unique, latest_unix, 30),
            '60': _nearest(unique, latest_unix, 60),
        },
    }


def get_snapshot() -> dict:
    """Cache with a lock to avoid overlapping Dexcom Share calls on Render."""
    global _cache_at, _cached_snapshot
    if not live_configured():
        raise DexcomLiveError('Dexcom LIVE není nakonfigurovaný.')
    now_mono = time.monotonic()
    with _cache_lock:
        if _cached_snapshot is not None and now_mono - _cache_at < CACHE_SECONDS:
            # Re-evaluate freshness on each response; don't freeze the age in cache.
            out = dict(_cached_snapshot)
            latest = out.get('latest')
            if latest:
                age = round((datetime.now(timezone.utc) - datetime.fromisoformat(latest['system_time'])).total_seconds() / 60, 1)
                out['age_minutes'] = age
                out['fresh'] = 0 <= age <= FRESH_MINUTES
            return out
        snapshot = _uncached_snapshot(datetime.now(timezone.utc))
        _cached_snapshot, _cache_at = snapshot, time.monotonic()
        return dict(snapshot)
