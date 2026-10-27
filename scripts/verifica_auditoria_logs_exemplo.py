"""Confere achados de uma auditoria externa sobre os 11 logs de relatorios/logs_exemplo.

1) Frequencia de base: em amostra aleatoria de urnas de cada pleito (logs do HD), quantas tem
   cada mensagem apontada como achado. Mensagem rara numa urna comum e diferente de mensagem
   que aparece em boa parte das urnas.
2) Mesma frequencia entre as urnas de contingencia que recuperaram a MV (lista do relatorio de integridade).
3) Reconciliacao log x boletim de urna das 11 secoes, por cargo quando o BU por cargo esta no HD.
Saida: relatorios/logs_exemplo/verificacao_*.csv
"""
import random
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from auditabr import logs  # noqa: E402
from export_logs_exemplo import pasta_logs  # noqa: E402

OUT = ROOT / 'relatorios' / 'logs_exemplo'
N = 300
MSG = {
    'A-001 log corrompido na ME': 'Identificado arquivo de log corrompido na ME',
    'A-002 habilitacao sem mesario identificado': 'Não é possível associar a habilitação a um mesário',
    'A-003 problema ao desmontar a MR': 'Problema ao desmontar a MR',
    'A-005 codigo de reinicio conferido': 'Código de reinício conferido',
    'A-006 monitoramento de alimentacao suspenso': 'Suspenso monitoramento de alimentação',
    'urna ligada na bateria interna': 'Urna operando na bateria interna',
}
FIM = re.compile(r'Gerando arquivo de resultado \[\.?log(jez|\.jez)\] \+ \[Início\]')


def perfil(path):
    t = logs.read_log(path).decode('latin-1').splitlines()
    r = {k: sum(m in x for x in t) for k, m in MSG.items()}
    col3 = Counter(x.split('\t')[2] for x in t if x.count('\t') >= 5)
    r['col3'] = col3.most_common(1)[0][0] if col3 else None
    r['termina_gerando_log'] = bool(t) and bool(FIM.search(t[-1]))
    mod = next((x.split('Modelo de Urna: ')[1].split('\t')[0] for x in t if 'Modelo de Urna: ' in x), None)
    r['modelo'] = mod
    return r


def resumo(df, grupo):
    rows = []
    for g, d in df.groupby(grupo):
        row = {grupo: g, 'urnas': len(d)}
        for k in MSG:
            row[k + ' (% urnas)'] = round(100 * (d[k] > 0).mean(), 1)
        row['termina em "Gerando [log.jez] Início" (%)'] = round(100 * d.termina_gerando_log.mean(), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    df = pd.read_parquet(ROOT / 'relatorios/integridade/integridade_todas_urnas.parquet',
                         columns=['eleicao', 'uf', 'log_nome', 'log_local', 'cert_cn'])
    df = df[df.log_local.eq(True)]
    random.seed(20261027)
    amostra = []
    for el, d in df.groupby('eleicao'):
        amostra.append(d.sample(N, random_state=20261027))
    am = pd.concat(amostra)
    rows = []
    for r in am.itertuples():
        try:
            p = perfil(pasta_logs(r.eleicao, r.uf) / r.log_nome)
        except Exception as exc:  # noqa: BLE001
            p = {'erro': repr(exc)[:80]}
        rows.append({'eleicao': r.eleicao, 'uf': r.uf, 'log_nome': r.log_nome, 'cert_cn': r.cert_cn, **p})
    a = pd.DataFrame(rows)
    a.to_csv(OUT / 'verificacao_amostra_urnas.csv', index=False, sep=';', encoding='utf-8-sig')
    base = resumo(a.dropna(subset=['modelo']), 'eleicao')
    base.to_csv(OUT / 'verificacao_frequencia_base.csv', index=False, sep=';', encoding='utf-8-sig')
    print(base.T.to_string())
    a22 = a[a.eleicao.str.startswith('2022')]
    print('\n2022: coluna 3 mais comum por modelo')
    print(a22.groupby('modelo').col3.agg(lambda s: s.value_counts().head(3).to_dict()).to_string())
    print('\n2024/2026: coluna 3 == numero do certificado da urna:',
          (a[~a.eleicao.str.startswith('2022')].apply(lambda r: str(r.col3).lstrip('0') == str(r.cert_cn)[4:].lstrip('0'), axis=1)).mean())

    div = pd.read_excel(ROOT / 'relatorios/integridade/INTEGRIDADE_URNAS.xlsx', sheet_name='urna_divergente')
    rows = []
    for r in div.itertuples():
        p = perfil(pasta_logs(r.eleicao, r.uf) / r.log_nome)
        rows.append({'eleicao': r.eleicao, 'uf': r.uf, 'log_nome': r.log_nome, 'explicacao': r.explicacao_no_log, **p})
    c = pd.DataFrame(rows)
    c.to_csv(OUT / 'verificacao_urnas_contingencia.csv', index=False, sep=';', encoding='utf-8-sig')
    cc = c[c.explicacao.str.contains('conting')]
    print('\ncontingencia com recuperacao de MV:', len(cc), 'urnas; com "log corrompido na ME":', int((cc[list(MSG)[0]] > 0).sum()))


if __name__ == '__main__':
    main()
