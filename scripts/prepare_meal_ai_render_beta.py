"""Prepare previously installed V8 for a guarded single-user Render beta.

Edit just app/main.py and requirements.txt, backing both up. Does NOT stage,
commit, push or change production Shadow logic. Run once after V8 installation.
"""
from __future__ import annotations

import shutil
import tempfile
import os
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'app' / 'main.py'
REQUIREMENTS = ROOT / 'requirements.txt'
EXPECTED = 'if _meal_ai_os.getenv("MEAL_AI_V8_LOCAL", "0") == "1":'
REPLACEMENT = ('if (_meal_ai_os.getenv("MEAL_AI_V8_LOCAL", "0") == "1" '
               'or _meal_ai_os.getenv("MEAL_AI_BETA", "0") == "1"):')
DEPENDENCY = 'Pillow>=12.0.0,<13.0'


def change(main: str, requirements: str) -> tuple[str, str]:
    if EXPECTED in main:
        assert main.count(EXPECTED) == 1, 'Nejednoznačný původní feature flag.'
        main = main.replace(EXPECTED, REPLACEMENT)
    elif REPLACEMENT not in main:
        raise RuntimeError('V8 router není nainstalovaný nebo je main.py jiný. Nic neměním.')
    req_lines = requirements.splitlines()
    if not any(x.lower().startswith('pillow') for x in req_lines):
        requirements = requirements.rstrip('\r\n') + '\n' + DEPENDENCY + '\n'
    return main, requirements


def write_atomic(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False,
                                     encoding='utf-8',newline='\n',suffix='.tmp') as fp:
        fp.write(content)
        temp = Path(fp.name)
    try: os.replace(temp,path)
    finally: temp.unlink(missing_ok=True)


def main() -> None:
    if not (ROOT/'app/routers/meal_ai_v8.py').is_file() or not (ROOT/'app/static/meal_ai_v8.html').is_file():
        raise RuntimeError('Nejdřív rozbal všechny nové soubory V8.1 do kořene projektu.')
    original_main = MAIN.read_text('utf-8-sig')
    original_req = REQUIREMENTS.read_text('utf-8-sig')
    main,req = change(original_main,original_req)
    if original_main == main and original_req == req:
        print('V8.1 beta už je připravená; nic se nezměnilo.')
        return
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_main = MAIN.with_name('main.before-meal-ai-beta-'+stamp+'.py')
    backup_req = REQUIREMENTS.with_name('requirements.before-meal-ai-beta-'+stamp+'.txt')
    shutil.copy2(MAIN,backup_main)
    shutil.copy2(REQUIREMENTS,backup_req)
    try:
        write_atomic(MAIN,main)
        write_atomic(REQUIREMENTS,req)
    except Exception:
        shutil.copy2(backup_main,MAIN)
        shutil.copy2(backup_req,REQUIREMENTS)
        raise
    print('Hotovo. BETA feature flag je v main.py, Pillow v requirements.txt.')
    print('Zálohy:',backup_main,backup_req,sep='\n  ')
    print('Pro Render povolit pouze s MEAL_AI_BETA=1, silným MEAL_AI_BETA_TOKEN a OPENAI_API_KEY.')

if __name__=='__main__':
    main()
