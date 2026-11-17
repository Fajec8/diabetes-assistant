"""Research-only retrospective Dexcom Share outcome lookup.

Does not write glucose data, infer missing values, or calculate insulin.
Returns only 5 timestamp-checked values rather than a full 24h record.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.services import dexcom_share_live_v88 as live

HORIZONS = (30, 60, 90, 120, 180)
TOLERANCE_SECONDS = 6 * 60
MAX_DECISION_AGE_MINUTES = 23 * 60


def _parse_decision_at(raw: str, now: datetime) -> datetime:
    if not isinstance(raw, str) or not (20 <= len(raw) <= 48):
        raise ValueError('Neplatný čas začátku situace.')
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Neplatný čas začátku situace.') from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Čas situace musí obsahovat časové pásmo.')
    decision = parsed.astimezone(timezone.utc)
    age_minutes = (now - decision).total_seconds() / 60
    if age_minutes < -2:
        raise ValueError('Situace začíná v budoucnosti. Výsledek nelze načíst.')
    if age_minutes > MAX_DECISION_AGE_MINUTES:
        raise ValueError('Situace je starší než 23 hodin. Dexcom Share už nemusí mít spolehlivou historii; hodnoty zadej ručně.')
    return decision


def _nearest(records: list[dict], target: datetime, now: datetime) -> dict | None:
    if target > now:  # A +180 minute value must never be guessed at +90 min.
        return None
    closest: dict | None = None
    best = TOLERANCE_SECONDS + 0.001
    for row in records:
        when = datetime.fromisoformat(row['system_time'])
        if when > now + timedelta(minutes=2):
            continue
        deviation = abs((when - target).total_seconds())
        if deviation <= TOLERANCE_SECONDS and deviation < best:
            closest, best = row, deviation
    if closest is None:
        return None
    return {
        'system_time': closest['system_time'],
        'value_mmol_l': closest['value_mmol_l'],
        'offset_minutes': round((datetime.fromisoformat(closest['system_time']) - target).total_seconds() / 60, 1),
        'target_time': target.isoformat(),
    }


def get_outcome_snapshot(decision_at: str) -> dict:
    """Look up +30/+60/+90/+120/+180 min, never changing the saved session."""
    now = datetime.now(timezone.utc)
    decision = _parse_decision_at(decision_at, now)
    age_minutes = (now - decision).total_seconds() / 60
    minutes = min(1440, max(210, math.ceil(age_minutes) + 12))
    count = min(288, max(43, math.ceil(minutes / 5) + 2))

    if not live.live_configured():
        raise live.DexcomLiveError('Dexcom LIVE není nastavený.')
    try:
        # Share the lock with V8.8, which can reuse the same pydexcom client.
        with live._cache_lock:
            readings = live._get_client().get_glucose_readings(minutes=minutes, max_count=count)
    except Exception:
        # Never pass upstream exception text (could contain account details).
        live._client = None
        live._client_params = None
        raise live.DexcomLiveError('Historii Dexcom Share se nepodařilo načíst. Zkontroluj Share a zkus to znovu.') from None

    records: list[dict] = []
    unique_times: set[str] = set()
    for reading in readings or []:
        parsed = live._normalize_reading(reading, now)
        if parsed is not None and parsed['system_time'] not in unique_times:
            unique_times.add(parsed['system_time'])
            records.append(parsed)

    fields = {str(h): _nearest(records, decision + timedelta(minutes=h), now) for h in HORIZONS}
    return {
        'source': 'dexcom_share_unofficial',
        'decision_at': decision.isoformat(),
        'checked_at': now.isoformat(),
        'window_minutes': minutes,
        'matched_count': sum(value is not None for value in fields.values()),
        'fields': fields,
    }
