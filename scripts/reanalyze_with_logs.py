"""Re-run section analyses for every election with urn logs after log re-identification."""
import sys, shutil
from pathlib import Path
sys.path.insert(0, 'scripts')
import uf_pipeline as U
import analyze_office as AO
import analyze_bahia_documents as AB
UFS = ['SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
for uf in UFS:
    for y, t in [(2022, 1), (2022, 2), (2026, 1)]:
        try:
            U.analyze(uf, y, t, U.folder_for(uf, y, t)); print('P', uf, y, t, 'ok', flush=True)
        except Exception as e:
            print('P', uf, y, t, 'FAIL', repr(e)[:120], flush=True)
for y, t in [(2022, 1), (2022, 2), (2026, 1)]:
    try:
        AB.analyze(y, t); print('P BA', y, t, 'ok', flush=True)
    except Exception as e:
        print('P BA', y, t, 'FAIL', repr(e)[:120], flush=True)
for office, els in [('GOVERNADOR', [(2022, 1), (2022, 2), (2026, 1)]), ('PREFEITO', [(2024, 1), (2024, 2)])]:
    for uf in ['BA'] + UFS:
        for y, t in els:
            d = AO.out_dir(uf, y, t, office)
            if (d / 'summary.json').exists():
                (d / 'summary.json').unlink()
            try:
                print(office, uf, y, t, AO.analyze(uf, y, t, office), flush=True)
            except Exception as e:
                print(office, uf, y, t, 'FAIL', repr(e)[:120], flush=True)
print('REANALYZE DONE', flush=True)
