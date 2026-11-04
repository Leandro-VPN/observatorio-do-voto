"""Habitantes x eleitores (titulos) x votantes: regua nacional por municipio e detalhe por zona/secao em Campos dos Goytacazes.

Fontes:
- BU por secao (research/padroes_2t/base_<ano>.parquet): t2_aptos = titulos aptos a votar na secao, t2_comp = votantes (2o turno).
- IBGE, Censo 2022, populacao por idade (SIDRA tabela 9514: total, 0-4, 5-9, 10-14, 15, 16 e 17 anos) -> habitantes com 16 anos ou mais
  (idade minima para votar) e com 18 ou mais (voto obrigatorio). Estimativas de populacao 2025 e 2026 (SIDRA tabela 6579). Lista de
  municipios (API de localidades). Arquivos em research/ibge/ (baixados em 04/11/2026).
- Casamento TSE x IBGE por UF + nome normalizado; o que sobra e casado por similaridade dentro da UF e registrado em casamento_fallback.csv.

Medidas por municipio (2026 e 2022, 2o turno): titulos / habitantes 16+ (Censo 2022), titulos / populacao estimada do ano, votantes /
habitantes 16+, titulos por secao, crescimento de titulos 2022 -> 2026 contra o crescimento da populacao estimada. Regua: distribuicao por
faixa de tamanho e posicao de Campos. Em Campos: por zona e por secao (titulos, votantes, titulos por secao, 2022 -> 2026, secoes novas).

Saida: relatorios/verificacoes/eleitorado_populacao/ (ELEITORADO_POPULACAO.pdf/.xlsx + CSVs).
Como repetir: python -I scripts/eleitorado_populacao.py
"""
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
BASE = ROOT / 'research' / 'padroes_2t'
IBGE = ROOT / 'research' / 'ibge'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'eleitorado_populacao'
CAMPOS = 58190
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
FAIXAS = [(0, 10_000, 'até 10 mil'), (10_000, 50_000, '10–50 mil'), (50_000, 200_000, '50–200 mil'), (200_000, 10**9, '200 mil ou mais')]


# ----------------------------------------------------------------------------------------------------------------------- IBGE
def _norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().upper()
    s = re.sub(r"['’`´\-]", ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def ibge_municipios():
    m = json.load(open(IBGE / 'municipios.json', encoding='utf-8'))
    d = pd.DataFrame({'ibge': [int(x['municipio-id']) for x in m], 'nome_ibge': [x['municipio-nome'] for x in m],
                      'uf': [x['UF-sigla'] for x in m]})
    d['chave'] = d.nome_ibge.map(_norm)
    return d


def _sidra(nome, dim_cod, dim_nome):
    d = json.load(open(IBGE / nome, encoding='utf-8'))[1:]
    t = pd.DataFrame({'ibge': [int(r['D1C']) for r in d], 'cat': [r[dim_nome] for r in d], 'v': pd.to_numeric([r['V'] for r in d], errors='coerce')})
    return t.pivot_table(index='ibge', columns='cat', values='v', aggfunc='first')


def ibge_populacao():
    p = _sidra('sidra_9514_idades.json', 'D5C', 'D5N')
    pop = pd.DataFrame({'pop_total': p['Total'],
                        'pop_16mais': p['Total'] - p['0 a 4 anos'] - p['5 a 9 anos'] - p['10 a 14 anos'] - p['15 anos'],
                        'pop_16_17': p['16 anos'] + p['17 anos']})
    pop['pop_18mais'] = pop.pop_16mais - pop.pop_16_17
    e = _sidra('sidra_6579_estimativas.json', 'D3C', 'D3N').rename(columns=lambda c: f'est_{c}')
    return pop.join(e, how='left').reset_index()


# ----------------------------------------------------------------------------------------------------------------------- TSE
def tse(ano):
    b = pd.read_parquet(BASE / f'base_{ano}.parquet', columns=['uf', 'municipality', 'municipio', 'zone', 'section', 'voting_place',
                                                                't2_aptos', 't2_comp', 't1_aptos', 't1_comp'])
    b = b[b.uf != 'ZZ']
    m = b.groupby(['uf', 'municipality', 'municipio']).agg(secoes=('section', 'size'), zonas=('zone', 'nunique'), locais=('voting_place', 'nunique'),
                                                           aptos=('t2_aptos', 'sum'), votantes=('t2_comp', 'sum'), aptos_t1=('t1_aptos', 'sum')).reset_index()
    m['chave'] = m.municipio.map(_norm)
    return b, m


MANUAL = {('GO', 'BOM JESUS'): 5203500, ('RN', 'BOA SAUDE'): 2405306, ('RR', 'SAO LUIZ'): 1400605}   # nomes diferentes nas duas fontes


def casa(m, ib):
    """Casa municipios do TSE com o IBGE por UF + nome normalizado; sobras por similaridade dentro da UF (1 para 1, registradas) e 3 a mao."""
    j = m.merge(ib[['uf', 'chave', 'ibge', 'nome_ibge']], on=['uf', 'chave'], how='left')
    fb = []
    for (uf, chave), cod in MANUAL.items():
        i = j.index[(j.uf == uf) & (j.chave == chave) & j.ibge.isna()]
        if len(i):
            k = ib[ib.ibge == cod].iloc[0]
            j.loc[i, ['ibge', 'nome_ibge']] = [k.ibge, k.nome_ibge]
            fb.append(dict(uf=uf, tse=int(j.loc[i[0], 'municipality']), nome_tse=j.loc[i[0], 'municipio'], ibge=cod, nome_ibge=k.nome_ibge, similaridade='manual'))
    for uf in sorted(j.uf.unique()):
        sem = j[(j.uf == uf) & j.ibge.isna()]
        livres = ib[(ib.uf == uf) & ~ib.ibge.isin(j.ibge.dropna())]
        for i, r in sem.iterrows():
            cand = difflib.get_close_matches(r.chave, list(livres.chave), n=1, cutoff=0.75)
            if cand:
                k = livres[livres.chave == cand[0]].iloc[0]
                j.loc[i, ['ibge', 'nome_ibge']] = [k.ibge, k.nome_ibge]
                livres = livres[livres.ibge != k.ibge]
                fb.append(dict(uf=uf, tse=r.municipality, nome_tse=r.municipio, ibge=int(k.ibge), nome_ibge=k.nome_ibge,
                               similaridade=round(difflib.SequenceMatcher(None, r.chave, k.chave).ratio(), 3)))
    return j, pd.DataFrame(fb)


# ----------------------------------------------------------------------------------------------------------------------- medidas
def faixa(pop):
    return pd.cut(pop, [f[0] for f in FAIXAS] + [10**9], labels=[f[2] for f in FAIXAS], right=False)


def medidas(j26, j22, pop):
    c = j26.merge(pop, on='ibge', how='left').merge(j22[['ibge', 'secoes', 'aptos', 'votantes']].rename(columns={'secoes': 'secoes_2022', 'aptos': 'aptos_2022', 'votantes': 'votantes_2022'}),
                                                     on='ibge', how='left')
    c['faixa'] = faixa(c.pop_16mais)
    c['titulos_por_hab16'] = c.aptos / c.pop_16mais
    c['titulos_por_hab18'] = c.aptos / c.pop_18mais
    c['titulos_por_hab_total'] = c.aptos / c.pop_total
    c['titulos_por_est_2026'] = c.aptos / c.est_2026
    c['votantes_por_hab16'] = c.votantes / c.pop_16mais
    c['titulos_por_secao'] = c.aptos / c.secoes
    c['titulos_2022_por_hab16'] = c.aptos_2022 / c.pop_16mais
    c['cresc_titulos'] = c.aptos / c.aptos_2022 - 1
    c['cresc_pop_est'] = c.est_2026 / c.pop_total - 1
    c['cresc_titulos_menos_pop'] = c.cresc_titulos - c.cresc_pop_est
    return c


def regua(c):
    linhas = []
    for f in [x[2] for x in FAIXAS] + ['todos']:
        g = c if f == 'todos' else c[c.faixa == f]
        r = g.titulos_por_hab16.dropna()
        linhas.append(dict(faixa=f, municipios=len(g), hab16_milhoes=g.pop_16mais.sum() / 1e6, titulos_milhoes=g.aptos.sum() / 1e6,
                           razao_agregada=g.aptos.sum() / g.pop_16mais.sum(), mediana=r.median(), p10=r.quantile(.1), p90=r.quantile(.9), p99=r.quantile(.99),
                           acima_100=int((r > 1).sum()), acima_110=int((r > 1.1).sum()), acima_120=int((r > 1.2).sum()),
                           titulos_acima_pop_total=int((g.titulos_por_hab_total > 1).sum()), mediana_2022=g.titulos_2022_por_hab16.median(),
                           acima_100_2022=int((g.titulos_2022_por_hab16 > 1).sum())))
    return pd.DataFrame(linhas)


def posicao(c, mun, col):
    r = c[c.municipality == mun].iloc[0]
    tudo = c[col].dropna()
    fx = c[c.faixa == r.faixa][col].dropna()
    return dict(valor=float(r[col]), pct_pais=float((tudo < r[col]).mean() * 100), pct_faixa=float((fx < r[col]).mean() * 100), n_faixa=int(len(fx)),
                acima_na_faixa=int((fx > r[col]).sum()))


# ----------------------------------------------------------------------------------------------------------------------- Campos
def campos(b26, b22, c):
    k = ['uf', 'municipality', 'zone', 'section']
    s26 = b26[b26.municipality == CAMPOS].copy()
    s22 = b22[b22.municipality == CAMPOS][k + ['t2_aptos', 't2_comp']].rename(columns={'t2_aptos': 'aptos_2022', 't2_comp': 'votantes_2022'})
    s = s26.merge(s22, on=k, how='outer', indicator=True)
    s['situacao'] = s._merge.map({'both': 'nas duas', 'left_only': 'nova em 2026', 'right_only': 'só em 2022'})
    s['cresc_titulos'] = s.t2_aptos / s.aptos_2022 - 1
    s['comparecimento'] = s.t2_comp / s.t2_aptos
    z = s.groupby('zone').agg(secoes_2026=('t2_aptos', lambda x: int(x.notna().sum())), secoes_2022=('aptos_2022', lambda x: int(x.notna().sum())),
                              novas=('situacao', lambda x: int((x == 'nova em 2026').sum())), so_2022=('situacao', lambda x: int((x == 'só em 2022').sum())),
                              titulos_2026=('t2_aptos', 'sum'), titulos_2022=('aptos_2022', 'sum'), votantes_2026=('t2_comp', 'sum'),
                              votantes_2022=('votantes_2022', 'sum'), locais=('voting_place', 'nunique')).reset_index()
    z['titulos_por_secao_2026'] = z.titulos_2026 / z.secoes_2026
    z['titulos_por_secao_2022'] = z.titulos_2022 / z.secoes_2022
    z['cresc_titulos'] = z.titulos_2026 / z.titulos_2022 - 1
    z['comparecimento_2026'] = z.votantes_2026 / z.titulos_2026
    z['comparecimento_2022'] = z.votantes_2022 / z.titulos_2022
    tot = dict(zone='total', secoes_2026=int(s.t2_aptos.notna().sum()), secoes_2022=int(s.aptos_2022.notna().sum()), novas=int((s.situacao == 'nova em 2026').sum()),
               so_2022=int((s.situacao == 'só em 2022').sum()), titulos_2026=s.t2_aptos.sum(), titulos_2022=s.aptos_2022.sum(), votantes_2026=s.t2_comp.sum(),
               votantes_2022=s.votantes_2022.sum(), locais=int(s.voting_place.nunique()))
    tot['titulos_por_secao_2026'] = tot['titulos_2026'] / tot['secoes_2026']
    tot['titulos_por_secao_2022'] = tot['titulos_2022'] / tot['secoes_2022']
    tot['cresc_titulos'] = tot['titulos_2026'] / tot['titulos_2022'] - 1
    tot['comparecimento_2026'] = tot['votantes_2026'] / tot['titulos_2026']
    tot['comparecimento_2022'] = tot['votantes_2022'] / tot['titulos_2022']
    z = pd.concat([z, pd.DataFrame([tot])], ignore_index=True)
    return s.drop(columns='_merge'), z


# ----------------------------------------------------------------------------------------------------------------------- figuras
TINTA, TINTA2, AZUL, LARANJA = '#1a365d', '#6b7280', '#2b6cb0', '#dd6b20'


def _eixos(ax):
    ax.tick_params(colors=TINTA2, labelsize=7)
    for s in ax.spines.values():
        s.set_color('#cccccc')
    ax.grid(True, color='#eeeeee', lw=.5)


def fig_regua(c):
    fig, axs = plt.subplots(1, 2, figsize=(14, 5.2))
    ax = axs[0]
    g = c.dropna(subset=['pop_16mais', 'titulos_por_hab16'])
    ax.scatter(g.pop_16mais, 100 * g.titulos_por_hab16, s=5, color=AZUL, alpha=.35, lw=0)
    r = g[g.municipality == CAMPOS].iloc[0]
    ax.scatter([r.pop_16mais], [100 * r.titulos_por_hab16], s=70, color=LARANJA, zorder=5)
    ax.annotate('Campos', (r.pop_16mais, 100 * r.titulos_por_hab16), xytext=(6, 6), textcoords='offset points', fontsize=8, color=LARANJA)
    ax.axhline(100, color=TINTA2, lw=.8, ls='--')
    ax.set_xscale('log'); ax.set_ylim(40, 180)
    ax.set_xlabel('habitantes com 16 anos ou mais (Censo 2022, escala log)', fontsize=8, color=TINTA2)
    ax.set_ylabel('títulos aptos no 2º turno de 2026 por 100 habitantes 16+', fontsize=8, color=TINTA2)
    ax.set_title('Cada ponto é um município', fontsize=9, color=TINTA)
    _eixos(ax)
    ax = axs[1]
    for f, cor in zip([x[2] for x in FAIXAS], ['#9ecae1', '#6baed6', '#3182bd', '#08519c']):
        v = 100 * c[c.faixa == f].titulos_por_hab16.dropna()
        ax.hist(v, bins=np.arange(40, 181, 2.5), histtype='step', lw=1.4, color=cor, label=f'{f} (n = {len(v)})', density=True)
    ax.axvline(100 * r.titulos_por_hab16, color=LARANJA, lw=1.2, label='Campos')
    ax.axvline(100, color=TINTA2, lw=.8, ls='--')
    ax.set_xlabel('títulos por 100 habitantes 16+', fontsize=8, color=TINTA2); ax.set_ylabel('densidade', fontsize=8, color=TINTA2)
    ax.legend(fontsize=7, frameon=False); ax.set_title('Distribuição por faixa de tamanho do município', fontsize=9, color=TINTA)
    _eixos(ax)
    fig.tight_layout(); p = OUT / 'figuras' / 'regua.png'; fig.savefig(p, dpi=130); plt.close(fig)
    return p


def fig_crescimento(c):
    fig, ax = plt.subplots(figsize=(8, 5))
    g = c.dropna(subset=['cresc_titulos', 'cresc_pop_est'])
    g = g[g.pop_16mais >= 20_000]
    ax.scatter(100 * g.cresc_pop_est, 100 * g.cresc_titulos, s=6, color=AZUL, alpha=.4, lw=0)
    r = g[g.municipality == CAMPOS].iloc[0]
    ax.scatter([100 * r.cresc_pop_est], [100 * r.cresc_titulos], s=70, color=LARANJA, zorder=5)
    ax.annotate('Campos', (100 * r.cresc_pop_est, 100 * r.cresc_titulos), xytext=(6, 6), textcoords='offset points', fontsize=8, color=LARANJA)
    lim = [-15, 35]
    ax.plot(lim, lim, color=TINTA2, lw=.8, ls='--'); ax.set_xlim(lim); ax.set_ylim(-20, 40)
    ax.set_xlabel('população: estimativa 2026 contra Censo 2022 (%)', fontsize=8, color=TINTA2)
    ax.set_ylabel('títulos: 2º turno 2026 contra 2º turno 2022 (%)', fontsize=8, color=TINTA2)
    ax.set_title('Municípios com 20 mil habitantes 16+ ou mais; a diagonal é crescimento igual', fontsize=9, color=TINTA)
    _eixos(ax); fig.tight_layout(); p = OUT / 'figuras' / 'crescimento.png'; fig.savefig(p, dpi=130); plt.close(fig)
    return p


def fig_campos(s, z):
    fig, axs = plt.subplots(1, 2, figsize=(14, 4.8))
    ax = axs[0]
    zz = z[z.zone != 'total']
    x = np.arange(len(zz))
    ax.bar(x - .2, zz.titulos_2022 / 1e3, .4, color='#9ecae1', label='2022')
    ax.bar(x + .2, zz.titulos_2026 / 1e3, .4, color=AZUL, label='2026')
    ax.set_xticks(x); ax.set_xticklabels([f'zona {int(v)}' for v in zz.zone], fontsize=8)
    ax.set_ylabel('títulos aptos (mil)', fontsize=8, color=TINTA2); ax.legend(fontsize=8, frameon=False)
    ax.set_title('Campos: títulos por zona', fontsize=9, color=TINTA); _eixos(ax)
    ax = axs[1]
    ax.hist(s.aptos_2022.dropna(), bins=np.arange(0, 1001, 25), histtype='step', lw=1.3, color='#9ecae1', label='2022')
    ax.hist(s.t2_aptos.dropna(), bins=np.arange(0, 1001, 25), histtype='step', lw=1.3, color=AZUL, label='2026')
    ax.set_xlabel('títulos aptos na seção', fontsize=8, color=TINTA2); ax.set_ylabel('seções', fontsize=8, color=TINTA2)
    ax.legend(fontsize=8, frameon=False); ax.set_title('Campos: tamanho das seções', fontsize=9, color=TINTA); _eixos(ax)
    fig.tight_layout(); p = OUT / 'figuras' / 'campos.png'; fig.savefig(p, dpi=130); plt.close(fig)
    return p


# ----------------------------------------------------------------------------------------------------------------------- relatório
def relatorio(c, R, fb, sem, s, z, p26, figs):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate
    from make_bahia_reports import H1, H2, P, SM, fig_img, n, table
    from make_padroes_report import sn

    pc = lambda v, d=1: f'{n(100 * v, d)}%'
    r = c[c.municipality == CAMPOS].iloc[0]
    tot = R[R.faixa == 'todos'].iloc[0]
    st = [Paragraph('Habitantes, títulos e votantes: o eleitorado cabe na população? (2º turno de 2026, com 2022 e o Censo 2022)', H1),
          Paragraph('Pergunta: em cada município, quantos títulos aptos a votar há por habitante em idade de votar, quantos votaram, e isso muda de '
                    '2022 para 2026 mais do que a população? Títulos e votantes vêm dos boletins de urna por seção (soma das seções do município); '
                    'habitantes vêm do Censo 2022 do IBGE por idade (16 anos ou mais = idade mínima para votar) e das estimativas de população '
                    'para 2026. Descritivo: títulos acima dos habitantes têm causas conhecidas (eleitor domiciliado em outro município, título não '
                    'cancelado após óbito ou mudança, revisão biométrica pendente, cidades de fronteira e de segunda residência, subcontagem censitária) '
                    'e nenhuma razão isolada afirma irregularidade.', P),
          Paragraph('1. Fontes e casamento dos municípios', H2),
          Paragraph(f'Base por seção: {n(p26["secoes"])} seções de {n(p26["municipios"])} municípios em 2026 (exterior excluído), {n(p26["aptos"] / 1e6, 2)} milhões de '
                    f'títulos aptos e {n(p26["votantes"] / 1e6, 2)} milhões de votantes no 2º turno. IBGE: 5.570 municípios, {n(tot.hab16_milhoes, 1)} milhões de '
                    f'habitantes com 16 anos ou mais no Censo 2022. Casamento por UF e nome: {n(p26["municipios"] - len(fb) - len(sem))} municípios casados pelo nome exato, '
                    f'{len(fb)} por similaridade (lista em casamento_fallback.csv) e {len(sem)} sem par' + (f' ({", ".join(sem.municipio + "/" + sem.uf)})' if len(sem) else '') +
                    f'. No país, há {n(tot.razao_agregada * 100, 1)} títulos por 100 habitantes 16+; a mediana dos municípios é {n(tot.mediana * 100, 1)}.', P),
          CondPageBreak(14 * cm), Paragraph('2. Régua nacional: títulos por 100 habitantes com 16 anos ou mais', H2),
          fig_img(figs['regua'], w=25)]
    t = [['Faixa (hab. 16+)', 'Municípios', 'Hab. 16+ (mi)', 'Títulos (mi)', 'Razão agregada', 'Mediana', 'p10', 'p90', 'p99', '> 100', '> 110', '> 120',
          'Títulos > pop. total', 'Mediana 2022', '> 100 em 2022']]
    for y in R.itertuples():
        t.append([y.faixa, n(y.municipios), n(y.hab16_milhoes, 1), n(y.titulos_milhoes, 1), pc(y.razao_agregada), pc(y.mediana), pc(y.p10), pc(y.p90), pc(y.p99),
                  n(y.acima_100), n(y.acima_110), n(y.acima_120), n(y.titulos_acima_pop_total), pc(y.mediana_2022), n(y.acima_100_2022)])
    st += [table(t, font=7, widths=[2.6 * cm, 1.8 * cm, 1.9 * cm, 1.8 * cm, 2 * cm, 1.6 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 1.2 * cm, 1.2 * cm, 1.2 * cm, 2.4 * cm, 2 * cm, 2 * cm]),
           Paragraph('“> 100”: municípios com mais títulos aptos do que habitantes de 16 anos ou mais; “Títulos > pop. total”: mais títulos do que habitantes de '
                     'qualquer idade. 2022: títulos do 2º turno de 2022 contra o mesmo Censo (mesmo ano da contagem). Percentis sobre os municípios da faixa.', SM)]
    g = c.dropna(subset=['titulos_por_hab16']).sort_values('titulos_por_hab16', ascending=False)
    t = [['Município', 'UF', 'Hab. 16+', 'Títulos 2026', 'Títulos/100 hab. 16+', 'Em 2022', 'Votantes/100 hab. 16+', 'Títulos/pop. total', 'Cresc. títulos 22→26', 'Cresc. pop. est. 22→26']]
    for y in g.head(20).itertuples():
        t.append([y.municipio.title(), y.uf, n(y.pop_16mais), n(y.aptos), pc(y.titulos_por_hab16), pc(y.titulos_2022_por_hab16), pc(y.votantes_por_hab16),
                  pc(y.titulos_por_hab_total), sn(100 * y.cresc_titulos, 1) + '%', sn(100 * y.cresc_pop_est, 1) + '%'])
    st += [CondPageBreak(8 * cm), Paragraph('Os 20 municípios com mais títulos por habitante 16+ (qualquer tamanho)', H2),
           table(t, font=7, widths=[4.2 * cm, 1 * cm, 2 * cm, 2.2 * cm, 2.6 * cm, 1.8 * cm, 2.8 * cm, 2.4 * cm, 2.8 * cm, 2.8 * cm])]
    gg = g[g.pop_16mais >= 100_000]
    t = [t[0]]
    for y in gg.head(20).itertuples():
        t.append([y.municipio.title(), y.uf, n(y.pop_16mais), n(y.aptos), pc(y.titulos_por_hab16), pc(y.titulos_2022_por_hab16), pc(y.votantes_por_hab16),
                  pc(y.titulos_por_hab_total), sn(100 * y.cresc_titulos, 1) + '%', sn(100 * y.cresc_pop_est, 1) + '%'])
    st += [CondPageBreak(8 * cm), Paragraph(f'Os 20 maiores valores entre os {n(len(gg))} municípios com 100 mil habitantes 16+ ou mais', H2),
           table(t, font=7, widths=[4.2 * cm, 1 * cm, 2 * cm, 2.2 * cm, 2.6 * cm, 1.8 * cm, 2.8 * cm, 2.4 * cm, 2.8 * cm, 2.8 * cm])]
    gc = c.dropna(subset=['cresc_titulos_menos_pop'])
    gc = gc[gc.pop_16mais >= 20_000].sort_values('cresc_titulos_menos_pop', ascending=False)
    t = [['Município', 'UF', 'Hab. 16+', 'Títulos 2022', 'Títulos 2026', 'Cresc. títulos', 'Cresc. pop. est.', 'Diferença', 'Títulos/100 hab. 16+ (2026)']]
    for y in gc.head(15).itertuples():
        t.append([y.municipio.title(), y.uf, n(y.pop_16mais), n(y.aptos_2022), n(y.aptos), sn(100 * y.cresc_titulos, 1) + '%', sn(100 * y.cresc_pop_est, 1) + '%',
                  sn(100 * y.cresc_titulos_menos_pop, 1) + ' pontos', pc(y.titulos_por_hab16)])
    st += [CondPageBreak(8 * cm), Paragraph('3. Títulos que crescem mais que a população (2022 → 2026, municípios com 20 mil hab. 16+ ou mais)', H2),
           fig_img(figs['crescimento'], w=13),
           Paragraph(f'Entre os {n(len(gc))} municípios dessa faixa, a mediana do crescimento dos títulos entre os 2º turnos de 2022 e 2026 é '
                     f'{sn(100 * gc.cresc_titulos.median(), 1)}% e a da população estimada (Censo 2022 → estimativa 2026) é {sn(100 * gc.cresc_pop_est.median(), 1)}%. '
                     f'Os 15 em que os títulos mais cresceram além da população:', P),
           table(t, font=7, widths=[4.4 * cm, 1 * cm, 2.2 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm, 2.6 * cm, 2.6 * cm, 3.4 * cm])]
    # Campos
    pos16 = posicao(c, CAMPOS, 'titulos_por_hab16')
    posv = posicao(c, CAMPOS, 'votantes_por_hab16')
    posg = posicao(c, CAMPOS, 'cresc_titulos_menos_pop')
    st += [CondPageBreak(8 * cm), Paragraph('4. Campos dos Goytacazes (RJ)', H2),
           Paragraph(f'Censo 2022: {n(r.pop_total)} habitantes, {n(r.pop_16mais)} com 16 anos ou mais ({n(r.pop_18mais)} com 18 ou mais); estimativa 2026: '
                     f'{n(r.est_2026)}. Títulos aptos no 2º turno: {n(r.aptos_2022)} em 2022 e {n(r.aptos)} em 2026 ({sn(100 * r.cresc_titulos, 1)}%), contra população '
                     f'estimada {sn(100 * r.cresc_pop_est, 1)}%. Votantes em 2026: {n(r.votantes)}. Razões de 2026: {n(100 * r.titulos_por_hab16, 1)} títulos por 100 '
                     f'habitantes 16+ (percentil {n(pos16["pct_pais"])} do país e {n(pos16["pct_faixa"])} da faixa “{r.faixa}”, {n(pos16["acima_na_faixa"])} dos '
                     f'{n(pos16["n_faixa"])} municípios da faixa acima dela); {n(100 * r.votantes_por_hab16, 1)} votantes por 100 habitantes 16+ (percentil '
                     f'{n(posv["pct_pais"])} do país); crescimento dos títulos além da população {sn(100 * r.cresc_titulos_menos_pop, 1)} pontos (percentil '
                     f'{n(posg["pct_pais"])} do país). Títulos por seção: {n(r.titulos_por_secao, 0)} ({n(r.secoes)} seções, {n(r.zonas)} zonas, {n(r.locais)} locais).', P),
           fig_img(figs['campos'], w=25)]
    t = [['Zona', 'Seções\n2022', 'Seções\n2026', 'Novas em\n2026', 'Só em\n2022', 'Títulos\n2022', 'Títulos\n2026', 'Cresc.', 'Títulos por\nseção 2022',
          'Títulos por\nseção 2026', 'Compare-\ncimento 2022', 'Compare-\ncimento 2026', 'Locais']]
    for y in z.itertuples():
        t.append([str(y.zone), n(y.secoes_2022), n(y.secoes_2026), n(y.novas), n(y.so_2022), n(y.titulos_2022), n(y.titulos_2026), sn(100 * y.cresc_titulos, 1) + '%',
                  n(y.titulos_por_secao_2022, 0), n(y.titulos_por_secao_2026, 0), pc(y.comparecimento_2022), pc(y.comparecimento_2026), n(y.locais)])
    st += [CondPageBreak(5 * cm), table(t, font=7, widths=[1.4 * cm, 1.8 * cm, 1.8 * cm, 2 * cm, 1.8 * cm, 2 * cm, 2 * cm, 1.6 * cm, 2.4 * cm, 2.4 * cm, 2.6 * cm, 2.6 * cm, 1.4 * cm])]
    novas = s[s.situacao == 'nova em 2026']
    grandes = s[s.t2_aptos > 600]
    cres = s[(s.situacao == 'nas duas') & (s.cresc_titulos > .2)]
    st += [Paragraph(f'Seções: {n(len(novas))} novas em 2026 (não existiam no 2º turno de 2022), com {n(novas.t2_aptos.sum())} títulos; {n((s.situacao == "só em 2022").sum())} '
                     f'só em 2022. Seções com mais de 600 títulos: {n(len(grandes))}. Seções existentes nos dois anos cujos títulos cresceram mais de 20%: {n(len(cres))} '
                     f'(lista em campos_secoes.csv). Comparecimento por seção em 2026: mediana {pc(s.comparecimento.median())}, mínimo {pc(s.comparecimento.min())}, '
                     f'máximo {pc(s.comparecimento.max())}; seções com comparecimento acima de 95%: {n((s.comparecimento > .95).sum())}.', P)]
    # leitura
    st += [CondPageBreak(6 * cm), Paragraph('5. Leitura', H2),
           Paragraph(f'No país há mais títulos aptos do que habitantes em idade de votar em {n(tot.acima_100)} dos {n(tot.municipios)} municípios '
                     f'({pc(tot.acima_100 / tot.municipios)}), quase todos pequenos; em 2022, contra o mesmo Censo, eram {n(tot.acima_100_2022)}. '
                     f'É o retrato conhecido do cadastro eleitoral: títulos de quem mora em outro município, óbitos e mudanças ainda não cancelados e, '
                     f'nas cidades pequenas, o peso de quem mantém o título na terra natal. Esse pano de fundo é o que uma cidade precisa superar para '
                     f'chamar atenção por essa medida. Campos fica no percentil {n(pos16["pct_pais"])} do país em títulos por habitante e no percentil '
                     f'{n(posg["pct_pais"])} em crescimento de títulos além da população: {"dentro do comum" if 5 < pos16["pct_pais"] < 95 and 5 < posg["pct_pais"] < 95 else "fora do comum"} '
                     f'nas duas. O que esta conta não vê: a população por zona ou por seção não existe nas fontes públicas, então o detalhe abaixo do '
                     f'município só pode comparar títulos, votantes e seções entre 2022 e 2026. Como repetir: scripts/eleitorado_populacao.py; tabelas em '
                     f'ELEITORADO_POPULACAO.xlsx e nos CSVs da pasta.', P)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7)
        cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE e do IBGE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(OUT / 'ELEITORADO_POPULACAO.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='Habitantes, títulos e votantes', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', OUT / 'ELEITORADO_POPULACAO.pdf')


def main():
    (OUT / 'figuras').mkdir(parents=True, exist_ok=True)
    ib = ibge_municipios()
    pop = ibge_populacao()
    b26, m26 = tse(2026)
    b22, m22 = tse(2022)
    j26, fb = casa(m26, ib)
    j22, fb22 = casa(m22, ib)
    sem = j26[j26.ibge.isna()]
    print('casados 2026:', j26.ibge.notna().sum(), 'de', len(j26), '| por similaridade:', len(fb), '| sem par:', len(sem))
    if len(sem):
        print(sem[['uf', 'municipality', 'municipio']].to_string(index=False))
    print('casados 2022:', j22.ibge.notna().sum(), 'de', len(j22), '| sem par:', j22.ibge.isna().sum())
    c = medidas(j26[j26.ibge.notna()].copy(), j22[j22.ibge.notna()], pop)
    R = regua(c)
    s, z = campos(b26, b22, c)
    p26 = dict(secoes=len(b26), municipios=len(m26), aptos=m26.aptos.sum(), votantes=m26.votantes.sum())
    figs = dict(regua=fig_regua(c), crescimento=fig_crescimento(c), campos=fig_campos(s, z))
    c.drop(columns=['chave']).to_csv(OUT / 'municipios.csv', **CSV)
    R.to_csv(OUT / 'regua_faixas.csv', **CSV)
    fb.to_csv(OUT / 'casamento_fallback.csv', **CSV)
    z.to_csv(OUT / 'campos_zonas.csv', **CSV)
    s.to_csv(OUT / 'campos_secoes.csv', **CSV)
    print(R.round(3).to_string(index=False))
    print(z.round(3).to_string(index=False))
    relatorio(c, R, fb, sem, s, z, p26, figs)
    from ultimo_voto_2026t2 import xlsx_leve
    xlsx_leve(OUT / 'ELEITORADO_POPULACAO.xlsx', [(p.stem[:31], pd.read_csv(p, sep=';', decimal=',', encoding='utf-8-sig')) for p in sorted(OUT.glob('*.csv'))])


if __name__ == '__main__':
    main()
