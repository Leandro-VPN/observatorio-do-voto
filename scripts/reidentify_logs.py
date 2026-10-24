"""Fill section identity from the log file name when the log content did not identify the section (contingency and reloaded urns).
Rewrites operations.jsonl in place (backup .bak once); identity_status becomes 'PARSED_FILENAME'."""
import json
import re
import shutil
import sys
from pathlib import Path

ID_RE = re.compile(r'(\d{5})(\d{4})(\d{4})(?:\.logjez|-log\.jez)$', re.I)

for folder in sys.argv[1:]:
    f = Path(folder) / 'operations.jsonl'
    if not f.exists() or f.stat().st_size == 0:
        print(folder, 'skip (no ops)', flush=True)
        continue
    bak = f.with_suffix('.jsonl.bak')
    if not bak.exists():
        shutil.copy2(f, bak)
    rows = [json.loads(l) for l in bak.read_text(encoding='utf-8').splitlines() if l.strip()]
    fixed = 0
    for r in rows:
        if r.get('identity_status') != 'PARSED':
            m = ID_RE.search(r.get('member', ''))
            if m:
                r['municipality'], r['zone'], r['section'] = int(m.group(1)), int(m.group(2)), int(m.group(3))
                r['identity_status'] = 'PARSED_FILENAME'
                fixed += 1
    with f.open('w', encoding='utf-8') as out:
        for r in rows:
            out.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(folder, 'rows', len(rows), 'reidentified', fixed, flush=True)
