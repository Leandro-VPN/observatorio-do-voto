"""Teste de "gatilho" no RDV: o RDV guarda, em cada voto nulo, o numero que o eleitor digitou.
Se um codigo digitado (ex.: 99) ligasse algum comportamento na urna, as secoes onde esse codigo
aparece deveriam destoar das vizinhas do mesmo local de votacao, depois de descontado o 1o turno.

coleta [UF ...]  le o RDV de cada urna do 2o turno de 2026 (zip oficial do TSE, HTTP Range) e grava,
                 por secao, os votos de presidente: 13, 22, branco e cada codigo nulo digitado.
                 Saida: research/rdv_gatilho/2026-t2/<UF>.parquet (retoma por UF).
"""
import json
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from auditabr.acquisition import RemoteZipReader  # noqa: E402
from rdv_lib import _rdv_votelist  # noqa: E402
from t2_2026_collect import ival, sval, tree  # noqa: E402
from verifica_rdv_bu_amostra import _member_bytes, indice  # noqa: E402

WORK = ROOT / 'research' / 'rdv_gatilho'
URL = 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_{t}t_{uf}.zip'
UFS = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR',
       'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO', 'ZZ']
THREADS = 4


def presidente(raw):
    """Votos de presidente do RDV: Counter com '13', '22', 'branco' e 'nulo:<digitado>'."""
    cnt = Counter()

    def walk(node):
        v = node[2]
        if not isinstance(v, list):
            return
        vls = [c for c in v if _rdv_votelist(c[2])]
        if vls:
            # cargo explicito (contexto 1) = 1; uma consulta popular na mesma urna (MT e PR em 2026) nao tem contexto 1
            # e o _cod de rdv_lib cairia no U2 = 1
            if not any(c[0] == 2 and c[1] == 1 and not isinstance(c[2], list) and ival(c[2]) == 1 for c in v):
                return
            for vl in vls:
                for voto in vl[2]:
                    kids = voto[2]
                    tipo = ival(kids[0][2])
                    val = sval(kids[1][2]) if len(kids) > 1 and not isinstance(kids[1][2], list) else ''
                    if tipo == 2:
                        cnt[val] += 1
                    elif tipo == 3:
                        cnt['branco'] += 1
                    else:
                        cnt['nulo:' + val] += 1
            return
        for c in v:
            walk(c)
    for t in tree(raw):
        walk(t)
    return cnt


def _lote(url, itens):
    rows = []
    with RemoteZipReader(url, budget=4 * 1024 ** 3) as rz:
        for stem, m in itens:
            row = {'stem': stem}
            for tentativa in range(4):
                try:
                    rz.seek(m['offset'])
                    raw = _member_bytes(rz.read(m['csize'] + 1024), m['offset'], m)
                    c = presidente(raw)
                    nul = {k[5:]: v for k, v in c.items() if k.startswith('nulo:')}
                    row.update(v13=c.get('13', 0), v22=c.get('22', 0), branco=c.get('branco', 0),
                               nulo=sum(nul.values()), nulos=json.dumps(nul, sort_keys=True),
                               outros=sum(v for k, v in c.items() if k not in ('13', '22', 'branco') and not k.startswith('nulo:')))
                    break
                except Exception as exc:
                    if tentativa == 3:
                        row['erro'] = repr(exc)[:150]
                    else:
                        time.sleep(2 * 2 ** tentativa)
            rows.append(row)
    return rows


def coleta_uf(uf, turno=2):
    dest = WORK / f'2026-t{turno}' / f'{uf}.parquet'
    if dest.exists():
        return
    url = URL.format(t=turno, uf=uf)
    t0 = time.time()
    with RemoteZipReader(url, budget=256 * 1024 ** 2) as rz:
        idx = indice(rz)
    itens = sorted((k, v['rdv']) for k, v in idx.items())
    random.Random(0).shuffle(itens)
    lotes = [itens[i::THREADS] for i in range(THREADS)]
    with ThreadPoolExecutor(THREADS) as ex:
        rows = [r for parte in ex.map(lambda x: _lote(url, x), lotes) for r in parte]
    d = pd.DataFrame(rows)
    s = d.stem.str.extract(r'^o\d{5}(?P<uf>[a-z]{2})(?P<municipio>\d{5})(?P<zona>\d{4})(?P<secao>\d{4})$')
    d = pd.concat([s, d], axis=1)
    d['uf'] = d.uf.str.upper()
    dest.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(dest, index=False)
    erros = int(d['erro'].notna().sum()) if 'erro' in d else 0
    print(uf, len(d), 'urnas', f'{time.time() - t0:.0f}s', 'erros', erros, flush=True)


OUT = ROOT / 'relatorios' / 'verificacoes' / 'rdv_gatilho'
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')
MIN_SECOES = 30      # codigo precisa aparecer em ao menos 30 secoes para entrar na varredura
SEED = 20261030


def carrega():
    """RDV de presidente por secao + base do 1o/2o turno (padroes_2t) no formato comum, com o modelo do local."""
    from padroes_lib import formato_comum, modelo_local, prepara
    r = pd.concat([pd.read_parquet(f) for f in sorted((WORK / '2026-t2').glob('*.parquet'))], ignore_index=True)
    for a, b in (('municipio', 'municipality'), ('zona', 'zone'), ('secao', 'section')):
        r[b] = r[a].astype(int)
    b = pd.read_parquet(ROOT / 'research' / 'padroes_2t' / 'base_2026.parquet')
    for c in ('municipality', 'zone', 'section'):
        b[c] = b[c].astype(int)
    m = b.merge(r[['uf', 'municipality', 'zone', 'section', 'v13', 'v22', 'branco', 'nulo', 'nulos', 'outros']],
                on=['uf', 'municipality', 'zone', 'section'], how='left')
    m['rdv_confere'] = (m.v13 == m.t2_A) & (m.v22 == m.t2_B) & (m.branco == m.t2_branco) & (m.nulo == m.t2_nulo)
    c = m[m.v13.notna()].reset_index(drop=True)
    d = prepara(formato_comum(c))
    for col in ('nulos', 'rdv_confere', 't2_nulo', 't2_branco'):
        d[col] = c[col].to_numpy()
    e, phi = modelo_local(d)
    e['res_pp'] = 100 * (e.t2_X / e.n2 - e.p_loo)
    return m, e, phi


def _covariaveis(e):
    x = pd.DataFrame(index=e.index)
    for c in [c for c in e if c.startswith('t1_o') and c[4:].isdigit()][:5] + ['t1_bn', 't1_abst', 't1_menores']:
        x[c] = e[c] / e.t1_aptos.clip(lower=1)
    x['t2_bn'] = e.t2_bn / e.t2_comp.clip(lower=1)
    x['t2_manual'] = e.t2_manual / e.t2_comp.clip(lower=1)
    x['log_n2'] = np.log(e.n2)
    return x.fillna(0)


def _dentro_do_local(v, place):
    return v - v.groupby(place).transform('mean')


def prepara_varredura(e, codigos=None):
    """Indicadores "o codigo aparece na secao", ja sem o efeito do local (efeito fixo) e dos controles (1o turno,
    brancos/nulos, abstencao, liberacao manual, tamanho). Nao dependem do voto em X/Y, entao servem tambem para o gatilho plantado."""
    pres = e.nulos.fillna('{}').map(json.loads)
    cont = Counter(k for p in pres for k in p)
    codigos = codigos or sorted(k for k, n in cont.items() if n >= MIN_SECOES)
    X = _covariaveis(e).apply(lambda s: _dentro_do_local(s, e.place)).to_numpy()
    Q, _ = np.linalg.qr(np.column_stack([X, np.ones(len(X))]))
    prep = {'Q': Q, 'place': e.place, 'cod': {}, 'pres': pres, 'cont': cont}
    for k in codigos:
        ind = pres.map(lambda p, k=k: k in p).astype(float)
        i = _dentro_do_local(ind, e.place).to_numpy()
        i = i - Q @ (Q.T @ i)
        ss = float(i @ i)
        if ss > 0:
            prep['cod'][k] = (i, ss, int(ind.sum()), int(sum(p.get(k, 0) for p in pres)))
    return prep


def varredura(e, prep, codigos=None):
    """Para cada codigo nulo digitado: as secoes onde ele aparece destoam das outras do mesmo local?
    Regressao dentro do local com controles; erro-padrao robusto. Efeito em z (desvio padronizado do modelo do local)
    e em pontos percentuais da fatia de X entre os dois finalistas."""
    Q, place = prep['Q'], prep['place']
    ys = {}
    for nome, c in (('z', 'z'), ('pp', 'res_pp')):
        y = _dentro_do_local(e[c], place).to_numpy()
        ys[nome] = y - Q @ (Q.T @ y)
    rows = []
    for k in codigos or prep['cod']:
        i, ss, nsec, nvot = prep['cod'][k]
        row = {'codigo': k, 'secoes_com_codigo': nsec, 'votos_nulos_com_codigo': nvot}
        for nome, y in ys.items():
            b = float(i @ y) / ss
            row[f'efeito_{nome}'] = b
            row[f'ep_{nome}'] = float(np.sqrt(np.sum((i * (y - b * i)) ** 2))) / ss
        row['t'] = row['efeito_z'] / row['ep_z']
        row['p'] = float(2 * stats.norm.sf(abs(row['t'])))
        rows.append(row)
    o = pd.DataFrame(rows).sort_values('p').reset_index(drop=True)
    o['q_bh'] = np.minimum.accumulate((o.p * len(o) / np.arange(1, len(o) + 1)).to_numpy()[::-1])[::-1].clip(max=1)
    o['limite_bonferroni_t'] = float(stats.norm.isf(.025 / len(prep['cod'])))
    return o


def destaques(e, v, prep):
    """Codigos acima do limite: efeito com 1 ocorrencia x 2 ou mais (gatilho nao depende de quantas vezes foi digitado;
    perfil do eleitor cresce com o numero de eleitores que digitam) e concentracao por UF."""
    Q, place = prep['Q'], prep['place']
    y = _dentro_do_local(e.res_pp, place).to_numpy()
    y = y - Q @ (Q.T @ y)
    rows = []
    for k in v[v.t.abs() > v.limite_bonferroni_t].codigo:
        n = prep['pres'].map(lambda p, k=k: p.get(k, 0))
        X = np.column_stack([(n == 1).astype(float), (n >= 2).astype(float)])
        X = np.column_stack([_dentro_do_local(pd.Series(X[:, j], index=e.index), place).to_numpy() for j in range(2)])
        X = X - Q @ (Q.T @ X)
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        res = y - X @ b
        inv = np.linalg.inv(X.T @ X)
        cov = inv @ (X.T * res ** 2) @ X @ inv
        uf = e.uf[n > 0].value_counts(normalize=True)
        rows.append(dict(codigo=k, secoes_1_vez=int((n == 1).sum()), secoes_2_ou_mais=int((n >= 2).sum()),
                         efeito_1_vez_pp=b[0], ep_1_vez=float(np.sqrt(cov[0, 0])), efeito_2_ou_mais_pp=b[1], ep_2_ou_mais=float(np.sqrt(cov[1, 1])),
                         ufs_principais=', '.join(f'{u} {100 * x:.0f}%' for u, x in uf.head(3).items())))
    return pd.DataFrame(rows)


def _planta(e, alvo, regra, frac_ativas, para_x, rng):
    """Gatilho plantado: nas secoes `alvo` (uma fracao delas ativa), a partir de um momento sorteado do dia os votos seguem a regra."""
    e = e.copy()
    idx = np.flatnonzero(alvo)
    idx = idx[rng.random(len(idx)) < frac_ativas]
    n2 = e.n2.to_numpy()[idx].astype(float)
    x = e.t2_X.to_numpy()[idx].astype(float)
    if not para_x:
        x = n2 - x
    depois = rng.random(len(idx))                      # fracao dos votos dados depois do gatilho
    xa, na = x * depois, n2 * depois
    if regra == '2_para_1':                            # depois do gatilho, 2 de cada 3 votos vao para o beneficiado
        novo_xa = np.maximum(np.round(na * 2 / 3), xa)
    else:                                              # 'um_em_tres': 1 de cada 3 votos do outro vira do beneficiado
        novo_xa = xa + np.round((na - xa) / 3)
    novo = np.clip(np.round(x - xa + novo_xa), 0, n2)
    col = e.columns.get_loc('t2_X')
    e.iloc[idx, col] = (novo if para_x else n2 - novo).astype(int)
    e['t2_Y'] = e.n2 - e.t2_X
    return e, len(idx)


def calibra(e, prep):
    """Poder da varredura: planta gatilhos num codigo real (nas secoes onde ele de fato aparece) e ve se ele sai da varredura."""
    from padroes_lib import modelo_local
    rng = np.random.default_rng(SEED)
    cont = {k: v[2] for k, v in prep['cod'].items()}
    alvos = ['99'] if '99' in cont else []
    for faixa in (100, 1000, 10000):                   # tambem codigos reais presentes em ~100, ~1.000 e ~10.000 secoes
        k = min(cont, key=lambda c: abs(cont[c] - faixa))
        if k not in alvos:
            alvos.append(k)
    base_cols = [c for c in e.columns if c not in ('p_loo', 'p_full', 'sd', 'z', 'z_troca', 'k', 'res_pp')]
    rows = []
    for cod in alvos:
        alvo = prep['pres'].map(lambda p, c=cod: c in p).to_numpy()
        fracs = [1.0, .5, .2]
        if cod == alvos[0]:                            # gatilho usado em poucas secoes: 10, 30 e 100
            fracs += [k / alvo.sum() for k in (10, 30, 100) if k < alvo.sum() * .2]
        for regra in ('2_para_1', 'um_em_tres'):
            for frac in fracs:
                for para_x in (True, False):
                    p, n_ativas = _planta(e[base_cols], alvo, regra, frac, para_x, rng)
                    ep, _ = modelo_local(p)
                    assert len(ep) == len(e)
                    ep['res_pp'] = 100 * (ep.t2_X / ep.n2 - ep.p_loo)
                    v = varredura(ep, prep)
                    s = v[v.codigo == cod].iloc[0]
                    rows.append(dict(codigo=cod, secoes_com_codigo=int(alvo.sum()), regra=regra, fracao_ativa=frac,
                                     beneficiado='X' if para_x else 'Y', secoes_ativas=n_ativas, t=s.t, efeito_pp=s.efeito_pp,
                                     posicao_na_varredura=int(s.name) + 1, codigos_na_varredura=len(v),
                                     passa_bonferroni=bool(abs(s.t) > s.limite_bonferroni_t),
                                     secoes_com_codigo_fora_do_modelo=int((np.abs(ep.z.to_numpy()[alvo]) > 4).sum()),
                                     fora_do_modelo_total=int((np.abs(ep.z) > 4).sum())))
                    print({k: rows[-1][k] for k in ('codigo', 'regra', 'fracao_ativa', 'beneficiado', 't', 'posicao_na_varredura')}, flush=True)
    return pd.DataFrame(rows)


def analisa():
    OUT.mkdir(parents=True, exist_ok=True)
    m, e, phi = carrega()
    tem = m.v13.notna()
    conf = pd.DataFrame([dict(secoes_base=len(m), secoes_com_rdv=int(tem.sum()), rdv_igual_bu=int(m.rdv_confere[tem].sum()),
                              rdv_diferente_bu=int((~m.rdv_confere[tem]).sum()), votos_outros_tipos=int(m.outros.fillna(0).sum()),
                              secoes_no_modelo=len(e), phi=phi)])
    conf.to_csv(OUT / 'rdv_x_bu_2026t2.csv', **CSV)
    print(conf.T, flush=True)
    m.loc[tem & ~m.rdv_confere, ['uf', 'municipality', 'zone', 'section', 'v13', 't2_A', 'v22', 't2_B', 'branco', 't2_branco',
                                'nulo', 't2_nulo']].to_csv(OUT / 'rdv_diferente_bu_2026t2.csv', **CSV)
    prep = prepara_varredura(e)
    v = varredura(e, prep)
    v.to_csv(OUT / 'varredura_codigos_2026t2.csv', **CSV)
    print(v.head(12).to_string(), flush=True)
    dd = destaques(e, v, prep)
    dd.to_csv(OUT / 'codigos_acima_do_limite.csv', **CSV)
    print(dd.to_string(), flush=True)
    calibra(e, prep).to_csv(OUT / 'calibracao_gatilho_plantado.csv', **CSV)


if __name__ == '__main__':
    from baixa_pais import prioridade_baixa
    prioridade_baixa()
    if sys.argv[1] == 'coleta':
        for uf in sys.argv[2:] or UFS:
            coleta_uf(uf)
    elif sys.argv[1] == 'analisa':
        analisa()
