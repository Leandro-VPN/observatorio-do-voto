"""Três documentos sobre a varredura de fiscalização (todos gerados dos números atuais, nunca digitados à mão):

  METODO_E_DADOS.pdf   — método completo, dados usados, definições, testes, pontuação, limites, registro de alterações e reprodutibilidade
  GRAFICOS.pdf         — caderno de gráficos simples, um por página, com "como ler"
  RESUMO_SIMPLES.pdf   — explicação curta em linguagem comum

Entrada: relatorios/fiscalizacao/{resumo_indicadores,testes_permutacao}.csv, relatorios/fiscalizacao/varredura/*.csv, relatorios/fiscalizacao/mapa_2026_T2/*.csv
Saída:   relatorios/fiscalizacao/documentos/ (PDFs e figuras PNG)

Revisão de 24/10/2026 (após parecer externo): resultado principal restrito ao mesmo prédio (≥3 pares), nível município em separado; "diferença acima do limiar"
em vez de "diferença real"; direção só nas presidenciais e só robusta em 2026; cruzamento prefeito × presidente pareado; "prioridade de observação" em vez de
"risco"; pontos operacionais × de resultado; faixa do acaso centrada no nulo (quantis), com embaralhamento no município e no local; tabelas dentro da largura.
"""
import os
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from PIL import Image as PI

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M  # noqa: E402

FISC = Path('relatorios/fiscalizacao')
VAR = FISC / 'varredura'
MAPA = FISC / 'mapa_2026_T2'
OUT = FISC / 'documentos'
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
CSV = dict(sep=';', decimal=',')
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC', 'MA']
LAB = {'P2022': 'Pres. 2022 T1', 'P2022b': 'Pres. 2022 T2', 'M2024': 'Pref. 2024 T1', 'M2024b': 'Pref. 2024 T2', 'P2026': 'Pres. 2026 T1'}
DAYS = {'P2022': '02/10/2022', 'P2022b': '30/10/2022', 'M2024': '06/10/2024', 'M2024b': '27/10/2024', 'P2026': '04/10/2026'}
EIDS = ['P2022', 'P2022b', 'M2024', 'M2024b', 'P2026']
# paleta de referência validada (dataviz): categóricas em ordem fixa, rampa ordinal azul (600/400/250), tinta/grade
C1, C2, C3 = '#2a78d6', '#eb6834', '#1baf7a'
SEQ = {'alta': '#184f95', 'média': '#3987e5', 'baixa': '#86b6ef'}
NIV = {'alta': 'prioridade alta', 'média': 'prioridade média', 'baixa': 'prioridade baixa'}
INK, INK2, MUTED, GRID = '#0b0b0b', '#52514e', '#898781', '#e1e0d9'
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True, 'grid.alpha': .6, 'grid.color': GRID, 'grid.linewidth': .6,
                     'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED, 'text.color': INK, 'figure.dpi': 150, 'axes.titlesize': 12, 'axes.titleweight': 'bold',
                     'axes.titlelocation': 'left', 'legend.frameon': False})
FLAG_DESC = [('late', 'Votos após 17h: fração acima do P99 do estado e pelo menos 20 votos após as 17h'),
             ('manual', 'Habilitação manual pelo mesário acima do esperado para a seção (resíduo da regressão > P99 do estado)'),
             ('manual_late', 'Pelo menos 10 votos com sequência manual após as 17h'),
             ('fast', 'Ritmo acelerado após 17h: mediana entre votos abaixo de 40 s com pelo menos 20 votos tardios'),
             ('last19', 'Último voto computado às 19h ou depois'),
             ('turnout', 'Comparecimento muito acima: z > 3 frente à mediana estadual (MAD) e ≥ 10 p.p. acima da mediana municipal'),
             ('close', 'Encerramento da urna mais de 60 min após as 17h sem troca de urna registrada'),
             ('cancel', 'Cancelamentos/suspensões de habilitação pelo mesário acima do P99 do estado e pelo menos 5')]
TW = 17 * cm - 12   # largura útil do texto em A4 com margens de 2 cm (frame menos o padding interno)


def n(x, d=0):
    return M.n(x, d)


def git_head():
    try:
        return subprocess.run(['C:/Program Files/Git/cmd/git.exe', 'log', '--format=%h %ad', '--date=short', '-1'], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return 'n/d'


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def wtable(rows, widths, font=6.8):
    """Tabela que cabe na largura do texto: larguras relativas escaladas a TW, todas as células em Paragraph (quebram por palavra), cabeçalho em negrito branco."""
    w = np.array(widths, float)
    w = w / w.sum() * TW
    body = ParagraphStyle('wt_body', parent=M.P, fontSize=font, leading=font + 1.8)
    hdr = ParagraphStyle('wt_hdr', parent=body, fontName='Helvetica-Bold', textColor=colors.white)
    data = [[Paragraph(esc(c), hdr) for c in rows[0]]] + [[Paragraph(esc(c), body) for c in r] for r in rows[1:]]
    t = Table(data, colWidths=list(w), repeatRows=1)
    t.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .25, colors.HexColor('#cccccc')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
                           ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f8fa')]), ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                           ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
    assert t.wrap(TW, 1e6)[0] <= TW + .5, 'tabela mais larga que o texto'
    return t


# ----------------------------------------------------------------------------- dados
def load():
    D = {}
    D['R'] = pd.read_csv(FISC / 'resumo_indicadores.csv', **CSV)
    D['T'] = pd.read_csv(FISC / 'testes_permutacao.csv', **CSV)
    D['V'] = pd.read_csv(VAR / 'resumo_por_eleicao.csv', **CSV)
    D['NV'] = pd.read_csv(VAR / 'comparacao_por_nivel.csv', **CSV)
    D['REC'] = pd.read_csv(VAR / 'recorrencia_condicional.csv', **CSV)
    D['PX'] = pd.read_csv(VAR / 'pres_x_pref_pareado.csv', **CSV)
    D['PXP'] = pd.read_csv(VAR / 'pres_x_pref_mesmas_secoes.csv', **CSV)
    D['L'] = pd.read_csv(VAR / 'locais_risco.csv', low_memory=False, **CSV)
    D['H'] = pd.read_csv(VAR / 'secoes_historico.csv', low_memory=False, usecols=['uf', 'n_eleicoes_comportamento', 'n_pres_dif_real', 'n_pref_dif_real', 'padrao_comportamento', 'padrao_desvio_resultado', 'direcao'], **CSV)
    D['CID'] = pd.read_csv(VAR / 'cidades.csv', **CSV)
    D['PR'] = pd.read_csv(VAR / 'prioridade_locais_2026_T2.csv', low_memory=False, usecols=['uf', 'prioridade_observacao', 'pontos'], **CSV)
    D['U'] = pd.read_csv(MAPA / 'resumo_por_uf.csv', **CSV)
    D['Z'] = pd.read_csv(MAPA / 'zonas_todas.csv', **CSV)
    lg = pd.read_csv(VAR / 'secoes_com_comportamento_por_eleicao.csv', low_memory=False, usecols=['eid', 'cmp_level', 'real', 'dir', 'excesso_alem_tardios'], **CSV)
    tf = lambda s: s.astype(str).isin(['True', 'true', '1'])  # noqa: E731
    lg = lg[tf(lg.real) & (lg.dir == 'A')]
    D['excesso'] = {eid: dict(todos=100 * tf(g.excesso_alem_tardios).mean(), local=100 * tf(g[g.cmp_level == 'local'].excesso_alem_tardios).mean(), n_local=int((g.cmp_level == 'local').sum())) for eid, g in lg.groupby('eid')}
    D['head'] = git_head()
    D['ufs'] = [u for u in ORDER if u in D['L'].uf.unique()]
    return D


def nv(D, eid, grupo, nivel):
    x = D['NV'][(D['NV'].eid == eid) & (D['NV'].grupo == grupo) & (D['NV'].nivel == nivel)]
    return x.iloc[0] if len(x) else None


# ----------------------------------------------------------------------------- gráficos
def save(f, name):
    f.tight_layout()
    f.savefig(FIG / f'{name}.png', dpi=150)
    plt.close(f)
    return FIG / f'{name}.png'


def bar_labels(ax, bars, fmt='{:,.0f}', fs=8.5):
    for b in bars:
        h = b.get_height()
        if np.isfinite(h):
            ax.annotate(fmt.format(h).replace(',', '.'), (b.get_x() + b.get_width() / 2, h), xytext=(0, 3), textcoords='offset points', ha='center', va='bottom', fontsize=fs, color=INK2)


def two_panel(D, col, ylabel, title, fmt, hline=None, ncol='n'):
    """Duas janelas: mesmo prédio (≥3 pares) × sem par no prédio (comparação ao município); séries = com comportamento / comuns.
    Eixos independentes; sob cada eleição, o tamanho da base de cada barra (n com comportamento / n comuns)."""
    V = D['V']
    f, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    for ax, lv, ttl in zip(axes, ['local', 'município'], ['Mesmo prédio (3 ou mais seções vizinhas sem comportamento)', 'Sem vizinha comparável no prédio: comparação ao município']):
        xs = np.arange(len(V))
        b = [nv(D, e, 'com comportamento', lv) for e in V.eid]
        c = [nv(D, e, 'comuns', lv) for e in V.eid]
        vb = [getattr(r, col) if r is not None else np.nan for r in b]
        vc = [getattr(r, col) if r is not None else np.nan for r in c]
        b1 = ax.bar(xs - .2, vb, .38, color=C1, label='Seções com comportamento')
        b2 = ax.bar(xs + .2, vc, .38, color=C2, label='Seções comuns (acaso)')
        bar_labels(ax, b1, fmt); bar_labels(ax, b2, fmt)
        if hline is not None:
            ax.axhline(hline, color=INK2, lw=.8, ls='--')
        labs = [f'{LAB[e]}\nn = {n(getattr(rb, ncol))} / {n(getattr(rc, ncol))}' if rb is not None and rc is not None else LAB[e] for e, rb, rc in zip(V.eid, b, c)]
        ax.set_xticks(xs); ax.set_xticklabels(labs, fontsize=8); ax.set_title(ttl, fontsize=10.5, loc='center')
        ax.set_ylim(0, np.nanmax(vb + vc) * 1.22)
    axes[0].set_ylabel(ylabel); axes[0].legend(loc='upper left', fontsize=8.5)
    f.suptitle(title, x=.01, ha='left', fontsize=12, fontweight='bold')
    return f


def charts(D):
    R, T, V, L, H, U = D['R'], D['T'], D['V'], D['L'], D['H'], D['U']
    figs = []
    x = np.arange(len(V))
    labs = [LAB[e] for e in V.eid]
    # 1 comportamento
    f, ax = plt.subplots(figsize=(10, 4.6))
    b1 = ax.bar(x - .2, V.tardia, .38, color=C1, label='Votação tardia')
    b2 = ax.bar(x + .2, V.manual, .38, color=C2, label='Habilitação manual excessiva')
    bar_labels(ax, b1); bar_labels(ax, b2)
    ax.set_xticks(x); ax.set_xticklabels(labs); ax.set_ylabel('seções'); ax.legend(loc='upper right')
    ax.set_title('Quantas seções mostraram cada comportamento, por eleição')
    first = V[V.eid.isin(['P2022', 'M2024', 'P2026'])].secoes
    figs.append((save(f, '01_comportamento'), f'Os primeiros turnos têm entre {n(first.min() / 1000)} e {n(first.max() / 1000)} mil seções analisadas nos {len(D["ufs"])} estados; os segundos turnos de prefeito, só onde houve ({n(V[V.eid == "M2024b"].secoes.iloc[0] / 1000)} mil). '
                 'Votação tardia é muito mais comum nos 1º turnos presidenciais, compatível com filas maiores, do que nas eleições de prefeito; a habilitação manual excessiva aparece em número parecido em todas, porque é definida pelo P99 de cada estado.'))
    # 2 diferença acima do limiar, por nível
    f = two_panel(D, 'pct_real', '% de seções com diferença acima do limiar', 'As seções com comportamento votam diferente das vizinhas? (por nível de comparação)', '{:.1f}%')
    p26l, c26l = nv(D, 'P2026', 'com comportamento', 'local'), nv(D, 'P2026', 'comuns', 'local')
    p26m, c26m = nv(D, 'P2026', 'com comportamento', 'município'), nv(D, 'P2026', 'comuns', 'município')
    figs.append((save(f, '02_diferenca_real'), f'Diferença acima do limiar = pelo menos 5 pontos percentuais, em módulo, na fração do lado A, e |z| ≥ 2. A barra laranja é o mesmo teste nas seções sem comportamento: o que se espera por acaso e por variação normal. Sob cada eleição, o número de seções de cada barra. '
                 f'À esquerda, o resultado principal: no mesmo prédio, em 2026, {n(p26l.real)} de {n(p26l.n)} seções com comportamento ({n(p26l.pct_real, 1)}%) ultrapassam o limiar, contra {n(c26l.real)} de {n(c26l.n)} comuns ({n(c26l.pct_real, 1)}%): razão de {n(p26l.pct_real / c26l.pct_real, 1)}. '
                 f'À direita, as seções sem vizinha comparável (seção única ou prédio inteiro com comportamento): a referência é o município, a taxa é várias vezes maior nos dois grupos ({n(p26m.pct_real, 1)}% contra {n(c26m.pct_real, 1)}% em 2026) '
                 'e por isso esse nível fica separado. Barras do 2º turno de prefeito têm poucas seções. Em qualquer nível, a maioria das seções com comportamento vota como a sua referência.'))
    # 3 direção, por nível
    f = two_panel(D, 'pct_A', '% das diferenças acima do limiar a favor do lado A', 'Quando a seção difere da referência, para que lado pende? (por nível de comparação)', '{:.0f}%', hline=50, ncol='real')
    figs.append((save(f, '03_direcao'), f'Lado A = PT (presidente) ou candidato líder do município (prefeito); 50% = sem direção. Sob cada eleição, o número de diferenças acima do limiar de cada barra. No mesmo prédio, em 2026, {n(p26l.pct_A, 0)}% das diferenças das seções com comportamento pendem para o PT, contra {n(c26l.pct_A, 0)}% nas comuns; '
                 f'em 2022 T1 a distância é pequena ({n(nv(D, "P2022", "com comportamento", "local").pct_A, 0)}% contra {n(nv(D, "P2022", "comuns", "local").pct_A, 0)}%). Nas eleições de prefeito não se observa direção consistente, e as bases são pequenas. '
                 'No nível município ambos os grupos pendem para A, o que mostra por que misturar níveis infla a leitura. Direção não é causa: pode refletir o perfil de quem enfrenta fila.'))
    # 4 permutação: faixa do acaso (quantis do nulo, dois esquemas) e ponto observado; só os indicadores que definem o comportamento da varredura
    f, ax = plt.subplots(figsize=(10, 4.8))
    flags = ['f_late', 'f_last19', 'f_close', 'f_manual', 'f_manual_late']
    xx = np.arange(len(flags))
    for i, (eid, col) in enumerate([('P2022', C1), ('P2026', C2), ('M2024', C3)]):
        s = T[T.eid == eid].set_index('flag').reindex(flags)
        xi = xx + (i - 1) * .27
        ax.vlines(xi, s.null_q025, s.null_q975, color='#c3c2b7', lw=7, zorder=1, label='acaso (embaralhando no município)' if i == 0 else None)
        ax.vlines(xi, s.null_q025_local, s.null_q975_local, color='#6b6a66', lw=2.2, zorder=2, label='acaso (embaralhando no local)' if i == 0 else None)
        ax.plot(xi, s.within_place_diff, 'o', ms=6.5, color=col, label=LAB[eid], zorder=3)
    ax.axhline(0, color=INK2, lw=.8)
    ax.set_xticks(xx); ax.set_xticklabels(['após 17h (late)', 'último voto ≥19h (last19)', 'encerramento >60 min (close)', 'manual acima do esperado', 'manuais após 17h ≥10'], fontsize=8.5)
    ax.set_ylabel('diferença (A − B) dentro do mesmo local, p.p.'); ax.legend(loc='upper right', fontsize=8.5)
    ax.set_title('Teste de direção nos cinco indicadores do comportamento (faixas = acaso; ponto = observado)')
    figs.append((save(f, '04_permutacao'), 'Cada ponto é a diferença de votação (lado A menos lado B) entre seções sinalizadas e não sinalizadas, medida como desvio da média do próprio local e ponderada por votos válidos. '
                 'As faixas vão do percentil 2,5 ao 97,5 das diferenças obtidas embaralhando a sinalização 500 vezes: a larga, dentro do município; a fina e escura, dentro do próprio local (mais fiel à pergunta do mesmo prédio). Ponto fora das faixas = diferença maior que o acaso. '
                 'Os dois esquemas dão o mesmo veredito em todos os casos. Em prefeito 2024 nenhum ponto sai da faixa. Comparecimento, cancelamentos e os escores combinados não definem o comportamento da varredura e estão só na tabela do documento técnico.'))
    # 5 locais por UF e prioridade
    f, ax = plt.subplots(figsize=(10, 4.6))
    ct = L.groupby(['uf', 'prioridade_observacao']).size().unstack(fill_value=0).reindex(D['ufs']).fillna(0)
    bottom = np.zeros(len(ct))
    for lv in ['alta', 'média', 'baixa']:
        if lv in ct:
            ax.bar(ct.index, ct[lv], .6, bottom=bottom, color=SEQ[lv], label=NIV[lv], edgecolor='white', linewidth=1)
            bottom += ct[lv].values
    for i, (u, tot) in enumerate(zip(ct.index, bottom)):
        ax.text(i, tot, f'{n(tot)}\n({n(ct.loc[u].get("alta", 0))} alta)', ha='center', va='bottom', fontsize=8, color=INK2, linespacing=1.1)
    ax.set_ylim(0, bottom.max() * 1.18)
    ax.set_ylabel('locais de votação com comportamento'); ax.legend(loc='upper right')
    ax.set_title('Locais de votação com comportamento, por estado e prioridade de observação')
    alta = L[L.prioridade_observacao == 'alta']
    top2 = alta.uf.value_counts().head(2)
    figs.append((save(f, '05_locais_uf'), f'Sobre cada barra, o total de locais e, entre parênteses, quantos são de prioridade alta. {top2.index[0]} e {top2.index[1]} concentram {n(top2.sum())} dos {n(len(alta))} locais de prioridade alta.'))
    # 6 distribuição de pontos
    f, ax = plt.subplots(figsize=(10, 4.4))
    ax.hist(L.pontos, bins=np.arange(0, 101, 5), color=C1, edgecolor='white')
    for v, t in ((25, 'prioridade média ≥ 25'), (45, 'prioridade alta ≥ 45')):
        ax.axvline(v, color=INK2, lw=.9, ls='--'); ax.text(v + 1, ax.get_ylim()[1] * .9, t, fontsize=8.5, color=INK2)
    ax.set_xlabel('pontos do local (0–100)'); ax.set_ylabel('locais'); ax.set_yscale('log')
    ax.set_title('Distribuição dos pontos dos locais (escala logarítmica)')
    one = 100 * ((L.secoes_com_comportamento == 1) & (L.recorrentes_2plus == 0)).mean()
    figs.append((save(f, '06_pontos'), f'O caso típico é uma única seção com comportamento em uma única eleição ({n(one, 0)}% dos locais). Os cortes de 25 e 45 pontos separam as prioridades média e alta. A escala vertical é logarítmica para que a cauda apareça.'))
    # 7 composição dos pontos nos locais de prioridade alta
    f, ax = plt.subplots(figsize=(10, 4.2))
    comp = {'recorrência (2+ eleições)': ('pts_recorrencia', 'operacional'), 'desvio acima do limiar nas presidenciais': ('pts_desvio_real_pres', 'resultado'), 'direção única (presidenciais)': ('pts_direcao_unica', 'resultado'),
            'seções com comportamento em 2026 T1': ('pts_comportamento_2026_comp', 'operacional'), 'seções com diferença em 2026 T1': ('pts_comportamento_2026_real', 'resultado'), 'prédio inteiro atípico': ('pts_local_inteiro', 'misto'),
            'volume de tardios/manuais': ('pts_volume', 'operacional'), '2+ seções com desvio só nas presidenciais': ('pts_desvio_2plus_pres', 'resultado')}
    vals = pd.Series({k: alta[v].mean() for k, (v, _) in comp.items() if v in alta}).sort_values()
    tipo = {k: t for k, (_, t) in comp.items()}
    cor = {'operacional': C1, 'resultado': C2, 'misto': C3}
    bars = ax.barh(vals.index, vals.values, color=[cor[tipo[k]] for k in vals.index])
    for b in bars:
        ax.text(b.get_width() + .3, b.get_y() + b.get_height() / 2, n(b.get_width(), 1), va='center', fontsize=8.5, color=INK2)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=C1, label='operacional (fila/manual, volume)'), Patch(color=C2, label='resultado (diferenças de votação)'), Patch(color=C3, label='misto (prédio inteiro vs município)')], loc='lower right', fontsize=8.5)
    ax.set_xlabel('pontos médios por componente (locais de prioridade alta)')
    ax.set_title('De onde vêm os pontos dos locais de prioridade alta (médias)')
    ordem = ', '.join(vals.sort_values(ascending=False).index[:3])
    sem = int(alta.sinal_resultado.isin(['nenhum', 'só local (vs município)']).sum())
    zero = int((alta.pts_resultado == 0).sum())
    figs.append((save(f, '07_composicao_pontos'), f'Médias observadas nos {n(len(alta))} locais de prioridade alta; os três componentes que mais pesam são {ordem}. Em média, {n(alta.pts_operacional.mean(), 0)} pontos são operacionais (fila/manual recorrentes, volume, comportamento em 2026) e '
                 f'{n(alta.pts_resultado.mean(), 0)} são de resultado. {n(sem)} dos {n(len(alta))} não têm nenhuma seção com diferença acima do limiar e {n(zero)} não têm nenhum ponto de resultado: entram por operação, não por resultado.'))
    # 8 prefeito × presidente pareado
    PX, PXP = D['PX'], D['PXP']
    f, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
    for ax, rec, ttl in zip(axes, ['todas', 'local'], ['Todas as seções presentes nas três eleições', 'Só comparações no mesmo prédio (3 ou mais vizinhas)']):
        s = PX[PX.recorte == rec].set_index('eid').reindex(['P2022', 'M2024', 'P2026'])
        xs = np.arange(len(s))
        b1 = ax.bar(xs - .2, s.pct_dif_entre_comportamento, .38, color=C1, label='entre seções com comportamento')
        b2 = ax.bar(xs + .2, s.pct_dif_entre_comuns, .38, color=C2, label='entre seções comuns')
        bar_labels(ax, b1, '{:.1f}%'); bar_labels(ax, b2, '{:.1f}%')
        ax.set_xticks(xs); ax.set_xticklabels([LAB[e] for e in s.index]); ax.set_title(ttl, fontsize=10.5, loc='center')
        ax.set_ylim(0, np.nanmax(pd.concat([s.pct_dif_entre_comportamento, s.pct_dif_entre_comuns])) * 1.25)
    axes[0].set_ylabel('% de seções com diferença acima do limiar'); axes[0].legend(loc='upper center', bbox_to_anchor=(.5, -.12), ncol=2, fontsize=8.5)
    f.suptitle('Prefeito × presidente, nas mesmas seções, com denominadores', x=.01, ha='left', fontsize=12, fontweight='bold')
    pp = PXP[(PXP.recorte == 'todas')]
    pp26 = pp[pp.par.str.contains('2026')].iloc[0] if pp.par.str.contains('2026').any() else None
    cap8 = ('Mesmas seções nas três eleições de primeiro turno, com denominadores explícitos. Entre as seções com comportamento, a fração que ultrapassa o limiar é da mesma ordem nos dois cargos (um pouco maior na municipal no painel de todas as seções, não no do mesmo prédio). '
            'A contagem bruta de seções com desvio “só nas presidenciais” é muito maior porque há muito mais seções com fila nos 1º turnos presidenciais, não porque elas desviem mais.')
    if pp26 is not None:
        cap8 += (f' Comparação estrita, seções com comportamento nos dois cargos ({pp26.par}, {n(pp26.secoes_com_comportamento_em_ambas)} seções): {n(pp26.pct_dif_presidencial, 1)}% contra {n(pp26.pct_dif_municipal, 1)}% '
                 f'(p de McNemar {n(pp26.p_mcnemar, 2)}): sem evidência de assimetria entre cargos.')
    figs.append((save(f, '08_pres_x_pref'), cap8))
    # 9 recorrência
    f, ax = plt.subplots(figsize=(10, 4.2))
    rc = H.n_eleicoes_comportamento.value_counts().sort_index()
    bars = ax.bar([str(int(k)) for k in rc.index], rc.values, .6, color=C1)
    bar_labels(ax, bars)
    ax.set_yscale('log'); ax.set_xlabel('número de eleições (de 5) em que a seção mostrou comportamento'); ax.set_ylabel('seções (escala log)')
    ax.set_title('Recorrência: quantas vezes a mesma seção repete o comportamento')
    REC = D['REC']
    r22 = REC[(REC.de == 'Pres 2022 T1') & (REC.para == 'Pres 2026 T1')]
    cap9 = 'A grande maioria aparece uma única vez. '
    if len(r22):
        r22 = r22.iloc[0]
        cap9 += (f'Entre as seções que tiveram comportamento em 2022 T1, {n(r22.pct_repete, 0)}% repetiram em 2026 T1, contra {n(r22.pct_sem_comportamento_antes, 0)}% das que não tiveram ({n(r22.razao, 1)} vezes mais). ')
    cap9 += 'A recorrência pode ter causas estruturais (prédio grande, eleitorado sem biometria, zona com filas sempre); por isso pesa na pontuação, sem indicar irregularidade.'
    figs.append((save(f, '09_recorrencia'), cap9))
    # 10 votos após 17h
    f, ax = plt.subplots(figsize=(10, 4.4))
    Rx = R.set_index('eid').reindex(EIDS)
    xr = np.arange(len(Rx))
    b1 = ax.bar(xr - .2, Rx.late_votes_all, .38, color=C1, label='Todos os logs')
    b2 = ax.bar(xr + .2, Rx.late_votes_contingency, .38, color=C2, label='Em urnas de contingência/recarregadas')
    bar_labels(ax, b1); bar_labels(ax, b2)
    ax.set_xticks(xr); ax.set_xticklabels([LAB[e] for e in Rx.index]); ax.set_ylabel('votos computados após 17h'); ax.legend(loc='upper right')
    ax.set_title('Votos computados após as 17h, por eleição')
    figs.append((save(f, '10_votos_apos_17h'), 'Contagem direta nos logs das urnas: eventos “voto computado” com horário posterior às 17h no dia da eleição. Nos 1º turnos presidenciais são milhões; nos 2º turnos e nas municipais, muito menos. '
                 'Votar após as 17h é legal para quem já estava na fila; o número mede fila, não irregularidade.'))
    # 11 mapa por UF
    f, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    Ux = U.set_index('uf').reindex([u for u in ORDER if u in U.uf.values])
    a1.bar(Ux.index, Ux.locais_alta, .6, color=SEQ['alta'], label='prioridade alta')
    a1.bar(Ux.index, Ux.locais_media, .6, bottom=Ux.locais_alta, color=SEQ['média'], label='prioridade média')
    for i, (a, m) in enumerate(zip(Ux.locais_alta, Ux.locais_media)):
        a1.text(i, a + m, n(a + m), ha='center', va='bottom', fontsize=8.5, color=INK2)
    a1.set_title('Locais no mapa de fiscalização 2026 T2', loc='center'); a1.set_ylabel('locais'); a1.legend(loc='upper right')
    bars = a2.bar(Ux.index, Ux.secoes_a_checar, .6, color=C1)
    bar_labels(a2, bars)
    a2.set_title('Seções a checar', loc='center'); a2.set_ylabel('seções')
    figs.append((save(f, '11_mapa_uf'), f'O mapa cobre {n(int(Ux.locais.sum()))} locais e {n(int(Ux.secoes_a_checar.sum()))} seções nos {len(Ux)} estados; a sugestão é de {n(int(Ux.fiscais_sugeridos.sum()))} fiscais (1 por local de prioridade alta e 1 a cada 2 de média, arredondado para cima em cada zona). '
                 f'{n(int(Ux.locais_com_sinal_resultado.sum()))} desses locais têm alguma seção com diferença de resultado acima do limiar.'))
    # 12 cidades
    f, ax = plt.subplots(figsize=(10, 5))
    cid = D['CID'].sort_values(['locais_prioridade_alta', 'pontos_max'], ascending=False).head(15).iloc[::-1]
    lab = [f'{r.municipality_name.title()} ({r.uf})' for r in cid.itertuples()]
    ax.barh(lab, cid.locais_prioridade_alta, color=SEQ['alta'], label='prioridade alta', edgecolor='white', linewidth=1)
    ax.barh(lab, cid.locais_prioridade_media, left=cid.locais_prioridade_alta, color=SEQ['média'], label='prioridade média', edgecolor='white', linewidth=1)
    for i, (a, m) in enumerate(zip(cid.locais_prioridade_alta, cid.locais_prioridade_media)):
        ax.text(a + m, i, ' ' + n(a) + ' alta', va='center', fontsize=8.5, color=INK2)
    ax.set_xlabel('locais de votação'); ax.legend(loc='lower right')
    ax.set_title('Cidades com mais locais de prioridade alta')
    figs.append((save(f, '12_cidades'), 'Cidades grandes aparecem porque têm mais locais; para alocar fiscais, o que conta é a lista por zona e local dentro de cada cidade, no mapa de fiscalização.'))
    return figs


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


# ----------------------------------------------------------------------------- PDF: gráficos
def pdf_graficos(figs, D):
    P, H1, H2 = M.P, M.H1, M.H2
    st = [Paragraph('Varredura de fiscalização — caderno de gráficos', H1),
          Paragraph(f'Um gráfico por página, com uma frase de como ler. Os números vêm dos arquivos da varredura em relatorios/fiscalizacao/ ({len(D["ufs"])} estados) e são regenerados pelo script. '
                    'Lado A = PT (presidente) ou líder do município (prefeito); lado B = PL ou 2º colocado. “Diferença acima do limiar” = ≥5 p.p. em módulo na fração do lado A e |z| ≥ 2 frente à referência. '
                    'Os dados não dizem em quem votaram os eleitores tardios ou habilitados manualmente: compara-se a seção inteira. Sinalização não é acusação.', P), Spacer(1, 6)]
    for i, (p, cap) in enumerate(figs, 1):
        st += [Paragraph(f'Gráfico {i}', H2), img(p, 24), Paragraph('<b>Como ler:</b> ' + cap, P)]
        if i < len(figs):
            st.append(PageBreak())

    def foot(c, d_):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Caderno de gráficos — varredura de fiscalização — sinalização não é acusação'); c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'GRAFICOS.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.3 * cm, bottomMargin=1.5 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


# ----------------------------------------------------------------------------- PDF: método
def pdf_metodo(D, figs):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    H3 = ParagraphStyle('H3', parent=H2, fontSize=11, spaceBefore=8, spaceAfter=3)
    R, T, V, L, U, PX, PXP = D['R'], D['T'], D['V'], D['L'], D['U'], D['PX'], D['PXP']
    Rx, Vx = R.set_index('eid'), V.set_index('eid')
    ufs = D['ufs']
    alta = L[L.prioridade_observacao == 'alta']
    media = L[L.prioridade_observacao == 'média']
    st = [Paragraph('Varredura de fiscalização por local de votação — método, dados e resultados', H1),
          Paragraph(f'Documento técnico para avaliação. Gerado automaticamente dos resultados atuais em {pd.Timestamp.today():%d/%m/%Y}; código no commit {D["head"]}. Revisado em 24/10/2026 após parecer externo (ver seção 11).', SM),
          Paragraph('<b>Pergunta.</b> Existem locais de votação onde seções com (a) votação depois do horário e/ou (b) habilitação manual de eleitores pelo mesário acima do esperado '
                    'apresentam resultado diferente do das seções vizinhas, de forma recorrente entre eleições? E o padrão difere entre eleições de prefeito e de presidente? '
                    'O objetivo é ordenar locais para observação presencial. Os dados não observam compra de voto, coação ou intenção, nem em quem votaram os eleitores tardios ou habilitados manualmente; observam horários, habilitações, encerramento e votos por seção.', P),
          Paragraph('Sinalização não é acusação. Toda diferença medida aqui pode ter explicação legítima (fila, falha de biometria, perfil do eleitorado da rua atendida pela seção). A pontuação ordena prioridades de observação; não é probabilidade nem estimativa de irregularidade.', NOTE),
          Paragraph('1. Dados usados', H2),
          Paragraph('Todas as fontes são públicas, do Portal de Dados Abertos do TSE (dadosabertos.tse.jus.br). A aquisição lê os membros dos arquivos ZIP por HTTP Range, guarda apenas as colunas e linhas '
                    'necessárias em Parquet comprimido, e registra URL, hash SHA-256 e recibo de cada captura. Nenhum arquivo nacional inteiro é armazenado.', P)]
    t = [['Conjunto (TSE)', 'O que é', 'O que se usa aqui'],
         ['Boletins de urna por seção (bweb_<turno>t_<UF>)', 'Uma linha por seção × candidatura, com aptos, comparecimento, abstenções, votos, horários de abertura/encerramento, urna efetivada, eleitores habilitados manualmente (campo do BU) e seções agregadas.',
          'Aptos, comparecimento, votos válidos e por candidato (lado A/B), horário de encerramento, agregação. Base de todas as seções.'],
         ['Logs das urnas (arqurnatot … <ano>_<turno>t_<UF>.zip; logjez/logd.dat)', 'Registro de eventos de cada urna com horário: habilitações, tipo de habilitação, voto computado, cancelamentos, mensagens de operação.',
          'Contagem de votos computados por horário (após 17h, após 19h), sequência de habilitação manual, cancelamentos, último voto, intervalos entre votos tardios, reversões de relógio.'],
         ['Correspondências efetivadas (ceft_<turno>t_<UF>)', 'Para cada seção, a urna esperada e a urna efetivamente usada, cargas e origem do voto (RED = recuperação de dados).', 'Troca de urna (esperada ≠ efetivada) e contingência; usada para não contar encerramento tardio quando houve troca.'],
         ['Perfil do eleitorado por seção (perfil_eleitor_secao_2022_<UF>)', 'Eleitores por seção com faixa etária, escolaridade e biometria cadastrada; nome do local de votação.', 'Controles da regressão de habilitação manual (% com biometria, % 60+, % baixa escolaridade), nome dos locais. Perfil de 2022 para todas as eleições.'],
         ['Logs de urnas de contingência', 'Logs cujo nome de arquivo identifica a seção de destino quando a urna original foi substituída.', 'Re-identificados pelo nome do arquivo (identity_status PARSED_FILENAME) e incluídos; marcados como contingência.']]
    st += [wtable(t, [4.2, 7.3, 6.5], font=7),
           Paragraph(f'Recortes: {len(ufs)} estados ({", ".join(M.NAMES[u] for u in ufs)}). Eleições com logs de urna disponíveis e processados: presidente 2022 (1º e 2º turnos) e 2026 (1º turno); prefeito 2024 (1º e 2º turnos). '
                     'Eleições anteriores (2012–2020) foram capturadas em boletins e correspondências para estudos de persistência, mas não entram nesta varredura por não terem logs processados.', P),
           Paragraph('1.1 Cobertura observada', H3)]
    t = [['Eleição', 'Dia', 'Seções (BU)', 'Com log', 'Log completo', 'Contingência / recarregadas', 'Votos após 17h (todos os logs)', '… em contingência', 'Votos com sequência manual', 'Manuais após 17h']]
    for eid in EIDS:
        r = Rx.loc[eid]
        t.append([LAB[eid], DAYS[eid], n(r.sections), n(r.with_log), n(r.log_complete), n(r.contingency_logs), n(r.late_votes_all), n(r.late_votes_contingency), n(r.manual_votes), n(r.manual_late)])
    st += [wtable(t, [2.0, 1.7, 1.5, 1.4, 1.5, 2.0, 2.0, 1.7, 1.9, 1.6], font=6.8),
           Paragraph('“Log completo” = o número de votos computados no log é igual ao comparecimento do boletim da seção. Só seções com log completo entram nos indicadores de horário e habilitação; '
                     'comparecimento e encerramento usam todas as seções elegíveis (≥ 50 aptos).', SM),
           Paragraph('2. Como os logs são lidos', H2),
           Paragraph('Cada log é lido linha a linha, somente no dia da eleição e no módulo de votação (VOTA). Uma máquina de estados por urna acompanha a habilitação de cada eleitor: '
                     '<b>solicitação de dado pessoal para habilitação manual</b> → <b>captura da digital do mesário</b> → <b>eleitor habilitado</b> → <b>voto computado</b>. Só quando a sequência completa termina em voto computado '
                     'o voto conta como “sequência manual”. Mensagens de tipo de habilitação biométrica, “eleitor não possui biometria”, cancelamentos e suspensões reiniciam ou classificam a sequência; '
                     'um voto com rótulos conflitantes é contado como conflito, não como manual. Horários são os do relógio de cada urna; reversões de relógio são contadas e interrompem a sequência. '
                     'A taxonomia foi conferida contra o formato oficial dos logs (TSE, 2022) e contra amostras reais antes de ser adotada; a contagem de votos computados de cada log foi reconciliada com o comparecimento do boletim.', P),
           Paragraph('Validação: no piloto Bahia 2022 T2, 33.082 de 33.084 logs com identidade inequívoca tiveram contagem de votos igual ao comparecimento presidencial do BU. '
                     'Nada disso valida o relógio das urnas nem prova que toda habilitação manual foi registrada; o que se mede é o que o log registra.', SM),
           Paragraph('3. Indicadores por seção', H2),
           Paragraph('Seção elegível: pelo menos 50 aptos e votos válidos > 0. Limiares P99 são calculados por estado, só entre seções elegíveis com log completo, dentro de cada eleição.', P)]
    t = [['Indicador', 'Definição']] + [[a, b] for a, b in FLAG_DESC]
    st += [wtable(t, [2.6, 15.4], font=7.2),
           Paragraph('<b>Habilitação manual esperada.</b> Para cada estado e eleição, regressão linear (mínimos quadrados) da fração de votos com sequência manual sobre: % de eleitores com biometria cadastrada, % com 60 anos ou mais e % de baixa escolaridade da seção '
                     '(perfil 2022), estimada nas seções com log completo (mínimo de 200 seções). O resíduo (observado − esperado) é o que se compara ao P99. Isso ajusta por eleitorado idoso ou sem biometria; não separa causas.', P),
           Paragraph('<b>Comportamento da seção</b> (usado na varredura): TARDIO = late ou last19 ou close; MANUAL = manual ou manual_late. Comportamento = TARDIO ou MANUAL. '
                     'Os demais indicadores (fast, turnout, cancel) entram no score do estudo de inconsistências e nos testes de direção, mas não na definição de comportamento da varredura.', P),
           Paragraph('4. Comparação com as seções vizinhas e “diferença acima do limiar”', H2),
           Paragraph('Para cada seção com comportamento, os <b>pares</b> são as outras seções do mesmo local de votação (mesmo município, zona e código de local) que não têm comportamento na mesma eleição. '
                     'Mede-se a diferença, em pontos percentuais, entre a fração de votos válidos do lado A na seção e a média ponderada dessa fração nos pares. '
                     'Lado A = PT nas presidenciais; nas eleições de prefeito, o candidato líder do município (lado B = PL ou o 2º colocado).', P),
           Paragraph('<b>z</b> = diferença ÷ √(variância da fração do lado A entre os pares + erro binomial da própria seção, 100²·p(1−p)/votos válidos). '
                     '<b>Diferença acima do limiar</b> = |diferença| ≥ 5 p.p. e |z| ≥ 2 (nas colunas dos arquivos chama-se “real”, nome herdado da primeira versão). <b>Diferença alta</b> = |diferença| ≥ 10 p.p. (descritiva).', P),
           Paragraph('<b>Níveis de comparação.</b> “Local”: 3 ou mais pares no mesmo prédio — é o resultado principal. “Local (poucos pares)”: 1 ou 2 pares; a média de referência é do prédio, mas a dispersão do z vem das seções comuns do município. '
                     '“Município”: nenhum par no prédio — seção única no local ou prédio em que todas as demais seções também têm comportamento — e a comparação é com as seções comuns do município. '
                     f'Em 2026 T1, das {n(Vx.loc["P2026", "cmp_municipio"])} seções com comportamento no nível município, {n(Vx.loc["P2026", "municipio_secao_unica"])} são seção única e {n(Vx.loc["P2026", "municipio_predio_sem_par"])} estão em prédios sem par comum.', P),
           Paragraph('<b>Taxa-base.</b> O mesmo teste é aplicado a cada seção comum contra as demais seções comuns da sua referência, deixando-a de fora (leave-one-out), no mesmo nível. A fração de seções comuns que passa no teste é o que se espera por acaso e por heterogeneidade normal. '
                     'A taxa-base é muito maior no nível município (eleitorados diferentes) do que no nível local; por isso os níveis não são misturados e o resultado principal usa só o nível local.', P),
           Paragraph('4.1 Taxa de diferença acima do limiar e direção, por nível (2026 T1 e 2022 T1)', H3)]
    t = [['Eleição', 'Nível', 'Com comp.: n', 'acima do limiar', '%', 'favor A', 'favor B', '% A', 'Comuns: n', 'acima do limiar', '%', 'favor A', 'favor B', '% A']]
    for eid in ['P2026', 'P2022', 'M2024']:
        for lv in ['local', 'local (poucos pares)', 'município']:
            b, c = nv(D, eid, 'com comportamento', lv), nv(D, eid, 'comuns', lv)
            if b is None or c is None:
                continue
            t.append([LAB[eid], lv, n(b.n), n(b.real), n(b.pct_real, 1), n(b.favor_A), n(b.favor_B), n(b.pct_A, 1), n(c.n), n(c.real), n(c.pct_real, 1), n(c.favor_A), n(c.favor_B), n(c.pct_A, 1)])
    st += [wtable(t, [1.6, 1.9, 1.3, 1.2, .9, 1.0, 1.0, .9, 1.3, 1.2, .9, 1.0, 1.0, .9], font=6.2),
           Paragraph('Também se calcula a diferença de comparecimento frente aos pares (p.p.) e, quando metade ou mais das seções do local têm comportamento (“local inteiro”), a diferença do local inteiro frente às seções comuns do município. '
                     'A razão de chances de Mantel–Haenszel (favor A × grupo, estratos = nível) resume a direção controlando a composição por nível.', P),
           Paragraph('5. Teste de direção por permutação', H2),
           Paragraph('Pergunta: as seções sinalizadas por um indicador votam, em média, mais para um lado do que as demais seções do mesmo local? Estatística: diferença (A − B) na seção menos a média ponderada do seu local, '
                     'ponderada por votos válidos, entre sinalizadas e não sinalizadas. Distribuição nula: a sinalização é embaralhada 500 vezes (semente 20261016) em dois esquemas — dentro do município e, como sensibilidade mais fiel à pergunta do mesmo prédio, '
                     'dentro do próprio local; p = fração de embaralhamentos com diferença igual ou maior em módulo (bilateral); q = correção de Benjamini–Hochberg. A faixa do acaso nos gráficos é o intervalo entre os percentis 2,5 e 97,5 do nulo (centrada no nulo, não no efeito). '
                     'Resultados completos em relatorios/fiscalizacao/testes_permutacao.csv; resumo:', P)]
    t = [['Eleição', 'Indicador', 'Sinalizadas', 'Lado A % (sinal.)', 'Lado A % (demais)', 'Dif. no local (p.p.)', 'Faixa 95% do acaso (município)', 'p (município)', 'q', 'p (local)']]
    for eid in ['P2022', 'P2026', 'M2024']:
        for r in T[(T.eid == eid) & T.flag.isin(['f_late', 'f_manual', 'f_manual_late', 'f_last19', 'f_close', 'score2'])].itertuples():
            t.append([LAB[eid], r.flag.replace('f_', ''), n(r.n_flag), n(r.share_a_flag, 1), n(r.share_a_rest, 1), n(r.within_place_diff, 2), f'[{n(r.null_q025, 2)}; {n(r.null_q975, 2)}]', n(r.p_perm, 3), n(r.q, 3), n(r.p_perm_local, 3)])
    st += [wtable(t, [1.8, 1.6, 1.5, 1.6, 1.6, 1.7, 2.4, 1.4, 1.1, 1.3], font=6.6),
           Paragraph('Associação não é causa nem importância prática: significância diz apenas que a diferença é maior do que o acaso produz; a direção pode refletir o perfil de quem enfrenta fila.', SM),
           PageBreak(), Paragraph('6. Prefeito × presidente, nas mesmas seções', H2),
           Paragraph('Seções presentes nas três eleições de primeiro turno (presidente 2022, prefeito 2024, presidente 2026). A contagem bruta de seções com desvio “só nas presidenciais” é muito maior que “só nas municipais” porque há muito mais seções com '
                     'comportamento nos 1º turnos presidenciais (fila); a comparação correta usa taxas com denominadores e, de forma estrita, as mesmas seções com comportamento nos dois cargos. '
                     'Lado A tem significado distinto por cargo (PT × líder do município); por isso direção e pontos de direção usam só as presidenciais.', P)]
    if len(PX):
        t = [['Eleição', 'Recorte', 'Presentes', 'Com comp.', '% com comp.', 'Com comp. e acima do limiar', '% entre com comp.', 'Comuns acima do limiar', '% entre comuns']]
        for r in PX.itertuples():
            t.append([r.eleicao, r.recorte, n(r.presentes), n(r.com_comportamento), n(r.pct_com_comportamento, 2), n(r.com_comportamento_e_dif), n(r.pct_dif_entre_comportamento, 2), n(r.comuns_dif), n(r.pct_dif_entre_comuns, 2)])
        st += [wtable(t, [2.0, 1.3, 1.6, 1.5, 1.6, 2.2, 1.9, 2.0, 1.7], font=6.6)]
    if len(PXP):
        t = [['Par', 'Recorte', 'Seções c/ comp. nos dois cargos', 'Acima do limiar na presidencial', 'na municipal', '% pres.', '% mun.', 'Só pres.', 'Só mun.', 'p (McNemar)']]
        for r in PXP.itertuples():
            t.append([r.par, r.recorte, n(r.secoes_com_comportamento_em_ambas), n(r.dif_na_presidencial), n(r.dif_na_municipal), n(r.pct_dif_presidencial, 2), n(r.pct_dif_municipal, 2), n(r.so_presidencial), n(r.so_municipal), n(r.p_mcnemar, 3)])
        st += [wtable(t, [3.0, 1.3, 2.0, 1.9, 1.5, 1.2, 1.2, 1.3, 1.3, 1.5], font=6.6),
               Paragraph('Comparação estrita: nas mesmas seções com comportamento nos dois cargos, a propensão a ultrapassar o limiar é parecida (p alto no teste de McNemar): não há evidência de assimetria entre cargos.', SM)]
    st += [Paragraph('7. Pontuação do local e prioridade de observação', H2),
           Paragraph('A pontuação é uma soma transparente, pensada para ser lida e discutida, não um modelo ajustado. Componentes, máximos e tipo (operacional = fila/habilitação manual e volume; resultado = diferenças de votação):', P)]
    t = [['Componente', 'Regra', 'Máx.', 'Tipo'],
         ['Recorrência', '3 pontos por seção com comportamento em 2+ eleições (até 5) + 2 por seção em 3+ eleições (até 3)', '21', 'operacional'],
         ['Desvio nas presidenciais', '5 pontos por seção com comportamento e diferença acima do limiar em alguma presidencial (até 5)', '25', 'resultado'],
         ['Direção única', '8 pontos se há 2+ diferenças acima do limiar nas presidenciais e todas para o mesmo lado', '8', 'resultado'],
         ['Comportamento em 2026 T1', '3 por seção com comportamento em 2026 T1 (até 4)', '12', 'operacional'],
         ['Diferença em 2026 T1', '3 por seção com diferença acima do limiar em 2026 T1 (até 3)', '9', 'resultado'],
         ['Prédio inteiro atípico', '8 se ≥50% das seções têm comportamento em 2026 T1 e o prédio difere do município com |z| ≥ 2; 4 se só a primeira condição', '8', 'resultado (vs município) / operacional'],
         ['Volume', 'votos após 17h no local: ≥100 → 3, ≥500 → 6; habilitações manuais após 17h: ≥20 → 3, ≥50 → 6', '12', 'operacional'],
         ['2+ seções com desvio só nas presidenciais', '5 se 2+ seções do local têm diferença acima do limiar só nas presidenciais (redundante com o desvio presidencial; mantido com registro)', '5', 'resultado']]
    st += [wtable(t, [3.6, 9.4, 1.0, 3.0], font=7),
           Paragraph(f'Níveis de <b>prioridade de observação</b>: alta ≥ 45 pontos; média 25–44; baixa < 25. É ordem de prioridade, não probabilidade. '
                     f'Dos {n(len(alta))} locais de prioridade alta, {n(int(alta.sinal_resultado.isin(["nenhum", "só local (vs município)"]).sum()))} não têm nenhuma seção com diferença acima do limiar frente à própria referência '
                     f'({n(int((alta.sinal_resultado == "só local (vs município)").sum()))} têm o prédio inteiro divergindo do município) e {n(int((alta.pts_resultado == 0).sum()))} não têm nenhum ponto de resultado: entram por fila/habilitação manual recorrentes, volume e comportamento em 2026. '
                     f'Na prioridade média, {n(int(media.sinal_resultado.isin(["nenhum", "só local (vs município)"]).sum()))} de {n(len(media))}.', P),
           Paragraph('Prioridade para o 2º turno de 2026: locais com seções presentes em 2026 e comportamento em 2026 T1 ou recorrente, ordenados por pontos. '
                     'No mapa de fiscalização entram os níveis alta e média; “seções a checar” são as seções do local com comportamento em 2026 T1 ou recorrentes (2+ eleições) existentes em 2026; '
                     'fiscais sugeridos = 1 por local de prioridade alta + 1 a cada 2 de média, arredondado para cima em cada zona (ponto de partida para alocação).', P),
           Paragraph('8. Resultados principais', H2), Paragraph('8.1 Contagens, com o nível “local” (mesmo prédio, ≥3 pares) como resultado principal', H3)]
    t = [['Eleição', 'Seções', 'Com comp.', 'Tardia', 'Manual', 'Com comp. no nível local', 'acima do limiar (local)', '% (com comp., local)', '% (comuns, local)', 'acima do limiar (município)', 'Locais inteiros']]
    for eid in EIDS:
        r = Vx.loc[eid]
        t.append([LAB[eid], n(r.secoes), n(r.com_comportamento), n(r.tardia), n(r.manual), n(r.local_com_comportamento), n(r.local_dif_real), n(r.local_pct_real_com_comportamento, 1), n(r.local_pct_real_secoes_comuns, 1), n(r.real_municipio), n(r.locais_inteiros)])
    st += [wtable(t, [2.0, 1.5, 1.5, 1.4, 1.4, 1.9, 1.8, 1.8, 1.7, 1.9, 1.6], font=6.8), Paragraph('8.2 Direção (nível local) e resumo por estratos', H3)]
    EX = D['excesso']
    t = [['Eleição', 'Favor A / B (com comp., local)', '% A', 'Favor A / B (comuns, local)', '% A', 'OR Mantel–Haenszel (estratos = nível)', 'Comparec. dif. p.p.', 'Excesso A além dos votos após 17h: % (nível local)', '% (todos os níveis)']]
    for eid in EIDS:
        r = Vx.loc[eid]
        ex = EX.get(eid, {})
        t.append([LAB[eid], f'{n(r.local_favor_A)} / {n(r.local_favor_B)}', n(r.local_pct_A, 1), f'{n(r.local_comuns_favor_A)} / {n(r.local_comuns_favor_B)}', n(r.local_comuns_pct_A, 1), n(r.or_mantel_haenszel, 2), n(r.comparecimento_dif_media_pp, 2),
                  n(ex.get('local', np.nan), 1), n(ex.get('todos', np.nan), 1)])
    st += [wtable(t, [1.9, 2.4, 1.1, 2.4, 1.1, 2.3, 1.8, 2.3, 1.7], font=6.6), Spacer(1, 4)]
    p26, p22 = Vx.loc['P2026'], Vx.loc['P2022']
    pr = D['PR'].prioridade_observacao.value_counts()
    dirs = L.direcao.value_counts()
    for s in [f'No mesmo prédio, seções com comportamento ultrapassam o limiar em {n(Vx.local_pct_real_com_comportamento.min(), 1)}% a {n(Vx.local_pct_real_com_comportamento.max(), 1)}% dos casos, contra '
              f'{n(Vx.local_pct_real_secoes_comuns.min(), 1)}% a {n(Vx.local_pct_real_secoes_comuns.max(), 1)}% nas seções comuns (em 2026, razão de {n(p26.local_pct_real_com_comportamento / p26.local_pct_real_secoes_comuns, 1)}): a maioria vota como o resto do prédio.',
              f'Direção: em 2026 T1, no mesmo prédio, {n(p26.local_pct_A, 0)}% das diferenças das seções com comportamento pendem para o lado A (PT), contra {n(p26.local_comuns_pct_A, 0)}% nas comuns (OR de Mantel–Haenszel {n(p26.or_mantel_haenszel, 2)}). '
              f'Em 2022 T1 a distância é pequena ({n(p22.local_pct_A, 0)}% contra {n(p22.local_comuns_pct_A, 0)}%; OR {n(p22.or_mantel_haenszel, 2)}). Nas eleições de prefeito não se observa assimetria. A direção é robusta só em 2026 T1.',
              f'Misturando os níveis de comparação, 2026 T1 teria {n(p26.dif_real_com_comportamento)} diferenças acima do limiar, {n(p26.real_municipio)} delas no nível município, onde ambos os grupos pendem para A: por isso o resultado principal é o do nível local.',
              f'Locais com ao menos uma seção com comportamento: {n(len(L))}; prioridade alta {n(len(alta))}, média {n(len(media))}, baixa {n(int((L.prioridade_observacao == "baixa").sum()))}. Entre os locais com alguma diferença nas presidenciais, direção única para A em {n(dirs.get("sempre A", 0))}, para B em {n(dirs.get("sempre B", 0))}, mista em {n(dirs.get("mista", 0))}.',
              f'Prioridade 2026 T2: {n(len(D["PR"]))} locais, {n(pr.get("alta", 0))} de prioridade alta e {n(pr.get("média", 0))} média. Mapa de fiscalização: {n(int(U.locais.sum()))} locais, {n(int(U.secoes_a_checar.sum()))} seções a checar, {n(int(U.fiscais_sugeridos.sum()))} fiscais sugeridos.']:
        st.append(Paragraph('• ' + s, P))
    st += [Paragraph('9. Limitações e o que não se pode concluir', H2)]
    for s in ['Os dados não observam compra de voto, coação, transporte de eleitores ou intenção. Observam horários, habilitações, encerramento e votos por seção.',
              f'Não se sabe em quem votaram os eleitores habilitados manualmente ou após as 17h; compara-se o resultado da seção inteira. Em 2026 T1, no nível local, mesmo que todos os votos após as 17h fossem do lado A, em {n(EX.get("P2026", {}).get("local", np.nan), 0)}% das {n(EX.get("P2026", {}).get("n_local", 0))} seções com comportamento que destoaram a favor de A '
              'o excesso não seria explicado por eles (o contrafactual cobre só os votos após as 17h, não os habilitados manualmente): a diferença é da seção, não só dos eleitores tardios.',
              'Votar após as 17h é legal para quem estava na fila; habilitação manual é o procedimento previsto quando a biometria falha ou o eleitor não a tem cadastrada. Ambos medem fila e falha, não irregularidade.',
              'A diferença frente aos vizinhos reflete também composição do eleitorado: seções do mesmo prédio atendem ruas e perfis distintos. O teste z e a taxa-base reduzem, mas não eliminam, esse fator.',
              'Seções sem par comum no prédio (seção única ou prédio inteiro com comportamento) são comparadas ao município, referência fraca com taxa-base alta nos dois grupos; estão separadas do resultado principal e não devem ser lidas como diferença frente ao prédio.',
              'A direção favorável ao lado A nas seções com comportamento é robusta só em 2026 T1; em 2022 é pequena e, no agregado, majoritariamente efeito de composição por nível. É compatível com várias explicações (perfil de quem enfrenta fila; densidade; operação irregular); os dados não distinguem entre elas.',
              'Horários são do relógio de cada urna, não certificados. Reversões são contadas; desvios constantes de relógio não são detectáveis. O perfil do eleitorado é de 2022 e é usado para todas as eleições.',
              'A pontuação é uma regra transparente escolhida pelos autores, não um modelo validado contra casos confirmados; ordena prioridades de observação. O componente “2+ seções com desvio só nas presidenciais” é redundante com o desvio presidencial e foi mantido com registro; mudanças de pesos mudam a lista.',
              '2º turnos (2022 e prefeito 2024) têm poucas seções com comportamento e baixo poder; prefeito 2024 T2 só existe em municípios com segundo turno.']:
        st.append(Paragraph('• ' + s, P))
    st += [Paragraph('10. Reprodutibilidade', H2),
           Paragraph('Ambientes: Python 3.12; pacote auditabr 0.2.0 (requirements.lock) para aquisição e leitura de logs; .venv-report (requirements-report.lock) para análises e PDFs. Sequência de scripts, todos em scripts/:', P)]
    t = [['Etapa', 'Script', 'Saída'],
         ['Catálogo CKAN e aquisição de BU/logs por UF', 'uf_pipeline.py, mun_logs_pipeline.py, bu_capture_all.py', 'research/estados/<UF>/…, research/municipais/<UF>/…, research/bu/'],
         ['Correspondências de urnas e perfil do eleitorado', 'ceft_capture.py, profile_capture.py', 'research/ceft/, research/perfil/2022/'],
         ['Leitura dos logs (máquina de estados)', 'analyze_pilot_operations.py (motor), process_bahia_document_logs.py, extract_contingency_logs.py, reidentify_logs.py', 'operations.jsonl por eleição/UF'],
         ['Análise por seção e cargo', 'analyze_office.py, reanalyze_with_logs.py', 'sections.parquet, candidate_sections.parquet, summary.json'],
         ['Indicadores, testes de permutação, ferramenta', 'make_fiscalizacao_study.py', 'relatorios/fiscalizacao/ (secoes_indicadores_*.parquet, testes_permutacao.csv, PDF)'],
         ['Varredura por local', 'make_varredura_locais.py', 'relatorios/fiscalizacao/varredura/ (locais_risco.csv, comparacao_por_nivel.csv, pres_x_pref_*.csv, VARREDURA_LOCAIS.xlsx, PDF)'],
         ['Mapa de fiscalização 2026 T2', 'make_mapa_fiscalizacao_2026t2.py', 'relatorios/fiscalizacao/mapa_2026_T2/ (XLSX e PDF por UF)'],
         ['Estes documentos', 'make_documentos_metodo.py', 'relatorios/fiscalizacao/documentos/']]
    st += [wtable(t, [4.6, 7.0, 6.4], font=7),
           Paragraph('Parâmetros fixos: elegibilidade ≥ 50 aptos; P99 por estado; diferença acima do limiar ≥ 5 p.p. e |z| ≥ 2; pares mínimos 3; permutação 500 réplicas, semente 20261016, dois esquemas; cortes de prioridade 25 e 45 pontos. '
                     'Cada captura tem recibo com URL, SHA-256 e data; cada saída tem data de geração. O repositório git do projeto registra o código; os dados brutos ficam fora do versionamento por tamanho.', P),
           Paragraph('11. Registro de alterações (24/10/2026, após parecer externo)', H2)]
    for s in ['Resultado principal restrito ao nível “local” (≥3 pares no mesmo prédio); nível “município” reportado em separado, com origem (seção única / prédio sem par) e taxa-base própria; tabela por nível publicada (comparacao_por_nivel.csv).',
              '“Diferença real” passou a “diferença acima do limiar” na prosa; os nomes de colunas (“real”) foram mantidos para não quebrar planilhas e scripts.',
              'Direção (favor A/B) e pontos de direção passaram a usar só as presidenciais, onde lado A tem significado estável; prefeito reportado à parte. “Só municipais” passou a exigir presença nos dados presidenciais, espelhando “só presidenciais”.',
              'Cruzamento prefeito × presidente substituído pela comparação pareada nas mesmas seções, com denominadores, e pela comparação estrita (seções com comportamento nos dois cargos, McNemar).',
              '“Risco” passou a “prioridade de observação”; pontos separados em operacionais e de resultado; coluna sinal_resultado; componente “só presidenciais” renomeado para “2+ seções com desvio só nas presidenciais”, peso mantido e redundância registrada.',
              'Teste de permutação: desvio frente à média ponderada do local (nulo centrado), faixa do acaso pelos quantis do nulo, embaralhamento adicional dentro do local; gráfico redesenhado (faixa cinza = acaso; ponto = observado).',
              'Textos: retiradas atribuições causais (“muda o resultado”, “não é acaso”, “o que importa”); acrescentada a ressalva de que não se sabe em quem votaram os eleitores tardios; tabelas redimensionadas para a largura do texto.',
              'Maranhão incluído em toda a cadeia (11 estados).']:
        st.append(Paragraph('• ' + s, P))
    st += [Paragraph('12. Glossário', H2)]
    t = [['Termo', 'Significado'],
         ['Seção', 'Menor unidade de votação (uma urna); identificada por município, zona e número.'], ['Local de votação', 'Prédio (escola etc.) que reúne várias seções; identificado por município, zona e código do local.'],
         ['Zona eleitoral', 'Divisão administrativa que agrupa seções; pode abranger vários municípios ou parte de um.'], ['BU / boletim de urna', 'Resultado oficial impresso e transmitido por cada urna ao fim da votação.'],
         ['Log de urna', 'Arquivo com os eventos registrados pela urna, com horário.'], ['Habilitação manual', 'Liberação do eleitor pelo mesário sem reconhecimento biométrico, com registro da digital do mesário.'],
         ['Lado A / lado B', 'PT / PL nas presidenciais; líder / 2º colocado do município nas eleições de prefeito.'], ['p.p.', 'Pontos percentuais (diferença entre duas porcentagens).'],
         ['P99', 'Valor acima do qual está apenas 1% das seções do estado.'], ['z', 'Quantos desvios-padrão a diferença da seção está da variação normal entre seções da sua referência.'],
         ['Diferença acima do limiar', '≥5 p.p. e |z| ≥ 2; chamada “real” nas colunas dos arquivos.'], ['Nível de comparação', 'local (≥3 pares no prédio), local (poucos pares), município (sem par no prédio).'],
         ['Permutação', 'Teste que embaralha os rótulos muitas vezes para ver o que aconteceria por acaso.'], ['q (BH)', 'p corrigido para muitos testes simultâneos (Benjamini–Hochberg).'],
         ['OR de Mantel–Haenszel', 'Razão de chances combinada entre estratos; 1 = sem diferença de direção entre grupos.'], ['McNemar', 'Teste pareado para duas medidas na mesma unidade (aqui, a mesma seção em dois cargos).'],
         ['Contingência', 'Urna substituta usada quando a original falha.'], ['CEFT', 'Correspondência entre a urna prevista e a efetivamente usada em cada seção.']]
    st += [wtable(t, [3.4, 14.6], font=7.2)]

    def foot(c, d_):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Método e dados — varredura de fiscalização — sinalização não é acusação'); c.drawRightString(19 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'METODO_E_DADOS.pdf'), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.6 * cm, bottomMargin=1.8 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


# ----------------------------------------------------------------------------- PDF: resumo simples
def pdf_resumo(D, figs):
    V, L, U = D['V'], D['L'], D['U']
    Vx = V.set_index('eid')
    T1 = ParagraphStyle('T1', parent=M.H1, fontSize=20, leading=24, spaceAfter=10)
    Hh = ParagraphStyle('Hh', parent=M.H2, fontSize=14, leading=17, spaceBefore=12, spaceAfter=4)
    Pp = ParagraphStyle('Pp', parent=M.P, fontSize=11.5, leading=16)
    Bb = ParagraphStyle('Bb', parent=Pp, leftIndent=14, bulletIndent=2, spaceAfter=3)
    Nn = ParagraphStyle('Nn', parent=M.NOTE, fontSize=11, leading=15)
    p26, p22 = Vx.loc['P2026'], Vx.loc['P2022']
    m24 = Vx.loc['M2024']
    p26m, c26m = nv(D, 'P2026', 'com comportamento', 'município'), nv(D, 'P2026', 'comuns', 'município')
    alta = L[L.prioridade_observacao == 'alta']
    media = L[L.prioridade_observacao == 'média']
    n_alta_res = int(alta.sinal_resultado.isin(['seções', 'seções + local']).sum())
    pr = D['PR'].prioridade_observacao.value_counts()
    st = [Paragraph('O que é esta varredura, em palavras simples', T1),
          Paragraph(f'Um levantamento feito com dados públicos do TSE, em {len(D["ufs"])} estados, para indicar <b>em quais escolas e prédios de votação vale a pena ter um fiscal atento</b> no 2º turno de 2026 e nas próximas eleições. '
                    'Ele não acusa ninguém e não mede probabilidade de fraude. Ele aponta onde olhar.', Pp),
          Paragraph('O que olhamos', Hh),
          Paragraph('Em cada seção (cada urna), nas eleições de 2022, 2024 e 2026, procuramos três coisas:', Pp),
          Paragraph('<b>1. Fila depois da hora.</b> A votação termina às 17h. Quem já está na fila pode votar depois. Procuramos seções onde muita gente votou depois das 17h, onde o último voto saiu depois das 19h, ou onde a urna só foi encerrada mais de uma hora depois, sem ter sido trocada.', Bb, bulletText='•'),
          Paragraph('<b>2. Liberação manual pelo mesário.</b> Quando a biometria falha ou o eleitor não tem digital cadastrada, o mesário libera o eleitor “na mão”. Isso é normal. O que procuramos é a seção onde isso aconteceu <i>muito mais</i> do que o esperado para o tipo de eleitor que ela tem (idosos, pessoas sem biometria).', Bb, bulletText='•'),
          Paragraph(f'<b>3. Voto diferente dos vizinhos.</b> Comparamos o resultado dessa seção com o das outras seções <i>do mesmo prédio</i> que não tiveram fila nem liberação manual acima do normal. Se a diferença passa de 5 pontos, para qualquer lado, e é maior do que a variação comum entre salas do mesmo prédio, '
                    f'dizemos que ela “passou do limiar”. Entre salas comuns, isso acontece por acaso e por variação normal em cerca de {n(nv(D, "P2026", "comuns", "local").pct_real, 0)}% dos casos. Quando a seção não tem vizinha comparável no prédio, comparamos com o município inteiro, uma referência mais fraca, e contamos isso à parte.', Bb, bulletText='•'),
          Paragraph('Depois juntamos tudo por prédio: quantas seções têm esses sinais, se repetem eleição após eleição, se o resultado delas pende sempre para o mesmo lado na eleição de presidente, e se o prédio inteiro se comporta assim. '
                    'Cada prédio recebe uma nota de 0 a 100 e uma <b>prioridade de observação</b>: alta, média ou baixa. É uma ordem para decidir onde colocar gente, não uma medida de irregularidade.', Pp),
          Paragraph('O que encontramos', Hh),
          Paragraph(f'<b>Fila é comum.</b> No 1º turno de 2026, {n(p26.com_comportamento)} seções mostraram fila tardia ou liberação manual acima do normal. A maioria é só fila.', Bb, bulletText='•'),
          Paragraph(f'<b>Fila ou liberação manual, sozinhas, raramente vêm com resultado diferente.</b> Das {n(p26.com_comportamento)} seções com sinais em 2026, {n(p26.local_com_comportamento)} têm 3 ou mais vizinhas comparáveis no prédio; dessas, {n(p26.local_dif_real)} ({n(p26.local_pct_real_com_comportamento, 1)}%) passaram do limiar, '
                    f'contra {n(p26.local_comuns_real)} de {n(p26.local_comuns)} seções comuns ({n(p26.local_pct_real_secoes_comuns, 1)}%): quase o dobro da taxa, mas {n(100 - p26.local_pct_real_com_comportamento, 0)}% votaram como o resto do prédio. '
                    f'Outras {n(p26.cmp_municipio)} seções com sinais só puderam ser comparadas ao município ({n(p26.real_municipio)} passaram do limiar, {n(p26m.pct_real, 1)}%, contra {n(c26m.pct_real, 1)}% das comuns nessa situação).', Bb, bulletText='•'),
          Paragraph(f'<b>Quando a seção destoa do prédio, em 2026 isso ocorreu mais para um lado.</b> Nas seções com sinais que destoaram em 2026, {n(p26.local_pct_A, 0)}% penderam para o PT; nas seções comuns que também destoaram, {n(p26.local_comuns_pct_A, 0)}%. '
                    f'Em 2022 a diferença foi pequena ({n(p22.local_pct_A, 0)}% contra {n(p22.local_comuns_pct_A, 0)}%). Na eleição de prefeito de 2024 não se vê direção consistente: {n(m24.local_pct_A, 0)}% para o candidato líder contra {n(m24.local_comuns_pct_A, 0)}% nas comuns, com poucas seções ({n(m24.local_dif_real)}) para afirmar algo.', Bb, bulletText='•'),
          Paragraph(f'<b>Poucos prédios reúnem os sinais repetidos.</b> De {n(len(L))} prédios com ao menos uma seção sinalizada, {n(len(alta))} são de prioridade alta e {n(len(media))} de prioridade média; desses, {n(pr.get("alta", 0) + pr.get("média", 0))} têm seções em 2026 e entram no mapa de amanhã. '
                    f'Entre os de prioridade alta, {n(n_alta_res)} têm alguma seção que destoou do resultado; os outros {n(len(alta) - n_alta_res)} entram por fila e liberação manual repetidas, volume ou prédio inteiro fora do padrão do município.', Bb, bulletText='•'),
          Paragraph('O que isso significa e o que não significa', Hh),
          Paragraph('Não significa que houve fraude ou compra de votos nesses lugares. Fila pode ser só fila; liberação manual pode ser só biometria que falhou; um resultado diferente pode ser porque aquela sala atende uma rua diferente. '
                    'Os dados não enxergam intenção nem dinheiro, e não dizem em quem votaram as pessoas que votaram tarde ou foram liberadas manualmente: comparamos a seção inteira. '
                    'O que eles mostram é que <b>alguns prédios repetem, eleição após eleição, fila tardia e liberação manual acima do normal, e parte deles também tem seções com resultado fora do padrão do próprio prédio</b>. '
                    'Isso é motivo suficiente para alguém estar lá, olhando e anotando.', Nn),
          Paragraph('Como usar amanhã (25/10/2026)', Hh),
          Paragraph(f'Há um mapa por estado, com {n(int(U.locais.sum()))} prédios e {n(int(U.secoes_a_checar.sum()))} seções a checar, e uma planilha com uma linha por seção para o fiscal preencher. Em cada seção indicada, o fiscal observa e anota, com horário:', Pp),
          Paragraph('se havia fila às 17h e de que tamanho;', Bb, bulletText='•'), Paragraph('quantos eleitores foram liberados manualmente pelo mesário e por quê;', Bb, bulletText='•'),
          Paragraph('a hora do último voto e a hora em que a urna foi encerrada;', Bb, bulletText='•'), Paragraph('se a urna foi trocada ou houve contingência;', Bb, bulletText='•'),
          Paragraph('quem está coordenando o prédio, quando o prédio inteiro tem o mesmo padrão.', Bb, bulletText='•'),
          Paragraph('Ordem: prédios de prioridade alta primeiro. A sugestão é um fiscal por prédio de prioridade alta e um para cada dois de prioridade média, arredondando para cima em cada zona.', Pp),
          Paragraph('Onde estão os arquivos', Hh),
          Paragraph('Pasta relatorios/fiscalizacao/: <b>mapa_2026_T2/</b> (mapa e checklist por estado, PDF e Excel), <b>varredura/</b> (lista completa de prédios com a nota e os motivos), '
                    '<b>documentos/</b> (este resumo, o caderno de gráficos e o documento técnico com método e dados para quem quiser conferir).', Pp)]
    st += [PageBreak(), Paragraph('Dois gráficos para entender', Hh), img(figs[1][0], 17.5),
           Paragraph(f'À esquerda, no mesmo prédio: {n(p26.local_pct_real_com_comportamento, 1)}% das seções com fila ou liberação manual passaram do limiar em 2026, contra {n(p26.local_pct_real_secoes_comuns, 1)}% das comuns: quase o dobro da taxa, mas a grande maioria vota como as vizinhas. À direita, sem vizinha comparável, a comparação é com o município e fica separada.', Pp),
           Spacer(1, 8), img(figs[2][0], 17.5), Paragraph('Quando votam diferente, no mesmo prédio e em 2026, pendem para um lado mais do que as seções comuns; nas eleições de prefeito, não.', Pp)]

    def foot(c, d_):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Resumo simples — varredura de fiscalização — sinalização não é acusação'); c.drawRightString(19 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'RESUMO_SIMPLES.pdf'), pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


def main():
    D = load()
    figs = charts(D)
    pdf_graficos(figs, D)
    pdf_metodo(D, figs)
    pdf_resumo(D, figs)
    print('ok', len(figs), 'graficos;', D['head'], '; UFs:', ','.join(D['ufs']))


if __name__ == '__main__':
    main()
