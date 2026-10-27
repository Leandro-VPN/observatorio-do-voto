"""Comparacao entre os dois canais publicos do TSE, por amostra aleatoria de urnas.

Canal 1: dados abertos (zip "arquivos transmitidos para totalizacao") -> logs guardados no HD.
Canal 2: sistema de resultados (resultados.tse.jus.br/oficial/eleAAAA/arquivo-urna/<pleito>/dados/...).
Para cada urna sorteada: baixa o log e o manifesto do canal 2, compara byte a byte com o log do HD,
confere o manifesto do canal 2 (hash + assinatura) contra o log do HD e registra quantas versoes
(hashes) o sistema de resultados lista para a secao (retransmissao).
Saida: research/integridade/resultado/canais.parquet
"""
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
import integridade_lib as I  # noqa: E402
import t2_2026_collect as T  # noqa: E402

NAME = re.compile(r'^o0*(?P<pleito>\d+)(?P<uf>[a-z]{2})(?P<mun>\d{5})(?P<zone>\d{4})(?P<sec>\d{4})-log\.jez$')
YEAR = {'452': 2024, '453': 2024, '3220': 2026}
PER_ROOT = 250
OUT = ROOT / 'research' / 'integridade' / 'resultado' / 'canais.parquet'


def roots():
    rs = []
    for p in sorted((ROOT / 'research').glob('estados/*/2026-t1')) + sorted((ROOT / 'research').glob('municipais/*/2024-t*')) \
            + [ROOT / 'research' / 'bahia-presidente-2022-2026' / '2026-t1']:
        if (p / 'logs').exists():
            rs.append(p)
    return rs


def job(args):
    root, name = args
    m = NAME.match(name)
    row = {'raiz': str(root.relative_to(ROOT / 'research')), 'log_nome': name}
    if not m:
        row['erro'] = 'nome fora do padrao'
        return row
    pl, uf, mu, z, s = m['pleito'], m['uf'], m['mun'], m['zone'], m['sec']
    base = f'https://resultados.tse.jus.br/oficial/ele{YEAR[pl]}/arquivo-urna/{pl}/dados/{uf}/{mu}/{z}/{s}'
    aux = T.get(f'{base}/p{int(pl):06d}-{uf}-m{mu}-z{z}-s{s}-aux.json')
    if not aux:
        row['erro'] = 'aux indisponivel'
        return row
    hs = aux.get('hashes', [])
    row['n_hashes'] = len(hs)
    row['status_hashes'] = '|'.join(str(h.get('st')) for h in hs)
    lp = root / 'logs' / name
    if not lp.exists():
        row['erro'] = 'log nao esta no HD'
        return row
    local = lp.read_bytes()
    found = False
    for h in reversed(hs):  # procura a versao que contem este log
        arq = {a['tp']: a['nm'] for a in h.get('arq', [])}
        if arq.get('log') != name:
            continue
        remote = T.get(f'{base}/{h["hash"]}/{name}', kind='bytes')
        vname = next((a['nm'] for a in h['arq'] if a['nm'].endswith('-vota.vsc')), None)
        man = T.get(f'{base}/{h["hash"]}/{vname}', kind='bytes') if vname else None
        row['versao_usada'] = hs.index(h) + 1
        row['log_canal2_baixado'] = remote is not None
        row['log_canal2_igual_hd'] = (remote == local) if remote is not None else None
        if man:
            r = I.check_urn(man, {'log': local})
            row.update({k: r.get(k) for k in ('manifest_ok', 'cert_cn', 'cert_emissor', 'cadeia_ok', 'log_hash_ok', 'log_assinatura_ok')})
        found = True
        break
    if not found:
        row['erro'] = 'log do HD nao listado no sistema de resultados'
    return row


def main():
    random.seed(20261026)
    tasks = []
    for r in roots():
        import json
        inv = json.loads((r / 'remote-inventory.json').read_text(encoding='utf-8'))
        names = sorted({m['name'] for e in inv for m in e.get('members', []) if m['name'].endswith('-log.jez')})
        tasks += [(r, n) for n in random.sample(names, min(PER_ROOT, len(names)))]
    print('urnas sorteadas', len(tasks), 'raizes', len(roots()), flush=True)
    t0 = time.monotonic()
    rows = []
    with ThreadPoolExecutor(8) as ex:
        for k, row in enumerate(ex.map(job, tasks), 1):
            rows.append(row)
            if k % 500 == 0:
                print(k, f'{(time.monotonic() - t0) / 60:.1f} min', flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(OUT, index=False)
    print(df.drop(columns=['log_nome']).groupby('raiz').agg(n=('raiz', 'size')).shape, flush=True)
    for c in ('log_canal2_igual_hd', 'log_hash_ok', 'log_assinatura_ok', 'cadeia_ok', 'n_hashes', 'erro'):
        if c in df:
            print(c, df[c].value_counts(dropna=False).to_dict(), flush=True)


if __name__ == '__main__':
    main()
