"""Pericia de log das secoes destoantes do 2o turno de 2026 contra as vizinhas do mesmo local de votacao.

Grupos (a partir de research/anomalias_2t/secoes_2026.parquet, gerado por anomalias_2t.py secoes):
  modelo     fora dos modelos: |z| > 4 no modelo do local (M1) ou no gradient boosting (M2), ou p < 1e-6 na distancia
             robusta (M3), ou entre as 0,01% mais isoladas (Isolation Forest)
  tarde      periodo tardio: voto depois das 19h, 5 ou mais votos depois das 17h, ou encerramento depois das 19h (Brasilia)
  vizinhas   as demais secoes dos mesmos locais (controle)
Do log de cada uma (so o dia da eleicao, hora de Brasilia): votos por meia hora, pausas, mudanca de ritmo (razao de
verossimilhanca de duas taxas), habilitacao manual (total e depois das 16h/17h), correcoes na tela de confirmacao, alertas e
a contagem de cada tipo de evento. Comparacao dentro do local: Cochran-Mantel-Haenszel (evento presente ou nao) e diferenca
media grupo - vizinhas (variaveis continuas), com correcao de Benjamini-Hochberg.
Saida: relatorios/verificacoes/anomalias_2t/logs_*.csv e research/anomalias_2t/logs_secoes.parquet (retoma por bloco).
"""
import json
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]

WORK = ROOT / 'research' / 'anomalias_2t'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'anomalias_2t'
UV = ROOT / 'relatorios' / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv'
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')
CHAVE = ['uf', 'municipality', 'zone', 'section']
DIA = '25/10/2026 '
BINS = np.arange(480, 1201, 30)          # 8h00 a 20h00, de meia em meia hora (Brasilia)
MAX_VIZINHAS = 6                         # por secao marcada, no maximo 6 vizinhas do mesmo local
VOTO = 'O voto do eleitor foi computado'
MANUAL = 'Solicitação de dado pessoal do eleitor para habilitação manual'
CORRIGIU = 'Eleitor corrigiu na tela de confirmação de candidato'
ENCERRA = 'Operador selecionou: Encerrar votação'
CONTING = 'INFO | GAP | Início do procedimento de contingência'
CANCELA = 'INFO | VOTA | Operador cancelou o encerramento da votação'


def _norm(msg):
    return re.sub(r'\d+', '#', re.sub(r'\[[^\]]*\]', '[]', msg))[:90]


def _mudanca_de_ritmo(v):
    """Maior razao de log-verossimilhanca entre 'uma taxa de votos' e 'duas taxas, antes e depois de um ponto' (intervalos exponenciais)."""
    g = np.diff(v)
    g = g[g > 0]
    m = len(g)
    if m < 30:
        return np.nan, np.nan
    c = np.cumsum(g)
    k = np.arange(10, m - 10)
    s1, s2 = c[k - 1], c[-1] - c[k - 1]
    ll = k * np.log(k / s1) + (m - k) * np.log((m - k) / s2) - m * np.log(m / c[-1])
    i = int(np.argmax(ll))
    return float(ll[i]), float(v[0] + c[k[i] - 1])


def le_log(args):
    path, desloc = args
    from auditabr.logs import read_log
    try:
        data = read_log(Path(path))
    except Exception as exc:
        return {'erro': repr(exc)[:120]}, {}
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('latin1')
    cnt, votos, manual, corr, alertas, encerra, tempos = Counter(), [], [], [], 0, [], []
    for line in text.splitlines():
        if not line.startswith(DIA):
            continue
        f = line.split('\t')
        if len(f) < 5:
            continue
        try:
            t = int(line[11:13]) * 60 + int(line[14:16]) + int(line[17:19]) / 60 + 60 * desloc
        except ValueError:
            continue
        msg = f[4]
        tempos.append(t)
        cnt[f'{f[1]} | {f[3]} | {_norm(msg)}'] += 1
        alertas += f[1] != 'INFO'
        if msg == VOTO:
            votos.append(t)
        elif msg == MANUAL:
            manual.append(t)
        elif msg == CORRIGIU:
            corr.append(t)
        elif msg == ENCERRA:
            encerra.append(t)
    v = np.sort(np.array(votos))
    o = {'votos': len(v), 'alertas': alertas, 'manual': len(manual), 'corrigiu': len(corr), 'eventos_distintos': len(cnt)}
    if len(v):
        g = np.diff(v)
        man = np.array(manual)
        o.update(primeiro_voto=v[0], ultimo_voto=v[-1], pausa_max_min=float(g.max()) if len(g) else np.nan,
                 intervalo_mediano_min=float(np.median(g)) if len(g) else np.nan, pausas_15min=int((g > 15).sum()),
                 votos_apos_16h=int((v >= 960).sum()), votos_apos_17h=int((v >= 1020).sum()),
                 manual_apos_16h=int((man >= 960).sum()), manual_apos_17h=int((man >= 1020).sum()))
        o['ritmo_llr'], o['ritmo_ponto_min'] = _mudanca_de_ritmo(v)
        if encerra:
            tt = np.array(tempos)
            o['encerrou_min'] = encerra[-1]
            o['min_ultimo_voto_ate_encerrar'] = encerra[-1] - v[-1]
            o['eventos_entre_ultimo_voto_e_encerrar'] = int(((tt > v[-1]) & (tt < encerra[-1])).sum())
        h = np.histogram(v, BINS)[0]
        for i, x in enumerate(h):
            o[f'b{BINS[i] // 60:02d}h{BINS[i] % 60:02d}'] = int(x)
    return o, dict(cnt)


def grupos():
    s = pd.read_parquet(WORK / 'secoes_2026.parquet')
    from scipy.stats import chi2
    s['g_modelo'] = (s.z.abs() > 4) | (s.z_m2.abs() > 4) | (chi2.sf(s.d2_m3, 5) < 1e-6) | (s.iso_m3 >= s.iso_m3.quantile(.9999))
    s['g_tarde'] = (s.votos_apos_19h.fillna(0) > 0) | (s.votos_apos_17h.fillna(0) >= 5) | (s.t2_enc_bsb >= 1140)
    s['marcada'] = s.g_modelo | s.g_tarde
    loc = s.groupby(['uf', 'municipality', 'zone', 'voting_place'])
    s['local_marcado'] = loc.marcada.transform('any')
    s['n_marcadas_local'] = loc.marcada.transform('sum')
    viz = s[s.local_marcado & ~s.marcada].copy()
    viz['ordem'] = np.random.default_rng(0).random(len(viz))
    viz['r'] = viz.groupby(['uf', 'municipality', 'zone', 'voting_place']).ordem.rank()
    viz = viz[viz.r <= MAX_VIZINHAS * viz.n_marcadas_local]
    sel = pd.concat([s[s.marcada], viz])
    sel['grupo'] = np.where(sel.marcada, np.where(sel.g_modelo, 'modelo', 'tarde'), 'vizinhas')
    sel['tambem_tarde'] = sel.g_tarde & sel.g_modelo
    print(sel.grupo.value_counts().to_dict(), 'locais', sel.groupby(['uf', 'municipality', 'zone', 'voting_place']).ngroups, flush=True)
    return sel


def coleta():
    sel = grupos()
    u = pd.read_csv(UV, sep=';', decimal=',', encoding='utf-8-sig', usecols=CHAVE + ['path', 'desloc_h'], low_memory=False)
    for c in ('municipality', 'zone', 'section'):
        u[c] = u[c].astype(int)
    sel = sel.merge(u.drop_duplicates(CHAVE), on=CHAVE, how='left')
    sel = sel[sel.path.notna()].reset_index(drop=True)
    cache = WORK / 'logs_cache'
    cache.mkdir(parents=True, exist_ok=True)
    feitos = {p.stem for p in cache.glob('*.parquet')}
    blocos = [sel.iloc[i:i + 1000] for i in range(0, len(sel), 1000)]
    with ProcessPoolExecutor(2) as ex:
        for k, b in enumerate(blocos):
            if f'{k:04d}' in feitos:
                continue
            res = list(ex.map(le_log, zip(b.path, b.desloc_h.fillna(0)), chunksize=20))
            f = pd.DataFrame([r[0] for r in res], index=b.index)
            f['eventos'] = [json.dumps(r[1], ensure_ascii=False) for r in res]
            pd.concat([b[CHAVE + ['voting_place', 'grupo', 'tambem_tarde', 'z', 'z_m2', 'res_pp', 'n2']], f], axis=1).to_parquet(cache / f'{k:04d}.parquet')
            print('bloco', k + 1, 'de', len(blocos), flush=True)
    pd.concat([pd.read_parquet(p) for p in sorted(cache.glob('*.parquet'))]).to_parquet(WORK / 'logs_secoes.parquet', index=False)


def _bh(p):
    p = np.asarray(p, float)
    o = np.argsort(p)
    q = np.empty_like(p)
    q[o] = np.minimum.accumulate((p[o] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    return q.clip(max=1)


def _cmh(tem, grupo, estrato):
    """Cochran-Mantel-Haenszel (2x2 por local): o evento aparece mais nas secoes do grupo do que nas vizinhas do mesmo local?"""
    df = pd.DataFrame({'a': tem & grupo, 'g': grupo, 'e': tem, 's': estrato})
    k = df.groupby('s').agg(a=('a', 'sum'), n1=('g', 'sum'), m1=('e', 'sum'), n=('g', 'size'))
    k = k[(k.n1 > 0) & (k.n1 < k.n) & (k.n > 1)]
    ea = k.n1 * k.m1 / k.n
    va = k.n1 * (k.n - k.n1) * k.m1 * (k.n - k.m1) / (k.n ** 2 * (k.n - 1))
    if va.sum() <= 0:
        return np.nan, np.nan, np.nan
    z = (k.a.sum() - ea.sum()) / np.sqrt(va.sum())
    return float(k.a.sum()), float(ea.sum()), float(z)


def compara():
    d = pd.read_parquet(WORK / 'logs_secoes.parquet')
    d = d[d.votos.fillna(0) > 0].copy()
    d['local'] = d.groupby(['uf', 'municipality', 'zone', 'voting_place']).ngroup()
    bcols = [c for c in d if re.fullmatch(r'b\d\dh\d\d', c)]
    for c in bcols:
        d['pct_' + c] = 100 * d[c].fillna(0) / d.votos
    d['pct_manual'] = 100 * d.manual / d.votos
    d['pct_manual_apos_17h'] = 100 * d.manual_apos_17h / d.manual.where(d.manual > 0)
    d['alertas_por_100_votos'] = 100 * d.alertas / d.votos
    d['corrigiu_por_100_votos'] = 100 * d.corrigiu / d.votos
    cont = ['votos', 'pct_manual', 'pct_manual_apos_17h', 'alertas_por_100_votos', 'corrigiu_por_100_votos', 'pausa_max_min',
            'intervalo_mediano_min', 'pausas_15min', 'ritmo_llr', 'ritmo_ponto_min', 'primeiro_voto', 'ultimo_voto', 'encerrou_min',
            'min_ultimo_voto_ate_encerrar', 'eventos_entre_ultimo_voto_e_encerrar'] + ['pct_' + c for c in bcols]
    # o grupo "modelo" se divide em: destoou no voto (M1/M2) e destoou so no vetor de mudanca (M3, Isolation Forest)
    voto = (d.z.abs() > 4) | (d.z_m2.abs() > 4)
    d['grupo'] = np.where(d.grupo == 'modelo', np.where(voto, 'fora_voto', 'fora_multivariado'), d.grupo)
    cont = ['res_pp'] + cont
    ev = d.eventos.map(json.loads).to_numpy()
    onde = {}
    for i, e in enumerate(ev):
        for k in e:
            onde.setdefault(k, []).append(i)
    pos = pd.Series(np.arange(len(d)), index=d.index)
    rows_c, rows_e, resumo = [], [], []
    for g in ('fora_voto', 'fora_multivariado', 'tarde'):
        x = d[d.grupo.isin([g, 'vizinhas'])]
        x = x[x.groupby('local').grupo.transform(lambda s, g=g: (s == g).any() and (s == 'vizinhas').any())]
        eg = (x.grupo == g).to_numpy()
        px = pos[x.index].to_numpy()
        for c in cont:
            m = x.groupby(['local', eg])[c].mean().unstack()
            if True not in m or False not in m:
                continue
            dif = (m[True] - m[False]).dropna()
            if len(dif) < 3 or dif.std() == 0:
                continue
            rows_c.append(dict(grupo=g, variavel=c, locais=len(dif), media_grupo=float(x.loc[eg, c].mean()), media_vizinhas=float(x.loc[~eg, c].mean()),
                               diferenca=float(dif.mean()), ep=float(dif.std(ddof=1) / np.sqrt(len(dif))),
                               p=float(stats.ttest_1samp(dif, 0).pvalue)))
        for t, idx in onde.items():
            if len(idx) < 20:
                continue
            tem = pd.Series(np.isin(px, idx), index=x.index)
            a, ea, z = _cmh(tem, pd.Series(eg, index=x.index), x.local)
            if np.isnan(z):
                continue
            rows_e.append(dict(grupo=g, evento=t, secoes_grupo_com=int(a), esperado=ea, pct_grupo=100 * float(tem[eg].mean()),
                               pct_vizinhas=100 * float(tem[~eg].mean()), z=z, p=float(2 * stats.norm.sf(abs(z)))))
        tg = d[d.grupo == g]
        cc = [r for r in rows_c if r['grupo'] == g and r['variavel'] == 'res_pp']
        resumo.append(dict(grupo=g, secoes=len(tg), locais_comparados=int(x.local.nunique()),
                           contingencia_pct=100 * float(np.isin(pos[tg.index], onde.get(CONTING, [])).mean()),
                           cancelou_encerramento_pct=100 * float(np.isin(pos[tg.index], onde.get(CANCELA, [])).mean()),
                           a_favor_PT=int((tg.z_m2 > 4).sum()), a_favor_adversario=int((tg.z_m2 < -4).sum()),
                           diferenca_res_pp=cc[0]['diferenca'] if cc else np.nan, ep_res_pp=cc[0]['ep'] if cc else np.nan))
    v = d[d.grupo == 'vizinhas']
    resumo.append(dict(grupo='vizinhas', secoes=len(v), contingencia_pct=100 * float(np.isin(pos[v.index], onde.get(CONTING, [])).mean()),
                       cancelou_encerramento_pct=100 * float(np.isin(pos[v.index], onde.get(CANCELA, [])).mean())))
    c = pd.DataFrame(rows_c)
    c['q_bh'] = c.groupby('grupo').p.transform(lambda x: _bh(x.fillna(1)))
    e = pd.DataFrame(rows_e)
    e['q_bh'] = e.groupby('grupo').p.transform(lambda x: _bh(x.fillna(1)))
    c.sort_values(['grupo', 'p']).to_csv(OUT / 'logs_continuas.csv', **CSV)
    e.sort_values(['grupo', 'p']).to_csv(OUT / 'logs_eventos.csv', **CSV)
    pd.DataFrame(resumo).to_csv(OUT / 'logs_resumo_grupos.csv', **CSV)
    perfil = {}
    for g in ('fora_voto', 'fora_multivariado', 'tarde'):   # so locais com o grupo e vizinhas: compara o mesmo lugar
        x = d[d.grupo.isin([g, 'vizinhas'])]
        x = x[x.groupby('local').grupo.transform(lambda s, g=g: (s == g).any() and (s == 'vizinhas').any())]
        perfil[g] = x[x.grupo == g][['pct_' + c for c in bcols]].mean()
        perfil[g + '_vizinhas'] = x[x.grupo == 'vizinhas'][['pct_' + c for c in bcols]].mean()
    pd.DataFrame(perfil).reset_index().rename(columns={'index': 'meia_hora'}).to_csv(OUT / 'logs_perfil_horario.csv', **CSV)
    print(pd.DataFrame(resumo).to_string(), flush=True)
    for g in ('fora_voto', 'fora_multivariado', 'tarde'):
        print(g)
        print(c[c.grupo == g].sort_values('p').head(8)[['variavel', 'media_grupo', 'media_vizinhas', 'diferenca', 'ep', 'q_bh']].to_string(), flush=True)
        print(e[e.grupo == g].sort_values('p').head(8)[['evento', 'pct_grupo', 'pct_vizinhas', 'z', 'q_bh']].to_string(), flush=True)

def _tardios(args):
    """Votos no dia e votos depois das 17h (Brasilia) de um log."""
    path, desloc, dia = args
    from auditabr.logs import read_log
    try:
        text = read_log(Path(path)).decode('utf-8-sig', errors='replace')
    except Exception:
        return np.nan, np.nan
    v = a17 = 0
    for line in text.splitlines():
        if line.startswith(dia) and VOTO in line:
            v += 1
            a17 += int(line[11:13]) * 60 + int(line[14:16]) + 60 * desloc >= 1020
    return v, a17


def controle_2022():
    """Mesma medida do M6 ("teve voto depois das 17h" x vizinhas) em 2022 e 2026, com a mesma regra de selecao:
    locais em que alguma secao encerrou depois das 17h15 (Brasilia). 2022 le o log so dessas secoes."""
    loc = ['uf', 'municipality', 'zone', 'voting_place']
    rows = []
    for ano in (2022, 2026):
        b = pd.read_parquet(ROOT / 'research' / 'padroes_2t' / f'base_{ano}.parquet', columns=loc + ['section', 't2_enc_bsb', 'desloc_h'])
        for c in ('municipality', 'zone', 'section'):
            b[c] = b[c].astype(int)
        b = b[(b.groupby(loc).t2_enc_bsb.transform('max') > 1035) & (b.uf != 'ZZ')]
        s = pd.read_parquet(WORK / f'secoes_{ano}.parquet').merge(b[CHAVE + ['desloc_h']], on=CHAVE)
        if ano == 2022:
            cache = WORK / 'controle_2022_logs.parquet'
            if not cache.exists():
                pasta = {uf: ROOT / 'research' / ('piloto-ba-2022-t2' if uf == 'BA' else f'estados/{uf}/2022-t2') / 'logs' for uf in s.uf.unique()}
                paths = [str(pasta[u] / f'o00407-{m:05d}{z:04d}{x:04d}.logjez') for u, m, z, x in zip(s.uf, s.municipality, s.zone, s.section)]
                with ProcessPoolExecutor(2) as ex:
                    res = list(ex.map(_tardios, zip(paths, s.desloc_h.fillna(0), ['30/10/2022 '] * len(s)), chunksize=50))
                pd.DataFrame(res, columns=['votos_log', 'votos_apos_17h']).assign(**{c: s[c].to_numpy() for c in CHAVE}).to_parquet(cache)
            s = s.drop(columns=[c for c in ('votos_log', 'votos_apos_17h') if c in s]).merge(pd.read_parquet(cache), on=CHAVE)
        s = s[s.votos_log.notna()]
        s['place'] = s.groupby(loc).ngroup()
        x = (s.votos_apos_17h > 0).astype(float)
        dm = lambda v: (v - v.groupby(s.place).transform('mean')).to_numpy()  # noqa: E731
        xi, y, ln = dm(x), dm(s.res_pp), dm(np.log(s.n2))
        for nome, xx, yy in (('sem controle', xi, y), ('com tamanho', xi - ln * (ln @ xi) / (ln @ ln), y - ln * (ln @ y) / (ln @ ln))):
            bb = float(xx @ yy) / float(xx @ xx)
            se = float(np.sqrt(np.sum((xx * (yy - bb * xx)) ** 2))) / float(xx @ xx)
            rows.append(dict(ano=ano, regra='locais com secao encerrada depois das 17h15', versao=nome, secoes=len(s), locais=int(s.place.nunique()),
                             secoes_com_voto_apos_17h=int(x.sum()), votos_apos_17h=int(s.votos_apos_17h.sum()), efeito_pp=bb, ep_pp=se, t=bb / se))
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(OUT / 'm6_controle_2022.csv', **CSV)


if __name__ == '__main__':
    from baixa_pais import prioridade_baixa
    prioridade_baixa()
    {'grupos': grupos, 'coleta': coleta, 'compara': compara, 'controle_2022': controle_2022}[sys.argv[1]]()
