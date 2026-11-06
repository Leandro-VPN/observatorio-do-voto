"""Testes do relatório da varredura forense: tabelas-resumo puras e montagem do PDF/XLSX/edicao.json numa pasta temporária."""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('UF', 'BA')
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / 'scripts'))
M = pytest.importorskip('make_varredura_forense_report')
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)


def _reg():
    return pd.DataFrame([
        dict(id='A-C2-001', dossie='dossies/A-C2-001.md', camada='C2', titulo='pacote sem log intermediário', pleito='2026-t2', cargo='presidente',
             uf='MA', escopo='2 seções', tipo='dados', efeito='188 × 224', efeito_num=-36, materialidade_min=13, materialidade_max=36,
             margem_referencia='nacional 6,1 M', status='PLAUSIVEL-EXPLICAVEL', status_sugerido='PLAUSÍVEL', exploratorio=True,
             artefato_excluido='leitor aninhado', controles='2022: 0 casos', hipoteses='H1 | H2', dados_externos='ata', fonte='a.csv',
             prioridade=1, id_sugerido='x', origem='c2.json', altera_publicado=False, errata='', data='2026-11-05'),
        dict(id='A-C4-001', dossie='dossies/A-C4-001.md', camada='C4', titulo='BH 39/168 só no T2', pleito='2026-t1', cargo='presidente',
             uf='MG', escopo='1 seção', tipo='dados', efeito='-130 votos', efeito_num=-130, materialidade_min=130, materialidade_max=559,
             margem_referencia='município', status='EXPLICADO', status_sugerido='EXPLICADO', exploratorio=True, artefato_excluido='',
             controles='', hipoteses='', dados_externos='', fonte='b.csv', prioridade=2, id_sugerido='y', origem='c4.json',
             altera_publicado=False, errata='', data='2026-11-05')])


def _chk():
    return pd.DataFrame([dict(camada='C2', id='C2-01', status='feita', resultado='8 seções documentadas', numeros='8', arquivos='a.csv', motivo='', origem='c2.json'),
                         dict(camada='C2', id='C2-02', status='nao_feita', resultado='', numeros='', arquivos='', motivo='passada de logs', origem='c2.json'),
                         dict(camada='C4', id='C4-01', status='parcial', resultado='T2 fechou; T1 com 2 municípios', numeros='5.569/5.571', arquivos='b.csv', motivo='', origem='c4.json')])


def test_resumos():
    rc = M.resumo_checagens(_chk())
    assert list(rc.columns) == ['camada', 'feita', 'parcial', 'nao_feita', 'total'] and rc.set_index('camada').loc['total', 'total'] == 3
    assert rc.set_index('camada').loc['C2', 'nao_feita'] == 1
    ra = M.resumo_achados(_reg())
    assert list(ra.status)[:2] == ['PLAUSIVEL-EXPLICAVEL', 'EXPLICADO'] and ra.set_index('status').loc['total', 'total'] == 2
    assert M.n(1234567) == '1.234.567' and M.n(None) == '—' and M.n(1.5, 1) == '1,5'
    assert M.versao_protocolo('# Protocolo — versão 1.0\n') == '1.0'


def test_monta_pdf_xlsx_manifesto(tmp_path):
    (tmp_path / 'C2').mkdir()
    _reg().to_csv(tmp_path / 'registro_de_achados.csv', **CSV)
    _chk().to_csv(tmp_path / 'checagens_feitas.csv', **CSV)
    pd.DataFrame([dict(camadas='C2,C3', dado='ata da seção', para_que='fechar', fonte_possivel='TRE', achados='A-C2-001')]).to_csv(
        tmp_path / 'dados_externos_necessarios.csv', **CSV)
    (tmp_path / 'PROTOCOLO.md').write_text('# Protocolo da varredura forense — versão 1.0\n', encoding='utf-8')
    (tmp_path / 'C2' / 'C2_resumo.json').write_text(json.dumps({'notas': 'nota do agente'}), encoding='utf-8')
    assert M.main(tmp_path) == 0
    man = json.loads((tmp_path / 'edicao.json').read_text(encoding='utf-8'))
    assert man['protocolo_versao'] == '1.0' and set(man['entradas']) == {'registro_de_achados.csv', 'checagens_feitas.csv', 'dados_externos_necessarios.csv'}
    assert (tmp_path / 'RELATORIO_VARREDURA.xlsx').stat().st_size > 5000
    fitz = pytest.importorskip('fitz')
    doc = fitz.open(tmp_path / 'RELATORIO_VARREDURA.pdf')
    texto = ''.join(p.get_text() for p in doc)
    assert doc.page_count >= 4
    for trecho in ['O que foi checado', 'A-C2-001', 'pacote sem log', 'ata da seção', 'nota do agente', 'não indica irregularidade']:
        assert trecho in texto, trecho
