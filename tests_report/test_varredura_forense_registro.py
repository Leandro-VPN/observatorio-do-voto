"""Testes do montador do registro de achados e dos dossiês (dados sintéticos pequenos; ambiente .venv-report)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
R = pytest.importorskip('varredura_forense_registro')


def _resultado(camada, achados, arquivo):
    return dict(camada=camada, checagens=[dict(id=f'{camada}-01', status='feita', resultado_resumo='ok', arquivos=['x.csv'])],
                achados=achados, _arquivo=arquivo)


def _achado(titulo, prio, status, **kw):
    a = dict(id_sugerido='X', titulo=titulo, pleito='2026-t2', escopo='3 seções', efeito='188 × 224', materialidade_min=13,
             materialidade_max=36, status_sugerido=status, fonte=['a.csv', 'b.csv'], prioridade=prio, hipoteses=['H1', 'H2'],
             dados_externos='ata da seção')
    a.update(kw)
    return a


def test_normaliza_status():
    assert R.normaliza_status('PLAUSÍVEL-EXPLICÁVEL') == 'PLAUSIVEL-EXPLICAVEL'
    assert R.normaliza_status('não testável com estes dados') == 'NAO_TESTAVEL'
    assert R.normaliza_status('Explicado') == 'EXPLICADO'
    assert R.normaliza_status('artefato') == 'ARTEFATO'
    assert R.normaliza_status('inexplicado') == 'INEXPLICADO'
    assert R.normaliza_status('') == 'INDETERMINADO'


def test_registro_ids_por_camada_e_prioridade():
    res = [_resultado('C2', [_achado('b', 2, 'EXPLICADO'), _achado('a', 1, 'INEXPLICADO')], 'c2.json'),
           _resultado('C5', [_achado('c', 3, 'ARTEFATO')], 'c5a.json'), _resultado('C5', [_achado('d', 1, 'PLAUSÍVEL')], 'c5b.json')]
    reg = R.monta_registro(res, hoje='2026-11-05')
    assert list(reg.id) == ['A-C2-001', 'A-C2-002', 'A-C5-001', 'A-C5-002']
    assert list(reg.titulo) == ['a', 'b', 'd', 'c']           # prioridade 1 antes; C5 junta os dois arquivos
    assert reg.loc[0, 'status'] == 'INEXPLICADO' and reg.loc[2, 'status'] == 'PLAUSIVEL-EXPLICAVEL'
    assert reg.loc[0, 'dossie'] == 'dossies/A-C2-001.md' and reg.loc[0, 'fonte'] == 'a.csv | b.csv'
    chk = R.monta_checagens(res)
    assert len(chk) == 3 and set(chk.camada) == {'C2', 'C5'}


def test_dados_externos_junta_mapa_e_achados():
    res = [_resultado('C2', [_achado('a', 1, 'INEXPLICADO')], 'c2.json')]
    reg = R.monta_registro(res, hoje='2026-11-05')
    mapas = {'C2': dict(lacunas_de_dados=[dict(dado='Ata da seção', para_que='fechar C2-01', fonte_possivel='TRE')]),
             'C3': dict(lacunas_de_dados=[dict(dado='ata da seção ', para_que='reinícios'), dict(dado='CEFT 2026 T2', para_que='trocas')])}
    ext = R.dados_externos(mapas, reg)
    assert len(ext) == 2                                      # 'ata da seção' deduplicada entre C2, C3 e o achado
    linha = ext[ext.dado.str.lower().str.startswith('ata')].iloc[0]
    assert linha.camadas == 'C2,C3' and 'A-C2-001' in linha.achados and 'TRE' in linha.fonte_possivel


def test_dossie_escrito(tmp_path):
    res = [_resultado('C7', [_achado('vetores idênticos', 2, 'PLAUSÍVEL', controles='2022: 551 pares')], 'c7.json')]
    reg = R.monta_registro(res, hoje='2026-11-05')
    assert R.escreve_dossies(reg, tmp_path) == 1
    txt = (tmp_path / 'A-C7-001.md').read_text(encoding='utf-8')
    assert txt.startswith('# Dossiê A-C7-001 — vetores idênticos')
    for trecho in ['mínimo 13 / máximo 36 votos', '| H1 |', '2022: 551 pares', 'ata da seção', '`a.csv`', 'não é acusação']:
        assert trecho in txt


def test_main_sem_resultados(monkeypatch, tmp_path):
    monkeypatch.setattr(R, 'RES', tmp_path)
    assert R.main() == 1


def test_fluxo_completo_em_pasta_temporaria(monkeypatch, tmp_path):
    (tmp_path / 'res').mkdir()
    (tmp_path / 'mapa').mkdir()
    (tmp_path / 'res' / 'c4.json').write_text(json.dumps(_resultado('C4', [_achado('x', 1, 'EXPLICADO')], 'c4.json')), encoding='utf-8')
    (tmp_path / 'mapa' / 'mapa_C4.json').write_text(json.dumps(dict(lacunas_de_dados=[dict(dado='u.json bruto', para_que='t')])), encoding='utf-8')
    monkeypatch.setattr(R, 'RES', tmp_path / 'res')
    monkeypatch.setattr(R, 'MAPA', tmp_path / 'mapa')
    monkeypatch.setattr(R, 'OUT', tmp_path / 'out')
    assert R.main() == 0
    assert (tmp_path / 'out' / 'registro_de_achados.csv').exists() and (tmp_path / 'out' / 'dossies' / 'A-C4-001.md').exists()
    assert (tmp_path / 'out' / 'dados_externos_necessarios.csv').read_text(encoding='utf-8-sig').count('\n') == 3   # cabeçalho + 2 linhas
