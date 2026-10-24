"""Checagens do site publicado (arquivos versionados em site/): links locais existem, números do painel iguais ao CSV, sem placeholders, índice de busca por UF."""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'


def test_sem_placeholders():
    html = (SITE / 'index.html').read_text(encoding='utf-8')
    assert not re.search(r'__[A-Z_]+__', html)


def test_links_locais_existem():
    html = (SITE / 'index.html').read_text(encoding='utf-8')
    refs = set(re.findall(r'(?:href|src)="([^"#:]+)"', html))
    missing = [r for r in refs if not (SITE / r.split('#')[0]).exists()]
    assert not missing, missing


def test_painel_igual_ao_csv():
    js = (SITE / 'app.js').read_text(encoding='utf-8')
    records = json.loads(re.search(r'const records = (\{.*?\});', js, re.S).group(1))
    csv = pd.read_csv(SITE / 'dados/resumo-por-eleicao.csv', sep=';', decimal=',').set_index('eid')
    for eid, r in records.items():
        for k, v in r.items():
            assert int(csv.loc[eid, k]) == v, (eid, k)


def test_indice_de_busca_por_uf():
    html = (SITE / 'index.html').read_text(encoding='utf-8')
    ufs = re.findall(r'<option value="([A-Z]{2})">', html)
    assert ufs
    for uf in ufs:
        j = json.loads((SITE / f'dados/locais/{uf}.json').read_text(encoding='utf-8'))
        assert j['uf'] == uf and len(j['colunas']) == 12 and all(len(r) == 12 for r in j['locais'])


def test_manifesto_da_edicao():
    ed = json.loads((SITE / 'dados/edicao.json').read_text(encoding='utf-8'))
    assert ed['edicao'] and ed['parametros']['MIN_PP'] == 5.0 and ed['ufs']
