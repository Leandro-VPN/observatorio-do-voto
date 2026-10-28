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
        assert j['uf'] == uf and len(j['colunas']) == 15 and all(len(r) == 15 for r in j['locais'])
        # kit de campo: todo link aponta para um PDF publicado em site/kit/
        assert all((SITE / r[14]).is_file() for r in j['locais'] if r[14])


def test_versao_em_ingles():
    """site/en/: sem placeholders, links relativos resolvem a partir de site/en/, mesmo painel e link de volta ao português."""
    html = (SITE / 'en/index.html').read_text(encoding='utf-8')
    assert '<html lang="en">' in html and not re.search(r'__[A-Z_]+__', html)
    refs = set(re.findall(r'(?:href|src)="([^"#:]+)"', html))
    missing = [r for r in refs if not (SITE / 'en' / r.split('#')[0]).resolve().exists()]
    assert not missing, missing
    js = (SITE / 'en/app.js').read_text(encoding='utf-8')
    rec_en = json.loads(re.search(r'const records = (\{.*?\});', js, re.S).group(1))
    rec_pt = json.loads(re.search(r'const records = (\{.*?\});', (SITE / 'app.js').read_text(encoding='utf-8'), re.S).group(1))
    assert rec_en == rec_pt
    assert 'href="en/"' in (SITE / 'index.html').read_text(encoding='utf-8')


def test_manifesto_da_edicao():
    ed = json.loads((SITE / 'dados/edicao.json').read_text(encoding='utf-8'))
    assert ed['edicao'] and ed['parametros']['MIN_PP'] == 5.0 and ed['ufs']
