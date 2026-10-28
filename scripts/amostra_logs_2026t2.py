"""Logs do 2o turno de 2026 para as UFs que ainda nao tem log no HD, no mesmo desenho de amostra das demais:
todas as secoes que encerraram a partir de 17h10 (Brasilia) + amostra aleatoria de 3% das que encerraram antes.

Le cada log direto do zip oficial dos dados abertos (HTTP Range, CRC conferido) e grava em
research/segundo_turno_2026/logs/<UF>/ (mesmo nome do zip; o download completo depois pula o arquivo).
A lista da amostra aleatoria fica em research/segundo_turno_2026/amostra_controle_dados_abertos.csv
(log_why = control), usada por scripts/ultimo_voto_2026t2.py para os pesos.
"""
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
import baixa_pais as B  # noqa: E402

T2 = ROOT / 'research' / 'segundo_turno_2026'
FECH = ROOT / 'relatorios' / 'verificacoes' / 'fechamento_2026t2' / 'secoes_fechamento_recebimento.parquet'
UFS = ['AC', 'AL', 'AM', 'AP', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'RO', 'RR', 'TO']
URL = 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_2t_{}.zip'
KEY = ['uf', 'municipality', 'zone', 'section']


def main():
    s = pd.read_parquet(FECH, columns=KEY + ['encerramento'])
    s = s[s.uf.isin(UFS)].copy()
    s['tarde'] = s.encerramento >= pd.Timestamp('2026-10-25 17:10')
    rng = random.Random(20261025)
    ctrl = []
    for uf, g in s.groupby('uf'):
        resto = g[~g.tarde]
        k = max(1, round(.03 * len(resto)))
        ctrl.append(resto.loc[rng.sample(list(resto.index), k)])
    C = pd.concat(ctrl).assign(log_why='control')[KEY + ['log_why']]
    C.to_csv(T2 / 'amostra_controle_dados_abertos.csv', index=False, sep=';', encoding='utf-8-sig')
    alvo = pd.concat([s[s.tarde][KEY], C[KEY]]).drop_duplicates()
    alvo['chave'] = alvo.uf.str.lower() + alvo.municipality.astype(int).astype(str).str.zfill(5) + alvo.zone.astype(int).astype(str).str.zfill(4) \
        + alvo.section.astype(int).astype(str).str.zfill(4)
    print('secoes alvo:', len(alvo), '| encerraram 17h10+:', int(s.tarde.sum()), '| amostra:', len(C), flush=True)
    for uf, g in alvo.groupby('uf'):
        url = URL.format(uf)
        size, ulist = B.indice(url)
        quer = set(g.chave)
        dest = T2 / 'logs' / uf
        dest.mkdir(parents=True, exist_ok=True)
        jobs = []
        for u in ulist:
            m = next((m for m in u['members'] if m['type'] == 'log'), None)
            if m and u['stem'][-15:] in quer:  # stem = o03221 + uf + municipio(5) + zona(4) + secao(4)
                if not ((dest / m['name']).exists() and (dest / m['name']).stat().st_size == m['size']):
                    jobs.append(m)

        def um(m):
            b = B._read(url, m['offset'], min(size, m['offset'] + m['csize'] + 1024))
            (dest / m['name']).write_bytes(B.member_bytes(b, m['offset'], m))
            return 1
        with ThreadPoolExecutor(8) as ex:
            ok = sum(ex.map(um, jobs))
        print(uf, 'alvo', len(g), '| baixados', ok, flush=True)


if __name__ == '__main__':
    main()
