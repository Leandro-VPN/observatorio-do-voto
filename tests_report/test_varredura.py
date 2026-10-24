"""Testes da varredura por local (funções puras de scripts/make_varredura_locais.py) com dados sintéticos pequenos. Rodam no ambiente .venv-report."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('UF', 'BA')
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / 'scripts'))
V = pytest.importorskip('make_varredura_locais')


def secoes(place, n, beh_idx=(), share_a=40.0, votes=300, mun='BA|1', uf='BA', jitter=0.0, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        sa = share_a + (rng.normal(0, jitter) if jitter else 0)
        rows.append(dict(uf=uf, municipality=int(mun.split('|')[1]), municipality_name='CIDADE', zone=1, section=i + 1, voting_place=place.split('|')[-1], place_name='ESCOLA', place=place, mun=mun,
                         share_a=sa, share_b=100 - sa - 5, valid_votes=votes, votes_a=sa / 100 * votes, eligible=votes + 50, turnout=0.8, after_17_recorded=0, after_17_manual_sequence=0,
                         BEH=i in beh_idx, LATE=i in beh_idx, MANUAL=False))
    return pd.DataFrame(rows)


def test_niveis_de_comparacao():
    d = pd.concat([secoes('BA|1|1|100', 5, beh_idx=(0,)),            # 4 pares → local
                   secoes('BA|1|1|200', 3, beh_idx=(0,)),            # 2 pares → poucos pares
                   secoes('BA|1|1|300', 1, beh_idx=(0,)),            # seção única → município
                   secoes('BA|1|1|400', 2, beh_idx=(0, 1))], ignore_index=True)  # prédio sem par comum → município
    d['section'] = range(1, len(d) + 1)
    out = V.compare(d)
    b = out[out.BEH].set_index('place')
    assert b.loc['BA|1|1|100', 'cmp_level'] == 'local' and b.loc['BA|1|1|100', 'cmp_n'] == 4
    assert b.loc['BA|1|1|200', 'cmp_level'] == 'local (poucos pares)'
    assert b.loc['BA|1|1|300', 'cmp_level'] == 'município' and b.loc['BA|1|1|300', 'origem_municipio'] == 'seção única'
    assert (b.loc['BA|1|1|400', 'cmp_level'] == 'município').all() and (b.loc['BA|1|1|400', 'origem_municipio'] == 'prédio sem par comum').all()


def test_diferenca_acima_do_limiar_e_direcao():
    d = secoes('BA|1|1|100', 8, beh_idx=(0,), jitter=1.0, seed=1)
    d.loc[0, 'share_a'] = 70.0          # seção com comportamento muito acima dos pares (~40%)
    d.loc[0, 'votes_a'] = 0.7 * 300
    out = V.compare(d)
    s = out.iloc[0]
    assert s.cmp_level == 'local' and s.diff_a > 25 and s.real and s.dir == 'A' and np.isfinite(s.z_a)
    # seção igual aos pares não ultrapassa o limiar
    d2 = secoes('BA|1|1|100', 8, beh_idx=(0,), jitter=1.0, seed=2)
    assert not V.compare(d2).iloc[0].real


def test_leave_one_out_nas_comuns():
    d = secoes('BA|1|1|100', 6, beh_idx=(), jitter=2.0, seed=3)
    out = V.compare(d)
    # cada comum é comparada às outras 5 (não a si mesma)
    assert (out.cmp_n == 5).all() and (out.cmp_level == 'local').all()
    assert not np.allclose(out.cmp_a, out.share_a)


def test_pres_x_pref_sem_municipal():
    E = {'P2022': V.compare(secoes('BA|1|1|100', 6, beh_idx=(0,))), 'P2026': V.compare(secoes('BA|1|1|100', 6, beh_idx=(0,)))}
    px, pxp = V.pres_x_pref(E)
    assert set(px.eid) == {'P2022', 'P2026'} and pxp.empty      # sem M2024 não há par estrito
    hist = V.section_history(E)
    assert (hist.padrao_comportamento == 'só presidenciais (sem dado municipal)').all()


def test_pontuacao_operacional_mais_resultado():
    d = secoes('BA|1|1|100', 6, beh_idx=(0, 1), jitter=1.0, seed=4)
    d.loc[0, 'share_a'], d.loc[0, 'votes_a'] = 75.0, 0.75 * 300
    d.loc[0, 'after_17_recorded'] = 600
    E = {e: V.compare(d.copy()) for e in ('P2022', 'P2026', 'M2024')}
    hist = V.section_history(E)
    pl = V.places_table(E, hist)
    assert (pl.pontos == pl.pts_operacional + pl.pts_resultado).all()
    assert set(pl.prioridade_observacao) <= {'alta', 'média', 'baixa'}
    assert ((pl.pontos >= 45) == (pl.prioridade_observacao == 'alta')).all()
    assert (pl.nivel_risco == pl.prioridade_observacao).all()
    assert pl.sinal_resultado.iloc[0] in {'seções', 'seções + local'}
