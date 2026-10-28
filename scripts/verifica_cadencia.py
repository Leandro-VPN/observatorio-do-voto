"""Cadencia de atendimento por secao (1o turno 2026) e habilitacao manual por tipo de liberacao.

Grupos (secao pode estar em mais de um):
  G1 acima_limiar   - secoes com comportamento cujo resultado difere das vizinhas do mesmo predio
                      (>= 5 p.p. e |z| >= 2): as 664 do estudo de locais
  G2 abaixo_limiar  - demais secoes com comportamento comparadas no mesmo predio
  G3 vizinhas       - secoes comuns (sem comportamento) dos mesmos predios do G1
  G4 amostra        - amostra aleatoria de 5.000 secoes do pleito (base de comparacao)
  local_alta        - todas as secoes dos 451 locais de prioridade alta
Para cada secao: atendimentos do log (cadencia_lib) e metricas por periodo (antes das 16h / 16h em
diante). O limiar de "atendimento muito curto" e o percentil 5 do tempo de atendimento na amostra G4.
Saidas em relatorios/verificacoes/cadencia/:
  atendimentos.parquet       um registro por voto (sem identificacao de pessoa)
  secoes_cadencia.parquet    metricas por secao e grupos
  resumo_grupos.csv          medianas por grupo e periodo
  pares_mesmo_predio.csv     G1 contra as vizinhas G3 do mesmo predio
  locais_alta_habilitacao_manual.csv  liberacoes manuais por tipo nos locais de prioridade alta
"""
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from auditabr.logs import read_log  # noqa: E402
from cadencia_lib import atendimentos, metricas  # noqa: E402
from export_logs_exemplo import pasta_logs  # noqa: E402

OUT = ROOT / 'relatorios' / 'verificacoes' / 'cadencia'
EL, DIA = '2026-t1', '04/10/2026'
CSV = dict(sep=';', encoding='utf-8-sig', low_memory=False, decimal=',')
NOME = re.compile(r'^o0*\d+(?:-|[a-z]{2})(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})')
SEC = ['municipality', 'zone', 'section']
LOC = ['municipality', 'zone', 'voting_place']
TIPOS = {'biometrica': 0, 'manual_identificado': 1, 'manual_nao_associado': 2, 'manual_outro': 3, 'sem_biometria': 4, 'outro': 5}


def grupos():
    ind = pd.read_parquet(ROOT / 'relatorios/fiscalizacao/secoes_indicadores_P2026.parquet',
                          columns=['uf'] + SEC + ['voting_place', 'place_name', 'municipality_name', 'vote_events', 'attendance'])
    for c in SEC + ['voting_place']:
        ind[c] = ind[c].astype(int)
    comp = pd.read_csv(ROOT / 'relatorios/fiscalizacao/varredura/secoes_com_comportamento_por_eleicao.csv', **CSV)
    comp = comp[comp.eid == 'P2026']
    for c in SEC + ['voting_place']:
        comp[c] = comp[c].astype(int)
    loc = comp[comp.cmp_level == 'local']
    g1 = loc[loc.real.astype(bool)][SEC].assign(g1=True)
    g2 = loc[~loc.real.astype(bool)][SEC].assign(g2=True)
    pred_g1 = loc[loc.real.astype(bool)][LOC].drop_duplicates()
    com_comp = comp[SEC].assign(_c=True)
    viz = ind.merge(pred_g1, on=LOC).merge(com_comp, on=SEC, how='left')
    g3 = viz[viz._c.isna()][SEC].assign(g3=True)
    g4 = ind.sample(5000, random_state=20261028)[SEC].assign(g4=True)
    alta = pd.read_csv(ROOT / 'relatorios/fiscalizacao/varredura/locais_risco.csv', **CSV)
    alta = alta[alta.prioridade_observacao == 'alta'][LOC].astype(int).drop_duplicates()
    ga = ind.merge(alta, on=LOC)[SEC].assign(local_alta=True)
    s = ind
    for g in (g1, g2, g3, g4, ga):
        s = s.merge(g, on=SEC, how='left')
    for c in ('g1', 'g2', 'g3', 'g4', 'local_alta'):
        s[c] = s[c].fillna(False).astype(bool)
    return s[s[['g1', 'g2', 'g3', 'g4', 'local_alta']].any(axis=1)].copy()


def mapa_logs():
    d = pd.read_parquet(ROOT / 'relatorios/integridade/integridade_todas_urnas.parquet', columns=['eleicao', 'uf', 'log_nome', 'log_local'])
    d = d[(d.eleicao == EL) & d.log_local.eq(True)].copy()
    m = d.log_nome.str.extract(NOME)
    d['municipality'], d['zone'], d['section'] = m['mun'].astype(float), m['zona'].astype(float), m['sec'].astype(float)
    d = d.dropna(subset=SEC)
    for c in SEC:
        d[c] = d[c].astype(int)
    return d.drop_duplicates(SEC)[['uf', 'log_nome'] + SEC]


def job(args):
    uf, nome, mun, zona, sec = args
    try:
        text = read_log(pasta_logs(EL, uf) / nome).decode('latin-1')
        ats, rev = atendimentos(text, DIA)
        return (mun, zona, sec), ats, rev, None
    except Exception as exc:  # noqa: BLE001
        return (mun, zona, sec), [], 0, repr(exc)[:120]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = grupos()
    lg = mapa_logs()
    s = s.merge(lg.rename(columns={'uf': 'uf_log'}), on=SEC, how='left')
    print('secoes:', len(s), '| com log no HD:', int(s.log_nome.notna().sum()),
          '| G1', int(s.g1.sum()), 'G2', int(s.g2.sum()), 'G3', int(s.g3.sum()), 'G4', int(s.g4.sum()), 'alta', int(s.local_alta.sum()), flush=True)
    todo = [(r.uf_log, r.log_nome, r.municipality, r.zone, r.section) for r in s[s.log_nome.notna()].itertuples()]
    rows, info = [], {}
    with ProcessPoolExecutor(6) as ex:
        for k, (key, ats, rev, err) in enumerate(ex.map(job, todo, chunksize=20), 1):
            info[key] = (rev, err)
            for a in ats:
                rows.append((*key, a['t_id'] if a['t_id'] is not None else -1, a['t_hab'] if a['t_hab'] is not None else -1,
                             a['t_voto'], TIPOS[a['tipo']], a['tent'], hash(a['dev']) & 0xffff))
            if k % 2000 == 0:
                print(k, len(todo), flush=True)
    A = pd.DataFrame(rows, columns=SEC + ['t_id', 't_hab', 't_voto', 'tipo', 'tentativas', 'dev'])
    A.to_parquet(OUT / 'atendimentos.parquet', index=False)

    amostra = A.merge(s[s.g4][SEC], on=SEC)
    at = (amostra.t_voto - amostra.t_id)[amostra.t_id >= 0]
    rapido = float(np.percentile(at, 5))
    print('limiar de atendimento muito curto (P5 da amostra):', rapido, 's', flush=True)

    inv = {v: k for k, v in TIPOS.items()}
    met = []
    for key, g in A.groupby(SEC, sort=False):
        ats = [{'dev': d_, 't_id': None if ti < 0 else ti, 't_hab': None if th < 0 else th, 't_voto': tv, 'tipo': inv[tp], 'tent': te}
               for ti, th, tv, tp, te, d_ in zip(g.t_id, g.t_hab, g.t_voto, g.tipo, g.tentativas, g.dev)]
        rev, err = info.get(key, (0, None))
        met.append({**dict(zip(SEC, key)), **metricas(ats, rapido), 'reversoes_relogio': rev})
    M = pd.DataFrame(met)
    S = s.merge(M, on=SEC, how='left')
    S['erro_log'] = [info.get((r.municipality, r.zone, r.section), (0, None))[1] for r in S.itertuples()]
    S['limiar_rapido_s'] = rapido
    S['frac_manual_nao_associado'] = S.n_manual_nao_associado / (S.n_manual_identificado + S.n_manual_nao_associado + S.n_manual_outro).replace(0, np.nan)
    S.to_parquet(OUT / 'secoes_cadencia.parquet', index=False)

    cols = ['votos_log', 'dia_atend_med', 'tarde_atend_med', 'dia_cabine_med', 'tarde_cabine_med', 'dia_interv_med', 'tarde_interv_med',
            'dia_interv_cv', 'tarde_interv_cv', 'dia_ocioso_med', 'tarde_ocioso_med', 'dia_frac_rapido', 'tarde_frac_rapido',
            'tarde_maior_sequencia_rapida', 'atend_med_biometrica', 'atend_med_manual_identificado', 'atend_med_manual_nao_associado',
            'frac_manual_nao_associado']
    R = []
    for g, lab in (('g1', 'G1 acima do limiar (664)'), ('g2', 'G2 com comportamento, abaixo do limiar'), ('g3', 'G3 vizinhas comuns do G1'),
                   ('g4', 'G4 amostra aleatória'), ('local_alta', 'locais de prioridade alta')):
        sub = S[S[g] & S.votos_log.notna()]
        R.append({'grupo': lab, 'secoes': len(sub), 'votos': int(sub.votos_log.sum()),
                  'manuais': int((sub.n_manual_identificado + sub.n_manual_nao_associado + sub.n_manual_outro).sum()),
                  'manuais_nao_associados': int(sub.n_manual_nao_associado.sum()),
                  **{f'mediana_{c}': sub[c].median() for c in cols}})
    R = pd.DataFrame(R)
    R.to_csv(OUT / 'resumo_grupos.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')

    # pares no mesmo predio: cada secao G1 contra a mediana das vizinhas G3 do predio
    g1 = S[S.g1 & S.votos_log.notna()]
    g3 = S[S.g3 & S.votos_log.notna()].groupby(LOC)[cols].median().add_suffix('_vizinhas').reset_index()
    P = g1.merge(g3, on=LOC)
    for c in ('tarde_interv_cv', 'tarde_atend_med', 'tarde_frac_rapido', 'tarde_cabine_med', 'dia_atend_med'):
        P[f'dif_{c}'] = P[c] - P[f'{c}_vizinhas']
    P.to_csv(OUT / 'pares_mesmo_predio.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')

    # liberacoes manuais por tipo nos locais de prioridade alta
    la = S[S.local_alta & S.votos_log.notna()].groupby(['uf'] + LOC + ['municipality_name', 'place_name']).agg(
        secoes=('section', 'size'), votos=('votos_log', 'sum'), manual_identificado=('n_manual_identificado', 'sum'),
        manual_nao_associado=('n_manual_nao_associado', 'sum'), manual_outro=('n_manual_outro', 'sum'),
        manual_nao_associado_apos_16h=('n_manual_nao_associado_tarde', 'sum'),
        secoes_g1=('g1', 'sum')).reset_index()
    la['manuais'] = la.manual_identificado + la.manual_nao_associado + la.manual_outro
    la['pct_manual_nao_associado'] = (100 * la.manual_nao_associado / la.manuais.replace(0, np.nan)).round(1)
    la.sort_values(['manual_nao_associado', 'manuais'], ascending=False).to_csv(
        OUT / 'locais_alta_habilitacao_manual.csv', index=False, sep=';', encoding='utf-8-sig', decimal=',')

    pd.set_option('display.width', 250)
    print(R.T.to_string())
    print('\npares G1 x vizinhas (mesmo predio):', len(P))
    for c in ('tarde_interv_cv', 'tarde_atend_med', 'tarde_frac_rapido', 'tarde_cabine_med', 'dia_atend_med'):
        x = P[f'dif_{c}'].dropna()
        print(f'  {c}: mediana da diferenca {x.median():.3f} | G1 acima da vizinhanca em {100 * (x > 0).mean():.0f}% (n={len(x)})')
    print('\nlocais alta: total manuais', int(la.manuais.sum()), '| nao associados', int(la.manual_nao_associado.sum()))


if __name__ == '__main__':
    main()
