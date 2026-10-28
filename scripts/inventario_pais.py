"""Inventario dos zips oficiais do TSE (arquivos de urna) para o pais inteiro, sem baixar os zips.

Para cada pleito e UF, le so o diretorio central do zip "bu_imgbu_logjez_rdv_vscmr" (HTTP Range) e
soma, por tipo de arquivo (log, bu, rdv, imgbu, assinatura), quantos arquivos e quantos bytes
(comprimidos, como vem no zip) existem. Compara com o que ja esta no HD (relatorio de integridade).
Saida: relatorios/disco/inventario_zips_pais.csv
"""
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from auditabr.acquisition import RemoteZipReader  # noqa: E402

OUT = ROOT / 'relatorios' / 'disco'
URL = 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/arqurnatot/bu_imgbu_logjez_rdv_vscmr_{ano}_{t}t_{uf}.zip'
UFS = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR',
       'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO', 'ZZ']
PLEITOS = [('2022-t1', 2022, 1), ('2022-t2', 2022, 2), ('2024-t1', 2024, 1), ('2024-t2', 2024, 2),
           ('2026-t1', 2026, 1), ('2026-t2', 2026, 2)]
MEMBER = re.compile(r'^(?P<stem>.+?)(?:\.(?P<a>bu|imgbu|logjez|rdv|vscmr)|-(?P<b>bu|imgbu|log|rdv|vota)\.(?:dat|jez|vsc))$')
TIPO = {'bu': 'bu', 'imgbu': 'imgbu', 'logjez': 'log', 'log': 'log', 'rdv': 'rdv', 'vscmr': 'assinatura', 'vota': 'assinatura'}


def um_zip(args):
    el, ano, t, uf = args
    url = URL.format(ano=ano, t=t, uf=uf)
    row = {'eleicao': el, 'uf': uf, 'url': url}
    try:
        with RemoteZipReader(url, budget=1 << 30) as rz, zipfile.ZipFile(rz) as z:
            row['zip_bytes'] = rz.size
            row['publicado_em'] = rz.headers.get('last-modified') or rz.headers.get('Last-Modified')
            urnas = set()
            for i in z.infolist():
                m = MEMBER.match(Path(i.filename).name)
                if not m:
                    row['outros_arquivos'] = row.get('outros_arquivos', 0) + 1
                    continue
                tp = TIPO[m.group('a') or m.group('b')]
                urnas.add(m.group('stem'))
                row[f'{tp}_arquivos'] = row.get(f'{tp}_arquivos', 0) + 1
                row[f'{tp}_bytes'] = row.get(f'{tp}_bytes', 0) + i.compress_size
            row['urnas'] = len(urnas)
            row['status'] = 'ok'
    except Exception as exc:  # zip inexistente (ex.: DF em 2024, ZZ em municipal) ou ainda nao publicado
        row['status'] = 'sem zip: ' + repr(exc)[:90]
    print(el, uf, row['status'], row.get('urnas', ''), flush=True)
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(el, ano, t, uf) for el, ano, t in PLEITOS for uf in UFS]
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(um_zip, jobs))
    d = pd.DataFrame(rows)
    integ = pd.read_parquet(ROOT / 'relatorios/integridade/integridade_todas_urnas.parquet', columns=['eleicao', 'uf', 'log_local'])
    no_hd = integ[integ.log_local.eq(True)].groupby(['eleicao', 'uf']).size().rename('logs_no_hd').reset_index()
    d = d.merge(no_hd, on=['eleicao', 'uf'], how='left')
    d['logs_no_hd'] = d.logs_no_hd.fillna(0).astype(int)
    d.to_csv(OUT / 'inventario_zips_pais.csv', index=False, sep=';', encoding='utf-8-sig')
    ok = d[d.status == 'ok'].copy()
    gb = lambda c: round(ok[c].fillna(0).sum() / 1e9, 1)  # noqa: E731
    print('\nzips:', len(ok), 'de', len(d), '| urnas:', int(ok.urnas.sum()))
    print('bytes no zip (GB): log', gb('log_bytes'), '| bu', gb('bu_bytes'), '| rdv', gb('rdv_bytes'),
          '| imgbu', gb('imgbu_bytes'), '| assinatura', gb('assinatura_bytes'), '| zip total', gb('zip_bytes'))
    falta = ok[ok.logs_no_hd < ok.log_arquivos.fillna(0) * 0.99]
    print('UF/pleitos sem os logs no HD:', len(falta), '| logs+bu+assinatura faltando (GB):',
          round((falta.log_bytes.fillna(0) + falta.bu_bytes.fillna(0) + falta.assinatura_bytes.fillna(0)).sum() / 1e9, 1))
    print(d[d.status != 'ok'][['eleicao', 'uf', 'status']].to_string(index=False))


if __name__ == '__main__':
    main()
