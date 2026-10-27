"""Reconcilia os 11 logs de relatorios/logs_exemplo com o boletim de urna (BU) da mesma secao.

Conta no log, so no dia da eleicao: eleitores com voto computado e confirmacoes por cargo.
Compara com aptos/comparecimento do BU (por cargo quando o BU por cargo esta no HD) e com a
urna efetivada. Para a urna de contingencia usa tambem o log da urna original, que vem arquivado
dentro do pacote oficial (arquivo ...ME.jez).
Saida: relatorios/logs_exemplo/verificacao_log_x_bu.csv
"""
import io
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
OUT = ROOT / 'relatorios' / 'logs_exemplo'
CARGO = re.compile(r'Voto confirmado para \[([^\]]+)\]')


def conta(linhas, dia):
    d = [x.split('\t') for x in linhas if x.startswith(dia) and x.count('\t') >= 5]
    r = {'log_computados': sum(f[4] == 'O voto do eleitor foi computado' for f in d)}
    for f in d:
        m = CARGO.match(f[4])
        if m:
            r[f'log_{m[1]}'] = r.get(f'log_{m[1]}', 0) + 1
    return r


def bu_por_cargo(uf, el, mun, zona, sec):
    p = R / 'estados' / uf / el / 'bu.parquet'
    if uf == 'BA' and el in ('2022-t1', '2026-t1'):
        p = R / 'bahia-presidente-2022-2026' / el / 'bu.parquet'
    if not p.exists():
        return None
    b = pd.read_parquet(p, columns=['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'DS_CARGO_PERGUNTA', 'QT_APTOS',
                                    'QT_COMPARECIMENTO', 'NR_URNA_EFETIVADA', 'DT_ABERTURA', 'DT_ENCERRAMENTO'])
    x = b[(b.CD_MUNICIPIO.astype(int) == int(mun)) & (b.NR_ZONA.astype(int) == int(zona)) & (b.NR_SECAO.astype(int) == int(sec))]
    return x.drop_duplicates('DS_CARGO_PERGUNTA')


def bu_secao(uf, el, mun, zona, sec):
    if el == '2026-t2':
        b = pd.read_parquet(R / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet',
                            columns=['uf', 'municipality', 'zone', 'section', 'e6258_aptos', 'e6258_comparecimento', 'opening', 'closing'])
        x = b[(b.uf == uf) & (b.municipality.astype(int) == int(mun)) & (b.zone.astype(int) == int(zona)) & (b.section.astype(int) == int(sec))]
        return x.rename(columns={'e6258_aptos': 'aptos', 'e6258_comparecimento': 'comparecimento'})
    p = R / 'piloto-ba-2022-t2' / 'analysis' / 'sections.parquet' if (uf, el) == ('BA', '2022-t2') \
        else R / 'analysis' / 'PREFEITO' / uf / el / 'sections.parquet'
    s = pd.read_parquet(p)
    x = s[(s.municipality.astype(int) == int(mun)) & (s.zone.astype(int) == int(zona)) & (s.section.astype(int) == int(sec))]
    return x.rename(columns={'eligible': 'aptos', 'attendance': 'comparecimento'}).drop_duplicates('member' if 'member' in x else None)


def main():
    ix = pd.read_csv(OUT / 'indice.csv', sep=';', dtype=str)
    rows = []
    for r in ix.itertuples():
        linhas = (OUT / r.arquivo).read_text(encoding='utf-8').splitlines()
        dia = linhas[-1][:10]
        row = {'n': int(r.n), 'eleicao': r.eleicao, 'uf': r.uf, 'mun': r.municipio_tse, 'zona': r.zona, 'secao': r.secao,
               'dia': dia, 'urna_do_log': linhas[0].split('\t')[2]}
        if r.n == '11':  # contingencia: votos estao no log da urna original arquivado no pacote
            z = zipfile.ZipFile(OUT / 'originais_jez' / r.arquivo_original)
            me = next(n for n in z.namelist() if n.endswith('ME.jez'))
            orig = zipfile.ZipFile(io.BytesIO(z.read(me))).read('logd.dat').decode('latin-1').splitlines()
            row['urna_do_log'] += ' (contingência); original ' + orig[0].split('\t')[2]
            linhas = orig
        row.update(conta(linhas, dia))
        bc = bu_por_cargo(r.uf, r.eleicao, r.municipio_tse, r.zona, r.secao)
        if bc is not None and len(bc):
            row['bu_urna_efetivada'] = int(bc.NR_URNA_EFETIVADA.iloc[0])
            row['bu_abertura'] = str(bc.DT_ABERTURA.iloc[0])
            row['bu_encerramento'] = str(bc.DT_ENCERRAMENTO.iloc[0])
            for c in bc.itertuples():
                row[f'bu_aptos_{c.DS_CARGO_PERGUNTA}'] = int(c.QT_APTOS)
                row[f'bu_comparecimento_{c.DS_CARGO_PERGUNTA}'] = int(c.QT_COMPARECIMENTO)
        else:
            s = bu_secao(r.uf, r.eleicao, r.municipio_tse, r.zona, r.secao)
            if len(s):
                row['bu_aptos'] = int(s.aptos.iloc[0])
                row['bu_comparecimento'] = int(s.comparecimento.iloc[0])
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / 'verificacao_log_x_bu.csv', index=False, sep=';', encoding='utf-8-sig')
    pd.set_option('display.width', 250)
    for row in rows:
        print({k: v for k, v in row.items() if pd.notna(v)})


if __name__ == '__main__':
    main()
