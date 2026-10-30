"""Presidente 2026, 1o x 2o turno por secao: viradas, secoes com 100% para um candidato e crescimento de cada
candidato por secao, zona, municipio, UF e regiao (Lula 13 x Flavio Bolsonaro 22).

Fonte: o BU de cada urna nos arquivos de dados abertos do TSE (research/bu_urna/2026-t1 e 2026-t2, baixados por
scripts/baixa_pais.py), decodificado com t2_2026_collect.decode_bu. Eleicao 6257 (1o turno) e 6258 (2o turno), cargo 1.
Nomes de municipio: arquivos de configuracao do sistema de resultados (research/segundo_turno_2026/config/<UF>-cs.json).
Nomes de candidato: BU dos dados abertos de SP, 1o turno (research/estados/SP/2026-t1/bu.parquet).
Conferencia: soma por municipio contra o total oficial do sistema de resultados (research/segundo_turno_2026/mun_todos.parquet).

Definicoes (votos validos = votos em candidatos; branco e nulo a parte):
  lider do 1o turno no confronto = quem teve mais votos entre 13 e 22 no 1o turno (os demais candidatos ficam de fora)
  virada = o lider do confronto no 1o turno perdeu a secao no 2o turno (empates nao contam)
  100%   = no 2o turno, um candidato teve todos os votos validos da secao
  crescimento % = (votos no 2o turno - votos no 1o turno) / votos no 1o turno
  variacao em p.p. = % dos validos no 2o turno - % dos validos no 1o turno
  local de votacao = UF + municipio + zona + numero do local; "outras secoes do local" exclui a propria secao
Descritivo: no 2o turno os votos dos demais candidatos do 1o turno se redistribuem, e viradas onde a margem era
pequena sao esperadas. Nada aqui indica irregularidade por si so.
Uso: python scripts/virada_1t_2t_2026.py coleta | analise
Saida: relatorios/verificacoes/virada_1t_2t_2026/
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from baixa_pais import em_janela, prioridade_baixa  # noqa: E402

R = ROOT / 'research'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'virada_1t_2t_2026'
BASE = OUT / 'secoes_t1_t2.parquet'
ELEICAO = {'2026-t1': ('t1', 6257), '2026-t2': ('t2', 6258)}
KEY = ['uf', 'municipality', 'zone', 'section']
LOC = ['uf', 'municipality', 'zone', 'voting_place']
REGIAO = {**dict.fromkeys(['AC', 'AP', 'AM', 'PA', 'RO', 'RR', 'TO'], 'Norte'),
          **dict.fromkeys(['AL', 'BA', 'CE', 'MA', 'PB', 'PE', 'PI', 'RN', 'SE'], 'Nordeste'),
          **dict.fromkeys(['GO', 'MS', 'MT'], 'Centro-Oeste (sem DF)'), 'DF': 'Distrito Federal',
          **dict.fromkeys(['ES', 'MG', 'RJ', 'SP'], 'Sudeste'), **dict.fromkeys(['PR', 'RS', 'SC'], 'Sul'), 'ZZ': 'Exterior'}
ORDEM_REGIAO = ['Norte', 'Nordeste', 'Centro-Oeste (sem DF)', 'Distrito Federal', 'Sudeste', 'Sul', 'Exterior']
NOME = {'13': 'LULA', '22': 'FLÁVIO BOLSONARO'}


def secoes_da_parte(args):
    """Um arquivo part-*.parquet (ate 2000 BUs) -> uma linha por secao com os votos de presidente."""
    from t2_2026_collect import decode_bu
    el, uf, path = args
    tag, e = ELEICAO[el]
    pre = f'e{e}_c1_'
    rows = []
    for stem, raw in pd.read_parquet(path, columns=['stem', 'bu_raw']).itertuples(index=False):
        try:
            r = decode_bu(raw)
        except Exception as exc:  # noqa: BLE001
            rows.append({'uf': uf, 'stem': stem, 'erro': repr(exc)[:120]})
            continue
        o = {'uf': uf, 'stem': stem, 'municipality': r.get('municipality'), 'zone': r.get('zone'), 'voting_place': r.get('voting_place'),
             'section': r.get('section'), 'aptos': r.get(f'e{e}_aptos'), 'comparecimento': r.get(f'e{e}_comparecimento')}
        o.update({k[len(pre):]: v for k, v in r.items() if k.startswith(pre)})
        rows.append(o)
    return el, pd.DataFrame(rows)


def coleta():
    OUT.mkdir(parents=True, exist_ok=True)
    tarefas = [(el, uf.name, p) for el in ELEICAO for uf in sorted((R / 'bu_urna' / el).iterdir()) for p in sorted(uf.glob('part-*.parquet'))]
    partes = {el: [] for el in ELEICAO}
    with ProcessPoolExecutor(3, initializer=prioridade_baixa) as ex:
        for k, (el, df) in enumerate(em_janela(ex, secoes_da_parte, tarefas, 6), 1):
            partes[el].append(df)
            if k % 25 == 0:
                print(k, len(tarefas), 'partes', flush=True)
    rodadas = []
    for el, dfs in partes.items():
        tag = ELEICAO[el][0]
        d = pd.concat(dfs, ignore_index=True)
        erros = d[d['erro'].notna()] if 'erro' in d else d.iloc[:0]
        d = d[d.section.notna()].copy()
        for c in ('municipality', 'zone', 'voting_place', 'section'):
            d[c] = d[c].astype(int)
        dup = d.duplicated(KEY, keep='first')
        print(el, 'BUs', len(d) + len(erros), '| erros de decodificacao', len(erros), '| secao repetida', int(dup.sum()), flush=True)
        d = d[~dup].drop(columns=[c for c in ('erro',) if c in d])
        votos = [c for c in d if c.startswith('v') and c[1:].isdigit()]
        d[votos + ['branco', 'nulo', 'aptos', 'comparecimento']] = d[votos + ['branco', 'nulo', 'aptos', 'comparecimento']].fillna(0).astype(int)
        rodadas.append(d.rename(columns={c: f'{tag}_{c}' for c in d if c not in KEY}))
    s = rodadas[0].merge(rodadas[1], on=KEY, how='outer', indicator=True)
    print(s._merge.value_counts().to_dict(), flush=True)
    s.to_parquet(BASE, index=False)
    print('OK', BASE, len(s))


def nomes_municipios():
    rows = []
    for p in sorted((R / 'segundo_turno_2026' / 'config').glob('*-cs.json')):
        cfg = json.loads(p.read_text(encoding='utf-8'))
        rows += [(p.name[:2], int(mu['cd']), mu['nm']) for ab in cfg['abr'] for mu in ab['mu']]
    return pd.DataFrame(rows, columns=['uf', 'municipality', 'municipio']).drop_duplicates(['uf', 'municipality'])


def nomes_candidatos():
    """Numero -> nome dos candidatos a presidente no 1o turno (BU dos dados abertos de SP, que lista todos)."""
    b = pd.read_parquet(R / 'estados' / 'SP' / '2026-t1' / 'bu.parquet', columns=['DS_CARGO_PERGUNTA', 'NR_VOTAVEL', 'NM_VOTAVEL'])
    b = b[b.DS_CARGO_PERGUNTA.str.contains('Presidente', na=False)].drop_duplicates('NR_VOTAVEL')
    return dict(zip(b.NR_VOTAVEL.astype(str), b.NM_VOTAVEL))


def pct(a, b):
    return np.where(b > 0, 100 * a / np.where(b > 0, b, 1), np.nan)


def cresc(t2, t1):
    return np.where(t1 > 0, 100 * (t2 - t1) / np.where(t1 > 0, t1, 1), np.nan)


def lider(a, b):
    return np.select([a > b, b > a], ['13', '22'], 'empate')


def medidas(g):
    """Colunas de comparacao 1o x 2o turno a partir das somas de votos (serve para secao e para qualquer agregado)."""
    g = g.copy()
    for t in ('t1', 't2'):
        g[f'{t}_p13'] = pct(g[f'{t}_v13'], g[f'{t}_validos'])
        g[f'{t}_p22'] = pct(g[f'{t}_v22'], g[f'{t}_validos'])
        g[f'{t}_comparec_pct'] = pct(g[f'{t}_comparecimento'], g[f'{t}_aptos'])
    g['t1_poutros'] = pct(g.t1_outros, g.t1_validos)
    for c in ('13', '22'):
        g[f'cresc_votos_{c}_pct'] = cresc(g[f't2_v{c}'], g[f't1_v{c}'])
        g[f'ganho_votos_{c}'] = g[f't2_v{c}'] - g[f't1_v{c}']
        g[f'var_{c}_pp'] = g[f't2_p{c}'] - g[f't1_p{c}']
        g[f'var_{c}_rel_pct'] = cresc(g[f't2_p{c}'], g[f't1_p{c}'])
    g['cresc_comparecimento_pct'] = cresc(g.t2_comparecimento, g.t1_comparecimento)
    g['lider_t1_confronto'] = lider(g.t1_v13, g.t1_v22)
    g['vencedor_t2'] = lider(g.t2_v13, g.t2_v22)
    g['virou'] = g.lider_t1_confronto.isin(['13', '22']) & g.vencedor_t2.isin(['13', '22']) & (g.lider_t1_confronto != g.vencedor_t2)
    return g


SOMAS = ['t1_v13', 't1_v22', 't1_outros', 't1_validos', 't1_branco', 't1_nulo', 't1_aptos', 't1_comparecimento',
         't2_v13', 't2_v22', 't2_validos', 't2_branco', 't2_nulo', 't2_aptos', 't2_comparecimento']


def agrega(s, por):
    g = s.groupby(por, observed=True).agg(secoes=('section', 'size'), secoes_viradas=('virou', 'sum'),
                                          viradas_para_13=('sentido', lambda x: (x == 'FLÁVIO → LULA').sum()),
                                          viradas_para_22=('sentido', lambda x: (x == 'LULA → FLÁVIO').sum()),
                                          secoes_100pct=('cem_pct', 'sum'), **{c: (c, 'sum') for c in SOMAS}).reset_index()
    g = medidas(g)
    return g.rename(columns={'virou': 'unidade_virou'})


def analise():
    s = pd.read_parquet(BASE)
    so = s._merge.value_counts().to_dict()
    fora = s[s._merge != 'both'][KEY + ['_merge']].rename(columns={'_merge': 'origem'}).merge(nomes_municipios(), on=['uf', 'municipality'], how='left')
    s = s[s._merge == 'both'].drop(columns=['_merge'])
    s['voting_place'] = s.t2_voting_place.fillna(s.t1_voting_place).astype(int)
    outros = [c for c in s if c.startswith('t1_v') and c[4:].isdigit() and c not in ('t1_v13', 't1_v22')]
    s['t1_outros'] = s[outros].sum(axis=1)
    s['t1_validos'] = s.t1_v13 + s.t1_v22 + s.t1_outros
    s['t2_validos'] = s.t2_v13 + s.t2_v22
    # lider geral do 1o turno (pode ser um terceiro candidato)
    cand = ['t1_v13', 't1_v22'] + outros
    s['lider_t1_geral'] = np.where(s.t1_validos > 0, s[cand].idxmax(axis=1).str[4:], '')
    s = medidas(s)
    s['sentido'] = np.where(s.virou, np.where(s.vencedor_t2 == '13', 'FLÁVIO → LULA', 'LULA → FLÁVIO'), '')
    s['margem_t1_pp'] = s.t1_p13 - s.t1_p22
    s['margem_t2_pp'] = s.t2_p13 - s.t2_p22
    s['cem_pct'] = (s.t2_validos > 0) & ((s.t2_v13 == s.t2_validos) | (s.t2_v22 == s.t2_validos))
    s['cem_pct_para'] = np.where(s.cem_pct, np.where(s.t2_v13 == s.t2_validos, NOME['13'], NOME['22']), '')
    s['regiao'] = s.uf.map(REGIAO)
    s = s.merge(nomes_municipios(), on=['uf', 'municipality'], how='left')

    # outras secoes do mesmo local de votacao (soma do local menos a propria secao)
    s['n_um'] = 1
    s['n_virou13'] = (s.sentido == 'FLÁVIO → LULA').astype(int)
    s['n_virou22'] = (s.sentido == 'LULA → FLÁVIO').astype(int)
    s['n_cem'] = s.cem_pct.astype(int)
    soma_loc = ['n_um', 'n_virou13', 'n_virou22', 'n_cem', 't1_v13', 't1_v22', 't1_validos', 't2_v13', 't2_v22', 't2_validos']
    tot = s.groupby(LOC)[soma_loc].transform('sum')
    o = tot - s[soma_loc].values
    s['local_outras_secoes'] = o['n_um']
    s['local_outras_viradas_mesmo_sentido'] = np.where(s.sentido == 'FLÁVIO → LULA', o['n_virou13'], np.where(s.sentido == 'LULA → FLÁVIO', o['n_virou22'], 0))
    s['local_outras_viradas_total'] = o['n_virou13'] + o['n_virou22']
    s['local_outras_100pct'] = o['n_cem']
    for t in ('t1', 't2'):
        s[f'local_outras_{t}_p13'] = pct(o[f'{t}_v13'], o[f'{t}_validos'])
        s[f'local_outras_{t}_p22'] = pct(o[f'{t}_v22'], o[f'{t}_validos'])
    s['local_outras_vencedor_t2'] = np.where(o['n_um'] > 0, lider(o.t2_v13, o.t2_v22), '')
    s['local_outras_var_13_pp'] = s.local_outras_t2_p13 - s.local_outras_t1_p13
    s['dif_var_13_pp_vs_local'] = s.var_13_pp - s.local_outras_var_13_pp
    s['virada_no_local'] = np.select(
        [~s.virou, s.local_outras_secoes == 0, s.local_outras_viradas_mesmo_sentido == s.local_outras_secoes, s.local_outras_viradas_mesmo_sentido > 0],
        ['', 'seção única no local', 'todas as outras seções do local também viraram', 'parte das outras seções do local também virou'],
        'só esta seção virou no local')
    s = s.drop(columns=['n_um', 'n_virou13', 'n_virou22', 'n_cem'])

    OUT.mkdir(parents=True, exist_ok=True)
    CSV = dict(index=False, sep=';', encoding='utf-8-sig', decimal=',')
    ident = ['regiao', 'uf', 'municipio', 'municipality', 'zone', 'voting_place', 'section']
    comp = ['t1_v13', 't1_v22', 't1_outros', 't1_validos', 't1_branco', 't1_nulo', 't1_comparecimento', 't1_aptos',
            't2_v13', 't2_v22', 't2_validos', 't2_branco', 't2_nulo', 't2_comparecimento', 't2_aptos',
            't1_p13', 't1_p22', 't1_poutros', 't2_p13', 't2_p22', 'ganho_votos_13', 'ganho_votos_22', 'cresc_votos_13_pct', 'cresc_votos_22_pct',
            'var_13_pp', 'var_22_pp', 'var_13_rel_pct', 'var_22_rel_pct', 'cresc_comparecimento_pct',
            'lider_t1_geral', 'lider_t1_confronto', 'vencedor_t2', 'margem_t1_pp', 'margem_t2_pp']
    local = ['local_outras_secoes', 'local_outras_t1_p13', 'local_outras_t2_p13', 'local_outras_var_13_pp', 'local_outras_vencedor_t2',
             'local_outras_viradas_mesmo_sentido', 'local_outras_viradas_total', 'local_outras_100pct', 'dif_var_13_pp_vs_local']
    s = s.sort_values(['uf', 'municipality', 'zone', 'section'])
    por_secao = s[ident + comp + ['virou', 'sentido', 'cem_pct', 'cem_pct_para'] + local + ['virada_no_local']]
    viradas = por_secao[por_secao.virou].drop(columns=['virou', 'cem_pct'])
    cem = por_secao[por_secao.cem_pct].drop(columns=['cem_pct'])
    por_secao.to_parquet(OUT / 'por_secao.parquet', index=False)
    por_secao.to_csv(OUT / 'por_secao.csv', **CSV)
    viradas.to_csv(OUT / 'secoes_com_virada.csv', **CSV)
    cem.to_csv(OUT / 'secoes_100pct_um_candidato.csv', **CSV)

    zona = agrega(s, ['regiao', 'uf', 'zone'])
    mun = agrega(s, ['regiao', 'uf', 'municipality', 'municipio'])
    uf = agrega(s, ['regiao', 'uf'])
    reg = agrega(s.assign(regiao=pd.Categorical(s.regiao, ORDEM_REGIAO, ordered=True)), ['regiao'])
    br = agrega(s[s.uf != 'ZZ'].assign(regiao='Brasil (sem exterior)'), ['regiao'])
    tudo = agrega(s.assign(regiao='Total (com exterior)'), ['regiao'])
    reg = pd.concat([reg.assign(regiao=reg.regiao.astype(str)), br, tudo], ignore_index=True)
    for nm, df in (('por_zona', zona), ('por_municipio', mun), ('por_uf', uf), ('por_regiao', reg)):
        df.to_csv(OUT / f'{nm}.csv', **CSV)

    # conferencia: soma das secoes x total oficial por municipio (sistema de resultados)
    of = pd.read_parquet(R / 'segundo_turno_2026' / 'mun_todos.parquet', columns=['uf', 'mun_cd', 't1_v13', 't1_v22', 't2_v13', 't2_v22'])
    of['municipality'] = of.mun_cd.astype(int)
    cf = mun.merge(of.drop(columns='mun_cd'), on=['uf', 'municipality'], how='inner', suffixes=('', '_oficial'))
    for c in ('t1_v13', 't1_v22', 't2_v13', 't2_v22'):
        cf[f'dif_{c}'] = cf[c] - pd.to_numeric(cf[f'{c}_oficial'], errors='coerce')
    cf['bate'] = cf[[c for c in cf if c.startswith('dif_')]].abs().sum(axis=1) == 0
    cf[['uf', 'municipality', 'municipio', 'bate'] + [c for c in cf if c.startswith('dif_') or c.endswith('_oficial')]].to_csv(OUT / 'conferencia_municipios.csv', **CSV)

    # 1o turno: votos por candidato (Total e por UF), com o nome do candidato
    nomes = nomes_candidatos()
    vt1 = [c for c in s if c.startswith('t1_v') and c[4:].isdigit()]
    cand = pd.concat([s.groupby('uf')[vt1].sum(), s[vt1].sum().to_frame('Total (com exterior)').T]).stack().rename('votos').reset_index()
    cand.columns = ['uf', 'numero', 'votos']
    cand['numero'] = cand.numero.str[4:]
    cand['candidato'] = cand.numero.map(nomes)
    cand['pct_validos'] = 100 * cand.votos / cand.groupby('uf').votos.transform('sum')
    cand = cand.sort_values(['uf', 'votos'], ascending=[True, False])
    cand.to_csv(OUT / 'candidatos_1o_turno.csv', **CSV)

    resumo = {'secoes_nos_dois_turnos': len(s), 'so_no_1o_turno': int(so.get('left_only', 0)), 'so_no_2o_turno': int(so.get('right_only', 0)),
              'secoes_lideradas_por_terceiro_no_1o_turno': int((~s.lider_t1_geral.isin(['13', '22']) & (s.t1_validos > 0)).sum()),
              'viradas': int(s.virou.sum()), 'viradas_para_13': int((s.sentido == 'FLÁVIO → LULA').sum()), 'viradas_para_22': int((s.sentido == 'LULA → FLÁVIO').sum()),
              'secoes_100pct': int(s.cem_pct.sum()), 'municipios_conferidos': len(cf), 'municipios_batem': int(cf.bate.sum()),
              'secoes_fora': [{'uf': r.uf, 'municipio': r.municipio, 'zona': int(r.zone), 'secao': int(r.section),
                               'so_no': '1º turno' if r.origem == 'left_only' else '2º turno'} for r in fora.itertuples()],
              'municipios_que_nao_batem': cf.loc[~cf.bate, 'municipio'].tolist()}
    (OUT / 'resumo.json').write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding='utf-8')

    from ultimo_voto_2026t2 import xlsx_leve
    curtas = ident + ['t1_v13', 't1_v22', 't1_outros', 't1_validos', 't2_v13', 't2_v22', 't2_validos', 't1_p13', 't1_p22', 't2_p13', 't2_p22',
                      'cresc_votos_13_pct', 'cresc_votos_22_pct', 'var_13_pp', 'var_22_pp', 'lider_t1_confronto', 'vencedor_t2', 'sentido', 'cem_pct_para']
    xlsx_leve(OUT / 'VIRADA_1T_2T_2026.xlsx', [('regioes', reg), ('ufs', uf), ('candidatos_1o_turno', cand), ('municipios', mun), ('zonas', zona),
                                               ('secoes_com_virada', viradas), ('secoes_100pct', cem), ('conferencia_municipios', cf),
                                               ('todas_as_secoes', por_secao[curtas])])
    pd.set_option('display.width', 250)
    print(json.dumps(resumo, ensure_ascii=False))
    print(reg[['regiao', 'secoes', 't1_p13', 't1_p22', 't2_p13', 't2_p22', 'cresc_votos_13_pct', 'cresc_votos_22_pct', 'var_13_pp', 'var_22_pp',
               'secoes_viradas', 'viradas_para_13', 'viradas_para_22', 'secoes_100pct']].round(2).to_string(index=False))
    print(viradas.virada_no_local.value_counts().to_string())
    print(cem.cem_pct_para.value_counts().to_string())


if __name__ == '__main__':
    {'coleta': coleta, 'analise': analise}[sys.argv[1]]()
