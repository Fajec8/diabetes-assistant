"""Patch ONLY app/main.py and app/static/shadow.html with backed-up, exact anchors.

The new router, service, HTML and local catalogue arrive as complete files in
this ZIP. This installer intentionally does not touch Shadow inference logic,
PostgreSQL, schemas, already collected data or any experimental V3-V7 files.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'app' / 'main.py'
SHADOW = ROOT / 'app' / 'static' / 'shadow.html'
MARKER = 'MEAL_AI_V8_LOCAL_INTEGRATION'


MAIN_ADDITION = '''\n# MEAL_AI_V8_LOCAL_INTEGRATION: deliberately disabled on Render by default.\n# Production requires real user authentication, consent and spending controls.\nimport os as _meal_ai_os\nif _meal_ai_os.getenv("MEAL_AI_V8_LOCAL", "0") == "1":\n    from app.routers.meal_ai_v8 import router as _meal_ai_router\n    app.include_router(_meal_ai_router)\n\n'''

SHADOW_CSS = '''\n/* MEAL_AI_V8_LOCAL_INTEGRATION */\n.meal-ai-overlay { position:fixed; inset:0; z-index:5000; display:flex; justify-content:center;\n align-items:center; background:rgba(11,27,40,.75); padding:8px; }\n.meal-ai-overlay.hidden { display:none !important; }\n.meal-ai-panel { background:white; border-radius:14px; width:min(100%,940px); height:min(96vh,1000px);\n display:flex; flex-direction:column; overflow:hidden; }\n.meal-ai-bar { display:flex; align-items:center; justify-content:space-between; padding:9px 12px;\n border-bottom:1px solid #e2e8ec; gap:10px; }\n.meal-ai-panel iframe { width:100%; flex:1; border:0; }\n'''

SHADOW_MODAL = '''\n<!-- MEAL_AI_V8_LOCAL_INTEGRATION -->\n<div id="mealAiModal" class="meal-ai-overlay hidden" role="dialog" aria-modal="true" aria-label="Asistent jídla">\n  <div class="meal-ai-panel">\n    <div class="meal-ai-bar">\n      <strong>Diabetes Assistant • jídlo</strong>\n      <button id="mealAiClose" class="secondary" type="button">Zavřít ✕</button>\n    </div>\n    <iframe id="mealAiFrame" title="Foto, EAN a ruční zadání jídla" allow="camera"></iframe>\n  </div>\n</div>\n'''

SHADOW_BUTTON = '''\n            <!-- MEAL_AI_V8_LOCAL_INTEGRATION: ruční pole zůstávají vždy dostupná -->\n            <div style="margin-top:12px">\n                <button id="openMealAiButton" class="secondary hidden" type="button">📷 Vyfotit jídlo / načíst EAN / ručně</button>\n                <p class="mini">Výzkumný asistent vyplní jídlo až po potvrzení. Ruční zadání výše funguje dál.</p>\n            </div>\n'''

SHADOW_SCRIPT = r'''// MEAL_AI_V8_LOCAL_INTEGRATION
let mealAiItems = [];
let mealAiConfirmedCarbs = null;
let mealAiConfirmedDescription = null;

function resetMealAiItems() {
    mealAiItems = [];
    mealAiConfirmedCarbs = null;
    mealAiConfirmedDescription = null;
}

function openMealAi() {
    byId("mealAiModal").classList.remove("hidden");
    byId("mealAiFrame").src = "/meal-ai";
}

function closeMealAi() {
    byId("mealAiModal").classList.add("hidden");
    byId("mealAiFrame").src = "about:blank";
}

window.addEventListener("message", event => {
    const frame = byId("mealAiFrame");
    if (event.origin !== window.location.origin || event.source !== frame.contentWindow) return;
    const data = event.data;
    if (!data || typeof data !== "object") return;
    if (data.type === "diabetes-assistant-meal-v8-close") {
        closeMealAi();
        return;
    }
    if (data.type !== "diabetes-assistant-meal-v8" || data.confirmed !== true) return;
    const carbs = Number(data.carbohydrates_g);
    const description = String(data.description || "").trim().slice(0, 500);
    if (!Number.isFinite(carbs) || carbs < 0 || carbs > 1000 || !description) return;
    if (!Array.isArray(data.items) || data.items.length < 1 || data.items.length > 20) return;
    const verifiedItems = [];
    for (const row of data.items) {
        if (!row || typeof row !== "object") return;
        const name = String(row.food_name || "").trim().slice(0, 120);
        const amount = row.amount_g === undefined ? null : Number(row.amount_g);
        const itemCarbs = row.carbohydrates_g === undefined ? null : Number(row.carbohydrates_g);
        if (!name || (amount !== null && (!Number.isFinite(amount) || amount <= 0 || amount > 3000)) ||
            (itemCarbs !== null && (!Number.isFinite(itemCarbs) || itemCarbs < 0 || itemCarbs > 3000))) return;
        verifiedItems.push({
            food_name: name,
            amount_g: amount,
            carbohydrates_g: itemCarbs,
            note: String(row.note || "").slice(0, 500)
        });
    }
    byId("mealPlanned").checked = true;
    updateMealFields();
    byId("mealCarbs").value = String(carbs);
    byId("mealDescription").value = description;
    mealAiItems = verifiedItems;
    mealAiConfirmedCarbs = String(carbs);
    mealAiConfirmedDescription = description;
    closeMealAi();
    showMessage("Potvrzené jídlo bylo vloženo do formuláře (" + carbs + " g sacharidů). Situaci musíš ještě sám uložit.", "success");
});

// Do not show a broken button when the local experiment is disabled on Render.
fetch("/meal-ai/api/status", {cache: "no-store"})
    .then(response => {if (response.ok) byId("openMealAiButton").classList.remove("hidden");})
    .catch(() => {});
byId("openMealAiButton").addEventListener("click", openMealAi);
byId("mealAiClose").addEventListener("click", closeMealAi);
byId("mealCarbs").addEventListener("input", resetMealAiItems);
byId("mealDescription").addEventListener("input", resetMealAiItems);
'''


def replace_one(contents: str, old: str, new: str, label: str) -> str:
    count = contents.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: očekávám jediný úsek, nalezeno {count}. Soubor nebyl změněn.')
    return contents.replace(old, new, 1)


def modify_files(main: str, shadow: str) -> tuple[str, str]:
    if MARKER in main or MARKER in shadow:
        if MARKER in main and MARKER in shadow:
            return main, shadow
        raise RuntimeError('Část úpravy už je nainstalovaná. Neprovádím částečné přepsání.')

    main = replace_one(
        main, 'app.include_router(\n    dexcom_router\n)\n',
        'app.include_router(\n    dexcom_router\n)\n' + MAIN_ADDITION,
        'main.py – registrace routeru'
    )
    shadow = replace_one(shadow, '</style>', SHADOW_CSS + '\n</style>', 'Shadow CSS')
    shadow = replace_one(
        shadow,
        '            </div>\n        </div>\n\n        <hr class="separator">\n\n        <h3>NovoRapid podaný před touto situací</h3>',
        '            </div>' + SHADOW_BUTTON + '        </div>\n\n        <hr class="separator">\n\n        <h3>NovoRapid podaný před touto situací</h3>',
        'Shadow – tlačítko u plánovaného jídla'
    )
    shadow = replace_one(shadow, '\n<script>\n', SHADOW_MODAL + '\n<script>\n', 'Shadow – dialog')
    shadow = replace_one(shadow,
                         'byId("decisionAt").value = localDateTimeValue();\nrestoreSameDayContext();\nupdateMealFields();',
                         SHADOW_SCRIPT + '\nbyId("decisionAt").value = localDateTimeValue();\nrestoreSameDayContext();\nupdateMealFields();',
                         'Shadow – JS na konci stránky')
    shadow = replace_one(shadow, '                items: []\n            };',
                         '                items: (mealAiConfirmedCarbs === String(carbs) &&\n'
                         '                        mealAiConfirmedDescription === byId("mealDescription").value.trim())\n'
                         '                    ? mealAiItems.map(item => ({...item})) : []\n            };',
                         'Shadow – položky plánovaného jídla')
    # The older app constructs payload with planned_meal already. After a new
    # session starts we must not carry over old meal items.
    shadow = replace_one(shadow, 'function clearForms() {\n',
                         'function clearForms() {\n    resetMealAiItems();\n',
                         'Shadow – reset položek')
    shadow = replace_one(shadow,
                         '<input id="mealCarbs" type="number" inputmode="decimal" min="0" step="1"',
                         '<input id="mealCarbs" type="number" inputmode="decimal" min="0" step="0.1"',
                         'Shadow – desetinné sacharidy')
    return main, shadow


def atomic_replace(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                     dir=path.parent, suffix='.tmp', delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(content)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> None:
    for required in (MAIN, SHADOW, ROOT / 'app' / 'routers' / 'meal_ai_v8.py',
                     ROOT / 'app' / 'services' / 'meal_ai_v8.py',
                     ROOT / 'app' / 'static' / 'meal_ai_v8.html'):
        if not required.is_file():
            raise RuntimeError(f'Chybí soubor: {required}. Rozbal celý ZIP do kořene projektu.')
    original_main = MAIN.read_text(encoding='utf-8')
    original_shadow = SHADOW.read_text(encoding='utf-8')
    updated_main, updated_shadow = modify_files(original_main, original_shadow)
    if original_main == updated_main and original_shadow == updated_shadow:
        print('MEAL AI V8 už je nainstalovaná. Nic dalšího se nepřepsalo.')
        return
    now = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_main = MAIN.with_name(f'main.before-meal-ai-v8-{now}.py')
    backup_shadow = SHADOW.with_name(f'shadow.before-meal-ai-v8-{now}.html')
    shutil.copy2(MAIN, backup_main)
    shutil.copy2(SHADOW, backup_shadow)
    try:
        atomic_replace(MAIN, updated_main)
        atomic_replace(SHADOW, updated_shadow)
    except Exception:
        shutil.copy2(backup_main, MAIN)
        shutil.copy2(backup_shadow, SHADOW)
        raise
    print('MEAL AI V8: instalováno do hlavní aplikace (lokální feature flag).')
    print('Zálohy:', backup_main, 'a', backup_shadow, sep='\n - ')
    print('V produkci je nová část ve výchozím stavu VYPNUTÁ.')
    print('Spusť testy a pak v PowerShellu nastav $env:MEAL_AI_V8_LOCAL="1".')


if __name__ == '__main__':
    main()
