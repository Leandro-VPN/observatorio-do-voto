"""Três documentos sobre a varredura de fiscalização (todos gerados dos números atuais, nunca digitados à mão):

  METODO_E_DADOS.pdf   — método completo, dados usados, definições, testes, pontuação, limites e reprodutibilidade (para quem quer avaliar)
  GRAFICOS.pdf         — caderno de gráficos simples, um por página, com "como ler"
  RESUMO_SIMPLES.pdf   — explicação curta em linguagem comum

Entrada: relatorios/fiscalizacao/{resumo_indicadores,testes_permutacao}.csv, relatorios/fiscalizacao/varredura/*.csv, relatorios/fiscalizacao/mapa_2026_T2/*.csv
Saída:   relatorios/fiscalizacao/documentos/ (PDFs e figuras PNG)
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
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer
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
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
LAB = {'P2022': 'Pres. 2022 T1', 'P2022b': 'Pres. 2022 T2', 'M2024': 'Pref. 2024 T1', 'M2024b': 'Pref. 2024 T2', 'P2026': 'Pres. 2026 T1'}
DAYS = {'P2022': '02/10/2022', 'P2022b': '30/10/2022', 'M2024': '06/10/2024', 'M2024b': '27/10/2024', 'P2026': '04/10/2026'}
# paleta de referência validada (dataviz): categóricas em ordem fixa, sequencial azul, tinta/grade
C1, C2, C3 = '#2a78d6', '#eb6834', '#1baf7a'
SEQ = {'alta': '#184f95', 'média': '#3987e5', 'baixa': '#9ec5f4'}
INK, INK2, MUTED, GRID = '#0b0b0b', '#52514e', '#898781', '#e1e0d9'
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True, 'grid.alpha': .6, 'grid.color': GRID, 'grid.linewidth': .6,
                     'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED, 'text.color': INK, 'figure.dpi': 150, 'axes.titlesize': 12, 'axes.titleweight': 'bold',
                     'axes.titlelocation': 'left', 'legend.frameon': False})
FLAG_DESC = [('late', 'Votos após 17h: fração acima do P99 do estado e pelo menos 20 votos após as 17h'),
             ('manual', 'Habilitação manual pelo mesário acima do esperado para a seção (resíduo da regressão > P99 do estado)'),
             ('manual_late', 'Pelo menos 10 votos com sequência manual após as 17h'),
             ('fast', 'Ritmo acelerado após 17h: mediana entre votos < 40 s com pelo menos 20 votos tardios'),
             ('last19', 'Último voto computado às 19h ou depois'),
             ('turnout', 'Comparecimento muito acima: z > 3 frente à mediana estadual (MAD) e ≥ 10 p.p. acima da mediana municipal'),
             ('close', 'Encerramento da urna mais de 60 min após as 17h sem troca de urna registrada'),
             ('cancel', 'Cancelamentos/suspensões de habilitação pelo mesário acima do P99 do estado e pelo menos 5')]


def n(x, d=0):
    return M.n(x, d)


def pct(x, d=1):
    return n(x, d) + '%'


def git_head():
    try:
        return subprocess.run(['C:/Program Files/Git/cmd/git.exe', 'log', '--format=%h %ad', '--date=short', '-1'], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return 'n/d'


# ----------------------------------------------------------------------------- dados
def load():
    D = {}
    D['R'] = pd.read_csv(FISC / 'resumo_indicadores.csv', **CSV)
    D['T'] = pd.read_csv(FISC / 'testes_permutacao.csv', **CSV)
    D['V'] = pd.read_csv(VAR / 'resumo_por_eleicao.csv', **CSV)
    D['L'] = pd.read_csv(VAR / 'locais_risco.csv', low_memory=False, **CSV)
    D['H'] = pd.read_csv(VAR / 'secoes_historico.csv', low_memory=False, usecols=['uf', 'n_eleicoes_comportamento', 'n_pres_dif_real', 'n_pref_dif_real', 'padrao_comportamento', 'padrao_desvio_resultado', 'direcao'], **CSV)
    D['CID'] = pd.read_csv(VAR / 'cidades.csv', **CSV)
    D['PR'] = pd.read_csv(VAR / 'prioridade_locais_2026_T2.csv', low_memory=False, usecols=['uf', 'nivel_risco', 'pontos'], **CSV)
    D['U'] = pd.read_csv(MAPA / 'resumo_por_uf.csv', **CSV)
    D['Z'] = pd.read_csv(MAPA / 'zonas_todas.csv', **CSV)
    D['head'] = git_head()
    return D


# ----------------------------------------------------------------------------- gráficos
def save(f, name):
    f.tight_layout()
    f.savefig(FIG / f'{name}.png', dpi=150)
    plt.close(f)
    return FIG / f'{name}.png'


def bar_labels(ax, bars, fmt='{:,.0f}', fs=8.5, dx=0, dy=0):
    for b in bars:
        h = b.get_height()
        if np.isfinite(h):
            ax.annotate(fmt.format(h).replace(',', '.'), (b.get_x() + b.get_width() / 2 + dx, h), xytext=(0, 3 + dy), textcoords='offset points', ha='center', va='bottom', fontsize=fs, color=INK2)


def charts(D):
    R, T, V, L, H, U = D['R'], D['T'], D['V'], D['L'], D['H'], D['U']
    figs = []
    x = np.arange(len(V))
    labs = [LAB[e] for e in V.eid]
    # 1 seções com comportamento: tardia × manual
    f, ax = plt.subplots(figsize=(10, 4.6))
    b1 = ax.bar(x - .2, V.tardia, .38, color=C1, label='Votação tardia')
    b2 = ax.bar(x + .2, V.manual, .38, color=C2, label='Habilitação manual excessiva')
    bar_labels(ax, b1); bar_labels(ax, b2)
    ax.set_xticks(x); ax.set_xticklabels(labs); ax.set_ylabel('seções'); ax.legend(loc='upper right')
    ax.set_title('Quantas seções mostraram cada comportamento, por eleição')
    figs.append((save(f, '01_comportamento'), 'Cada eleição tem cerca de 350 mil seções analisadas nos 10 estados. Votação tardia é muito mais comum nos 1º turnos presidenciais (fila) do que nas eleições de prefeito; '
                 'a habilitação manual excessiva aparece em número parecido em todas, porque é definida pelo P99 de cada estado.'))
    # 2 diferença real: com comportamento vs comuns
    f, ax = plt.subplots(figsize=(10, 4.6))
    b1 = ax.bar(x - .2, V.pct_real_com_comportamento, .38, color=C1, label='Seções com comportamento')
    b2 = ax.bar(x + .2, V.pct_real_secoes_comuns, .38, color='#9ec5f4', label='Seções comuns (acaso)')
    bar_labels(ax, b1, '{:.1f}%'); bar_labels(ax, b2, '{:.1f}%')
    ax.set_xticks(x); ax.set_xticklabels(labs); ax.set_ylabel('% de seções com diferença real frente às vizinhas'); ax.legend(loc='upper left')
    ax.set_title('As seções com comportamento votam diferente das vizinhas do mesmo prédio?')
    figs.append((save(f, '02_diferenca_real'), 'Diferença real = pelo menos 5 pontos percentuais no lado A e |z| ≥ 2 frente às outras seções do mesmo local. A barra clara é o mesmo teste nas seções sem comportamento: '
                 'o quanto se espera por acaso. A diferença entre as duas barras é pequena: o comportamento, por si, pouco muda o resultado da seção.'))
    # 3 direção
    f, ax = plt.subplots(figsize=(10, 4.6))
    pa = 100 * V.dif_real_favor_A / (V.dif_real_favor_A + V.dif_real_favor_B)
    pc = 100 * V.comuns_real_favor_A / (V.comuns_real_favor_A + V.comuns_real_favor_B)
    b1 = ax.bar(x - .2, pa, .38, color=C1, label='Seções com comportamento')
    b2 = ax.bar(x + .2, pc, .38, color='#9ec5f4', label='Seções comuns')
    bar_labels(ax, b1, '{:.0f}%'); bar_labels(ax, b2, '{:.0f}%')
    ax.axhline(50, color=INK2, lw=.8, ls='--'); ax.text(len(V) - .5, 51, '50% = sem direção', ha='right', fontsize=8.5, color=INK2)
    ax.set_ylim(0, 100); ax.set_xticks(x); ax.set_xticklabels(labs); ax.set_ylabel('% das diferenças reais a favor do lado A'); ax.legend(loc='lower left')
    ax.set_title('Quando a seção difere das vizinhas, para que lado pende?')
    figs.append((save(f, '03_direcao'), 'Lado A = PT (presidente) ou candidato líder do município (prefeito). Nas presidenciais, as seções com comportamento que diferem das vizinhas pendem para o PT muito mais '
                 'do que as seções comuns pendem (por exemplo 82% contra 59% em 2026). Nas eleições de prefeito não há direção: fica perto de 50% nos dois grupos.'))
    # 4 permutação
    f, ax = plt.subplots(figsize=(10, 4.8))
    flags = ['f_late', 'f_manual', 'f_manual_late', 'f_last19', 'f_turnout', 'f_close', 'f_cancel', 'score2', 'score3']
    xx = np.arange(len(flags))
    for i, (eid, col) in enumerate([('P2022', C1), ('P2026', C2), ('M2024', C3)]):
        s = T[T.eid == eid].set_index('flag').reindex(flags)
        ax.errorbar(xx + (i - 1) * .25, s.within_place_diff, yerr=1.96 * s.null_sd, fmt='o', ms=6, color=col, ecolor=col, elinewidth=1.2, capsize=3, label=LAB[eid])
    ax.axhline(0, color=INK2, lw=.8)
    ax.set_xticks(xx); ax.set_xticklabels([q.replace('f_', '') for q in flags]); ax.set_ylabel('diferença (A − B) dentro do mesmo local, p.p.'); ax.legend(loc='upper left')
    ax.set_title('Teste de favorecimento: seções sinalizadas × demais do mesmo local (barras = faixa do acaso)')
    figs.append((save(f, '04_permutacao'), 'Cada ponto é a diferença de votação (lado A menos lado B) entre seções sinalizadas e não sinalizadas do mesmo local, ponderada por votos válidos. A barra é a faixa de ±1,96 desvios '
                 'obtida embaralhando a sinalização 500 vezes dentro do município. Ponto fora da barra = diferença maior que o acaso. Em 2026, votação tardia e encerramento tardio ficam acima do acaso a favor de A; em prefeito 2024 nada sai do acaso.'))
    # 5 locais por UF e nível
    f, ax = plt.subplots(figsize=(10, 4.6))
    ct = L.groupby(['uf', 'nivel_risco']).size().unstack(fill_value=0).reindex(ORDER).fillna(0)
    bottom = np.zeros(len(ct))
    NIV = {'alta': 'risco alto', 'média': 'risco médio', 'baixa': 'risco baixo'}
    for lv in ['alta', 'média', 'baixa']:
        if lv in ct:
            ax.bar(ct.index, ct[lv], .6, bottom=bottom, color=SEQ[lv], label=NIV[lv], edgecolor='white', linewidth=1)
            bottom += ct[lv].values
    for i, (u, tot) in enumerate(zip(ct.index, bottom)):
        ax.text(i, tot, f'{n(tot)}\n({n(ct.loc[u].get("alta", 0))} alto)', ha='center', va='bottom', fontsize=8, color=INK2, linespacing=1.1)
    ax.set_ylim(0, bottom.max() * 1.18)
    ax.set_ylabel('locais de votação com comportamento'); ax.legend(loc='upper right')
    ax.set_title('Locais de votação com comportamento, por estado e nível de risco')
    figs.append((save(f, '05_locais_uf'), 'Sobre cada barra, o total de locais e, entre parênteses, quantos são de risco alto. Bahia e Pernambuco concentram a maior parte; São Paulo e Minas, apesar do tamanho, têm poucos locais de risco alto.'))
    # 6 distribuição de pontos
    f, ax = plt.subplots(figsize=(10, 4.4))
    ax.hist(L.pontos, bins=np.arange(0, 101, 5), color=C1, edgecolor='white')
    for v, t in ((25, 'risco médio ≥ 25'), (45, 'risco alto ≥ 45')):
        ax.axvline(v, color=INK2, lw=.9, ls='--'); ax.text(v + 1, ax.get_ylim()[1] * .9, t, fontsize=8.5, color=INK2)
    ax.set_xlabel('pontos do local (0–100)'); ax.set_ylabel('locais'); ax.set_yscale('log')
    ax.set_title('Distribuição dos pontos de risco dos locais (escala logarítmica)')
    figs.append((save(f, '06_pontos'), 'A maioria dos locais tem poucos pontos: uma seção com fila em uma única eleição. Os cortes de 25 e 45 pontos separam os níveis médio e alto. A escala vertical é logarítmica para que a cauda apareça.'))
    # 7 composição dos pontos nos locais de risco alto
    f, ax = plt.subplots(figsize=(10, 4.2))
    comp = {'recorrência (2+ eleições)': 'pts_recorrencia', 'desvio real nas presidenciais': 'pts_desvio_real_pres', 'direção única': 'pts_direcao_unica', 'comportamento em 2026 T1': 'pts_comportamento_2026',
            'local inteiro atípico': 'pts_local_inteiro', 'volume de tardios/manuais': 'pts_volume', 'desvio só nas presidenciais': 'pts_so_presidenciais'}
    alta = L[L.nivel_risco == 'alta']
    vals = pd.Series({k: alta[v].mean() for k, v in comp.items()}).sort_values()
    bars = ax.barh(vals.index, vals.values, color=C1)
    for b in bars:
        ax.text(b.get_width() + .3, b.get_y() + b.get_height() / 2, n(b.get_width(), 1), va='center', fontsize=8.5, color=INK2)
    ax.set_xlabel('pontos médios por componente (locais de risco alto)')
    ax.set_title('De onde vêm os pontos dos locais de risco alto')
    figs.append((save(f, '07_composicao_pontos'), 'Média dos pontos de cada componente nos locais classificados como risco alto. Recorrência, desvio real de resultado e comportamento em 2026 pesam mais; '
                 '"desvio só nas presidenciais" e "local inteiro" são complementos.'))
    # 8 padrão prefeito × presidente
    f, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.8))
    pcn = H.padrao_comportamento.value_counts().sort_values()
    a1.barh(pcn.index, pcn.values, color=C1)
    for i, v in enumerate(pcn.values):
        a1.text(v, i, ' ' + n(v), va='center', fontsize=8.5, color=INK2)
    a1.set_xscale('log'); a1.set_xlim(right=pcn.max() * 6); a1.set_title('Onde aparece o comportamento (fila/manual)', loc='center'); a1.set_xlabel('seções (escala log)')
    pdv = H.padrao_desvio_resultado.value_counts().sort_values()
    a2.barh(pdv.index, pdv.values, color=C2)
    for i, v in enumerate(pdv.values):
        a2.text(v, i, ' ' + n(v), va='center', fontsize=8.5, color=INK2)
    a2.set_xscale('log'); a2.set_xlim(right=pdv.max() * 6); a2.set_title('Onde vota diferente das vizinhas', loc='center'); a2.set_xlabel('seções (escala log)')
    figs.append((save(f, '08_pres_x_pref'), 'À esquerda, o comportamento (fila/manual) aparece quase sempre só nas presidenciais, o que é esperado: as filas de 1º turno presidencial são maiores. À direita, o que importa: '
                 f'{n(int((H.padrao_desvio_resultado == "desvio real só em presidenciais").sum()))} seções votam diferente das vizinhas só nas presidenciais, contra {n(int((H.padrao_desvio_resultado == "desvio real só em municipais").sum()))} só nas municipais.'))
    # 9 recorrência
    f, ax = plt.subplots(figsize=(10, 4.2))
    rc = H.n_eleicoes_comportamento.value_counts().sort_index()
    bars = ax.bar([str(int(k)) for k in rc.index], rc.values, .6, color=C1)
    bar_labels(ax, bars)
    ax.set_yscale('log'); ax.set_xlabel('número de eleições (de 5) em que a seção mostrou comportamento'); ax.set_ylabel('seções (escala log)')
    ax.set_title('Recorrência: quantas vezes a mesma seção repete o comportamento')
    figs.append((save(f, '09_recorrencia'), 'A grande maioria aparece uma única vez. Seções que repetem em 3 ou mais eleições são poucas e pesam na pontuação: uma fila pode ser acaso; a mesma seção com fila em 2022, 2024 e 2026 não é.'))
    # 10 votos após 17h
    f, ax = plt.subplots(figsize=(10, 4.4))
    Rx = R.set_index('eid').reindex(['P2022', 'P2022b', 'M2024', 'M2024b', 'P2026'])
    xr = np.arange(len(Rx))
    b1 = ax.bar(xr - .2, Rx.late_votes_all, .38, color=C1, label='Todos os logs')
    b2 = ax.bar(xr + .2, Rx.late_votes_contingency, .38, color=C2, label='Em urnas de contingência/recarregadas')
    bar_labels(ax, b1); bar_labels(ax, b2)
    ax.set_xticks(xr); ax.set_xticklabels([LAB[e] for e in Rx.index]); ax.set_ylabel('votos computados após 17h'); ax.legend(loc='upper right')
    ax.set_title('Votos computados após as 17h, por eleição')
    figs.append((save(f, '10_votos_apos_17h'), 'Contagem direta nos logs das urnas: eventos "voto computado" com horário posterior às 17h no dia da eleição. Nos 1º turnos presidenciais são milhões; nos 2º turnos e nas municipais, muito menos. '
                 'Votar após as 17h é legal para quem já estava na fila; o número mede fila, não irregularidade.'))
    # 11 mapa: locais e seções a checar por UF
    f, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    Ux = U.set_index('uf').reindex([u for u in ORDER if u in U.uf.values])
    a1.bar(Ux.index, Ux.locais_alta, .6, color=SEQ['alta'], label='risco alto')
    a1.bar(Ux.index, Ux.locais_media, .6, bottom=Ux.locais_alta, color=SEQ['média'], label='risco médio')
    for i, (a, m) in enumerate(zip(Ux.locais_alta, Ux.locais_media)):
        a1.text(i, a + m, n(a + m), ha='center', va='bottom', fontsize=8.5, color=INK2)
    a1.set_title('Locais no mapa de fiscalização 2026 T2'); a1.set_ylabel('locais'); a1.legend(loc='upper right')
    bars = a2.bar(Ux.index, Ux.secoes_a_checar, .6, color=C1)
    bar_labels(a2, bars)
    a2.set_title('Seções a checar'); a2.set_ylabel('seções')
    figs.append((save(f, '11_mapa_uf'), f'O mapa cobre {n(int(Ux.locais.sum()))} locais e {n(int(Ux.secoes_a_checar.sum()))} seções nos 10 estados; a sugestão é de {n(int(Ux.fiscais_sugeridos.sum()))} fiscais (1 por local alto e 1 a cada 2 médios).'))
    # 12 cidades
    f, ax = plt.subplots(figsize=(10, 5))
    cid = D['CID'].sort_values(['locais_risco_alta', 'pontos_max'], ascending=False).head(15).iloc[::-1]
    lab = [f'{r.municipality_name.title()} ({r.uf})' for r in cid.itertuples()]
    ax.barh(lab, cid.locais_risco_alta, color=SEQ['alta'], label='risco alto', edgecolor='white', linewidth=1)
    ax.barh(lab, cid.locais_risco_media, left=cid.locais_risco_alta, color=SEQ['média'], label='risco médio', edgecolor='white', linewidth=1)
    for i, (a, m) in enumerate(zip(cid.locais_risco_alta, cid.locais_risco_media)):
        ax.text(a + m, i, ' ' + n(a) + ' alto', va='center', fontsize=8.5, color=INK2)
    ax.set_xlabel('locais de votação'); ax.legend(loc='lower right')
    ax.set_title('Cidades com mais locais de risco alto')
    figs.append((save(f, '12_cidades'), 'Cidades grandes aparecem porque têm mais locais; o que importa para alocar fiscais é a lista por zona e local dentro de cada cidade, no mapa de fiscalização.'))
    return figs


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


# ----------------------------------------------------------------------------- PDF: gráficos
def pdf_graficos(figs, D):
    P, H1, H2, SM = M.P, M.H1, M.H2, M.SM
    st = [Paragraph('Varredura de fiscalização — caderno de gráficos', H1),
          Paragraph('Um gráfico por página, com uma frase de como ler. Os números vêm dos arquivos da varredura em relatorios/fiscalizacao/ e são regenerados pelo script. '
                    'Lado A = PT (presidente) ou líder do município (prefeito); lado B = PL ou 2º colocado. Sinalização não é acusação.', P), Spacer(1, 6)]
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
    R, T, V, L, H, U = D['R'], D['T'], D['V'], D['L'], D['H'], D['U']
    Rx = R.set_index('eid')
    Vx = V.set_index('eid')
    st = [Paragraph('Varredura de fiscalização por local de votação — método, dados e resultados', H1),
          Paragraph(f'Documento técnico para avaliação. Gerado automaticamente dos resultados atuais em {pd.Timestamp.today():%d/%m/%Y}; código no commit {D["head"]}.', SM),
          Paragraph('<b>Pergunta.</b> Existem locais de votação onde seções com (a) votação depois do horário e/ou (b) habilitação manual de eleitores pelo mesário acima do esperado '
                    'apresentam resultado diferente do das seções vizinhas do mesmo prédio, de forma recorrente entre eleições, e com padrão distinto entre eleições de prefeito e de presidente? '
                    'O objetivo é priorizar fiscalização presencial. Os dados não observam compra de voto, coação ou intenção; observam horários, habilitações, encerramento e votos por seção.', P),
          Paragraph('Sinalização não é acusação. Toda diferença medida aqui pode ter explicação legítima (fila, falha de biometria, perfil do eleitorado da rua atendida pela seção).', NOTE),
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
    st += [M.table(t, [4.2 * cm, 7.3 * cm, 6.5 * cm], font=7),
           Paragraph('Recortes: 10 estados de maior eleitorado (BA, SP, MG, RJ, PR, RS, PE, CE, PA, SC). Eleições com logs de urna disponíveis e processados: presidente 2022 (1º e 2º turnos) e 2026 (1º turno); prefeito 2024 (1º e 2º turnos). '
                     'Eleições anteriores (2012–2020) foram capturadas em boletins e correspondências para estudos de persistência, mas não entram nesta varredura por não terem logs processados.', P),
           Paragraph('1.1 Cobertura observada', H3)]
    t = [['Eleição', 'Dia', 'Seções (BU)', 'Com log', 'Log completo', 'Contingência / recarregadas', 'Votos após 17h (todos os logs)', '… em contingência', 'Votos com sequência manual', 'Manuais após 17h']]
    for eid in ['P2022', 'P2022b', 'M2024', 'M2024b', 'P2026']:
        r = Rx.loc[eid]
        t.append([LAB[eid], DAYS[eid], n(r.sections), n(r.with_log), n(r.log_complete), n(r.contingency_logs), n(r.late_votes_all), n(r.late_votes_contingency), n(r.manual_votes), n(r.manual_late)])
    st += [M.table(t, font=6.8),
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
    st += [M.table(t, [2.6 * cm, 15.4 * cm], font=7.2),
           Paragraph('<b>Habilitação manual esperada.</b> Para cada estado e eleição, regressão linear (mínimos quadrados) da fração de votos com sequência manual sobre: % de eleitores com biometria cadastrada, % com 60 anos ou mais e % de baixa escolaridade da seção '
                     '(perfil 2022), estimada nas seções com log completo (mínimo de 200 seções). O resíduo (observado − esperado) é o que se compara ao P99. Isso separa “muita habilitação manual porque o eleitorado é idoso ou sem biometria” de '
                     '“muita habilitação manual para o eleitorado que tem”.', P),
           Paragraph('<b>Comportamento da seção</b> (usado na varredura): TARDIO = late ou last19 ou close; MANUAL = manual ou manual_late. Comportamento = TARDIO ou MANUAL. '
                     'Os demais indicadores (fast, turnout, cancel) entram no score do estudo de inconsistências e nos testes de favorecimento, mas não na definição de comportamento da varredura.', P),
           Paragraph('4. Comparação com as seções vizinhas e “diferença real”', H2),
           Paragraph('Para cada seção com comportamento, os <b>pares</b> são as outras seções do mesmo local de votação (mesmo município, zona e código de local) que não têm comportamento na mesma eleição. '
                     'Mede-se a diferença, em pontos percentuais, entre a fração de votos válidos do lado A na seção e a média ponderada dessa fração nos pares. '
                     'Lado A = PT nas presidenciais; nas eleições de prefeito, o candidato líder do município (lado B = PL ou o 2º colocado).', P),
           Paragraph('<b>z</b> = diferença ÷ √(variância da fração do lado A entre os pares + erro binomial da própria seção, 100²·p(1−p)/votos válidos). '
                     'Com menos de 3 pares no local, a variância usada é a das seções comuns do município; sem nenhum par no local, a comparação é com as seções comuns do município (nível “município”). '
                     '<b>Diferença real</b> = |diferença| ≥ 5 p.p. e |z| ≥ 2. <b>Diferença alta</b> = |diferença| ≥ 10 p.p. (descritiva).', P),
           Paragraph('<b>Taxa-base.</b> O mesmo teste é aplicado a cada seção comum contra as demais seções comuns do seu local, deixando-a de fora (leave-one-out). A fração de seções comuns que passa no teste é o que se espera por acaso e por heterogeneidade normal '
                     'entre seções do mesmo prédio. Ela é publicada ao lado da fração das seções com comportamento, por eleição.', P),
           Paragraph('Também se calcula a diferença de comparecimento frente aos pares (p.p.) e, quando metade ou mais das seções do local têm comportamento (“local inteiro”), a diferença do local inteiro frente às seções comuns do município.', P),
           Paragraph('5. Teste de favorecimento por permutação', H2),
           Paragraph('Pergunta: as seções sinalizadas por um indicador votam, em média, mais para um lado do que as demais seções do mesmo local? Estatística: diferença (A − B) na seção menos a média do seu local, '
                     'ponderada por votos válidos, entre sinalizadas e não sinalizadas. Distribuição nula: a sinalização é embaralhada 500 vezes entre as seções do mesmo município (semente 20261016); p = fração de embaralhamentos com diferença '
                     'igual ou maior em módulo (bilateral); q = correção de Benjamini–Hochberg sobre todos os testes. Resultados completos em relatorios/fiscalizacao/testes_permutacao.csv; resumo:', P)]
    t = [['Eleição', 'Indicador', 'Seções sinalizadas', 'Lado A % (sinalizadas)', 'Lado A % (demais)', 'Dif. dentro do local (p.p.)', 'DP do acaso', 'p', 'q']]
    for eid in ['P2022', 'P2026', 'M2024']:
        for r in T[(T.eid == eid) & T.flag.isin(['f_late', 'f_manual', 'f_manual_late', 'f_last19', 'f_close', 'score2'])].itertuples():
            t.append([LAB[eid], r.flag.replace('f_', ''), n(r.n_flag), n(r.share_a_flag, 1), n(r.share_a_rest, 1), n(r.within_place_diff, 2), n(r.null_sd, 2), n(r.p_perm, 3), n(r.q, 3)])
    st += [M.table(t, font=6.8), PageBreak(),
           Paragraph('6. Cruzamento prefeito × presidente por seção', H2),
           Paragraph('Para cada seção presente em mais de uma eleição, registra-se em que tipo de eleição aparece o comportamento (só presidenciais, só municipais, ambos) e em que tipo aparece a diferença real de resultado. '
                     '“Só presidenciais” exige que a seção exista nos dados de prefeito 2024 (senão é marcada “sem dado municipal”). Como a votação tardia é estruturalmente muito mais frequente nos 1º turnos presidenciais, '
                     'o padrão de <i>comportamento</i> “só presidenciais” domina e não pontua sozinho; pontua apenas o <i>desvio real de resultado</i> restrito às presidenciais, em 2 ou mais seções do local.', P),
           Paragraph('7. Pontuação do local e níveis de risco', H2),
           Paragraph('A pontuação é uma soma transparente, pensada para ser lida e discutida, não um modelo ajustado. Componentes e máximos:', P)]
    t = [['Componente', 'Regra', 'Máx.'],
         ['Recorrência', '3 pontos por seção com comportamento em 2+ eleições (até 5) + 2 por seção em 3+ eleições (até 3)', '21'],
         ['Desvio real nas presidenciais', '5 pontos por seção com comportamento e diferença real em alguma presidencial (até 5)', '25'],
         ['Direção única', '8 pontos se há 2+ diferenças reais no local e todas para o mesmo lado', '8'],
         ['Comportamento em 2026 T1', '3 por seção com comportamento em 2026 T1 (até 4) + 3 por seção com diferença real em 2026 T1 (até 3)', '21'],
         ['Local inteiro atípico', '8 se ≥50% das seções têm comportamento em 2026 T1 e o local difere do município com |z| ≥ 2; 4 se só a primeira condição', '8'],
         ['Volume', 'votos após 17h no local: ≥100 → 3, ≥500 → 6; habilitações manuais após 17h: ≥20 → 3, ≥50 → 6', '12'],
         ['Desvio só nas presidenciais', '5 se 2+ seções do local têm diferença real só nas presidenciais', '5']]
    st += [M.table(t, [4 * cm, 12.6 * cm, 1.4 * cm], font=7.2),
           Paragraph('Níveis: <b>alto</b> ≥ 45 pontos; <b>médio</b> 25–44; <b>baixo</b> < 25. Prioridade para o 2º turno de 2026: locais com seções presentes em 2026 e comportamento em 2026 T1 ou recorrente, ordenados por pontos. '
                     'No mapa de fiscalização entram os níveis alto e médio; “seções a checar” são as seções do local com comportamento em 2026 T1 ou recorrentes (2+ eleições) existentes em 2026; '
                     'fiscais sugeridos = 1 por local alto + 1 a cada 2 locais médios (ponto de partida para alocação).', P),
           Paragraph('8. Resultados principais', H2)]
    t = [['Eleição', 'Seções', 'Com comportamento', 'Tardia', 'Manual', 'Dif. real', '% (com comp.)', '% (comuns)', 'Favor A / B', 'Comuns A / B', 'Dif. média p.p.', 'Comparec. dif. p.p.', 'Locais inteiros']]
    for eid in ['P2022', 'P2022b', 'M2024', 'M2024b', 'P2026']:
        r = Vx.loc[eid]
        t.append([LAB[eid], n(r.secoes), n(r.com_comportamento), n(r.tardia), n(r.manual), n(r.dif_real_com_comportamento), n(r.pct_real_com_comportamento, 1), n(r.pct_real_secoes_comuns, 1),
                  f'{n(r.dif_real_favor_A)} / {n(r.dif_real_favor_B)}', f'{n(r.comuns_real_favor_A)} / {n(r.comuns_real_favor_B)}', n(r.dif_media_pp, 2), n(r.comparecimento_dif_media_pp, 2), n(r.locais_inteiros)])
    st += [M.table(t, font=6.4), Spacer(1, 4)]
    lv = L.nivel_risco.value_counts()
    pr = D['PR'].nivel_risco.value_counts()
    dirs = L.direcao.value_counts()
    pa26 = 100 * Vx.loc['P2026', 'dif_real_favor_A'] / (Vx.loc['P2026', 'dif_real_favor_A'] + Vx.loc['P2026', 'dif_real_favor_B'])
    pc26 = 100 * Vx.loc['P2026', 'comuns_real_favor_A'] / (Vx.loc['P2026', 'comuns_real_favor_A'] + Vx.loc['P2026', 'comuns_real_favor_B'])
    for s in [f'Seções com comportamento têm diferença real frente às vizinhas em {n(Vx.pct_real_com_comportamento.min(), 1)}% a {n(Vx.pct_real_com_comportamento.max(), 1)}% dos casos, contra '
              f'{n(Vx.pct_real_secoes_comuns.min(), 1)}% a {n(Vx.pct_real_secoes_comuns.max(), 1)}% nas seções comuns: o comportamento, isoladamente, está pouco associado a resultado diferente.',
              f'Nas presidenciais, as diferenças reais das seções com comportamento pendem para o lado A (PT) mais do que as das seções comuns: em 2026 T1, {n(pa26, 0)}% contra {n(pc26, 0)}%. Nas eleições de prefeito não há assimetria.',
              f'Locais com ao menos uma seção com comportamento: {n(len(L))}; risco alto {n(lv.get("alta", 0))}, médio {n(lv.get("média", 0))}, baixo {n(lv.get("baixa", 0))}. Entre os locais com alguma diferença real, direção única para A em {n(dirs.get("sempre A", 0))}, para B em {n(dirs.get("sempre B", 0))}, mista em {n(dirs.get("mista", 0))}.',
              f'Prioridade 2026 T2: {n(len(D["PR"]))} locais, {n(pr.get("alta", 0))} de risco alto e {n(pr.get("média", 0))} médio. Mapa de fiscalização: {n(int(U.locais.sum()))} locais, {n(int(U.secoes_a_checar.sum()))} seções a checar, {n(int(U.fiscais_sugeridos.sum()))} fiscais sugeridos.',
              f'Seções com comportamento só nas presidenciais (existindo nos dados de prefeito): {n(int((H.padrao_comportamento == "só presidenciais").sum()))}; com desvio real de resultado só nas presidenciais: {n(int((H.padrao_desvio_resultado == "desvio real só em presidenciais").sum()))}; só nas municipais: {n(int((H.padrao_desvio_resultado == "desvio real só em municipais").sum()))}.']:
        st.append(Paragraph('• ' + s, P))
    st += [Paragraph('9. Limitações e o que não se pode concluir', H2)]
    for s in ['Os dados não observam compra de voto, coação, transporte de eleitores ou intenção. Observam horários, habilitações, encerramento e votos por seção.',
              'Votar após as 17h é legal para quem estava na fila; habilitação manual é o procedimento previsto quando a biometria falha ou o eleitor não a tem cadastrada. Ambos medem fila e falha, não irregularidade.',
              'A diferença frente às vizinhas reflete também composição do eleitorado: seções do mesmo prédio atendem ruas e perfis distintos. O teste z e a taxa-base reduzem, mas não eliminam, esse fator.',
              'Horários são do relógio de cada urna, não certificados. Reversões são contadas; desvios constantes de relógio não são detectáveis.',
              'O perfil do eleitorado é de 2022 e é usado para todas as eleições; seções criadas ou alteradas depois ficam sem controle de perfil.',
              'Locais de seção única são comparados ao município, referência mais fraca. 2º turnos (2022 e prefeito 2024) têm poucas seções com comportamento e baixo poder estatístico.',
              'A pontuação é uma regra transparente escolhida pelos autores, não um modelo validado contra casos confirmados. Mudanças de pesos mudam a lista; qualquer mudança deve ser registrada.',
              'A associação direcional nas presidenciais é compatível com várias explicações (perfil de quem enfrenta fila; locais de maior densidade; operação irregular). Os dados não distinguem entre elas. Por isso o produto é uma lista para olhar presencialmente, não uma conclusão.']:
        st.append(Paragraph('• ' + s, P))
    st += [Paragraph('10. Reprodutibilidade', H2),
           Paragraph('Ambientes: Python 3.12; pacote auditabr 0.2.0 (requirements.lock) para aquisição e leitura de logs; .venv-report (requirements-report.lock) para análises e PDFs. Sequência de scripts, todos em scripts/:', P)]
    t = [['Etapa', 'Script', 'Saída'],
         ['Catálogo CKAN e aquisição de BU/logs por UF', 'uf_pipeline.py, mun_logs_pipeline.py, bu_capture_all.py', 'research/estados/<UF>/…, research/municipais/<UF>/…, research/bu/'],
         ['Correspondências de urnas e perfil do eleitorado', 'ceft_capture.py, profile_capture.py', 'research/ceft/, research/perfil/2022/'],
         ['Leitura dos logs (máquina de estados)', 'analyze_pilot_operations.py (motor), process_bahia_document_logs.py, extract_contingency_logs.py, reidentify_logs.py', 'operations.jsonl por eleição/UF'],
         ['Análise por seção e cargo', 'analyze_office.py, reanalyze_with_logs.py', 'sections.parquet, candidate_sections.parquet, summary.json'],
         ['Indicadores, testes de permutação, ferramenta', 'make_fiscalizacao_study.py', 'relatorios/fiscalizacao/ (secoes_indicadores_*.parquet, testes_permutacao.csv, PDF)'],
         ['Varredura por local', 'make_varredura_locais.py', 'relatorios/fiscalizacao/varredura/ (locais_risco.csv, VARREDURA_LOCAIS.xlsx, PDF)'],
         ['Mapa de fiscalização 2026 T2', 'make_mapa_fiscalizacao_2026t2.py', 'relatorios/fiscalizacao/mapa_2026_T2/ (XLSX e PDF por UF)'],
         ['Estes documentos', 'make_documentos_metodo.py', 'relatorios/fiscalizacao/documentos/']]
    st += [M.table(t, [4.6 * cm, 7 * cm, 6.4 * cm], font=7),
           Paragraph('Parâmetros fixos: elegibilidade ≥ 50 aptos; P99 por estado; diferença real ≥ 5 p.p. e |z| ≥ 2; pares mínimos 3; permutação 500 réplicas, semente 20261016; cortes de risco 25 e 45 pontos. '
                     'Cada captura tem recibo com URL, SHA-256 e data; cada saída tem data de geração. O repositório git do projeto registra o código; os dados brutos ficam fora do versionamento por tamanho.', P),
           Paragraph('11. Glossário', H2)]
    t = [['Termo', 'Significado'],
         ['Seção', 'Menor unidade de votação (uma urna); identificada por município, zona e número.'], ['Local de votação', 'Prédio (escola etc.) que reúne várias seções; identificado por município, zona e código do local.'],
         ['Zona eleitoral', 'Divisão administrativa que agrupa seções; pode abranger vários municípios ou parte de um.'], ['BU / boletim de urna', 'Resultado oficial impresso e transmitido por cada urna ao fim da votação.'],
         ['Log de urna', 'Arquivo com os eventos registrados pela urna, com horário.'], ['Habilitação manual', 'Liberação do eleitor pelo mesário sem reconhecimento biométrico, com registro da digital do mesário.'],
         ['Lado A / lado B', 'PT / PL nas presidenciais; líder / 2º colocado do município nas eleições de prefeito.'], ['p.p.', 'Pontos percentuais (diferença entre duas porcentagens).'],
         ['P99', 'Valor acima do qual está apenas 1% das seções do estado.'], ['z', 'Quantos desvios-padrão a diferença da seção está da variação normal entre seções do local.'],
         ['Permutação', 'Teste que embaralha os rótulos muitas vezes para ver o que aconteceria por acaso.'], ['q (BH)', 'p corrigido para muitos testes simultâneos (Benjamini–Hochberg).'],
         ['Contingência', 'Urna substituta usada quando a original falha.'], ['CEFT', 'Correspondência entre a urna prevista e a efetivamente usada em cada seção.']]
    st += [M.table(t, [3.4 * cm, 14.6 * cm], font=7.2)]

    def foot(c, d_):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Método e dados — varredura de fiscalização — sinalização não é acusação'); c.drawRightString(19 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'METODO_E_DADOS.pdf'), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.6 * cm, bottomMargin=1.8 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


# ----------------------------------------------------------------------------- PDF: resumo simples
def pdf_resumo(D, figs):
    V, L, U, H = D['V'], D['L'], D['U'], D['H']
    Vx = V.set_index('eid')
    T1 = ParagraphStyle('T1', parent=M.H1, fontSize=20, leading=24, spaceAfter=10)
    Hh = ParagraphStyle('Hh', parent=M.H2, fontSize=14, leading=17, spaceBefore=12, spaceAfter=4)
    Pp = ParagraphStyle('Pp', parent=M.P, fontSize=11.5, leading=16)
    Bb = ParagraphStyle('Bb', parent=Pp, leftIndent=14, bulletIndent=2, spaceAfter=3)
    Nn = ParagraphStyle('Nn', parent=M.NOTE, fontSize=11, leading=15)
    p26 = Vx.loc['P2026']
    pa26 = 100 * p26.dif_real_favor_A / (p26.dif_real_favor_A + p26.dif_real_favor_B)
    pc26 = 100 * p26.comuns_real_favor_A / (p26.comuns_real_favor_A + p26.comuns_real_favor_B)
    m24 = Vx.loc['M2024']
    pa24 = 100 * m24.dif_real_favor_A / (m24.dif_real_favor_A + m24.dif_real_favor_B)
    lv = L.nivel_risco.value_counts()
    st = [Paragraph('O que é esta varredura, em palavras simples', T1),
          Paragraph('Um levantamento feito com dados públicos do TSE para indicar <b>em quais escolas e prédios de votação vale a pena ter um fiscal atento</b> no 2º turno de 2026 e nas próximas eleições. '
                    'Ele não acusa ninguém. Ele aponta onde olhar.', Pp),
          Paragraph('O que olhamos', Hh),
          Paragraph('Em cada seção (cada urna) de 10 estados, nas eleições de 2022, 2024 e 2026, procuramos três coisas:', Pp),
          Paragraph('<b>1. Fila depois da hora.</b> A votação termina às 17h. Quem já está na fila pode votar depois. Procuramos seções onde muita gente votou depois das 17h, onde o último voto saiu depois das 19h, ou onde a urna só foi encerrada mais de uma hora depois, sem ter sido trocada.', Bb, bulletText='•'),
          Paragraph('<b>2. Liberação manual pelo mesário.</b> Quando a biometria falha ou o eleitor não tem digital cadastrada, o mesário libera o eleitor “na mão”. Isso é normal. O que procuramos é a seção onde isso aconteceu <i>muito mais</i> do que o esperado para o tipo de eleitor que ela tem (idosos, pessoas sem biometria).', Bb, bulletText='•'),
          Paragraph('<b>3. Voto diferente dos vizinhos.</b> Comparamos o resultado dessa seção com o das outras seções <i>do mesmo prédio</i>, que atendem a mesma vizinhança. Se a diferença é grande demais para ser normal entre salas do mesmo prédio, chamamos de “diferença real”.', Bb, bulletText='•'),
          Paragraph('Depois juntamos tudo por prédio: quantas seções têm esses sinais, se repetem eleição após eleição, se o resultado delas pende sempre para o mesmo lado, e se isso acontece só na eleição de presidente ou também na de prefeito. '
                    'Cada prédio recebe uma nota de 0 a 100 e um nível: risco alto, médio ou baixo.', Pp),
          Paragraph('O que encontramos', Hh),
          Paragraph(f'<b>Fila é comum.</b> No 1º turno de 2026, {n(p26.com_comportamento)} seções mostraram fila tardia ou liberação manual acima do normal. A maioria é só fila.', Bb, bulletText='•'),
          Paragraph(f'<b>Fila, sozinha, quase não muda o resultado.</b> Entre as seções com esses sinais, {n(p26.pct_real_com_comportamento, 1)}% votaram de forma realmente diferente das vizinhas. Entre as seções comuns, {n(p26.pct_real_secoes_comuns, 1)}%. A diferença é pequena.', Bb, bulletText='•'),
          Paragraph(f'<b>Mas, quando muda, pende para um lado na eleição presidencial.</b> Nas seções com sinais que votaram diferente das vizinhas em 2026, {n(pa26, 0)}% penderam para o PT; nas seções comuns que também diferiram, {n(pc26, 0)}%. '
                    f'Na eleição de prefeito de 2024 não há lado: {n(pa24, 0)}% para o candidato líder, ou seja, metade.', Bb, bulletText='•'),
          Paragraph(f'<b>Poucos prédios concentram os sinais.</b> De {n(len(L))} prédios com ao menos uma seção sinalizada, {n(lv.get("alta", 0))} são de risco alto e {n(lv.get("média", 0))} de risco médio. Bahia e Pernambuco têm a maior parte dos de risco alto.', Bb, bulletText='•'),
          Paragraph('O que isso significa e o que não significa', Hh),
          Paragraph('Não significa que houve fraude ou compra de votos nesses lugares. Fila pode ser só fila; liberação manual pode ser só biometria que falhou; um resultado diferente pode ser porque aquela sala atende uma rua diferente. '
                    'Os dados não enxergam intenção nem dinheiro. O que eles mostram é que <b>alguns prédios combinam, repetidamente, fila tardia, liberação manual acima do normal e resultado fora do padrão do próprio prédio</b>. '
                    'Isso é motivo suficiente para alguém estar lá, olhando e anotando.', Nn),
          Paragraph('Como usar amanhã (25/10/2026)', Hh),
          Paragraph(f'Há um mapa por estado, com {n(int(U.locais.sum()))} prédios e {n(int(U.secoes_a_checar.sum()))} seções a checar, e uma planilha com uma linha por seção para o fiscal preencher. Em cada seção indicada, o fiscal observa e anota, com horário:', Pp),
          Paragraph('se havia fila às 17h e de que tamanho;', Bb, bulletText='•'), Paragraph('quantos eleitores foram liberados manualmente pelo mesário e por quê;', Bb, bulletText='•'),
          Paragraph('a hora do último voto e a hora em que a urna foi encerrada;', Bb, bulletText='•'), Paragraph('se a urna foi trocada ou houve contingência;', Bb, bulletText='•'),
          Paragraph('quem está coordenando o prédio, quando o prédio inteiro tem o mesmo padrão.', Bb, bulletText='•'),
          Paragraph('Prioridade: prédios de risco alto primeiro. A sugestão é um fiscal por prédio de risco alto e um para cada dois de risco médio.', Pp),
          Paragraph('Onde estão os arquivos', Hh),
          Paragraph('Pasta relatorios/fiscalizacao/: <b>mapa_2026_T2/</b> (mapa e checklist por estado, PDF e Excel), <b>varredura/</b> (lista completa de prédios com a nota e os motivos), '
                    '<b>documentos/</b> (este resumo, o caderno de gráficos e o documento técnico com método e dados para quem quiser conferir).', Pp)]
    # dois gráficos de apoio
    st += [PageBreak(), Paragraph('Dois gráficos para entender', Hh), img(figs[1][0], 17), Paragraph('Seções com fila ou liberação manual quase não votam diferente das vizinhas: a barra escura é só um pouco maior que a clara.', Pp),
           Spacer(1, 8), img(figs[2][0], 17), Paragraph('Quando votam diferente, nas eleições de presidente pendem para um lado mais do que as seções comuns; nas de prefeito, não.', Pp)]

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
    print('ok', len(figs), 'graficos;', D['head'])


if __name__ == '__main__':
    main()
