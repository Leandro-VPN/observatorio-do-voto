"""Secoes em que um candidato teve 100% dos votos validos no 2o turno, eleicao por eleicao, comparadas ao 1o turno
da mesma secao e as outras secoes do mesmo local de votacao. Mesma definicao de scripts/virada_1t_2t_2026.py.

Eleicoes:
  presidente 2014 (13 x 45), 2018 (17 x 13), 2022 (13 x 22) e 2026 (13 x 22), pais inteiro e exterior
  prefeito 2024, nos municipios que tiveram 2o turno (outra disputa: fica em bloco separado)
Fontes:
  2014, 2018, 2022: BU em CSV (BWEB) do TSE por UF, linhas de PRESIDENTE -> research/bu/<ano>-t<turno>/<UF>_PRESIDENTE.parquet
                    (scripts/bu_capture_all.py --offices PRESIDENTE)
  2026: relatorios/verificacoes/virada_1t_2t_2026/secoes_t1_t2.parquet (BU de cada urna, scripts/virada_1t_2t_2026.py)
  2024: BU de cada urna (research/bu_urna/2024-t1 e 2024-t2), t2_2026_collect.decode_bu, cargo 11 (prefeito)
Definicoes: validos = votos em candidatos; 100% = validos > 0 e um candidato com todos os validos da secao no 2o turno;
  "99% ou mais" so como referencia; % no 1o turno = fatia do mesmo candidato nos validos do 1o turno da mesma secao;
  local de votacao = UF + municipio + zona + numero do local (outras secoes do local excluem a propria secao).
Descritivo: secao com voto unanime acontece onde o eleitorado e pequeno e homogeneo. Nada aqui indica irregularidade por si so.
Uso: python scripts/cem_pct_2t_anos.py coleta_2024 | analise
Saida: relatorios/verificacoes/cem_pct_2t/
"""
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from baixa_pais import em_janela, prioridade_baixa  # noqa: E402
from virada_1t_2t_2026 import BASE as BASE_2026, REGIAO, nomes_candidatos, nomes_municipios  # noqa: E402

R = ROOT / 'research'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'cem_pct_2t'
BASE_2024 = OUT / 'secoes_2024_prefeito.parquet'
KEY = ['uf', 'municipality', 'zone', 'section']
LOC = ['uf', 'municipality', 'zone', 'voting_place']
PRESIDENTE = {2014: ('13', '45'), 2018: ('17', '13'), 2022: ('13', '22'), 2026: ('13', '22')}
STEM = re.compile(r'^o\d+(?P<uf>[a-z]{2})(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})$')


# ---------- 2024: prefeito, BU de cada urna ----------

def prefeito_da_parte(args):
    """Um part-*.parquet de 2024 -> uma linha por secao com os votos de prefeito (so dos municipios pedidos)."""
    from t2_2026_collect import decode_bu
    tag, uf, path, muns = args
    rows = []
    for stem, raw in pd.read_parquet(path, columns=['stem', 'bu_raw']).itertuples(index=False):
        m = STEM.match(stem)
        if muns is not None and (not m or int(m['mun']) not in muns):
            continue
        try:
            r = decode_bu(raw)
        except Exception as exc:  # noqa: BLE001
            rows.append({'uf': uf, 'stem': stem, 'erro': repr(exc)[:120]})
            continue
        el = sorted({k.split('_')[0] for k in r if '_c11_' in k})
        if not el:  # urna sem prefeito
            continue
        e = el[0]
        o = {'uf': uf, 'stem': stem, 'municipality': r.get('municipality'), 'zone': r.get('zone'), 'voting_place': r.get('voting_place'),
             'section': r.get('section'), 'aptos': r.get(f'{e}_aptos'), 'comparecimento': r.get(f'{e}_comparecimento'), 'eleicao': e}
        o.update({k.split('_c11_')[1]: v for k, v in r.items() if k.startswith(f'{e}_c11_')})
        rows.append(o)
    return tag, pd.DataFrame(rows)


def _roda(tarefas):
    partes = {'t1': [], 't2': []}
    with ProcessPoolExecutor(3, initializer=prioridade_baixa) as ex:
        for k, (tag, df) in enumerate(em_janela(ex, prefeito_da_parte, tarefas, 6), 1):
            partes[tag].append(df)
            if k % 25 == 0:
                print(k, len(tarefas), 'partes', flush=True)
    return partes


def coleta_2024():
    OUT.mkdir(parents=True, exist_ok=True)
    t2 = [('t2', uf.name, p, None) for uf in sorted((R / 'bu_urna' / '2024-t2').iterdir()) for p in sorted(uf.glob('part-*.parquet'))]
    d2 = pd.concat(_roda(t2)['t2'], ignore_index=True)
    muns = d2.dropna(subset=['municipality']).groupby('uf').municipality.apply(lambda s: set(s.astype(int))).to_dict()
    t1 = [('t1', uf.name, p, muns[uf.name]) for uf in sorted((R / 'bu_urna' / '2024-t1').iterdir()) if uf.name in muns
          for p in sorted(uf.glob('part-*.parquet'))]
    d1 = pd.concat(_roda(t1)['t1'], ignore_index=True)
    rodadas = []
    for tag, d in (('t1', d1), ('t2', d2)):
        erros = int(d['erro'].notna().sum()) if 'erro' in d else 0
        d = d[d.section.notna()].copy()
        for c in ('municipality', 'zone', 'voting_place', 'section'):
            d[c] = d[c].astype(int)
        dup = d.duplicated(KEY)
        print('2024', tag, 'secoes', len(d), '| erros', erros, '| repetidas', int(dup.sum()), '| eleicoes', d.eleicao.value_counts().to_dict(), flush=True)
        d = d[~dup].drop(columns=[c for c in ('erro', 'stem', 'eleicao') if c in d])
        num = [c for c in d if c.startswith('v') and c[1:].isdigit()] + ['branco', 'nulo', 'aptos', 'comparecimento']
        d[num] = d[num].fillna(0).astype(int)
        rodadas.append(d.rename(columns={c: f'{tag}_{c}' for c in d if c not in KEY}))
    s = rodadas[1].merge(rodadas[0], on=KEY, how='left', indicator=True)
    print('2024 secoes do 2o turno com 1o turno:', s._merge.value_counts().to_dict(), flush=True)
    s.drop(columns='_merge').to_parquet(BASE_2024, index=False)


# ---------- leitura das bases no formato comum ----------

def bweb(ano, turno):
    """BU em CSV (presidente) -> uma linha por secao, votos por candidato (v<numero>), branco, nulo, aptos, comparecimento."""
    cols = ['SG_UF', 'CD_MUNICIPIO', 'NM_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_LOCAL_VOTACAO', 'CD_TIPO_VOTAVEL', 'NR_VOTAVEL', 'NM_VOTAVEL',
            'QT_VOTOS', 'QT_APTOS', 'QT_COMPARECIMENTO']
    partes, nomes = [], {}
    fs = sorted((R / 'bu' / f'{ano}-t{turno}').glob('*_PRESIDENTE.parquet'))
    for f in fs:
        b = pd.read_parquet(f, columns=cols)
        for c in ('CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_LOCAL_VOTACAO', 'QT_VOTOS', 'QT_APTOS', 'QT_COMPARECIMENTO', 'CD_TIPO_VOTAVEL'):
            b[c] = pd.to_numeric(b[c], errors='coerce').fillna(0).astype(int)
        nomes.update(b[b.CD_TIPO_VOTAVEL == 1].drop_duplicates('NR_VOTAVEL').set_index('NR_VOTAVEL').NM_VOTAVEL.to_dict())
        b['rotulo'] = np.select([b.CD_TIPO_VOTAVEL == 1, b.CD_TIPO_VOTAVEL == 2], ['v' + b.NR_VOTAVEL.astype(str), 'branco'], 'nulo')
        k = ['SG_UF', 'CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO']
        w = b.pivot_table(index=k, columns='rotulo', values='QT_VOTOS', aggfunc='sum', fill_value=0)
        meta = b.groupby(k).agg(municipio=('NM_MUNICIPIO', 'first'), voting_place=('NR_LOCAL_VOTACAO', 'first'),
                                aptos=('QT_APTOS', 'first'), comparecimento=('QT_COMPARECIMENTO', 'first'))
        partes.append(meta.join(w).reset_index())
    d = pd.concat(partes, ignore_index=True).rename(columns={'SG_UF': 'uf', 'CD_MUNICIPIO': 'municipality', 'NR_ZONA': 'zone', 'NR_SECAO': 'section'})
    num = [c for c in d if c.startswith('v') and c[1:].isdigit()] + ['branco', 'nulo']
    for c in ('branco', 'nulo'):
        if c not in d:
            d[c] = 0
    d[num] = d[num].fillna(0).astype(int)
    return d, nomes, len(fs)


def base_presidente(ano):
    """Secoes do 2o turno de presidente com o 1o turno ao lado (prefixos t1_ e t2_)."""
    if ano == 2026:
        s = pd.read_parquet(BASE_2026)
        s = s[s._merge == 'both'].drop(columns=['_merge', 't1_stem', 't2_stem'])
        s['voting_place'] = s.t2_voting_place.astype(int)
        s = s.drop(columns=['t1_voting_place', 't2_voting_place']).merge(nomes_municipios(), on=['uf', 'municipality'], how='left')
        return s, nomes_candidatos(), {'ufs_t1': 28, 'ufs_t2': 28, 'so_no_2o_turno': 0}
    t1, n1, f1 = bweb(ano, 1)
    t2, n2, f2 = bweb(ano, 2)
    s = t2.rename(columns={c: f't2_{c}' for c in t2 if c not in KEY + ['municipio', 'voting_place']}).merge(
        t1.drop(columns=['municipio', 'voting_place']).rename(columns={c: f't1_{c}' for c in t1 if c not in KEY}), on=KEY, how='left', indicator=True)
    info = {'ufs_t1': f1, 'ufs_t2': f2, 'so_no_2o_turno': int((s._merge == 'left_only').sum())}
    s = s[s._merge == 'both'].drop(columns='_merge')
    return s, {**n1, **n2}, info


def base_prefeito_2024():
    s = pd.read_parquet(BASE_2024)
    info = {'so_no_2o_turno': int(s.t1_aptos.isna().sum())}
    s = s[s.t1_aptos.notna()].copy()
    vt = [c for c in s if re.fullmatch(r't[12]_v\d+', c)]
    s[vt] = s[vt].fillna(0).astype(int)
    s['voting_place'] = s.t2_voting_place.astype(int)
    s = s.drop(columns=['t1_voting_place', 't2_voting_place']).merge(nomes_municipios(), on=['uf', 'municipality'], how='left')
    return s, partidos_2024(), info


def partidos_2024():
    """Prefeito: o numero do candidato e o numero do partido -> sigla (BU em CSV de 2024 ja capturado, research/bu/2024-t1)."""
    m = {}
    for f in sorted((R / 'bu' / '2024-t1').glob('*_PREFEITO.parquet')):
        b = pd.read_parquet(f, columns=['NR_PARTIDO', 'SG_PARTIDO']).drop_duplicates()
        m.update(dict(zip(b.NR_PARTIDO.astype(str), b.SG_PARTIDO)))
    return m


# ---------- analise comum ----------

def cem_pct(s, eleicao):
    """Marca as secoes 100% no 2o turno e compara com o 1o turno e com as outras secoes do mesmo local."""
    v2 = sorted(c for c in s if re.fullmatch(r't2_v\d+', c))
    v1 = sorted(c for c in s if re.fullmatch(r't1_v\d+', c))
    s = s.copy()
    s['t2_validos'] = s[v2].sum(axis=1)
    s['t1_validos'] = s[v1].sum(axis=1)
    m2 = s[v2].to_numpy()
    top = m2.max(axis=1)
    s['cand'] = np.array([c[4:] for c in v2])[m2.argmax(axis=1)]
    s['t2_pct_cand'] = np.where(s.t2_validos > 0, 100 * top / s.t2_validos.where(s.t2_validos > 0, 1), np.nan)
    s['cem'] = (s.t2_validos > 0) & (top == s.t2_validos)
    s['ate99'] = s.t2_pct_cand >= 99
    # 1o turno do mesmo candidato (coluna ausente = nenhum voto)
    idx = {c[4:]: i for i, c in enumerate(v1)}
    m1 = s[v1].to_numpy()
    t1c = np.array([m1[i, idx[c]] if c in idx else 0 for i, c in enumerate(s.cand)])
    s['t1_votos_cand'] = t1c
    s['t1_pct_cand'] = np.where(s.t1_validos > 0, 100 * t1c / s.t1_validos.where(s.t1_validos > 0, 1), np.nan)
    s['t1_cem'] = (s.t1_validos > 0) & (t1c == s.t1_validos)
    # outras secoes do mesmo local: votos do mesmo candidato no 2o turno, sem a propria secao
    loc = s.groupby(LOC)[v2 + ['t2_validos']].transform('sum')
    li = {c[4:]: i for i, c in enumerate(v2)}
    lm = loc[v2].to_numpy()
    s['local_outras_secoes'] = s.groupby(LOC).section.transform('size') - 1
    outras_cand = np.array([lm[i, li[c]] for i, c in enumerate(s.cand)]) - top
    outras_val = loc.t2_validos.to_numpy() - s.t2_validos.to_numpy()
    s['local_outras_t2_pct_cand'] = np.where(outras_val > 0, 100 * outras_cand / np.where(outras_val > 0, outras_val, 1), np.nan)
    s['local_outras_100pct'] = s.groupby(LOC).cem.transform('sum') - s.cem.astype(int)
    s['eleicao'] = eleicao
    s['regiao'] = s.uf.map(REGIAO)
    return s


def resumo(s, eleicao, nomes, info):
    c = s[s.cem]
    tam = pd.cut(c.t2_validos, [0, 10, 50, 100, 200, 10_000], labels=['1 a 10', '11 a 50', '51 a 100', '101 a 200', 'mais de 200'])
    por_cand = c.cand.value_counts()
    return {'eleicao': eleicao, 'secoes': len(s), 'secoes_100pct': len(c), 'por_100_mil_secoes': round(1e5 * len(c) / len(s), 1),
            'secoes_99pct_ou_mais': int(s.ate99.sum()),
            'por_candidato': '; '.join(f'{nomes.get(k, k)} ({k}): {v}' for k, v in por_cand.items()),
            'validos_2t_mediana': float(c.t2_validos.median()) if len(c) else np.nan,
            'pct_1t_mesmo_cand_mediana': float(c.t1_pct_cand.median()) if len(c) else np.nan,
            'ja_100pct_no_1t': int(c.t1_cem.sum()),
            'secao_unica_no_local': int((c.local_outras_secoes == 0).sum()),
            'outras_do_local_pct_mediana': float(c.local_outras_t2_pct_cand.median()) if len(c) else np.nan,
            'ufs_com_mais_casos': ', '.join(f'{k} {v}' for k, v in c.uf.value_counts().head(6).items()),
            **{f'validos_{k}': int(v) for k, v in tam.value_counts(sort=False).items()},
            'secoes_so_no_2o_turno_fora': info.get('so_no_2o_turno', 0)}


def analise():
    OUT.mkdir(parents=True, exist_ok=True)
    CSV = dict(index=False, sep=';', encoding='utf-8-sig', decimal=',')
    resumos, listas, ufs = [], [], []
    eleicoes = [(f'Presidente {a}', lambda a=a: base_presidente(a)) for a in sorted(PRESIDENTE)]
    if BASE_2024.exists():
        eleicoes.append(('Prefeito 2024', base_prefeito_2024))
    for nome, carrega in eleicoes:
        s, nomes, info = carrega()
        s = cem_pct(s, nome)
        print(nome, 'secoes', len(s), '| 100%', int(s.cem.sum()), '| fora', info, flush=True)
        resumos.append(resumo(s, nome, nomes, info))
        c = s[s.cem].copy()
        c['candidato'] = c.cand.map(lambda k: f'{nomes.get(k, "nº " + k)} ({k})')
        listas.append(c[['eleicao', 'regiao', 'uf', 'municipio', 'municipality', 'zone', 'voting_place', 'section', 'candidato', 't2_validos', 't2_branco',
                         't2_nulo', 't2_aptos', 't2_comparecimento', 't1_validos', 't1_votos_cand', 't1_pct_cand', 't1_cem', 'local_outras_secoes',
                         'local_outras_t2_pct_cand', 'local_outras_100pct']])
        ufs.append(s.groupby('uf').agg(secoes=('cem', 'size'), secoes_100pct=('cem', 'sum')).assign(eleicao=nome).reset_index())
    R_ = pd.DataFrame(resumos)
    L = pd.concat(listas, ignore_index=True).sort_values(['eleicao', 't2_validos'], ascending=[True, False])
    U = pd.concat(ufs, ignore_index=True)
    # sem fill_value: UF sem secao naquela eleicao (ex.: sem 2o turno municipal) fica vazia, nao zero
    UF = U.pivot_table(index='uf', columns='eleicao', values='secoes_100pct', aggfunc='sum')
    REG = U.assign(regiao=U.uf.map(REGIAO)).pivot_table(index='regiao', columns='eleicao', values='secoes_100pct', aggfunc='sum')
    R_.to_csv(OUT / 'resumo_por_eleicao.csv', **CSV)
    L.to_csv(OUT / 'secoes_100pct_todas_eleicoes.csv', **CSV)
    UF.reset_index().to_csv(OUT / 'secoes_100pct_por_uf.csv', **CSV)
    REG.reset_index().to_csv(OUT / 'secoes_100pct_por_regiao.csv', **CSV)
    from ultimo_voto_2026t2 import xlsx_leve
    xlsx_leve(OUT / 'CEM_PCT_2T_ELEICOES.xlsx', [('resumo_por_eleicao', R_), ('por_uf', UF.reset_index()), ('por_regiao', REG.reset_index()),
                                                 ('secoes_100pct', L)])
    pd.set_option('display.width', 250)
    print(R_.drop(columns=['por_candidato', 'ufs_com_mais_casos']).to_string(index=False))
    print(R_[['eleicao', 'por_candidato', 'ufs_com_mais_casos']].to_string(index=False))


if __name__ == '__main__':
    {'coleta_2024': coleta_2024, 'analise': analise}[sys.argv[1]]()
