"""Relatorio JANELAS_HORARIO.pdf/.xlsx: gatilho por janela de horario (de uma hora ate outra) e por volume, todas as urnas;
alem da reta, curvatura, dispersao (mistura) e agrupamentos (UF, zona, municipio).
Le os CSVs de relatorios/verificacoes/janelas_horario (scripts/janelas_horario.py); as partes cujos CSVs ainda nao existem sao puladas."""
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from make_bahia_reports import H1, H2, P, SM, fig_img, n, table  # noqa: E402
from make_padroes_report import TINTA, TINTA2, _eixos, sn  # noqa: E402

D = ROOT / 'relatorios' / 'verificacoes' / 'janelas_horario'
FIG = D / 'figuras'
CSV = dict(sep=';', encoding='utf-8-sig', decimal=',')
AZUL, LARANJA, CINZA, CLARO = '#2a78d6', '#eb6834', '#9a9993', '#f1f0ec'
DIVERGENTE = LinearSegmentedColormap.from_list('t', [LARANJA, CLARO, AZUL])
NOME = {2022: 'Lula × Bolsonaro (2022)', 2026: 'Lula × Flávio (2026)'}
COR = {2022: CINZA, 2026: AZUL}
REGRA = {'2_para_1': '2 para 1', 'inversao': 'inversão'}
TIPO = {'deslocamento': 'deslocamento (2 para 1)', 'inversao': 'inversão'}
NIVEIS = ['UF', 'zona', 'município']
CTL_PRINCIPAL = '+ comparecimento suave'   # conjunto de controles mostrado no relatório (os outros ficam nos CSVs)


def r(nome):
    p = D / nome
    return pd.read_csv(p, **CSV) if p.exists() else None


def anos_de(prefixo):
    return [a for a in (2026, 2022) if (D / f'{prefixo}_{a}.csv').exists()]


def junta(prefixo):
    anos = anos_de(prefixo)
    return pd.concat([r(f'{prefixo}_{a}.csv') for a in anos], ignore_index=True) if anos else None


def _min(hhmm):
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def _estilo(ax):
    ax.tick_params(colors=TINTA2, labelsize=7)
    for s in ax.spines.values():
        s.set_color('#b9b8b3')


def fig_janelas(J):
    """Mapa início × fim da estatística t, por ano e tipo de regra (janelas inválidas em branco)."""
    FIG.mkdir(parents=True, exist_ok=True)
    anos = sorted(J.ano.unique())
    tipos = ['deslocamento', 'inversao']
    fig, axs = plt.subplots(len(anos), len(tipos), figsize=(5.2 * len(tipos), 4.6 * len(anos)), dpi=150, squeeze=False)
    lim = float(J.limite_bonferroni.iloc[0])
    vmax = max(lim + 1, float(J.t.abs().max()))
    for i, tipo in enumerate(tipos):
        for j, ano in enumerate(anos):
            ax = axs[j, i]
            g = J[(J.ano == ano) & (J.tipo == tipo)]
            grade = sorted({_min(x) for x in g.inicio} | {_min(x) for x in g.fim})
            pos = {m: k for k, m in enumerate(grade)}
            M = np.full((len(grade), len(grade)), np.nan)
            for y in g.itertuples():
                M[pos[_min(y.fim)], pos[_min(y.inicio)]] = y.t
            im = ax.imshow(M, origin='lower', cmap=DIVERGENTE, norm=TwoSlopeNorm(0, -vmax, vmax), aspect='equal')
            ticks = [k for k, m in enumerate(grade) if m % 120 == 0]
            ax.set_xticks(ticks)
            ax.set_xticklabels([f'{grade[k] // 60}h' for k in ticks], fontsize=7)
            ax.set_yticks(ticks)
            ax.set_yticklabels([f'{grade[k] // 60}h' for k in ticks], fontsize=7)
            ax.set_title(f'{NOME[ano]} · {TIPO[tipo]}', fontsize=8.5, color=TINTA)
            ax.set_xlabel('início da janela (hora local da urna)', fontsize=7.5, color=TINTA2)
            ax.set_ylabel('fim da janela', fontsize=7.5, color=TINTA2)
            _estilo(ax)
            k = g.t.abs().idxmax()
            ax.plot(pos[_min(g.inicio[k])], pos[_min(g.fim[k])], 'o', ms=9, mfc='none', mec=TINTA, mew=1)
            ax.text(.02, .97, f'máx |t| = {n(abs(g.t[k]), 1)} ({g.inicio[k]}–{g.fim[k]})\nlimite ±{n(lim, 1)}', transform=ax.transAxes,
                    fontsize=7, va='top', color=TINTA)
    cb = fig.colorbar(im, ax=axs, shrink=.6, pad=.02)
    cb.set_label('estatística t (+ = seção anda para Lula com a exposição; − = para o adversário)', fontsize=7.5, color=TINTA2)
    cb.ax.tick_params(labelsize=7, colors=TINTA2)
    p = FIG / 'janelas_t.png'
    fig.savefig(p, bbox_inches='tight')
    plt.close(fig)
    return p


def fig_perfis(L, Pf):
    """Resposta por decil de exposição na janela de maior |t| (reta) de cada ano e tipo, com a reta ajustada."""
    FIG.mkdir(parents=True, exist_ok=True)
    anos = sorted(L.ano.unique())
    tipos = ['deslocamento', 'inversao']
    fig, axs = plt.subplots(len(anos), len(tipos), figsize=(5 * len(tipos), 3.4 * len(anos)), dpi=150, squeeze=False)
    for i, tipo in enumerate(tipos):
        for j, ano in enumerate(anos):
            ax = axs[j, i]
            g = L[(L.ano == ano) & (L.tipo == tipo)]
            k = g.t_linear.abs().idxmax()
            pf = Pf[(Pf.ano == ano) & (Pf.tipo == tipo) & (Pf.inicio == g.inicio[k]) & (Pf.fim == g.fim[k])].sort_values('decil')
            x = pf.exposicao_residual_media.to_numpy() * 100
            ax.axhline(0, color='#b9b8b3', lw=.8)
            ax.plot(x, pf.beta_linear_pp.iloc[0] * x / 100, '-', color=CINZA, lw=1.2, label='reta ajustada')
            ax.plot(x, pf.residuo_medio_pp, 'o', ms=4.5, color=COR[ano], label='resíduo médio do decil')
            for d, xx, yy in zip(pf.decil, x, pf.residuo_medio_pp):
                ax.annotate(str(d), (xx, yy), textcoords='offset points', xytext=(0, 5), fontsize=6, color=TINTA2, ha='center')
            _eixos(ax, 'exposição residual média do decil (pontos de %, relativa ao prédio e aos controles)', 'resíduo médio (pontos)')
            ax.set_title(f'{NOME[ano]} · {TIPO[tipo]} · janela {g.inicio[k]}–{g.fim[k]}\nreta t = {n(g.t_linear[k], 1)} · curvatura (além da reta) t equiv. = {n(g.t_curvatura[k], 1)}',
                         fontsize=8, color=TINTA)
            if i == 0 and j == 0:
                ax.legend(fontsize=7, frameon=False, labelcolor=TINTA)
    fig.tight_layout()
    p = FIG / 'perfis_decis.png'
    fig.savefig(p)
    plt.close(fig)
    return p


def fig_chegada(Hs):
    FIG.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
    for ano, g in Hs.groupby('ano'):
        g = g.sort_values('D_de')
        ax.step(g.D_de, g.secoes / g.secoes.sum(), where='post', color=COR[ano], lw=1.4, label=NOME[ano])
    ax.axvline(1, color='#b9b8b3', lw=.8)
    ax.set_yscale('log')
    _eixos(ax, 'índice de dispersão D das contagens de 15 min da seção em torno da curva do prédio (Poisson = 1)', 'fração das seções (log)')
    ax.legend(fontsize=7, frameon=False, labelcolor=TINTA)
    fig.tight_layout()
    p = FIG / 'chegada_D.png'
    fig.savefig(p)
    plt.close(fig)
    return p


def fig_volume(V, C):
    FIG.mkdir(parents=True, exist_ok=True)
    V = V[V.controles == CTL_PRINCIPAL]
    fam = list(dict.fromkeys(V.regra))
    fig, axs = plt.subplots(2, len(fam) + 1, figsize=(4.2 * (len(fam) + 1), 6.4), dpi=150)
    lim = float(V.limite_bonferroni.iloc[0])
    for i, tipo in enumerate(('deslocamento', 'inversao')):
        for j, regra in enumerate(fam):
            ax = axs[i, j]
            ax.axhspan(-lim, lim, color=CLARO, zorder=0)
            for ano in (2022, 2026):
                g = V[(V.tipo == tipo) & (V.regra == regra) & (V.ano == ano)].sort_values('parametro')
                ax.plot(g.parametro, g.t, '-o', ms=3.5, lw=1.4, color=COR[ano], label=NOME[ano])
            ax.axhline(0, color='#b9b8b3', lw=.8)
            _eixos(ax, {'a partir do voto N': 'N (voto a partir do qual a regra vale)', 'a partir de p% dos aptos': 'p (% dos aptos)',
                        'só os últimos k votos': 'k (últimos votos)'}[regra], 't' if j == 0 else '')
            ax.set_title(f'{regra} · {TIPO[tipo]}', fontsize=8.5, color=TINTA)
            if i == 0 and j == 0:
                ax.legend(fontsize=7, frameon=False, labelcolor=TINTA)
        ax = axs[i, len(fam)]
        if i == 0:
            for ano in (2022, 2026):
                g = C[C.ano == ano]
                x = np.arange(len(g))
                ax.errorbar(x + (.15 if ano == 2026 else -.15), g.residuo_medio_pp, yerr=1.96 * g.ep_pp, fmt='o', ms=4, color=COR[ano], lw=1, label=NOME[ano])
            ax.axhline(0, color='#b9b8b3', lw=.8)
            ax.set_xticks(np.arange(len(g)))
            ax.set_xticklabels([str(s).replace('(', '').replace(']', '').replace(', ', ' a ') for s in g.comparecimento_menos_predio], rotation=60, fontsize=6.5)
            _eixos(ax, 'comparecimento da seção menos o do prédio (fração)', 'resíduo médio (pontos)')
            ax.set_title('a relação suave que as regras por volume carregam', fontsize=8.5, color=TINTA)
            ax.legend(fontsize=7, frameon=False, labelcolor=TINTA)
        else:
            ax.axis('off')
    fig.tight_layout()
    p = FIG / 'volume_t.png'
    fig.savefig(p)
    plt.close(fig)
    return p


def _mais_forte(g, col):
    k = g[col].abs().idxmax()
    return k, g.loc[k]


def secao_janelas(J, JP):
    st = []
    if J is None:
        return st
    Jv = J[J.valida] if 'valida' in J else J
    lim = float(Jv.limite_bonferroni.iloc[0])
    total = int((J.ano == J.ano.iloc[0]).sum() // 2)
    validas = int((Jv.ano == Jv.ano.iloc[0]).sum() // 2)
    st += [Paragraph('1. Janelas de horário: todas as combinações de início e fim', H2),
           Paragraph('O log de cada urna dá quantos votos foram computados em cada faixa de 15 minutos (hora local da urna; todas as urnas que '
                     f'atenderam a seção, inclusive as de contingência). A grade vai de 5h a 21h e gera {n(total)} janelas início–fim; valem as '
                     f'{n(validas)} em que pelo menos 1% das seções tem voto dentro e 1% tem voto fora (fora disso, uma única seção vira o '
                     f'“efeito”). Cada janela é testada nas duas formas de regra. O limite, corrigido para todos os testes, é |t| > {n(lim, 1)}.', P)]
    for ano in sorted(Jv.ano.unique()):
        for tipo in ('deslocamento', 'inversao'):
            g = Jv[(Jv.ano == ano) & (Jv.tipo == tipo)]
            k, y = _mais_forte(g, 't')
            acima = int((g.t.abs() > lim).sum())
            st += [Paragraph(f'<b>{NOME[ano]}, {TIPO[tipo]}:</b> maior |t| = {n(abs(y.t), 1)}, na janela {y.inicio}–{y.fim} '
                             f'(efeito {sn(y.beta_pp, 2)} ponto por 100% de exposição; exposição média {n(100 * y.exposicao_media, 1)}%). '
                             + (f'{n(acima)} janela(s) acima do limite.' if acima else 'Nenhuma janela acima do limite.'), P)]
    st += [fig_img(fig_janelas(Jv), w=18 if Jv.ano.nunique() > 1 else 20),
           Paragraph('Cada célula é uma janela (início no eixo horizontal, fim no vertical). A cor é a estatística t; o círculo marca a janela '
                     'de maior |t|; em branco, as janelas inválidas. Uma regra real apareceria como uma mancha forte em torno da janela certa. '
                     'Janelas que terminam depois do fim da votação (17h) são a mesma coisa que “da hora X até o fim”.', SM)]
    for ano in sorted(Jv.ano.unique()):
        t = [['Tipo', 'Início', 'Fim', 'Efeito (pontos\npor 100% de exposição)', 'Erro-padrão', 't', 'Exposição\nmédia', 'Seções\nexpostas']]
        for tipo in ('deslocamento', 'inversao'):
            g = Jv[(Jv.ano == ano) & (Jv.tipo == tipo)]
            for y in g.reindex(g.t.abs().sort_values(ascending=False).index).head(5).itertuples():
                t.append([TIPO[tipo], y.inicio, y.fim, sn(y.beta_pp, 2), n(y.ep_pp, 2), n(y.t, 1), f'{n(100 * y.exposicao_media, 1)}%', n(y.secoes_expostas)])
        st += [CondPageBreak(6 * cm), Paragraph(f'As 5 janelas de maior |t| em {NOME[ano]}, por tipo', H2),
               table(t, font=7.5, widths=[3.4 * cm, 1.6 * cm, 1.6 * cm, 4 * cm, 2.2 * cm, 1.6 * cm, 2.2 * cm, 2.2 * cm])]
    if JP is not None:
        det = JP[JP.t_na_janela_plantada.abs() > lim]
        t = [['Regra', 'Onde', 'Janela plantada', 'Exposição\nmédia', 't na janela\nplantada', 'Efeito\n(pontos)', 'Janela que a\nvarredura achou', 't máximo', 'Acertou']]
        for y in JP.itertuples():
            t.append([REGRA[y.regra], y.onde, y.janela_plantada, f'{n(y.exposicao_media_pct, 1)}%', n(y.t_na_janela_plantada, 1), sn(y.beta_na_janela_pp, 1),
                      y.janela_encontrada, n(y.t_maximo, 1), 'sim' if y.acertou_janela else 'não'])
        st += [CondPageBreak(8 * cm), Paragraph('2. A varredura pegaria uma regra por horário? (regras plantadas em cópias de 2026)', H2),
               Paragraph('Em cópias dos dados de 2026, aplicamos a regra numa janela escolhida: “2 para 1” (metade dos votos do adversário na janela '
                         'vira voto do PT) ou inversão (na janela, os votos trocam de lado). A regra vale no país inteiro, só em 20% das seções '
                         '(sorteadas) ou só em MG. Depois rodamos a mesma varredura, sem dizer a ela qual era a janela. Os votos da janela são '
                         'repartidos entre os candidatos na proporção da própria seção (o RDV não diz quem votou quando). “Acertou” = a janela '
                         'apontada é a plantada ou uma vizinha com a mesma exposição (depois das 17h quase não há voto, e 16h–17h = 16h–17h45).', P),
               table(t, font=7, widths=[2 * cm, 2.6 * cm, 2.4 * cm, 1.8 * cm, 2 * cm, 1.8 * cm, 3 * cm, 1.8 * cm, 1.6 * cm]),
               Paragraph(f'Passaram do limite {len(det)} de {len(JP)} cenários; a varredura apontou a janela em {int(JP.acertou_janela.sum())}. ' +
                         ('Escaparam: ' + '; '.join(f'{REGRA[y.regra]} {y.onde} em {y.janela_plantada}' for y in JP[~JP.index.isin(det.index)].itertuples()) + '.'
                          if len(det) < len(JP) else ''), SM)]
    return st


def secao_clusters(L, Pf, CP, Ch, Hs):
    st = []
    if L is None:
        return st
    anos = sorted(L.ano.unique())
    lim = float(L.limite_janelas.iloc[0])
    st += [CondPageBreak(8 * cm), Paragraph('3. Além da reta: curvatura, dispersão (mistura) e agrupamentos', H2),
           Paragraph('A reta “resíduo × exposição” no país inteiro só enxerga uma regra que valha em quase toda parte e na proporção da exposição. '
                     'A mesma regra pode ter outra forma, e cada forma pede outro teste, feito aqui em cada janela válida e nas duas formas de regra. '
                     '<b>Curvatura:</b> a resposta por decil de exposição (dentro do prédio, com controles) é comparada à reta; uma regra com limiar, '
                     'ou que só valesse acima de certa exposição, quebra a reta (Wald dos 9 contrastes de decil dado o termo linear; mostrado como '
                     't equivalente). <b>Dispersão:</b> se a regra vale num subconjunto de seções sem marca territorial, a média quase não anda, mas as '
                     'seções expostas se espalham mais: o quadrado do resíduo de Pearson (observado − previsto, dividido pelo desvio binomial, a '
                     'escala Poisson/binomial do ruído esperado) é regredido na exposição, e uma mistura de duas populações aparece como variância '
                     'que cresce com a exposição. <b>Agrupamento:</b> a reta é refeita dentro de cada UF, zona e município (com 30 prédios ou mais), '
                     'e vale o maior |t| entre todos os grupos e janelas, com limite corrigido para esse número de testes. As cópias plantadas '
                     '(abaixo) dizem o que cada teste enxerga; 2022, medido igual, dá a escala do que é normal.', P)]
    for ano in anos:
        for tipo in ('deslocamento', 'inversao'):
            g = L[(L.ano == ano) & (L.tipo == tipo)]
            kl, yl = _mais_forte(g, 't_linear')
            kd, yd = _mais_forte(g, 't_dispersao')
            kc, yc = _mais_forte(g, 't_curvatura')
            partes = [f'reta |t| máx {n(abs(yl.t_linear), 1)} ({yl.inicio}–{yl.fim})', f'dispersão |t| máx {n(abs(yd.t_dispersao), 1)} ({yd.inicio}–{yd.fim})',
                      f'curvatura t equiv. máx {n(yc.t_curvatura, 1)} ({yc.inicio}–{yc.fim}); limite {n(lim, 1)}']
            for nv in NIVEIS:
                kg, yg = _mais_forte(g, f't_{nv}')
                partes.append(f'{nv}: |t| máx {n(abs(yg[f"t_{nv}"]), 1)} em {yg[f"grupo_{nv}"]} ({yg.inicio}–{yg.fim}; limite {n(yg[f"limite_{nv}"], 1)})')
            st += [Paragraph(f'<b>{NOME[ano]}, {TIPO[tipo]}:</b> ' + '; '.join(partes) + '.', P)]
    if Pf is not None:
        st += [fig_img(fig_perfis(L, Pf), w=20),
               Paragraph('Pontos: resíduo médio das seções de cada decil de exposição (1 = menos exposta, 10 = mais exposta), já descontados prédio e '
                         'controles; linha: a reta do teste principal. Uma regra com limiar deixaria os decis altos fora da reta.', SM)]
    # os grupos mais fortes
    for ano in anos:
        t = [['Tipo', 'Nível', 'Grupo', 'Janela', 'Efeito (pontos\npor 100% de exposição)', 't', 'Seções', 'Limite']]
        for tipo in ('deslocamento', 'inversao'):
            g = L[(L.ano == ano) & (L.tipo == tipo)]
            for nv in NIVEIS:
                vistos, linhas = set(), 0
                for y in g.reindex(g[f't_{nv}'].abs().sort_values(ascending=False).index).itertuples():
                    grupo = getattr(y, f'grupo_{nv}')
                    if grupo in vistos or linhas >= 3:
                        continue
                    vistos.add(grupo)
                    linhas += 1
                    t.append([TIPO[tipo], nv, grupo, f'{y.inicio}–{y.fim}', sn(getattr(y, f'beta_{nv}'), 2), n(getattr(y, f't_{nv}'), 1),
                              n(getattr(y, f'secoes_{nv}')), n(getattr(y, f'limite_{nv}'), 1)])
        st += [CondPageBreak(8 * cm), Paragraph(f'Os grupos mais fortes em {NOME[ano]} (3 por nível e tipo, cada um na sua melhor janela)', H2),
               table(t, font=7, widths=[3.2 * cm, 1.8 * cm, 3.2 * cm, 2.4 * cm, 3.6 * cm, 1.4 * cm, 1.8 * cm, 1.6 * cm])]
    if CP is not None:
        t = [['Regra', 'Onde', 'Janela', 'Seções\ncom regra', 'reta t', 'dispersão t', 'curvatura\nt equiv.', 'zona: t máx\n(grupo)', 'zonas plantadas\nno top 10',
              'Varredura: reta\n(janela achada)', 'Varredura: zona\n(janela, zona)']]
        for y in CP.itertuples():
            t.append([REGRA[y.regra], y.onde, y.janela_plantada, n(y.secoes_com_regra), n(y.t_linear, 1), n(y.t_dispersao, 1), n(y.t_curvatura, 1),
                      f'{n(y.t_zona, 1)} ({y.grupo_zona})', n(y.zonas_plantadas_no_top10) if y.onde == '30 zonas' else '–',
                      f'{n(y.t_max_reta_grade, 1)} ({y.janela_reta}){" ✓" if y.acertou_reta else ""}',
                      f'{n(y.t_max_zona_grade, 1)} ({y.janela_zona}, {y.zona_achada}){" ✓" if y.acertou_zona else ""}'])
        st += [CondPageBreak(9 * cm), Paragraph('Regras com forma de cluster plantadas em cópias de 2026', H2),
               Paragraph('A regra vale no país, em 20% ou 5% das seções (sorteadas), em 30 zonas sorteadas, ou só nas seções com exposição acima do '
                         '70º percentil (regra com limiar). Para cada cenário: as quatro estatísticas na janela plantada e o que a varredura completa '
                         'acha sem saber a janela (reta e zona). ✓ = acertou a janela (e, na zona, uma das zonas plantadas). '
                         f'Limites: janelas {n(float(CP.limite_janelas.iloc[0]), 1)}; zona {n(float(CP.limite_zona.iloc[0]), 1)}.', P),
               table(t, font=6.5, widths=[1.7 * cm, 2.6 * cm, 1.9 * cm, 1.6 * cm, 1.4 * cm, 1.7 * cm, 1.6 * cm, 2.6 * cm, 2 * cm, 3.4 * cm, 4.2 * cm])]
    if Ch is not None:
        t = [['Eleição', 'Seções', 'D: 10%', 'mediana', '90%', '99%', 'D > 2', 'D > 3', 'Resíduo × log D\n(pontos por unidade)', 't']]
        for y in Ch.sort_values('ano').itertuples():
            t.append([NOME[y.ano], n(y.secoes), n(y.D_q10, 2), n(y.D_mediana, 2), n(y.D_q90, 2), n(y.D_q99, 2), f'{n(100 * y.fracao_D_maior_2, 1)}%',
                      f'{n(100 * y.fracao_D_maior_3, 2)}%', sn(y.beta_res_por_logD_pp, 2), n(y.t, 1)])
        st += [CondPageBreak(7 * cm), Paragraph('O ritmo de chegada: as contagens de 15 minutos são “Poisson”?', H2),
               Paragraph('Para cada seção, o esperado em cada faixa de 15 min é o total da seção repartido pela curva do prédio (sem a própria seção); '
                         'D é o qui-quadrado dessas contagens dividido pelos graus de liberdade. Chegadas de Poisson dariam D ≈ 1; filas e horários '
                         'próprios de cada seção dão mais. Uma troca de candidato no voto não muda a chegada, então isso só mede inserção ou remoção de '
                         'votos e ritmos fora do padrão, e se as seções de ritmo estranho se afastam das vizinhas no resultado.', P),
               table(t, font=7.5, widths=[4.2 * cm, 2 * cm, 1.6 * cm, 1.8 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm, 3.6 * cm, 1.4 * cm])]
        if Hs is not None:
            st += [fig_img(fig_chegada(Hs), w=15)]
    return st


class Exposicao2026:
    """Fração dos votos de cada seção numa janela, a partir dos bins de 2026 (para medir se duas janelas são 'a mesma
    região da grade': correlação das exposições ≥ 0,98, PROTOCOLO.md seção 7)."""

    def __init__(self):
        self.Cum = None

    def _carrega(self):
        h = pd.read_parquet(ROOT / 'research' / 'janelas_horario' / 'bins_2026.parquet')
        cols = [c for c in h.columns if c.startswith('b') and 'h' in c]
        H = h[cols].to_numpy(float)
        H = H[H.sum(1) >= 20]
        self.tot = H.sum(1)
        self.Cum = np.c_[np.zeros(len(H)), np.cumsum(H, 1)]

    def coluna(self, inicio, fim):
        if self.Cum is None:
            self._carrega()
        s, t = (_min(inicio) - 300) // 15, (_min(fim) - 300) // 15
        return (self.Cum[:, t] - self.Cum[:, s]) / self.tot

    def corr(self, j1, j2):
        if j1 == j2:
            return 1.0
        return float(np.corrcoef(self.coluna(*j1), self.coluna(*j2))[0, 1])


EXPO = Exposicao2026()


def escala_reta(ano, inicio, fim):
    """Dispersão, dentro do prédio, da exposição à janela e do resíduo: dá escala ao coeficiente da reta."""
    try:
        import janelas_horario as jh
        e = jh.prepara(ano)
        b = lambda hhmm: (_min(hhmm) - 300) // 15
        x = jh.Exposicoes(e, [(b(inicio), b(fim))]).coluna(0)
        pl = e.place.to_numpy()
        xd = x - pd.Series(x).groupby(pl).transform('mean').to_numpy()
        y = e.res_pp.to_numpy(float)
        yd = y - pd.Series(y).groupby(pl).transform('mean').to_numpy()
        return dict(sd_x=100 * float(xd.std()), sd_y=float(yd.std()), corr=float(np.corrcoef(xd, yd)[0, 1]))
    except Exception as ex:   # noqa: BLE001
        print('escala_reta falhou', ano, ex)
        return None
FAMILIAS = ['reta', 'dispersao', 'curvatura'] + NIVEIS
NOME_FAM = {'reta': 'reta', 'dispersao': 'dispersão', 'curvatura': 'curvatura', 'UF': 'agrupamento: UF', 'zona': 'agrupamento: zona', 'município': 'agrupamento: município'}


def _linhas_familia(L, ano, tipo, fam):
    """Janelas (e grupos) da família no ano/tipo, com colunas padronizadas: valor (com sinal), inicio, fim, grupo, limite."""
    g = L[(L.ano == ano) & (L.tipo == tipo)]
    if fam == 'reta':
        return pd.DataFrame({'valor': g.t_linear, 'inicio': g.inicio, 'fim': g.fim, 'grupo': '', 'limite': g.limite_janelas})
    if fam == 'dispersao':
        return pd.DataFrame({'valor': g.t_dispersao, 'inicio': g.inicio, 'fim': g.fim, 'grupo': '', 'limite': g.limite_janelas})
    if fam == 'curvatura':
        return pd.DataFrame({'valor': g.t_curvatura, 'inicio': g.inicio, 'fim': g.fim, 'grupo': '', 'limite': g.limite_janelas})
    return pd.DataFrame({'valor': g[f't_{fam}'], 'inicio': g.inicio, 'fim': g.fim, 'grupo': g[f'grupo_{fam}'], 'limite': g[f'limite_{fam}']})


def limites_permutacao(Pm):
    """Por ano, tipo e família: valor real (permutação 0), p95 dos máximos permutados e número de permutações."""
    if Pm is None:
        return None
    real = Pm[Pm.permutacao == 0].rename(columns={'max_abs_t': 'real', 'onde': 'onde_real'})
    nulo = Pm[Pm.permutacao > 0].groupby(['ano', 'tipo', 'familia']).max_abs_t.agg(limite_p95=lambda s: s.quantile(.95), nperm='size').reset_index()
    return real.merge(nulo, on=['ano', 'tipo', 'familia'], how='left')


def classifica(L, LP, tipo, fam):
    """Regra de decisão do PROTOCOLO.md (seção 7) para uma família e tipo. Devolve dict com os números e o veredito."""
    a26 = _linhas_familia(L, 2026, tipo, fam)
    if a26.valor.abs().max() != a26.valor.abs().max():   # tudo NaN
        return None
    k = a26.valor.abs().idxmax()
    v26, j26, g26 = float(a26.valor[k]), (a26.inicio[k], a26.fim[k]), a26.grupo[k]
    lim26, fonte = float(a26.limite[k]), 'Bonferroni'
    if LP is not None:
        p = LP[(LP.ano == 2026) & (LP.tipo == tipo) & (LP.familia == fam)]
        if len(p) and pd.notna(p.limite_p95.iloc[0]):
            lim26, fonte = float(p.limite_p95.iloc[0]), f'permutação ({int(p.nperm.iloc[0])})'
    out = dict(tipo=tipo, familia=fam, valor_2026=v26, janela_2026=f'{j26[0]}–{j26[1]}', grupo_2026=g26, limite=lim26, fonte=fonte,
               valor_2022=np.nan, janela_2022='', grupo_2022='', corr='')
    if abs(v26) <= lim26:
        out['veredito'] = 'nada a sinalizar'
        return out
    if 2022 not in set(L.ano):
        out['veredito'] = 'aguarda 2022'
        return out
    a22 = _linhas_familia(L, 2022, tipo, fam)
    lim22 = lim26
    if LP is not None:
        p = LP[(LP.ano == 2022) & (LP.tipo == tipo) & (LP.familia == fam)]
        if len(p) and pd.notna(p.limite_p95.iloc[0]):
            lim22 = float(p.limite_p95.iloc[0])
    k2 = a22.valor.abs().idxmax()
    out.update(valor_2022=float(a22.valor[k2]), janela_2022=f'{a22.inicio[k2]}–{a22.fim[k2]}', grupo_2022=a22.grupo[k2], limite_2022=lim22)
    acima22 = a22[a22.valor.abs() > lim22]
    if fam in NIVEIS:
        # a regra compara o mesmo grupo nos dois anos; o máximo do nível em 2022 (outro grupo) fica informado ao lado
        out['nivel_2022'] = f'{n(float(a22.valor[k2]), 1)} em {a22.inicio[k2]}–{a22.fim[k2]} {a22.grupo[k2]}'
        g22 = a22[a22.grupo == g26]
        if len(g22):
            kg = g22.valor.abs().idxmax()
            out.update(valor_2022=float(g22.valor[kg]), janela_2022=f'{g22.inicio[kg]}–{g22.fim[kg]}', grupo_2022=g26)
            out['corr_grupo'] = EXPO.corr((g22.inicio[kg], g22.fim[kg]), j26)   # a janela do mesmo grupo em 2022 é a mesma região?
        else:
            out.update(valor_2022=np.nan, janela_2022='', grupo_2022=g26)
        acima22 = acima22[acima22.grupo == g26]
    corrs = [EXPO.corr((r.inicio, r.fim), j26) for r in acima22.itertuples()]
    mesma = acima22[[c >= .98 for c in corrs]] if len(acima22) else acima22
    if len(acima22) and not len(mesma):
        out['corr'] = n(max(corrs), 3)   # a mais parecida entre as que passam em 2022, mesmo abaixo do corte
    if len(mesma):
        m = mesma.loc[mesma.valor.abs().idxmax()]
        out.update(valor_2022=float(m.valor), janela_2022=f'{m.inicio}–{m.fim}', grupo_2022=m.grupo, corr=n(EXPO.corr((m.inicio, m.fim), j26), 3))
        mesmo_sinal = (np.sign(m.valor) == np.sign(v26)) or fam == 'curvatura'
        out['veredito'] = 'padrão de comportamento (igual em 2022)' if mesmo_sinal else 'destoante: mesma região, sinal contrário em 2022'
    elif len(acima22) == 0:
        out['veredito'] = 'destoante: 2022 não passa do limite'
    else:
        out['veredito'] = 'indeterminado: 2022 passa em outra região'
    if out['corr'] == '' and 'corr_grupo' in out:
        out['corr'] = n(out['corr_grupo'], 3)
    return out


def secao_protocolo(L, LP):
    st = []
    if L is None:
        return st
    st += [CondPageBreak(8 * cm), Paragraph('4. Leitura pelo protocolo travado (PROTOCOLO.md, versão 1.1)', H2),
           Paragraph('O protocolo foi fixado em 03/11/2026 (versão 1.0 às 14h; versão 1.1 às 15h, que corrige o leitor de logs e só admite '
                     'seções cujo log do dia conta os mesmos eleitores do BU, diferença ≤ 5), antes de qualquer varredura dos logs de 2022. '
                     'Todos os números deste relatório foram produzidos sob a versão 1.1. Limite principal: o percentil 95 do '
                     'máximo de |t| em 60 permutações do vetor de horários entre as seções do mesmo prédio (a curvatura fica com Bonferroni). '
                     'Regra de decisão por família e tipo: abaixo do limite, nada a sinalizar; acima, se 2022 passa do limite na mesma região '
                     'da grade (exposições correlacionadas ≥ 0,98) e com o mesmo sinal, é padrão de comportamento; se 2022 não passa, ou passa com '
                     'sinal contrário, é destoante e pede investigação (nunca conclusão); se 2022 passa em outra região, indeterminado.', P)]
    if LP is not None:
        t = [['Eleição', 'Tipo', 'Família', 'Real: máx |t|', 'Onde', 'Limite por\npermutação (p95)', 'Permutações']]
        for y in LP.sort_values(['ano', 'tipo', 'familia']).itertuples():
            t.append([NOME[y.ano], TIPO[y.tipo], NOME_FAM.get(y.familia, y.familia), n(y.real, 1), y.onde_real,
                      n(y.limite_p95, 2) if pd.notna(y.limite_p95) else '–', n(y.nperm) if pd.notna(y.nperm) else '0'])
        st += [table(t, font=7, widths=[4 * cm, 3.4 * cm, 3.4 * cm, 2.2 * cm, 5.6 * cm, 3 * cm, 2 * cm])]
        if LP.nperm.fillna(0).min() < 60:
            st += [Paragraph(f'Permutações concluídas: mínimo {n(LP.nperm.fillna(0).min())} de 60; o limite por permutação é preliminar até 60.', SM)]
    t = [['Tipo', 'Família', '2026: máx |t|', 'Janela (grupo)', 'Limite (fonte)', '2022 na mesma região', 'Correlação', 'Veredito']]
    for tipo in ('deslocamento', 'inversao'):
        for fam in FAMILIAS:
            c = classifica(L, LP, tipo, fam)
            if c is None:
                continue
            if pd.notna(c['valor_2022']):
                em22 = f'{n(c["valor_2022"], 1)} em {c["janela_2022"]} {c["grupo_2022"]}'.strip()
            elif c.get('nivel_2022'):
                em22 = f'{c["grupo_2022"]}: não é o grupo de maior |t| em nenhuma janela de 2022'
            else:
                em22 = '–'
            if c.get('nivel_2022'):
                em22 += f' | máx. do nível em 2022: {c["nivel_2022"]}'
            t.append([TIPO[tipo], NOME_FAM[fam], n(c['valor_2026'], 1), f'{c["janela_2026"]} {c["grupo_2026"]}'.strip(), f'{n(c["limite"], 1)} ({c["fonte"]})',
                      em22, c['corr'], c['veredito']])
    st += [Paragraph('Veredito por família e tipo', H2),
           table(t, font=7, widths=[2.8 * cm, 3 * cm, 1.7 * cm, 3.3 * cm, 2.8 * cm, 5.8 * cm, 1.5 * cm, 5.1 * cm]),
           Paragraph('Nos agrupamentos, a regra compara o mesmo grupo nos dois anos (coluna “2022 na mesma região”); o máximo de 2022 no mesmo nível, em '
                     'outro grupo, aparece ao lado para dar a escala do que o nível produz num ano sem regra plantada.', SM)]
    st += secao_leitura(L, LP)
    return st


def secao_leitura(L, LP):
    """Parágrafos de leitura da tabela de vereditos: limites provisórios, o gradiente do dia inteiro em escala, os agrupamentos."""
    st = [CondPageBreak(7 * cm), Paragraph('Leitura', H2)]
    if LP is None:
        st += [Paragraph('Limites por permutação: ainda não disponíveis (as permutações estão em andamento). Todos os vereditos acima usam o limite de '
                         'Bonferroni e são provisórios; os que ficam a menos de duas unidades do limite (dispersão, zona, município) tendem a virar '
                         '“nada a sinalizar” com o limite por permutação, em geral mais alto. A tabela será refeita quando as 60 permutações de cada ano '
                         'terminarem.', P)]
    elif 2022 not in set(LP.ano):
        st += [Paragraph('Permutações de 2022: em andamento. Os limites por permutação acima são os de 2026; para julgar se 2022 passa do limite, a tabela '
                         'usa por enquanto o limite de 2026 da mesma família. A tabela será refeita quando as 60 permutações de 2022 terminarem.', P)]
    c = classifica(L, LP, 'deslocamento', 'reta')
    if not c or not c['veredito'].startswith('destoante: mesma região'):
        return st
    i26, f26 = c['janela_2026'].split('–')
    i22, f22 = c['janela_2022'].split('–')
    l26 = L[(L.ano == 2026) & (L.tipo == 'deslocamento') & (L.inicio == i26) & (L.fim == f26)].iloc[0]
    l22 = L[(L.ano == 2022) & (L.tipo == 'deslocamento') & (L.inicio == i22) & (L.fim == f22)].iloc[0]
    s26, s22 = escala_reta(2026, i26, f26), escala_reta(2022, i22, f22)
    JP = r('janelas_plantadas.csv')
    pais = JP[(JP.onde == 'país') & (JP.regra == '2_para_1')].beta_na_janela_pp
    escala = ''
    if s26 and s22:
        escala = (f'Em escala: a exposição a essa janela varia {n(s26["sd_x"], 1)} pontos entre seções do mesmo prédio (um desvio-padrão), o que '
                  f'corresponde a {n(abs(s26["sd_x"] * l26.beta_pp / 100), 2)} ponto de resíduo, contra um desvio-padrão do resíduo de {n(s26["sd_y"], 1)} '
                  f'pontos (correlação dentro do prédio {sn(s26["corr"], 3)} em 2026 e {sn(s22["corr"], 3)} em 2022). ')
    st += [Paragraph(f'O veredito “destoante: mesma região, sinal contrário em 2022” da reta (e, pelo mesmo motivo, do agrupamento por UF e da inversão) '
                     f'descreve uma única coisa: o gradiente do dia inteiro. Em 2026, dentro do mesmo prédio, a seção com mais votos à tarde ficou mais '
                     f'para Lula do que as vizinhas ({sn(l26.beta_pp, 2)} ponto por 100% de exposição à janela {c["janela_2026"]}); em 2022, menos '
                     f'({sn(l22.beta_pp, 2)} ponto, janela {c["janela_2022"]}). Os mapas da seção 1 são a imagem espelhada um do outro: mesma forma, cor '
                     f'trocada. {escala}Nas cópias plantadas, a regra “2 para 1” no país inteiro dá {n(pais.min(), 0)} a {n(pais.max(), 0)} pontos por 100% '
                     f'de exposição, cerca de dez vezes o gradiente real; uma regra que produzisse o gradiente de 2026 teria de valer em todas as seções '
                     f'do país, a tarde inteira, convertendo da ordem de 1 em 20 votos do adversário. O gradiente de 2022, do mesmo tamanho e sinal '
                     f'contrário, mostra que um gradiente desse tamanho existe sem regra. O que o teste não decide é por que a direção trocou: quem vota '
                     f'de manhã e quem vota à tarde não é o mesmo público, e o movimento de cada público entre o 1º e o 2º turno não precisa ser o mesmo '
                     f'em eleições diferentes. O passo seguinte previsto no protocolo (cenário plantado mais parecido e leitura dos logs e RDVs das seções '
                     f'apontadas) aqui não aponta seções: a reta é nacional, e as seções que mais a puxam são, por construção, as de exposição extrema em '
                     f'cada prédio. A conferência que cabe é a forma da relação: nas janelas do pico a reta serve nos dois anos (curvatura t equiv. '
                     f'{n(l26.t_curvatura, 1)} em 2026 e {n(l22.t_curvatura, 1)} em 2022, perfis da seção 3), e a curvatura máxima da grade tem veredito '
                     f'de padrão de comportamento. Fica registrado como destoante, a investigar, sem conclusão.', P),
           Paragraph('Agrupamentos por zona e município: a regra compara o mesmo grupo nos dois anos e por isso dá “2022 não passa” quando a zona ou o '
                     'município de 2026 não se repete. O máximo de 2022 no mesmo nível, em outro grupo, está na tabela: quando é maior que o de 2026, '
                     'valores desse tamanho aparecem num ano sem que o grupo se repita no outro, o esperado de máximos tomados sobre centenas de grupos. '
                     'O limite por permutação, que é o máximo sobre todos os grupos e janelas, é o que decide essas linhas.', P)]
    quase, restam = [], []
    for tipo in ('deslocamento', 'inversao'):
        for fam in FAMILIAS:
            cg = classifica(L, LP, tipo, fam)
            if not cg:
                continue
            if fam in NIVEIS and cg['veredito'].startswith(('indeterminado', 'destoante: 2022 não passa')) and cg['corr'] and pd.notna(cg['valor_2022']) \
                    and float(cg['corr'].replace(',', '.')) >= .95:
                quase.append(f'{TIPO[tipo]}, {NOME_FAM[fam]}: {cg["grupo_2026"]} tem {n(cg["valor_2026"], 1)} em {cg["janela_2026"]} em 2026 (limite {n(cg["limite"], 1)}) '
                             f'e {n(cg["valor_2022"], 1)} em {cg["janela_2022"]} em 2022 (limite de 2022 {n(cg.get("limite_2022", np.nan), 1)}), correlação {cg["corr"]}')
            elif cg['veredito'] == 'destoante: 2022 não passa do limite':
                restam.append(f'{TIPO[tipo]}, {NOME_FAM[fam]}: {n(cg["valor_2026"], 1)} em {cg["janela_2026"]} {cg["grupo_2026"]} (limite {n(cg["limite"], 1)}; '
                              f'2022 na mesma região: {n(cg["valor_2022"], 1) if pd.notna(cg["valor_2022"]) else "–"})'.replace('  ', ' '))
    if quase:
        st += [Paragraph('Caso-limite da regra, nos agrupamentos: mesmo grupo e janela quase igual nos dois anos (correlação acima de 0,95), mas o veredito '
                         'formal não é “mesma região” porque a correlação fica abaixo do corte 0,98 ou porque o valor de 2022 fica abaixo do limite de 2022, '
                         'que no nível de zona e município é bem mais alto que o de 2026 — ' + '; '.join(quase) + '. Com sinal trocado, é o mesmo gradiente '
                         'do dia inteiro visto dentro do grupo.', P)]
    if restam:
        st += [Paragraph('Ficam como “destoante: 2022 não passa do limite”, fora o gradiente do dia inteiro: ' + '; '.join(restam) + '. São valores próximos do '
                         'limite e sem contraparte em 2022; pelo protocolo, o passo seguinte é o cenário plantado mais parecido (seção 3) e a leitura dos logs e '
                         'RDVs das seções do grupo apontado, e o relatório não conclui.', P)]
    return st


def secao_volume(V, VP, C):
    st = []
    if V is None:
        return st
    lim = float(V.limite_bonferroni.iloc[0])
    Vs = V[V.controles == CTL_PRINCIPAL]
    st += [CondPageBreak(8 * cm), Paragraph('5. Regras por volume: a partir do N-ésimo voto, de p% dos aptos, ou só os últimos k votos', H2),
           Paragraph('A urna não sabe o total final enquanto vota, mas conhece o contador de votos e o número de aptos carregado na preparação. '
                     'Para cada regra, a fração de votos afetados é uma função conhecida do BU, e o teste é o mesmo. Há uma dificuldade própria '
                     'dessas regras: a exposição é função do comparecimento da seção, e o comparecimento (relativo ao prédio) já se relaciona '
                     'com o resíduo de forma suave, em sentidos opostos em 2022 e 2026 (gráfico à direita). Por isso o teste controla essa '
                     'relação (polinômio no comparecimento e no tamanho) e procura só a quebra que a regra criaria. A regra “p% dos aptos” '
                     'é função só do comparecimento; ela só é distinguível da relação suave pela forma, o que torna esse teste menos conclusivo '
                     f'que os outros dois (as cópias plantadas mostram isso). O limite é |t| > {n(lim, 1)}; como os controles não absorvem toda '
                     'a relação com o comparecimento, a leitura que vale é a comparação com 2022 e com as regras plantadas. Os CSVs trazem '
                     'também as versões com controles básicos e com faixas de comparecimento.', P)]
    for ano in (2022, 2026):
        partes = []
        for tipo in ('deslocamento', 'inversao'):
            for regra, g in Vs[(Vs.ano == ano) & (Vs.tipo == tipo)].groupby('regra', sort=False):
                k = g.t.abs().idxmax()
                partes.append(f'{TIPO[tipo]}, {regra}: |t| máx {n(abs(g.t[k]), 1)} em {g.parametro[k]}')
        st += [Paragraph(f'<b>{NOME[ano]}:</b> ' + '; '.join(partes) + '.', P)]
    st += [fig_img(fig_volume(V, C), w=25),
           Paragraph('Linhas: t de cada parâmetro, com os controles suaves (faixa clara = dentro do limite). Direita: resíduo médio por faixa de '
                     'comparecimento relativo ao prédio, a relação que os controles absorvem.', SM)]
    if VP is not None:
        t = [['Regra plantada', 'Onde', 'Tipo', 'Exposição\nmédia', 't na regra\nplantada', 'Efeito\n(pontos)', 'Regra que a\nvarredura achou', 't máximo']]
        for y in VP.itertuples():
            t.append([f'{y.regra_plantada} = {y.parametro}', y.onde, REGRA[y.tipo], f'{n(y.exposicao_media_pct, 1)}%', n(y.t_na_regra_plantada, 1),
                      sn(y.beta_pp, 1), y.regra_encontrada, n(y.t_maximo, 1)])
        det = VP[VP.t_na_regra_plantada.abs() > lim]
        st += [CondPageBreak(7 * cm), Paragraph('Regras por volume plantadas em cópias de 2026', H2),
               table(t, font=7, widths=[4.2 * cm, 2.8 * cm, 2 * cm, 1.8 * cm, 2 * cm, 1.8 * cm, 5 * cm, 1.8 * cm]),
               Paragraph(f'Passaram do limite {len(det)} de {len(VP)} cenários. ' +
                         ('Escaparam: ' + '; '.join(f'{REGRA[y.tipo]} {y.onde}, {y.regra_plantada} = {y.parametro}' for y in VP[~VP.index.isin(det.index)].itertuples()) + '.'
                          if len(det) < len(VP) else ''), SM)]
    return st


def main():
    J, JP = junta('janelas'), r('janelas_plantadas.csv')
    L, Pf, CP = junta('clusters'), junta('perfis'), r('clusters_plantados.csv')
    Ch, Hs = junta('chegada'), junta('chegada_hist')
    V, VP, C = r('volume_real.csv'), r('volume_plantado.csv'), r('curva_comparecimento.csv')
    LP = limites_permutacao(junta('permutacao'))

    st = [Paragraph('Gatilho por horário ou por volume: de uma hora até outra, em todas as urnas', H1),
          Paragraph('2º turno de 2026, presidente. A pergunta: se um programa trocasse votos só entre uma hora e outra (14h–15h, por exemplo), '
                    'ou só a partir do N-ésimo voto, dava para ver nos dados publicados? O RDV não tem ordem nem hora. Mas a fração de votos de cada '
                    'seção dentro da janela varia de seção para seção, e a seção se afastaria das vizinhas do mesmo prédio na proporção dessa '
                    'fração. É isso que a varredura mede: o resíduo do modelo do local (o quanto a seção saiu do esperado pelas vizinhas e pelo '
                    'próprio 1º turno) contra a exposição da seção a cada regra possível, dentro do prédio e com controles. Duas formas de regra: '
                    '<b>deslocamento</b> (“2 para 1”: a seção anda para um lado na proporção da exposição) e <b>inversão</b> (a seção anda contra o '
                    'lado que liderava nela). Além da reta no país inteiro, a regra é procurada em outras formas: curvatura, mistura (dispersão) e '
                    'agrupamento territorial. A régua é dupla: 2022 medido do mesmo jeito e cópias de 2026 com regras plantadas.', P)]
    st += secao_janelas(J, JP)
    st += secao_clusters(L, Pf, CP, Ch, Hs)
    st += secao_protocolo(L, LP)
    st += secao_volume(V, VP, C)
    st += [CondPageBreak(6 * cm), Paragraph('6. O que este teste não pega', H2),
           Paragraph('Uma regra proporcional e idêntica em todas as seções, sem “momento”, não cria diferença entre vizinhas e fica fora do alcance '
                     'desta varredura (é o limite já descrito no relatório de padrões: uma mudança suave numa UF inteira fica no limiar do modelo '
                     'regional). Uma regra em poucas dezenas de urnas escolhidas também escapa, em qualquer das formas testadas (as cópias com 5% das '
                     'seções mostram onde a sensibilidade acaba). A janela é medida pelo relógio da própria urna, que é o relógio que um programa '
                     'usaria; se o relógio estiver errado, a janela desloca junto. E uma associação entre horário e resíduo que apareça igual em 2022 '
                     'é comportamento de eleitor (quem vota tarde não é o mesmo público de quem vota cedo), não regra. Como repetir: '
                     'scripts/janelas_horario.py coleta 2026 | coleta 2022 | volume | janelas 2026 | janelas 2022 | plantadas | clusters 2026 | '
                     'clusters 2022 | clusters_plantadas | permutacao 2026 | permutacao 2022; scripts/make_janelas_report.py. Regras fixas em '
                     'docs/PROTOCOLO_JANELAS_HORARIO.md (cópia de trabalho em relatorios/verificacoes/janelas_horario/PROTOCOLO.md). Tabelas completas em JANELAS_HORARIO.xlsx e nos CSVs da pasta.', P)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7)
        cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(D / 'JANELAS_HORARIO.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='Gatilho por horário ou volume', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', D / 'JANELAS_HORARIO.pdf')
    from ultimo_voto_2026t2 import xlsx_leve
    xlsx_leve(D / 'JANELAS_HORARIO.xlsx', [(p.stem[:31], pd.read_csv(p, **CSV)) for p in sorted(D.glob('*.csv'))])
    print('OK', D / 'JANELAS_HORARIO.xlsx')


if __name__ == '__main__':
    main()
