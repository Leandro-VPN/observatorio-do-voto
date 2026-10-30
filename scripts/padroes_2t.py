"""Padroes da mudanca do 1o para o 2o turno, secao a secao, em quatro eleicoes para presidente: 2014 (Dilma x Aecio),
2018 (Haddad x Bolsonaro), 2022 (Lula x Bolsonaro) e 2026 (Lula x Flavio). As tres primeiras servem de controle para 2026.

Perguntas:
  - a mudanca tem cara de regra fixa ("algoritmo"): proporcao constante, secoes parecidas demais entre si, digitos viciados?
  - ha secoes com os votos dos dois candidatos trocados (inversao)? foco em RJ e GO
  - o ganho segue a composicao do 1o turno e as secoes vizinhas, como nas outras eleicoes?
  - conferencia das alegacoes sobre encerramento apos 17h, habilitacao manual, secoes acima de 90%/100% e Benford
Descritivo e estatistico. Nada aqui, sozinho, indica ou descarta irregularidade.

Uso: python scripts/padroes_2t.py coleta_2026 | base | testes | montecarlo | cego_prepara | cego_avalia | cego_abre
Saida: relatorios/verificacoes/padroes_2t/ (dados intermediarios em research/padroes_2t/)
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from baixa_pais import em_janela, prioridade_baixa  # noqa: E402

R = ROOT / 'research'
WORK = R / 'padroes_2t'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'padroes_2t'
KEY = ['uf', 'municipality', 'zone', 'section']
LOC = ['uf', 'municipality', 'zone', 'voting_place']


# ---------- 2026: habilitacao e horarios do BU de cada urna ----------

def hab_da_parte(args):
    """Um part-*.parquet de 2026 -> por secao: abertura, encerramento (hora local da urna) e habilitacao.
    hab_0 = eleitor sem biometria cadastrada, hab_1 = habilitado pela digital, hab_2 = tem biometria e nao foi reconhecido
    (habilitado pelo mesario; e o QT_ELEITORES_BIOMETRIA_NH do BU em CSV). hab_0 + hab_1 + hab_2 = comparecimento."""
    from t2_2026_collect import decode_bu
    turno, uf, path, dest = args
    rows = []
    for stem, raw in pd.read_parquet(path, columns=['stem', 'bu_raw']).itertuples(index=False):
        try:
            r = decode_bu(raw)
        except Exception as exc:  # noqa: BLE001
            rows.append({'uf': uf, 'stem': stem, 'erro': repr(exc)[:120]})
            continue
        rows.append({'uf': uf, 'stem': stem, **{k: r.get(k) for k in ('municipality', 'zone', 'voting_place', 'section', 'opening', 'closing',
                                                                       'hab_0', 'hab_1', 'hab_2', 'comparecimento_bu')}})
    d = pd.DataFrame(rows)
    tmp = dest.with_suffix('.tmp')
    d.to_parquet(tmp, index=False)
    tmp.replace(dest)
    return dest


def coleta_2026():
    cache = WORK / 'hab_2026'
    cache.mkdir(parents=True, exist_ok=True)
    tarefas = []
    for turno in ('t1', 't2'):
        for uf in sorted(p for p in (R / 'bu_urna' / f'2026-{turno}').iterdir() if p.is_dir()):
            for p in sorted(uf.glob('part-*.parquet')):
                dest = cache / f'{turno}_{uf.name}_{p.stem}.parquet'
                if dest.exists():
                    try:
                        pd.read_parquet(dest, columns=['stem'])
                        continue
                    except Exception:  # noqa: BLE001  arquivo cortado por queda: refaz
                        dest.unlink()
                tarefas.append((turno, uf.name, p, dest))
    print('partes a decodificar:', len(tarefas), flush=True)
    with ProcessPoolExecutor(3, initializer=prioridade_baixa) as ex:
        for k, _ in enumerate(em_janela(ex, hab_da_parte, tarefas, 6), 1):
            if k % 20 == 0 or k == len(tarefas):
                print(k, len(tarefas), flush=True)
    for turno in ('t1', 't2'):
        d = pd.concat([pd.read_parquet(f) for f in sorted(cache.glob(f'{turno}_*.parquet'))], ignore_index=True)
        erros = int(d['erro'].notna().sum()) if 'erro' in d else 0
        d = d[d.section.notna()].copy()
        for c in ('municipality', 'zone', 'voting_place', 'section'):
            d[c] = d[c].astype(int)
        d = d.sort_values('comparecimento_bu', ascending=False).drop_duplicates(KEY)
        d.drop(columns=[c for c in ('erro',) if c in d]).to_parquet(WORK / f'hab_2026_{turno}.parquet', index=False)
        print('2026', turno, 'secoes', len(d), '| erros', erros, '| hab_2 total', int(d.hab_2.sum()), flush=True)


# ---------- base comum: uma linha por secao, 1o e 2o turno lado a lado ----------
# A = candidato do PT no 2o turno; B = o adversario. Incumbente: 2014 Dilma (A), 2018 nenhum, 2022 Bolsonaro (B), 2026 Lula (A).
FINAL = {2014: ('13', '45'), 2018: ('13', '17'), 2022: ('13', '22'), 2026: ('13', '22')}
NOMES = {2014: ('Dilma', 'Aécio'), 2018: ('Haddad', 'Bolsonaro'), 2022: ('Lula', 'Bolsonaro'), 2026: ('Lula', 'Flávio')}
INCUMBENTE = {2014: 'A', 2018: None, 2022: 'B', 2026: 'A'}
HORA_BSB = {2014: False, 2018: False, 2022: True, 2026: True}  # 2022 em diante: votacao das 8h as 17h de Brasilia em todo o pais


def _minutos(s, fmt):
    t = pd.to_datetime(s, format=fmt, errors='coerce')
    return t.dt.hour * 60 + t.dt.minute + t.dt.second / 60


def bweb_secoes(ano, turno):
    """BU em CSV -> uma linha por secao: votos por candidato, branco, nulo, aptos, comparecimento, horarios e habilitacao manual."""
    import numpy as np
    extra = ['DT_ABERTURA', 'DT_ENCERRAMENTO', 'QT_ELEITORES_BIOMETRIA_NH'] if ano >= 2018 else []
    cols = ['SG_UF', 'CD_MUNICIPIO', 'NM_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_LOCAL_VOTACAO', 'CD_TIPO_VOTAVEL', 'NR_VOTAVEL',
            'QT_VOTOS', 'QT_APTOS', 'QT_COMPARECIMENTO'] + extra
    partes = []
    for f in sorted((R / 'bu' / f'{ano}-t{turno}').glob('*_PRESIDENTE.parquet')):
        b = pd.read_parquet(f, columns=cols)
        for c in ('CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_LOCAL_VOTACAO', 'QT_VOTOS', 'QT_APTOS', 'QT_COMPARECIMENTO', 'CD_TIPO_VOTAVEL'):
            b[c] = pd.to_numeric(b[c], errors='coerce').fillna(0).astype(int)
        b['rotulo'] = np.select([b.CD_TIPO_VOTAVEL == 1, b.CD_TIPO_VOTAVEL == 2], ['v' + b.NR_VOTAVEL.astype(str), 'branco'], 'nulo')
        k = ['SG_UF', 'CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO']
        w = b.pivot_table(index=k, columns='rotulo', values='QT_VOTOS', aggfunc='sum', fill_value=0)
        agg = dict(municipio=('NM_MUNICIPIO', 'first'), voting_place=('NR_LOCAL_VOTACAO', 'first'), aptos=('QT_APTOS', 'first'),
                   comp=('QT_COMPARECIMENTO', 'first'))
        if extra:
            agg.update(abertura=('DT_ABERTURA', 'first'), encerramento=('DT_ENCERRAMENTO', 'first'), manual=('QT_ELEITORES_BIOMETRIA_NH', 'first'))
        partes.append(b.groupby(k).agg(**agg).join(w).reset_index())
    d = pd.concat(partes, ignore_index=True).rename(columns={'SG_UF': 'uf', 'CD_MUNICIPIO': 'municipality', 'NR_ZONA': 'zone', 'NR_SECAO': 'section'})
    for c in ('branco', 'nulo'):
        if c not in d:
            d[c] = 0
    num = [c for c in d if c.startswith('v') and c[1:].isdigit()] + ['branco', 'nulo']
    d[num] = d[num].fillna(0).astype(int)
    if extra:
        d['abre_min'] = _minutos(d.pop('abertura'), '%d/%m/%Y %H:%M:%S')
        d['enc_min'] = _minutos(d.pop('encerramento'), '%d/%m/%Y %H:%M:%S')
        d['manual'] = pd.to_numeric(d.manual, errors='coerce')
    return d


def secoes_2026(turno):
    """2026: votos do BU de cada urna (base do virada_1t_2t_2026) + horarios e habilitacao (coleta_2026)."""
    s = pd.read_parquet(ROOT / 'relatorios' / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet')
    p = f't{turno}_'
    s = s[s[f'{p}stem'].notna()]
    d = s[KEY + [c for c in s if c.startswith(p)]].rename(columns=lambda c: c[len(p):] if c.startswith(p) else c)
    d = d.drop(columns=['stem']).rename(columns={'comparecimento': 'comp'})
    h = pd.read_parquet(WORK / f'hab_2026_t{turno}.parquet', columns=KEY + ['opening', 'closing', 'hab_0', 'hab_2'])
    d = d.merge(h, on=KEY, how='left')
    d['abre_min'] = _minutos(d.pop('opening'), '%Y%m%dT%H%M%S')
    d['enc_min'] = _minutos(d.pop('closing'), '%Y%m%dT%H%M%S')
    d = d.rename(columns={'hab_2': 'manual', 'hab_0': 'sem_biometria'})
    return d


def fuso():
    """Horas a somar a hora local para chegar a de Brasilia, por municipio (estimado pela abertura das urnas em 2026)."""
    f = pd.read_parquet(ROOT / 'relatorios' / 'verificacoes' / 'fechamento_2026t2' / 'secoes_fechamento_recebimento.parquet',
                        columns=['uf', 'municipality', 'desloc_h'])
    return f.dropna().drop_duplicates(['uf', 'municipality'])


def base(*anos):
    from virada_1t_2t_2026 import REGIAO, nomes_municipios
    WORK.mkdir(parents=True, exist_ok=True)
    fz = fuso()
    fz_uf = fz.groupby('uf').desloc_h.agg(lambda s: s.mode().iloc[0])
    nomes26 = nomes_municipios()
    for ano in [int(x) for x in anos] or (2014, 2018, 2022, 2026):
        a, b = FINAL[ano]
        rod = []
        for turno in (1, 2):
            d = secoes_2026(turno) if ano == 2026 else bweb_secoes(ano, turno)
            vs = [c for c in d if c.startswith('v') and c[1:].isdigit()]
            for c in (f'v{a}', f'v{b}'):
                if c not in d:
                    d[c] = 0
            d['validos'] = d[vs].sum(axis=1)
            if turno == 2:
                d = d.rename(columns={f'v{a}': 'A', f'v{b}': 'B'}).drop(columns=[c for c in vs if c not in (f'v{a}', f'v{b}')])
            else:
                d = d.rename(columns={f'v{a}': 'A', f'v{b}': 'B'})
            dup = d.duplicated(KEY)
            if dup.any():
                print(ano, turno, 'secoes repetidas descartadas:', int(dup.sum()), flush=True)
                d = d[~dup]
            rod.append(d.rename(columns={c: f't{turno}_{c}' for c in d if c not in KEY}))
        s = rod[1].merge(rod[0], on=KEY, how='inner')
        print(ano, 'secoes no 2o turno', len(rod[1]), '| com 1o turno', len(s), flush=True)
        s['voting_place'] = s.pop('t2_voting_place').astype(int)
        s = s.drop(columns=['t1_voting_place'], errors='ignore')
        if 't2_municipio' in s:
            s['municipio'] = s.pop('t2_municipio')
            s = s.drop(columns=['t1_municipio'], errors='ignore')
        else:
            s = s.merge(nomes26, on=['uf', 'municipality'], how='left')
        s['regiao'] = s.uf.map(REGIAO)
        # fuso: por municipio de 2026; municipio sem correspondencia fica com o fuso mais comum da UF
        s = s.merge(fz, on=['uf', 'municipality'], how='left')
        s['desloc_h'] = s.desloc_h.fillna(s.uf.map(fz_uf))
        for t in ('t1', 't2'):
            if f'{t}_enc_min' in s:
                s[f'{t}_enc_bsb'] = s[f'{t}_enc_min'] + 60 * s.desloc_h
        # candidatos do 1o turno: os que tiveram ao menos 0,5% dos validos no pais ficam em coluna propria; os demais somados
        v1 = [c for c in s if c.startswith('t1_v') and c[4:].isdigit()]
        tot = s[v1].sum() / s.t1_validos.sum()
        maiores = [c for c in v1 if tot[c] >= .005]
        s['t1_menores'] = s[[c for c in v1 if c not in maiores]].sum(axis=1)
        s = s.drop(columns=[c for c in v1 if c not in maiores])
        s['ano'] = ano
        s.to_parquet(WORK / f'base_{ano}.parquet', index=False)
        print(ano, 'colunas:', list(s.columns), flush=True)
        print(ano, 'totais 2o turno: A', int(s.t2_A.sum()), 'B', int(s.t2_B.sum()), '| 1o turno A', int(s.t1_A.sum()), 'B', int(s.t1_B.sum()),
              '| manual t2', s.get('t2_manual', pd.Series(dtype=float)).sum(), flush=True)
        del s, rod


# ---------- teste cego ----------
# Bases reais (4 eleicoes) + copias com manipulacoes plantadas, embaralhadas e com rotulos neutros (D01..D11, X/Y).
# A chave fica lacrada (so o hash e publicado antes) e so e aberta depois da classificacao.
CEGO = WORK / 'cego'
CEGO_OUT = OUT / 'teste_cego'
PLANTADAS = {
    'troca_2uf': 'em 2 UFs sorteadas, inverte X e Y no 2o turno em 10% das secoes que Y venceu',
    'troca_pais': 'no pais, inverte X e Y no 2o turno em 0,5% das secoes que Y venceu',
    'proporcao_municipios': 'em 20% dos municipios (todas as secoes), passa 8% dos votos de Y para X',
    'proporcao_secoes': 'em 10% das secoes sorteadas, passa 15% dos votos de Y para X',
    'fatia_fixa': 'em 5% das secoes sorteadas, fixa X em 60% dos validos',
    'manual': 'nas secoes do decimo com mais habilitacao sem digital, passa para X metade desse numero, tirando de Y',
    'regional_suave': 'numa regiao sorteada, passa 4% dos validos de Y para X em todas as secoes',
}
DECISIVAS = {  # metrica -> (sentido suspeito, piso da escala robusta)
    'trocas_razao_obs_sim': (1, .5), 'trocas_por_10mil': (1, 1), 'fora4_razao_obs_sim': (1, .5), 'fora4_por_10mil': (1, 2),
    'fora4_saldo_X_por_10mil': (0, 2), 'ganho_pct_uniforme_demais': (1, .3), 'fatia_pct_uniforme_demais': (1, .3),
    'ganho_pct_disperso_demais': (1, 1), 'ultimo_dig_X_menoslog10p': (1, 1), 'ultimo_dig_Y_menoslog10p': (1, 1),
    'razao_max_z': (1, 1), 'razao_picos_z6': (1, 2), 'fatia_max_z': (1, 1), 'fatia_picos_z6': (1, 2),
    'manual_mudanca_mesmo_local_incl': (0, .05), 'manual_nivel_mesmo_local_incl': (0, .05), 'viradas_razao_obs_sim': (1, .1),
    'dentro_local_sobre_piso': (1, .2), 'corr_com_vizinhas': (-1, .05), 'transf_rmse_municipio_pp': (1, .3),
    'transf_p99_municipio_pp': (1, 1), 'transf_erro_nacional_pp_medio': (1, .2)}
LIMIAR_Z = 4.0


def _planta(d, tipo, rng):
    import numpy as np
    d = d.copy()
    x, y = d.t2_X.to_numpy().copy(), d.t2_Y.to_numpy().copy()
    n = x + y
    info = {}
    if tipo in ('troca_2uf', 'troca_pais'):
        if tipo == 'troca_2uf':
            grandes = d.uf.value_counts()
            ufs = [str(u) for u in rng.choice(sorted(grandes[(grandes >= 5000) & (grandes.index != 'ZZ')].index), 2, replace=False)]
            pool = np.flatnonzero((d.uf.isin(ufs) & (d.t2_Y > d.t2_X)).to_numpy())
            m = rng.choice(pool, int(.10 * len(pool)), replace=False)
            info['ufs'] = ufs
        else:
            pool = np.flatnonzero((d.t2_Y > d.t2_X).to_numpy())
            m = rng.choice(pool, int(.005 * len(pool)), replace=False)
        x[m], y[m] = y[m].copy(), x[m].copy()
    elif tipo == 'proporcao_municipios':
        mun = d[['uf', 'municipality']].drop_duplicates()
        esc = mun.sample(frac=.2, random_state=int(rng.integers(1 << 31)))
        m = np.flatnonzero(d.set_index(['uf', 'municipality']).index.isin(esc.set_index(['uf', 'municipality']).index))
        k = np.round(.08 * y[m]).astype(int)
        x[m], y[m] = x[m] + k, y[m] - k
    elif tipo == 'proporcao_secoes':
        m = rng.choice(len(d), int(.10 * len(d)), replace=False)
        k = np.round(.15 * y[m]).astype(int)
        x[m], y[m] = x[m] + k, y[m] - k
    elif tipo == 'fatia_fixa':
        m = rng.choice(np.flatnonzero(n > 0), int(.05 * len(d)), replace=False)
        x[m] = np.round(.6 * n[m]).astype(int)
        y[m] = n[m] - x[m]
    elif tipo == 'manual':
        taxa = (d.t2_manual / d.t2_comp.where(d.t2_comp > 0)).to_numpy()
        m = np.flatnonzero(taxa >= np.nanquantile(taxa, .9))
        k = np.minimum(y[m], np.round(.5 * d.t2_manual.to_numpy()[m]).astype(int))
        x[m], y[m] = x[m] + k, y[m] - k
    elif tipo == 'regional_suave':
        reg = str(rng.choice(sorted(set(d.regiao) - {'Exterior'})))
        m = np.flatnonzero((d.regiao == reg).to_numpy())
        k = np.minimum(y[m], np.round(.04 * n[m]).astype(int))
        x[m], y[m] = x[m] + k, y[m] - k
        info['regiao'] = reg
    info['secoes_alteradas'] = int(len(m))
    info['votos_movidos_liquido_X'] = int((x - d.t2_X.to_numpy()).sum())
    d['t2_X'], d['t2_Y'] = x, y
    return d, info


def cego_prepara():
    import hashlib
    import json
    import os
    from datetime import datetime
    import numpy as np
    from padroes_lib import formato_comum
    CEGO.mkdir(parents=True, exist_ok=True)
    CEGO_OUT.mkdir(parents=True, exist_ok=True)
    if (CEGO / 'chave_lacrada.json').exists():
        raise SystemExit('teste cego ja preparado: apague research/padroes_2t/cego para refazer')
    semente = int.from_bytes(os.urandom(8), 'little')
    rng = np.random.default_rng(semente)
    itens = [('real', ano) for ano in (2014, 2018, 2022, 2026)]
    for tipo in PLANTADAS:
        itens.append((tipo, int(rng.choice([2018, 2022, 2026] if tipo == 'manual' else [2014, 2018, 2022, 2026]))))
    ordem = rng.permutation(len(itens))
    chave = {'semente': semente, 'conjuntos': {}}
    for pos, i in enumerate(ordem, 1):
        tipo, ano = itens[i]
        nome = f'D{pos:02d}'
        c1, c2 = bool(rng.integers(2)), bool(rng.integers(2))
        d = formato_comum(pd.read_parquet(WORK / f'base_{ano}.parquet'), troca_rotulos=c1)
        info = {}
        if tipo != 'real':
            d, info = _planta(d, tipo, rng)
        if c2:  # segunda troca de rotulos: o beneficiado da manipulacao pode ser X ou Y
            for t in ('t1', 't2'):
                d[f'{t}_X'], d[f'{t}_Y'] = d[f'{t}_Y'].copy(), d[f'{t}_X'].copy()
        d.to_parquet(CEGO / f'{nome}.parquet', index=False)
        chave['conjuntos'][nome] = {'tipo': tipo, 'base': ano, 'X_e_o_candidato_do_PT': (not c1) != c2,
                                    'beneficiado_da_manipulacao': ('Y' if c2 else 'X') if tipo != 'real' else None, **info}
        print(nome, 'pronto', flush=True)
    txt = json.dumps(chave, ensure_ascii=False, indent=1)
    (CEGO / 'chave_lacrada.json').write_text(txt, encoding='utf-8')
    h = hashlib.sha256(txt.encode('utf-8')).hexdigest()
    linhas = [f'# Teste cego: protocolo registrado antes da análise', '',
              f'Registrado em {datetime.now():%d/%m/%Y %H:%M}. SHA-256 da chave lacrada (research/padroes_2t/cego/chave_lacrada.json): `{h}`', '',
              f'{len(itens)} conjuntos (D01 a D{len(itens):02d}): as 4 eleições reais para presidente (2014, 2018, 2022, 2026) e '
              f'{len(PLANTADAS)} cópias de eleições reais sorteadas, cada uma com uma manipulação plantada. Ninguém sabe qual é qual até a chave ser aberta. '
              'Os dois finalistas viram X e Y, com troca sorteada; nas plantadas, o beneficiado pode ser X ou Y.', '',
              '## Manipulações plantadas', ''] + [f'- `{k}`: {v}' for k, v in PLANTADAS.items()] + [
              '', '## Regra de decisão (mecânica)', '',
              f'Para cada métrica decisiva, z robusto entre os {len(itens)} conjuntos: (valor − mediana) / max(1,4826·MAD, piso). '
              f'Conjunto marcado como "anômalo" se alguma métrica decisiva passar de z = {LIMIAR_Z} no sentido suspeito '
              '(nas métricas de sinal livre, em módulo). Benford (1º e 2º dígito) entra só como informação: '
              'em contagens por seção, que são limitadas pelo tamanho da seção, Benford não se aplica.', '',
              '| Métrica decisiva | Sentido suspeito | Piso |', '|---|---|---|'] + [
              f'| {k} | {"maior" if s == 1 else "menor" if s == -1 else "módulo"} | {p} |' for k, (s, p) in DECISIVAS.items()] + [
              '', '## Avaliação independente', '',
              'Além da regra mecânica, um avaliador independente (outro agente, sem acesso à chave nem aos dados, só à tabela de métricas '
              'mascarada e a este protocolo) classifica cada conjunto como real ou manipulado antes da abertura da chave.']
    (CEGO_OUT / 'PROTOCOLO.md').write_text('\n'.join(linhas) + '\n', encoding='utf-8')
    print('chave lacrada, sha256', h, flush=True)


def cego_avalia():
    import numpy as np
    from padroes_lib import todos
    rows = []
    for f in sorted(CEGO.glob('D*.parquet')):
        o = todos(pd.read_parquet(f), seed=int(f.stem[1:]))
        for k in ('X', 'Y'):
            o[f'ultimo_dig_{k}_menoslog10p'] = -np.log10(max(o.pop(f'ultimo_dig_{k}_p'), 1e-300))
        rows.append({'conjunto': f.stem, **o})
        print(f.stem, 'avaliado;', sum(pd.isna(v) for v in o.values()), 'metricas vazias', flush=True)
    m = pd.DataFrame(rows).set_index('conjunto')
    z = pd.DataFrame(index=m.index)
    for k, (s, piso) in DECISIVAS.items():
        if k not in m:
            continue
        x = m[k]
        med = x.median()
        esc = max(1.4826 * (x - med).abs().median(), piso)
        zz = (x - med) / esc
        z[k] = zz.abs() if s == 0 else s * zz
    m['regra_maior_z'] = z.max(axis=1)
    m['regra_metrica'] = z.idxmax(axis=1)
    m['regra_anomalo'] = m.regra_maior_z > LIMIAR_Z
    m.to_csv(CEGO_OUT / 'metricas_mascaradas.csv', sep=';', decimal=',', encoding='utf-8-sig')
    z.to_csv(CEGO_OUT / 'z_robusto_mascarado.csv', sep=';', decimal=',', encoding='utf-8-sig')
    print('metricas mascaradas gravadas', flush=True)


def cego_abre():
    import hashlib
    import json
    txt = (CEGO / 'chave_lacrada.json').read_text(encoding='utf-8')
    print('sha256 da chave', hashlib.sha256(txt.encode('utf-8')).hexdigest())
    chave = json.loads(txt)['conjuntos']
    m = pd.read_csv(CEGO_OUT / 'metricas_mascaradas.csv', sep=';', decimal=',', encoding='utf-8-sig').set_index('conjunto')
    k = pd.DataFrame(chave).T
    av = CEGO_OUT / 'avaliacao_independente.csv'
    r = k.join(m)
    if av.exists():
        r = r.join(pd.read_csv(av, sep=';', encoding='utf-8-sig').set_index('conjunto').add_prefix('avaliador_'))
    r.index.name = 'conjunto'
    r.to_csv(CEGO_OUT / 'resultado_aberto.csv', sep=';', decimal=',', encoding='utf-8-sig')
    print(r[['tipo', 'base', 'regra_anomalo', 'regra_metrica', 'regra_maior_z'] + [c for c in r if c.startswith('avaliador_')]].to_string())


if __name__ == '__main__':
    {'coleta_2026': coleta_2026, 'base': base, 'cego_prepara': cego_prepara, 'cego_avalia': cego_avalia,
     'cego_abre': cego_abre}[sys.argv[1]](*sys.argv[2:])
