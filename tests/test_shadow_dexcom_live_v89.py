"""Offline regression checks: V8.9 is opt-in/read-only until the user saves manually.

Actual browser/Dexcom Share integration must also be checked manually on Render.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SHADOW = ROOT / 'app/static/shadow.html'
LIVE_ROUTER = ROOT / 'app/routers/dexcom_live_v88.py'


def shadow():
    return SHADOW.read_text('utf-8-sig')


def bridge_js():
    page = shadow()
    return page.split('// DEXCOM_LIVE_V89_SHADOW_BRIDGE', 1)[1].split(
        'byId("decisionAt").value = localDateTimeValue();', 1
    )[0]


def test_bridge_is_present_once_and_only_shadow_html_is_extended():
    page = shadow()
    assert page.count('id="dexcomLiveV89Card"') == 1
    assert page.count('function dexcomLiveV89Apply()') == 1
    assert page.count('id="dexcomCard"') == 0  # obsolete sandbox card removed


def test_bridge_reads_only_private_live_endpoint():
    js = bridge_js()
    assert 'fetch("/meal-ai/api/live-dexcom"' in js
    assert 'credentials: "same-origin"' in js
    assert 'cache: "no-store"' in js
    router = LIVE_ROUTER.read_text('utf-8-sig')
    assert "@router.get('/api/live-dexcom')" in router
    assert '_access(request)' in router


def test_fetch_only_previews_without_writing_form_fields():
    js = bridge_js()
    fetch_body = js.split('async function dexcomLiveV89Fetch()', 1)[1].split(
        'function dexcomLiveV89Apply()', 1
    )[0]
    assert 'dexcomLiveV89Pending = candidate' in fetch_body
    for field in ('glucose', 'glucose15', 'glucose30', 'glucose60', 'trend', 'decisionAt'):
        assert f'byId("{field}").value =' not in fetch_body
    assert '/decision-sessions' not in fetch_body


def test_confirmation_only_changes_inputs_and_no_insulin_or_session_actions():
    js = bridge_js()
    body = js.split('function dexcomLiveV89Apply()', 1)[1]
    for field in ('glucose', 'glucose15', 'glucose30', 'glucose60', 'trend', 'decisionAt'):
        assert f'byId("{field}").value =' in body
    for forbidden in ('createDecisionSession(', 'saveSession(', 'create_session(', 'user-plan',
                      'insulinUnits', 'rapidDoseList', 'mealCarbs', 'localStorage.setItem(',
                      '/decision-sessions', 'POST'):
        assert forbidden not in js
    assert 'fetch(' not in body


def test_snapshot_guards_freshness_and_never_invents_missing_history():
    js = bridge_js()
    assert 'DEXCOM_LIVE_V89_MAX_AGE_MINUTES = 10' in js
    assert 'snapshot.fresh !== true' in js
    assert 'ageMinutes > DEXCOM_LIVE_V89_MAX_AGE_MINUTES' in js
    assert 'typeof value === "number"' in js
    assert 'lag < minutes - 7 || lag > minutes + 7' in js
    assert 'candidate.history15 === null ? ""' in js
    assert 'candidate.history30 === null ? ""' in js
    assert 'candidate.history60 === null ? ""' in js


def test_application_requires_user_click_and_editable_new_situation():
    js = bridge_js()
    assert 'byId("dexcomLiveV89Apply").addEventListener("click", dexcomLiveV89Apply)' in js
    assert 'byId("dexcomLiveV89Fetch").addEventListener("click", dexcomLiveV89Fetch)' in js
    assert 'byId("situationCard").classList.contains("hidden")' in js
    assert 'handleSituationDayChange();' in js


def test_preview_is_cancelable_and_uses_textcontent_not_html_injection():
    js = bridge_js()
    assert 'byId("dexcomLiveV89Cancel").addEventListener("click"' in js
    assert 'dexcomLiveV89ClearPreview(' in js
    assert 'textContent' in js
    assert 'innerHTML' not in js
    assert 'postMessage(' not in js


def test_old_sandbox_dexcom_panel_and_fetch_are_gone():
    page = shadow()
    assert page.count('id="dexcomLiveV89Card"') == 1
    assert 'Živý Dexcom (soukromý test)' not in page
    assert 'id="dexcomCard"' not in page
    assert 'loadDexcomContext(' not in page
    assert '/dexcom/context/' not in page
    assert 'useDexcomButton' not in page
    assert 'connectDexcomButton' not in page
    assert 'sandboxová data jsou stará' not in page
    assert 'Starší Dexcom karta níže' not in page
    assert '<a href="/meal-ai/live-dexcom"' in page
    assert 'function dexcomTrendInfo(rawTrend)' in page
    assert 'fetch("/meal-ai/api/live-dexcom"' in page
