"""Campos dos Goytacazes (RJ), 2º turno de 2026: o excesso de Lula entre os turnos está espalhado ou concentrado?

Checklist do texto "Campos dos Goytacazes — modelo de probabilidades do 2º turno de 2026":
  1. votação por seção do 2º turno de 2026 do RJ -> já está na base por seção (BU), 1.190 seções de Campos;
  2. por seção, ganho de Lula e variação de comparecimento entre os turnos, com 2022 como controle;
  3. o excesso está espalhado ou concentrado? distribuição dos ganhos por seção contra o esperado pelo acaso.

Medidas por cidade (todas as cidades com >= 10 mil votos em disputa, 2026 e 2022, para dar a régua):
  - f = ganho de Lula / votos em disputa; d = f da cidade - f do estado;
  - modelo de virada uniforme dentro da cidade: logit(p2) = logit(p1) + delta (delta ajustado ao total da cidade);
    resíduo de Pearson z por seção; var(z), curtose, fração |z| > 3; mistura de 2 normais (EM) contra 1 normal (dBIC);
    fatia do excesso positivo nos 10% de seções com maior excesso; R² dos prédios (quanto do resíduo é "de bairro");
    correlação do resíduo com a variação de comparecimento, com a fatia de "outros" no 1º turno e com p1;
  - resíduo dentro do prédio (M1, anomalias_2t): var(z), curtose, fração |z| > 3.
Marcas de log (2026): habilitação manual, votos depois das 16h/17h, cancelamentos, urna trocada; as seções de maior
resíduo em Campos contra as demais de Campos.

Saídas: relatorios/verificacoes/campos_goytacazes/ (CSVs, figuras, CAMPOS_2T.pdf).
Uso: python scripts/campos_2t.py
"""
import re
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.special import expit, logit
from scipy.stats import kurtosis, norm, skew

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]

OUT = ROOT / 'relatorios' / 'verificacoes' / 'campos_goytacazes'
FIG = OUT / 'figuras'
BASE = ROOT / 'research' / 'padroes_2t'
ANOM = ROOT / 'research' / 'anomalias_2t'
BINS = ROOT / 'research' / 'janelas_horario'
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')
CHAVE = ['uf', 'municipality', 'zone', 'section']
CAMPOS, SJB, UF = 58190, 58998, 'RJ'
MIN_DISPUTA = 10_000
NOME = {2026: 'Lula × Flávio (2026)', 2022: 'Lula × Bolsonaro (2022)'}
AZUL, LARANJA, CINZA, CLARO = '#2a78d6', '#eb6834', '#9a9993', '#f1f0ec'


# ---------------------------------------------------------------- base
def carrega(ano):
    b = pd.read_parquet(BASE / f'base_{ano}.parquet')
    e = pd.read_parquet(ANOM / f'secoes_{ano}.parquet', columns=CHAVE + ['z', 'res_pp', 'p_loo'])
    b = b.merge(e.rename(columns={'z': 'z_predio', 'res_pp': 'res_predio'}), on=CHAVE, how='left')
    b['disputa'] = b.t2_validos - b.t1_A - b.t1_B           # = outros do 1º turno + variação dos válidos
    b['ganho_A'] = b.t2_A - b.t1_A
    b['n1'], b['n2'] = b.t1_A + b.t1_B, b.t2_A + b.t2_B
    b['p1'], b['p2'] = b.t1_A / b.n1, b.t2_A / b.n2
    b['outros1'] = (b.t1_validos - b.n1) / b.t1_validos
    b['tx1'], b['tx2'] = b.t1_comp / b.t1_aptos, b.t2_comp / b.t2_aptos
    b['dtx'] = b.tx2 - b.tx1
    b['manual2'] = b.t2_manual / b.t2_comp
    if 't2_sem_biometria' in b:
        b['sem_bio2'] = b.t2_sem_biometria / b.t2_comp
    h = BINS / f'bins_{ano}.parquet'
    if h.exists():
        H = pd.read_parquet(h)
        cols = [c for c in H.columns if re.match(r'b\d\dh\d\d', c)]
        tot = H[cols].sum(1)
        H['apos16h'] = H[[c for c in cols if c >= 'b16h00']].sum(1) / tot.where(tot > 0)
        H['apos17h'] = H[[c for c in cols if c >= 'b17h00']].sum(1) / tot.where(tot > 0)
        b = b.merge(H[CHAVE + ['apos16h', 'apos17h', 'contingencia', 'n_logs']], on=CHAVE, how='left')
    return b


def virada_uniforme(c):
    """delta tal que a soma dos previstos bate com o total de Lula da cidade; resíduo de Pearson z e excesso em votos."""
    ok = (c.n1 >= 20) & (c.n2 >= 20)
    c = c[ok].copy()
    l1 = logit(np.clip(c.p1, 1e-3, 1 - 1e-3))
    lo, hi = -5.0, 5.0
    alvo = c.t2_A.sum()
    for _ in range(60):
        d = (lo + hi) / 2
        if (c.n2 * expit(l1 + d)).sum() < alvo:
            lo = d
        else:
            hi = d
    c['p_hat'] = expit(l1 + d)
    c['z'] = (c.p2 - c.p_hat) / np.sqrt(c.p_hat * (1 - c.p_hat) / c.n2)
    c['excesso'] = c.t2_A - c.n2 * c.p_hat
    c['delta'] = d
    return c


def em_mistura(z, it=200):
    """Mistura de duas normais contra uma normal: dBIC (> 0 favorece a mistura), peso e média do componente menor."""
    z = np.asarray(z, float)
    n = len(z)
    mu, sd = z.mean(), z.std()
    ll1 = norm.logpdf(z, mu, sd).sum()
    w, m1, m2, s1, s2 = .8, np.quantile(z, .4), np.quantile(z, .9), sd * .8, sd * 1.2
    for _ in range(it):
        a = w * norm.pdf(z, m1, s1)
        b = (1 - w) * norm.pdf(z, m2, s2)
        r = a / np.maximum(a + b, 1e-300)
        w = r.mean()
        m1, m2 = (r * z).sum() / r.sum(), ((1 - r) * z).sum() / (1 - r).sum()
        s1 = np.sqrt((r * (z - m1) ** 2).sum() / r.sum()) + 1e-6
        s2 = np.sqrt(((1 - r) * (z - m2) ** 2).sum() / (1 - r).sum()) + 1e-6
    ll2 = np.log(w * norm.pdf(z, m1, s1) + (1 - w) * norm.pdf(z, m2, s2)).sum()
    dbic = (2 * ll1 + 2 * np.log(n)) * -1 - (-2 * ll2 + 5 * np.log(n))
    dbic = (-2 * ll1 + 2 * np.log(n)) - (-2 * ll2 + 5 * np.log(n))
    menor = (1 - w, m2, s2) if w >= .5 else (w, m1, s1)
    return dict(dbic=float(dbic), peso_menor=float(menor[0]), media_menor=float(menor[1]), sd_menor=float(menor[2]))


def r2_predios(c):
    """Fração da variância de z explicada pelas médias dos prédios (ajustada pelo número de prédios)."""
    g = c.groupby('voting_place').z
    k, n = g.ngroups, len(c)
    if k < 3 or n <= k + 1:
        return np.nan
    sst = ((c.z - c.z.mean()) ** 2).sum()
    sse = ((c.z - g.transform('mean')) ** 2).sum()
    return float(1 - (sse / (n - k)) / (sst / (n - 1)))


def medidas_cidade(c, ano, f_uf):
    v = virada_uniforme(c)
    z = v.z.to_numpy()
    pos = np.clip(v.excesso, 0, None)
    top = int(np.ceil(.1 * len(v)))
    exc_sorted = np.sort(v.excesso.to_numpy())[::-1]
    m = dict(ano=ano, uf=c.uf.iloc[0], municipality=int(c.municipality.iloc[0]), municipio=c.municipio.iloc[0], secoes=len(c), predios=int(c.voting_place.nunique()),
             disputa=int(c.disputa.sum()), ganho_A=int(c.ganho_A.sum()), f_pct=100 * c.ganho_A.sum() / c.disputa.sum())
    m['d_pp'] = m['f_pct'] - 100 * f_uf
    m.update(delta=float(v.delta.iloc[0]), var_z=float(z.var()), curtose_z=float(kurtosis(z)), assimetria_z=float(skew(z)),
             frac_z_maior_3=float((np.abs(z) > 3).mean()), frac_z_maior_3_positivo=float((z > 3).mean()),
             top10_fatia_excesso_pos=float(np.clip(exc_sorted[:top], 0, None).sum() / max(pos.sum(), 1)),
             r2_predios=r2_predios(v), corr_z_dtx=float(np.corrcoef(z, v.dtx)[0, 1]), corr_z_outros1=float(np.corrcoef(z, v.outros1)[0, 1]),
             corr_z_p1=float(np.corrcoef(z, v.p1)[0, 1]))
    m.update({f'mistura_{k}': val for k, val in em_mistura(z).items()})
    zp = v.z_predio.dropna().to_numpy()
    if len(zp) >= 30:
        m.update(predio_var_z=float(zp.var()), predio_curtose_z=float(kurtosis(zp)), predio_frac_z_maior_3=float((np.abs(zp) > 3).mean()))
    return m, v


def percentil(serie, valor, maior=True):
    s = serie.dropna()
    return float(100 * ((s >= valor).mean() if maior else (s <= valor).mean()))


# ---------------------------------------------------------------- figuras
def _ax(ax, xl, yl):
    ax.set_xlabel(xl, fontsize=7.5, color='#4a4944')
    ax.set_ylabel(yl, fontsize=7.5, color='#4a4944')
    ax.tick_params(colors='#4a4944', labelsize=7)
    for s in ax.spines.values():
        s.set_color('#b9b8b3')
    ax.grid(True, color='#e6e5e0', lw=.6)
    ax.set_axisbelow(True)


def fig_reguas(C):
    FIG.mkdir(parents=True, exist_ok=True)
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.4), dpi=150)
    for ax, ano in zip(axs, (2022, 2026)):
        g = C[C.ano == ano]
        ax.hist(g.d_pp, bins=np.arange(-40, 41, 2.5), color=CINZA if ano == 2022 else AZUL, alpha=.85)
        k = g[g.municipality == CAMPOS]
        if len(k):
            ax.axvline(float(k.d_pp.iloc[0]), color=LARANJA, lw=1.6)
            ax.text(float(k.d_pp.iloc[0]) + .8, ax.get_ylim()[1] * .9, f'Campos {k.d_pp.iloc[0]:+.1f}', color=LARANJA, fontsize=7.5)
        s = g[g.municipality == SJB]
        if len(s):
            ax.axvline(float(s.d_pp.iloc[0]), color=LARANJA, lw=1, ls='--')
        ax.set_title(f'{NOME[ano]}: {len(g)} cidades com ≥ 10 mil votos em disputa', fontsize=8.5)
        _ax(ax, 'd = fatia dos votos em disputa para Lula, cidade − estado (pontos)', 'cidades')
    fig.tight_layout()
    p = FIG / 'reguas_cidades.png'
    fig.savefig(p)
    plt.close(fig)
    return p


def fig_secoes(V):
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.6), dpi=150)
    ax = axs[0]
    for ano, cor in ((2022, CINZA), (2026, AZUL)):
        v = V[(V.ano == ano) & (V.municipality == CAMPOS)]
        ax.hist(v.z, bins=np.arange(-8, 8.1, .4), histtype='step', lw=1.5, color=cor, density=True, label=f'Campos {ano} (var {v.z.var():.2f})')
    x = np.linspace(-8, 8, 200)
    ax.plot(x, norm.pdf(x), color='#b9b8b3', lw=1, label='só ruído binomial (var 1)')
    ax.legend(fontsize=7, frameon=False)
    ax.set_title('Resíduo por seção da virada uniforme (z)', fontsize=8.5)
    _ax(ax, 'z = (Lula observado − previsto) / desvio binomial', 'densidade')
    ax = axs[1]
    v = V[(V.ano == 2026) & (V.municipality == CAMPOS)]
    ax.scatter(100 * v.dtx, v.z, s=6, color=AZUL, alpha=.6)
    ax.axhline(0, color='#b9b8b3', lw=.8)
    r = np.corrcoef(v.dtx, v.z)[0, 1]
    ax.set_title(f'Campos 2026: resíduo × variação de comparecimento (r = {r:+.2f})', fontsize=8.5)
    _ax(ax, 'comparecimento 2º turno − 1º turno (pontos)', 'z')
    ax = axs[2]
    ax.scatter(100 * v.outros1, v.z, s=6, color=AZUL, alpha=.6)
    ax.axhline(0, color='#b9b8b3', lw=.8)
    r = np.corrcoef(v.outros1, v.z)[0, 1]
    ax.set_title(f'Campos 2026: resíduo × fatia de "outros" no 1º turno (r = {r:+.2f})', fontsize=8.5)
    _ax(ax, 'outros candidatos no 1º turno (% dos válidos da seção)', 'z')
    fig.tight_layout()
    p = FIG / 'secoes_campos.png'
    fig.savefig(p)
    plt.close(fig)
    return p


def fig_predios(V):
    """Excesso médio por prédio (Campos 2026), ordenado, com a faixa esperada pelo acaso."""
    v = V[(V.ano == 2026) & (V.municipality == CAMPOS)]
    g = v.groupby('voting_place').agg(z_medio=('z', 'mean'), k=('z', 'size'), zona=('zone', 'first')).sort_values('z_medio')
    g['ep'] = np.sqrt(v.z.var() / g.k)
    fig, ax = plt.subplots(figsize=(13, 3.4), dpi=150)
    x = np.arange(len(g))
    cores = {z: c for z, c in zip(sorted(g.zona.unique()), [AZUL, LARANJA, '#3aa876', '#8e6bd6'])}
    ax.bar(x, g.z_medio, color=[cores[z] for z in g.zona], width=.8)
    ax.errorbar(x, g.z_medio, yerr=1.96 * g.ep, fmt='none', ecolor='#4a4944', elinewidth=.5)
    ax.axhline(0, color='#b9b8b3', lw=.8)
    for z, c in cores.items():
        ax.bar([0], [0], color=c, label=f'zona {z}')
    ax.legend(fontsize=7, frameon=False, ncol=4)
    ax.set_title(f'Campos 2026: z médio por prédio ({len(g)} prédios, barras = ±1,96 erro-padrão)', fontsize=8.5)
    _ax(ax, 'prédios (locais de votação), do menor ao maior z médio', 'z médio do prédio')
    fig.tight_layout()
    p = FIG / 'predios_campos.png'
    fig.savefig(p)
    plt.close(fig)
    return p, g


# ---------------------------------------------------------------- relatório
def relatorio(C, V, K, T, L):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate
    from make_bahia_reports import H1, H2, P, SM, fig_img, n, table
    from make_padroes_report import sn

    c26 = C[(C.ano == 2026) & (C.municipality == CAMPOS)].iloc[0]
    c22 = C[(C.ano == 2022) & (C.municipality == CAMPOS)].iloc[0]
    st = [Paragraph('Campos dos Goytacazes (RJ), 2º turno de 2026: o excesso está espalhado ou concentrado?', H1),
          Paragraph('Teste por seção pedido no texto “Campos dos Goytacazes — modelo de probabilidades do 2º turno de 2026”. No nível do município as três '
                    'hipóteses (choque político local, intervenção numa parte das urnas, erro de dado) produzem o mesmo número; nas 1.190 seções elas '
                    'deixam marcas diferentes. Aqui, cada marca é medida em Campos e comparada com Campos em 2022 e com todas as cidades com 10 mil '
                    'votos em disputa ou mais, nas duas eleições. Descritivo: nenhuma medida isolada afirma irregularidade.', P),
          Paragraph('1. Conferência dos totais', H2),
          Paragraph(f'A base por seção (boletins de urna) de Campos soma, no 2º turno de 2026, Lula {n(T["t2_A"])}, Flávio {n(T["t2_B"])}, comparecimento '
                    f'{n(T["t2_comp"])}, aptos {n(T["t2_aptos"])}, brancos {n(T["t2_branco"])} e nulos {n(T["t2_nulo"])}: iguais aos totais publicados citados '
                    f'no texto. No 1º turno, Lula {n(T["t1_A"])}, Flávio {n(T["t1_B"])}, outros {n(T["outros1"])}. Votos em disputa {n(T["disputa"])}, '
                    f'ganho de Lula {n(T["ganho_A"])}: fatia de {n(c26.f_pct, 1)}%. No estado, com todas as seções do RJ, a fatia foi de {n(100 * T["f_uf_2026"], 1)}% '
                    f'(o texto estimava 81% a 93%): desvio de Campos d = {sn(c26.d_pp, 1)} pontos. Em 2022, Campos ficou em {n(c22.f_pct, 1)}% contra '
                    f'{n(100 * T["f_uf_2022"], 1)}% do RJ (d = {sn(c22.d_pp, 1)}). A hipótese “erro de dado” entre boletim e total publicado fica excluída. '
                    'O log de cada urna de Campos registra, no dia 25/10/2026, exatamente o número de eleitores do boletim (1.190 de 1.190 seções; '
                    '8 seções trocaram de urna durante o dia e os logs das duas urnas somam o boletim): a queda de comparecimento é de eleitores que não '
                    'foram habilitados, não de votos retirados. A conferência RDV × BU de 2026 para Campos não está nos dados baixados.', P)]
    # régua
    st += [Paragraph('2. Campos entre as cidades grandes, nas duas eleições', H2)]
    t = [['Eleição', 'Cidades', 'Campos: f', 'Estado: f', 'd (pontos)', 'Posição de Campos', 'Cidades com d ≥ Campos', 'São João da Barra: d']]
    for ano in (2022, 2026):
        g = C[C.ano == ano]
        k = g[g.municipality == CAMPOS].iloc[0]
        s = g[g.municipality == SJB]
        t.append([NOME[ano], n(len(g)), f'{n(k.f_pct, 1)}%', f'{n(100 * T[f"f_uf_{ano}"], 1)}%', sn(k.d_pp, 1), f'{n(int((g.d_pp >= k.d_pp).sum()))}ª de {n(len(g))}',
                  n(int((g.d_pp >= k.d_pp).sum()) - 1), sn(float(s.d_pp.iloc[0]), 1) if len(s) else '–'])
    st += [table(t, font=7.5, widths=[4.2 * cm, 1.8 * cm, 2 * cm, 2 * cm, 2 * cm, 3 * cm, 3.4 * cm, 3.6 * cm]),
           fig_img(fig_reguas(C), w=22),
           Paragraph('Distribuição de d (fatia dos votos em disputa que foi para Lula, cidade menos estado) nas cidades com 10 mil votos em disputa ou mais. '
                     'Linha cheia: Campos; tracejada: São João da Barra. Em 2026 a régua é a própria eleição, não só 2022.', SM)]
    g26 = C[C.ano == 2026].sort_values('d_pp', ascending=False).head(8)
    t = [['Cidade (2026)', 'UF', 'Seções', 'Votos em disputa', 'Ganho de Lula', 'f', 'd (pontos)']]
    for y in g26.itertuples():
        t.append([y.municipio, y.uf, n(y.secoes), n(y.disputa), n(y.ganho_A), f'{n(y.f_pct, 1)}%', sn(y.d_pp, 1)])
    st += [Paragraph('As 8 cidades de maior d em 2026', H2), table(t, font=7.5, widths=[5 * cm, 1.2 * cm, 1.6 * cm, 2.6 * cm, 2.4 * cm, 1.8 * cm, 2 * cm])]
    # seções
    st += [CondPageBreak(8 * cm), Paragraph('3. Dentro de Campos: a marca por seção', H2),
           Paragraph('Modelo de virada uniforme: cada seção recebe a virada da cidade (um único deslocamento em logit, ajustado ao total de Campos) e o resíduo é '
                     'o que a seção fez além disso, em desvios binomiais (z). Um choque político espalhado deixa o resíduo com a dispersão normal de uma '
                     'cidade (var(z) e curtose como as outras), acompanhando o perfil dos bairros (R² dos prédios, correlação com a fatia de “outros” do '
                     '1º turno) e a variação de comparecimento. Uma intervenção numa parte das urnas deixa excesso concentrado: cauda à direita, mistura de '
                     'duas populações (dBIC), fatia grande do excesso nos 10% de seções mais altas, e dispersão anormal entre seções do mesmo prédio '
                     '(z do modelo do local). Cada medida vem com a posição de Campos entre as cidades grandes do mesmo ano.', P)]
    linhas = [('var_z', 'var(z): dispersão entre seções (ruído puro = 1)'), ('curtose_z', 'curtose de z (cauda pesada > 0)'), ('assimetria_z', 'assimetria de z (> 0: cauda para Lula)'),
              ('frac_z_maior_3', 'fração de seções com |z| > 3'), ('frac_z_maior_3_positivo', 'fração com z > +3'),
              ('top10_fatia_excesso_pos', 'fatia do excesso positivo nos 10% de seções mais altas'), ('mistura_dbic', 'mistura de 2 normais: dBIC (> 10 = forte)'),
              ('mistura_peso_menor', 'mistura: peso do componente menor'), ('mistura_media_menor', 'mistura: média do componente menor (z)'),
              ('r2_predios', 'R² dos prédios (resíduo “de bairro”)'), ('corr_z_dtx', 'correlação z × variação de comparecimento'),
              ('corr_z_outros1', 'correlação z × fatia de “outros” no 1º turno'), ('corr_z_p1', 'correlação z × p1 (Lula no 1º turno)'),
              ('predio_var_z', 'dentro do prédio (M1): var(z)'), ('predio_curtose_z', 'dentro do prédio (M1): curtose'), ('predio_frac_z_maior_3', 'dentro do prédio (M1): fração |z| > 3')]
    t = [['Medida', 'Campos 2026', 'posição entre\ncidades 2026', 'Campos 2022', 'posição entre\ncidades 2022', 'mediana das\ncidades 2026']]
    for col, rot in linhas:
        g26, g22 = C[C.ano == 2026], C[C.ano == 2022]
        v26, v22 = c26[col], c22[col]
        t.append([rot, n(v26, 2), f'{n(percentil(g26[col], v26))}% ≥', n(v22, 2), f'{n(percentil(g22[col], v22))}% ≥', n(g26[col].median(), 2)])
    st += [table(t, font=7, widths=[8.4 * cm, 2.4 * cm, 2.6 * cm, 2.4 * cm, 2.6 * cm, 2.6 * cm]),
           Paragraph('“posição”: percentual de cidades grandes do ano com valor maior ou igual ao de Campos (100% = Campos é a menor; perto de 0% = a maior).', SM),
           fig_img(fig_secoes(V), w=25)]
    p_pred, g_pred = fig_predios(V)
    st += [CondPageBreak(7 * cm), fig_img(p_pred, w=25),
           Paragraph('Se o excesso estivesse numa parte das urnas, alguns prédios ficariam muito acima dos demais; se fosse um choque de bairro, os prédios '
                     'de uma região inteira subiriam juntos; se fosse uniforme, todas as barras ficariam dentro da faixa de erro.', SM)]
    # marcas de log
    if L is not None and len(L):
        t = [['Grupo de seções (Campos 2026)', 'Seções', 'z médio', 'Variação de\ncomparecimento', 'Habilitação\nmanual', 'Votos após\n16h', 'Votos após\n17h', 'Urna\ntrocada', 'Cancelamentos\n(log)']]
        for y in L.itertuples():
            t.append([y.grupo, n(y.secoes), sn(y.z_medio, 2), f'{sn(100 * y.dtx, 2)} pt', f'{n(100 * y.manual2, 1)}%', f'{n(100 * y.apos16h, 1)}%',
                      f'{n(100 * y.apos17h, 2)}%', n(y.contingencia), n(y.cancelamentos, 2) if pd.notna(y.cancelamentos) else '–'])
        st += [CondPageBreak(7 * cm), Paragraph('4. As seções de maior excesso têm marcas no log?', H2),
               Paragraph('As 10% de seções de Campos com maior z contra as 10% de menor z e o meio. Uma intervenção “sem mudança de comparecimento, com marcas '
                         'no log” apareceria como grupo alto com comparecimento igual e mais habilitação manual, votos tardios, urnas trocadas ou cancelamentos.', P),
               table(t, font=7, widths=[5 * cm, 1.6 * cm, 1.6 * cm, 2.6 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 1.8 * cm, 2.4 * cm])]
    st += [CondPageBreak(6 * cm), Paragraph('5. Leitura', H2), Paragraph(K, P),
           Paragraph('6. Limites', H2),
           Paragraph('A régua por seção vem de duas eleições; a virada uniforme é um modelo simples (um deslocamento por cidade) e parte da dispersão medida é '
                     'heterogeneidade real de bairros, por isso a leitura é sempre relativa às outras cidades e a 2022. O RDV de 2026 de Campos não foi '
                     'conferido contra o BU. Como repetir: scripts/campos_2t.py; tabelas em CAMPOS_2T.xlsx e nos CSVs da pasta.', P)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7)
        cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(OUT / 'CAMPOS_2T.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.6 * cm,
                      title='Campos dos Goytacazes, 2º turno 2026', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', OUT / 'CAMPOS_2T.pdf')
    from ultimo_voto_2026t2 import xlsx_leve
    xlsx_leve(OUT / 'CAMPOS_2T.xlsx', [(p.stem[:31], pd.read_csv(p, sep=';', decimal=',', encoding='utf-8-sig')) for p in sorted(OUT.glob('*.csv'))])


def leitura(C, L):
    """Texto de leitura automático a partir das posições de Campos (sem conclusão sobre causa)."""
    c26 = C[(C.ano == 2026) & (C.municipality == CAMPOS)].iloc[0]
    g26 = C[C.ano == 2026]
    pos = {k: percentil(g26[k], c26[k]) for k in ('var_z', 'curtose_z', 'top10_fatia_excesso_pos', 'mistura_dbic', 'predio_var_z', 'predio_frac_z_maior_3', 'r2_predios')}
    conc = [k for k in ('var_z', 'curtose_z', 'top10_fatia_excesso_pos', 'mistura_dbic', 'predio_var_z', 'predio_frac_z_maior_3') if pos[k] <= 10]
    partes = [f'No nível da cidade, o desvio de Campos em 2026 (d = {c26.d_pp:+.1f}) é o {int((g26.d_pp >= c26.d_pp).sum())}º maior entre {len(g26)} cidades grandes.']
    if conc:
        partes.append('Dentro da cidade, as medidas de concentração em que Campos está entre os 10% mais altos são: ' + ', '.join(conc) + '.')
    else:
        partes.append('Dentro da cidade, nenhuma medida de concentração (dispersão entre seções, cauda, mistura, fatia dos 10% mais altos, dispersão dentro do '
                      'prédio) põe Campos entre os 10% mais altos das cidades grandes de 2026: o excesso está espalhado pelas seções, no padrão de uma '
                      'cidade comum.')
    partes.append(f'O R² dos prédios (quanto o resíduo é “de bairro”) fica em {c26.r2_predios:.2f} (posição {pos["r2_predios"]:.0f}% ≥), e a correlação do resíduo com a '
                  f'variação de comparecimento é {c26.corr_z_dtx:+.2f}; com a fatia de “outros” no 1º turno, {c26.corr_z_outros1:+.2f}.')
    if L is not None and len(L):
        alto, baixo = L.iloc[0], L.iloc[-1]
        partes.append(f'As 10% de seções mais altas têm variação de comparecimento de {100 * alto.dtx:+.2f} pontos (as mais baixas, {100 * baixo.dtx:+.2f}), habilitação manual '
                      f'de {100 * alto.manual2:.1f}% ({100 * baixo.manual2:.1f}%) e {100 * alto.apos16h:.1f}% dos votos depois das 16h ({100 * baixo.apos16h:.1f}%).')
    partes.append('Isso é a marca por seção; qual causa a produziu não se decide aqui.')
    return ' '.join(partes)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cidades, secoes, T = [], [], {}
    for ano in (2026, 2022):
        b = carrega(ano)
        uf = b[b.uf == UF]
        T[f'f_uf_{ano}'] = uf.ganho_A.sum() / uf.disputa.sum()
        f_uf = b.groupby('uf').apply(lambda g: g.ganho_A.sum() / g.disputa.sum())
        if ano == 2026:
            k = b[b.municipality.eq(CAMPOS) & b.uf.eq(UF)]
            T.update(k[['t1_A', 't1_B', 't2_A', 't2_B', 't2_comp', 't2_aptos', 't2_branco', 't2_nulo', 'disputa', 'ganho_A']].sum().to_dict())
            T['outros1'] = int(k.t1_validos.sum() - k.n1.sum())
        tot = b.groupby(['uf', 'municipality']).disputa.sum()
        grandes = tot[tot >= MIN_DISPUTA].index
        for (u, m) in grandes:
            c = b[(b.uf == u) & (b.municipality == m)]
            med, v = medidas_cidade(c, ano, f_uf[u])
            cidades.append(med)
            if m in (CAMPOS, SJB) and u == UF:
                v = v.copy()
                v['ano'] = ano
                secoes.append(v)
        print(ano, 'cidades grandes:', len(grandes), flush=True)
    C = pd.DataFrame(cidades)
    C.to_csv(OUT / 'cidades.csv', **CSV)
    V = pd.concat(secoes, ignore_index=True)
    cols = CHAVE + ['voting_place', 'ano', 'n1', 'n2', 'p1', 'p2', 'p_hat', 'z', 'excesso', 'ganho_A', 'disputa', 'dtx', 'outros1', 'manual2', 'z_predio', 'res_predio',
                    'apos16h', 'apos17h', 'contingencia', 'n_logs']
    V[[c for c in cols if c in V]].to_csv(OUT / 'secoes_campos_sjb.csv', **CSV)
    # marcas de log: decis de z em Campos 2026
    v = V[(V.ano == 2026) & (V.municipality == CAMPOS)].copy()
    lp = pd.read_parquet(ROOT / 'research' / 'segundo_turno_2026' / 'logparse_RJ.parquet')
    m = lp.log_name.str.extract(r'o03221rj(\d{5})(\d{4})(\d{4})-log')
    lp['municipality'], lp['zone'], lp['section'] = m[0].astype(int), m[1].astype(int), m[2].astype(int)
    v = v.merge(lp[['municipality', 'zone', 'section', 'cancellations']].rename(columns={'cancellations': 'cancelamentos'}), on=['municipality', 'zone', 'section'], how='left')
    v['grupo'] = pd.cut(v.z.rank(pct=True), [0, .1, .9, 1], labels=['10% de menor z', 'meio (80%)', '10% de maior z'])
    L = v.groupby('grupo', observed=True).agg(secoes=('z', 'size'), z_medio=('z', 'mean'), dtx=('dtx', 'mean'), manual2=('manual2', 'mean'), apos16h=('apos16h', 'mean'),
                                              apos17h=('apos17h', 'mean'), contingencia=('contingencia', 'sum'), cancelamentos=('cancelamentos', 'mean')).reset_index()
    L = L.iloc[::-1].reset_index(drop=True)
    L.to_csv(OUT / 'marcas_log_campos.csv', **CSV)
    K = leitura(C, L)
    print(K)
    for ano in (2022, 2026):
        g = C[C.ano == ano]
        print(g[g.municipality.isin([CAMPOS, SJB])].T.to_string())
    relatorio(C, V, K, T, L)


if __name__ == '__main__':
    main()
