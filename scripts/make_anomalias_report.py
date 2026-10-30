"""Relatorio: busca de padrao destoante em todas as urnas do 2o turno de 2026 (2022 de controle, manipulacoes plantadas),
pericia de log das secoes destoantes e do periodo tardio, e teste de gatilho no RDV.
Le relatorios/verificacoes/anomalias_2t/ (anomalias_2t.py, anomalias_logs.py) e rdv_gatilho/ (rdv_gatilho.py).
Saida: ANOMALIAS_2T.pdf, ANOMALIAS_2T.xlsx e figuras/.
"""
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('UF', 'BA')
from make_bahia_reports import P, H1, H2, SM, table, n, fig_img  # noqa: E402
from make_padroes_report import TINTA, TINTA2, _eixos, sn  # noqa: E402

D = ROOT / 'relatorios' / 'verificacoes' / 'anomalias_2t'
G = ROOT / 'relatorios' / 'verificacoes' / 'rdv_gatilho'
W = ROOT / 'research' / 'anomalias_2t'
FIG = D / 'figuras'
CSV = dict(sep=';', encoding='utf-8-sig', decimal=',')
COR = {2022: '#1baf7a', 2026: '#eda100'}          # mesma paleta do relatorio de padroes (categorica, ordem fixa)
AZUL, LARANJA, CINZA = '#2a78d6', '#eb6834', '#9a9993'
DIVERG = LinearSegmentedColormap.from_list('div', [AZUL, '#f1f0ec', LARANJA])
NOMEP = {'inversao_local': 'inversão local (250 seções)', 'proporcional': 'proporcional (10% das seções, 5% dos votos)',
         'votos_tardios': 'votos tardios (todo voto depois das 17h para o PT)', 'regional_suave': 'regional suave (uma UF, 2%)',
         'enchimento': 'enchimento de urna (0,5% das seções)'}


LAB = {'res_pp': 'fatia do PT − previsto (pontos)', 'votos': 'votos no log', 'pct_manual': '% de habilitação manual',
       'pct_manual_apos_17h': '% das manuais depois das 17h', 'alertas_por_100_votos': 'alertas por 100 votos',
       'corrigiu_por_100_votos': 'correções na tela de confirmação por 100 votos', 'pausa_max_min': 'maior pausa entre votos (min)',
       'intervalo_mediano_min': 'intervalo mediano entre votos (min)', 'pausas_15min': 'pausas de 15 min ou mais',
       'ritmo_llr': 'mudança de ritmo (razão de verossimilhança)', 'ritmo_ponto_min': 'hora da mudança de ritmo', 'primeiro_voto': 'primeiro voto',
       'ultimo_voto': 'último voto', 'encerrou_min': 'encerramento', 'min_ultimo_voto_ate_encerrar': 'do último voto ao encerramento (min)',
       'eventos_entre_ultimo_voto_e_encerrar': 'eventos entre o último voto e o encerramento'}
HORA = {'ritmo_ponto_min', 'primeiro_voto', 'ultimo_voto', 'encerrou_min'}


def rotulo(v):
    if v.startswith('pct_b'):
        h, m = int(v[5:7]), int(v[8:10])
        f = h * 60 + m + 30
        return f'% dos votos das {h}h{m:02d} às {f // 60}h{f % 60:02d}'
    return LAB.get(v, v.replace('_', ' '))


def hm(x):
    return '—' if pd.isna(x) else f'{int(x // 60)}h{int(round(x % 60)):02d}'


def r(nome, pasta=D):
    return pd.read_csv(pasta / nome, low_memory=False, **CSV)


def _por100mil(x, n_):
    return 1e5 * x / n_


def fig_impressao():
    FIG.mkdir(parents=True, exist_ok=True)
    fig, axs = plt.subplots(1, 3, figsize=(12.5, 3.9), dpi=160)
    for ax, ano in zip(axs[:2], (2022, 2026)):
        z = np.load(W / f'impressao_{ano}.npz')
        ax.imshow(np.log1p(z['obs']).T, origin='lower', extent=[0, 1, 0, 1], aspect='auto', cmap='Greys')
        _eixos(ax, 'comparecimento', 'fatia do PT entre os dois')
        ax.set_title({2022: 'Lula × Bolsonaro (2022)', 2026: 'Lula × Flávio (2026)'}[ano], fontsize=9, color=TINTA)
        ax.grid(False)
    z = np.load(W / 'impressao_2026.npz')
    ex = (z['obs'] - z['sim']) / np.sqrt(z['sim'] + 1)
    im = axs[2].imshow(ex.T, origin='lower', extent=[0, 1, 0, 1], aspect='auto', cmap=DIVERG, vmin=-6, vmax=6)
    _eixos(axs[2], 'comparecimento', '')
    axs[2].set_title('2026: observado − simulado (desvios)', fontsize=9, color=TINTA)
    axs[2].grid(False)
    fig.colorbar(im, ax=axs[2], fraction=.046)
    fig.tight_layout()
    p = FIG / 'impressao_digital.png'
    fig.savefig(p)
    plt.close(fig)
    return p


def fig_perfil():
    pf = r('logs_perfil_horario.csv')
    pf['h'] = pf.meia_hora.str.extract(r'b(\d\d)h(\d\d)').astype(float).pipe(lambda x: x[0] + x[1] / 60 + .25)
    fig, axs = plt.subplots(1, 2, figsize=(12, 3.3), dpi=160, sharey=True)
    for ax, (g, cor, txt) in zip(axs, (('fora_voto', AZUL, 'voto fora dos modelos'), ('tarde', LARANJA, 'período tardio'))):
        ax.plot(pf.h, pf[g + '_vizinhas'], color=CINZA, lw=2, marker='o', ms=4, mec='white', label='vizinhas dos mesmos locais')
        ax.plot(pf.h, pf[g], color=cor, lw=2, marker='o', ms=4, mec='white', label=txt)
        _eixos(ax, 'hora de Brasília', '% dos votos da seção na meia hora' if g == 'fora_voto' else '')
        ax.legend(fontsize=7.5, frameon=False, labelcolor=TINTA)
    fig.tight_layout()
    p = FIG / 'perfil_horario.png'
    fig.savefig(p)
    plt.close(fig)
    return p


def main():
    m = r('metricas_real_x_plantadas.csv')
    real = m[m.base.str.startswith('real')].set_index('ano')
    pl = m[m.base.str.startswith('plantada')].copy()
    pl['tipo'] = pl.base.str.replace('plantada ', '', regex=False)
    r26, r22 = real.loc[2026], real.loc[2022]
    st = [Paragraph('2º turno de 2026: busca de padrão destoante em todas as urnas', H1),
          Paragraph(f'Todas as seções com BU nos dois turnos ({n(r26.secoes_no_modelo)} no modelo em 2026; {n(r22.secoes_no_modelo)} em 2022). '
                    'Seis modelos diferentes procuram seções, locais, municípios ou UFs cujo resultado não segue o padrão das vizinhas e do próprio '
                    '1º turno. A régua do “normal” é dupla: a eleição de 2022 (Lula × Bolsonaro), medida do mesmo jeito, e cópias de 2026 com '
                    'manipulações plantadas de propósito, para saber o que cada modelo consegue ver. Depois, o log das seções que destoaram e das '
                    'que votaram até tarde é comparado com o das vizinhas do mesmo local.', P)]

    # ---------- resumo
    def det(col, sinal=1, k=4):
        """plantada detectada se a metrica sai do valor real de 2026 por mais de k erros (contagem: Poisson)."""
        out = []
        for x in pl.itertuples():
            a, b = getattr(x, col), r26[col]
            if pd.isna(a) or pd.isna(b):
                continue
            if col.endswith('_t') or col.endswith('_z') or col.endswith('_ctrl'):
                ok = abs(a) > k and abs(a - b) > k
            elif col.startswith('m5_uf'):
                ok = a - b > .5
            elif col in ('m1_z_assimetria', 'm2_z_assimetria', 'm4_corr_comparecimento_voto'):
                ok = abs(a - b) > {'m4_corr_comparecimento_voto': .02}.get(col, .05)
            else:
                ok = (a - b) / np.sqrt(b + 1) > k
            if ok:
                out.append(x.tipo)
        return ', '.join(NOMEP[t].split(' (')[0] for t in out) or '—'
    linhas = [['Modelo', 'Medida', '2022', '2026', 'Detecta nas cópias plantadas']]
    linhas += [['M1 modelo do local', 'seções fora (|z| > 4)', n(r22.m1_fora4), n(r26.m1_fora4), det('m1_fora4')],
               ['M2 gradient boosting', 'seções fora (|z| > 4)', n(r22.m2_fora4), n(r26.m2_fora4), det('m2_fora4')],
               ['M2 gradient boosting', 'seções fora (|z| > 5)', n(r22.m2_fora5), n(r26.m2_fora5), det('m2_fora5')],
               ['M2 gradient boosting', 'seções fora a favor do PT (z > 4)', n(r22.m2_fora4_PT), n(r26.m2_fora4_PT), det('m2_fora4_PT')],
               ['M1 forma da distribuição', 'assimetria do resíduo', n(r22.m1_z_assimetria, 3), n(r26.m1_z_assimetria, 3), det('m1_z_assimetria')],
               ['M3 Mahalanobis robusta', 'seções com p < 1 em 1 milhão', n(r22.m3_p1e6), n(r26.m3_p1e6), det('m3_p1e6')],
               ['M4 impressão digital', 'canto comparec. ≥ 90% e PT ≥ 90% (desvios)', n(r22.m4_canto_comp90_PT90_z, 1), n(r26.m4_canto_comp90_PT90_z, 1),
                det('m4_canto_comp90_PT90_z')],
               ['M4 impressão digital', 'canto comparec. ≥ 90% e adversário ≥ 90%', n(r22.m4_canto_comp90_adv90_z, 1), n(r26.m4_canto_comp90_adv90_z, 1),
                det('m4_canto_comp90_adv90_z')],
               ['M4 comparec. × voto', 'correlação dos resíduos (no local)', n(r22.m4_corr_comparecimento_voto, 3), n(r26.m4_corr_comparecimento_voto, 3),
                det('m4_corr_comparecimento_voto')],
               ['M4 comparec. × voto', 'seções com comparec. > 4 e PT > 2 desvios', n(r22.m4_conjunto_comp4_PT2), n(r26.m4_conjunto_comp4_PT2),
                det('m4_conjunto_comp4_PT2')],
               ['M5 regional', 'maior resíduo de UF (pontos)', f'{n(r22.m5_uf_max_abs_pp, 2)} ({r22.m5_uf_max_onde})',
                f'{n(r26.m5_uf_max_abs_pp, 2)} ({r26.m5_uf_max_onde})', det('m5_uf_max_abs_pp')],
               ['M6 horário', 'encerrou depois de 17h30 (t)', n(r22.get('m6_encerrou_depois_17h30_t'), 1), n(r26.m6_encerrou_depois_17h30_t, 1),
                det('m6_encerrou_depois_17h30_t')],
               ['M6 horário', 'teve voto depois das 17h (t)', '—', n(r26.m6_teve_voto_apos_17h_t, 1), det('m6_teve_voto_apos_17h_t')],
               ['M6 horário', 'teve voto depois das 17h, com controles (t)', '—', n(r26.m6_teve_voto_apos_17h_t_ctrl, 1),
                det('m6_teve_voto_apos_17h_t_ctrl')],
               ['M6 horário', 'fração dos votos depois das 17h (t)', '—', n(r26.m6_fracao_votos_apos_17h_t, 1), det('m6_fracao_votos_apos_17h_t')]]
    st += [Paragraph('Resumo', H2), table(linhas, font=7.5, widths=[4.2 * cm, 6.6 * cm, 3 * cm, 3 * cm, 9.4 * cm]),
           Paragraph('“Detecta” = a medida da cópia plantada sai do valor real de 2026 por mais de 4 erros-padrão (contagens: aproximação de Poisson; '
                     'estatísticas t e z: acima de 4 em módulo). Uma manipulação que nenhum modelo detecta é um limite do método, não uma prova de que '
                     'ela não existiu; por isso as cópias plantadas cobrem tipos diferentes.', SM)]
    pi = pl.set_index('tipo')
    txt = [f'<b>Em resumo.</b> Medido do mesmo jeito, 2026 fica no nível de 2022: {n(r26.m1_fora4)} e {n(r22.m1_fora4)} seções fora do modelo do '
           f'local; {n(r26.m2_fora4)} e {n(r22.m2_fora4)} fora do gradient boosting (em 2026, {n(r26.m2_fora4_PT)} a favor de Lula e '
           f'{n(r26.m2_fora4 - r26.m2_fora4_PT)} a favor de Flávio). As manipulações plantadas em 2026 aparecem: inversão em 250 seções '
           f'({n(pi.loc["inversao_local", "m1_fora4"])} seções fora do M1), enchimento em 0,5% das seções, todo voto depois das 17h para um lado '
           f'(t = {n(pi.loc["votos_tardios", "m6_teve_voto_apos_17h_t"], 0)} contra {n(r26.m6_teve_voto_apos_17h_t, 1)} no real) e a mudança '
           'proporcional espalhada (pela assimetria e pela direção dos desvios). Fica no limite a mudança suave numa UF inteira.']
    if (D / 'logs_resumo_grupos.csv').exists():
        rg_ = r('logs_resumo_grupos.csv').set_index('grupo')
        txt.append(f' Nos logs, as seções cujo voto destoou não têm nada de diferente das vizinhas do mesmo prédio; as que destoaram só no '
                   f'comparecimento e na liberação manual trocaram de urna durante o dia em {n(rg_.loc["fora_multivariado", "contingencia_pct"], 0)}% '
                   f'dos casos (vizinhas: {n(rg_.loc["vizinhas", "contingencia_pct"], 1)}%); e as do período tardio esperaram até as 19h para '
                   f'encerrar, com resultado igual ao das vizinhas ({sn(rg_.loc["tarde", "diferenca_res_pp"], 2)} ± '
                   f'{n(rg_.loc["tarde", "ep_res_pp"], 2)} ponto).')
    st += [Paragraph(''.join(txt), P)]

    # ---------- M1/M2
    s26 = pd.read_parquet(W / 'secoes_2026.parquet')
    s22 = pd.read_parquet(W / 'secoes_2022.parquet')
    st += [CondPageBreak(7 * cm), Paragraph('1. Seção a seção: modelo do local (M1) e gradient boosting (M2)', H2),
           Paragraph('M1 prevê cada seção pelo próprio 1º turno mais a mudança das outras seções do mesmo prédio. M2 aprende, com todas as seções de '
                     'outros municípios, como a composição do 1º turno (cada candidato eliminado, brancos e nulos, abstenção, liberação manual) e a '
                     'mudança das vizinhas viram o 2º turno; cada seção é prevista por um modelo que não viu o município dela. O resíduo é medido em '
                     'desvios-padrão robustos.', P),
           Paragraph(f'Em 2026, M2 deixou {n(r26.m2_fora4)} seções além de 4 desvios ({n(r26.m2_fora4_PT)} a favor de Lula, '
                     f'{n(r26.m2_fora4 - r26.m2_fora4_PT)} a favor de Flávio); em 2022, {n(r22.m2_fora4)} ({n(r22.m2_fora4_PT)} a favor de Lula). '
                     f'Uma distribuição normal perfeita daria cerca de {n(r26.m2_esperado_normal_4)}: as caudas são mais pesadas que a normal nos dois '
                     'anos, como é comum em dados reais (seções com eleitorado atípico, transferências de seção). O que importa é a comparação entre '
                     f'os anos e com as cópias plantadas. M1, mais conservador, marca {n(r26.m1_fora4)} seções em 2026 e {n(r22.m1_fora4)} em 2022.', P)]
    mn = pd.read_parquet(ROOT / 'research' / 'segundo_turno_2026' / 'mun_todos.parquet', columns=['uf', 'mun5', 'municipality_name'])
    mn = {(u_, int(m_)): str(nm).title() for u_, m_, nm in zip(mn.uf, mn.mun5, mn.municipality_name)}
    fora2 = s26[s26.z_m2.abs() > 4]
    ext = int(((fora2.t1_X / fora2.n1 >= .85) | (fora2.t1_X / fora2.n1 <= .15)).sum())
    st += [Paragraph(f'Das {n(len(fora2))} seções fora do M2 em 2026, {n(ext)} já tinham 85% ou mais para um dos dois no 1º turno. Perto desses '
                     'extremos o M2 exagera a tendência (prevê 97% onde a seção repetiu 91%), e o M1, que olha as vizinhas do próprio prédio, '
                     'considera quase todas normais.', P)]

    def tab_secoes(top, titulo):
        t = [['UF', 'Município', 'Zona', 'Seção', 'Votos\n2º turno', 'PT 1º t.\n(% dos dois)', 'PT 2º t.\n(% dos dois)', 'Previsto\nM2 (%)', 'z M2', 'z M1']]
        for y in top.itertuples():
            t.append([y.uf, mn.get((y.uf, int(y.municipality)), str(y.municipality)), str(int(y.zone)), str(int(y.section)), n(y.n2),
                      n(100 * y.t1_X / y.n1, 1), n(100 * y.t2_X / y.n2, 1), n(100 * y.p_m2, 1), n(y.z_m2, 1), n(y.z, 1)])
        return [Paragraph(titulo, H2), table(t, font=7, widths=[1.2 * cm, 4.6 * cm, 1.4 * cm, 1.4 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 2.2 * cm, 1.6 * cm, 1.6 * cm])]
    st += tab_secoes(s26[s26.z.abs() > 4].sort_values('z'), f'As {n((s26.z.abs() > 4).sum())} seções de 2026 fora do modelo do local (M1)')
    st += tab_secoes(s26.reindex(s26.z_m2.abs().sort_values(ascending=False).index).head(15), 'As 15 seções de 2026 mais distantes do previsto (M2)')
    st += [
           Paragraph('Lista completa em secoes_destoantes_2026.csv. Cada seção destoante tem nome e endereço: é o ponto de partida para conferir o BU '
                     'impresso, o RDV e o log daquela urna.', SM)]

    # ---------- M3
    st += [CondPageBreak(6 * cm), Paragraph('2. Mudança em várias dimensões ao mesmo tempo (M3)', H2),
           Paragraph('Para cada seção, o vetor de mudança do 1º para o 2º turno (votos do PT, do adversário, brancos e nulos, comparecimento e '
                     'liberação manual, como fração do eleitorado), comparado com as vizinhas do mesmo local. A distância de Mahalanobis robusta '
                     '(estimador MCD) mede o quanto o vetor é raro; o Isolation Forest, sem supor forma de distribuição, faz o mesmo por outro '
                     f'caminho. Seções com chance menor que 1 em 1 milhão: {n(r26.m3_p1e6)} em 2026 e {n(r22.m3_p1e6)} em 2022. A perícia de log '
                     '(seção 6) mostra o que está por trás delas.', P)]

    # ---------- M4
    st += [CondPageBreak(8 * cm), Paragraph('3. Impressão digital comparecimento × voto (M4)', H2),
           Paragraph('Método de Klimek e coautores (PNAS, 2012): enchimento de urna aparece como um acúmulo de seções com comparecimento e '
                     'fatia do vencedor altos ao mesmo tempo. Comparamos o histograma observado com o simulado (8 repetições) a partir do '
                     'modelo do local, para comparecimento e voto.', P),
           fig_img(fig_impressao(), w=25)]
    t = [['Canto', '2022 obs.', '2022 sim.', '2022 (desvios)', '2026 obs.', '2026 sim.', '2026 (desvios)']]
    for k, txt in (('canto_comp90_PT90', 'comparec. ≥ 90% e PT ≥ 90%'), ('canto_comp95_PT95', 'comparec. ≥ 95% e PT ≥ 95%'),
                   ('canto_comp90_adv90', 'comparec. ≥ 90% e adversário ≥ 90%'), ('canto_comp95_adv95', 'comparec. ≥ 95% e adversário ≥ 95%')):
        t.append([txt] + [n(rr[f'm4_{k}_{c}'], 1 if c != 'z' else 2) for rr in (r22, r26) for c in ('obs', 'sim', 'z')])
    st += [table(t, font=7.5, widths=[6.2 * cm, 2.4 * cm, 2.4 * cm, 2.8 * cm, 2.4 * cm, 2.4 * cm, 2.8 * cm]),
           Paragraph(f'Célula com maior excesso em 2026: {r26.m4_celula_max_onde} ({n(r26.m4_celula_max_z, 1)} desvios); em 2022: '
                     f'{r22.m4_celula_max_onde} ({n(r22.m4_celula_max_z, 1)}). As faixas verticais do terceiro painel (vermelho no meio, azul nas '
                     'bordas) mostram que o comparecimento real varia menos de seção para seção do que o sorteio binomial supõe (dispersão '
                     f'{n(r26.m4_phi_comparecimento, 2)} em 2026 e {n(r22.m4_phi_comparecimento, 2)} em 2022, contra 1 no binomial). Os cantos de '
                     'comparecimento e fatia altos, onde o enchimento de urna aparece, ficam dentro do simulado. A cópia com enchimento plantado '
                     f'(0,5% das seções) é vista pela assinatura conjunta: {n(pl.set_index("tipo").loc["enchimento", "m4_conjunto_comp4_PT2"])} seções '
                     f'com comparecimento e voto altos ao mesmo tempo, contra {n(r26.m4_conjunto_comp4_PT2)} no real.', SM)]

    # ---------- M5
    u = pd.concat([r('m5_ufs_2022.csv'), r('m5_ufs_2026.csv')]).pivot(index='uf', columns='ano', values='residuo_pp')
    u = u.reindex(u[2026].abs().sort_values(ascending=False).index)
    t = [['UF', 'Resíduo 2022\n(pontos)', 'Resíduo 2026\n(pontos)']] + [[k, sn(v[2022], 2), sn(v[2026], 2)] for k, v in u.head(10).iterrows()]
    st += [CondPageBreak(7 * cm), Paragraph('4. Municípios e UFs previstos pelas outras UFs (M5)', H2),
           Paragraph('Cada município é previsto por um modelo treinado só com os municípios das outras UFs (composição do 1º turno). Se uma UF '
                     'inteira tivesse uma mudança “suave” e igual, ela apareceria aqui como resíduo da UF. Desvio-padrão entre municípios: '
                     f'{n(r22.m5_mun_dp_pp, 2)} ponto em 2022 e {n(r26.m5_mun_dp_pp, 2)} em 2026.', P),
           table(t, font=7.5, widths=[2 * cm, 3.4 * cm, 3.4 * cm])]
    rs = pl[pl.tipo == 'regional_suave']
    if len(rs) and isinstance(rs.iloc[0].get('m5_residuos_uf'), str):
        import json
        x = rs.iloc[0]
        uf_p = x.uf
        antes = json.loads(r26.m5_residuos_uf)[uf_p]
        depois = json.loads(x.m5_residuos_uf)
        pos = sorted(depois, key=lambda k: -abs(depois[k])).index(uf_p) + 1
        st += [Paragraph(f'Na cópia “regional suave” ({uf_p}, 2% dos votos do adversário passados para o PT em todas as seções, '
                         f'{n(x.votos_movidos)} votos), o resíduo de {uf_p} foi de {sn(antes, 2)} para {sn(depois[uf_p], 2)} ponto, o '
                         f'{pos}º maior entre as UFs. A variação natural entre UFs é dessa ordem: uma mudança assim fica no limite do que '
                         'o modelo regional distingue.', SM)]

    # ---------- M6
    h = r('m6_horario.csv')
    t = [['Ano', 'Variável', 'Seções com', 'Efeito no PT\n(pontos)', 't', 'Efeito com\ncontroles', 't com\ncontroles']]
    for y in h.itertuples():
        t.append([y.ano, y.variavel.replace('_', ' '), n(y.secoes_com), sn(y.efeito_pp, 3), n(y.t, 1), sn(y.efeito_pp_com_controles, 3),
                  n(y.t_com_controles, 1)])
    st += [CondPageBreak(7 * cm), Paragraph('5. Horário: seções que votaram até tarde × vizinhas (M6)', H2),
           Paragraph('O RDV não tem horário, mas o log diz quantos votos cada seção recebeu depois das 17h e das 19h. Se os votos tardios '
                     'fossem diferentes (ou alterados), a fatia do PT nessas seções sairia do previsto, e mais quanto maior a fração tardia. '
                     'Comparação dentro do mesmo local, com o resíduo do M1.', P),
           table(t, font=7.5, widths=[1.6 * cm, 6 * cm, 2.6 * cm, 3.4 * cm, 1.8 * cm, 3.2 * cm, 2.4 * cm]),
           Paragraph('Controles: mudança de comparecimento do 1º para o 2º turno, tamanho da seção e liberação manual, todos comparados dentro '
                     'do local. Se o efeito some com os controles, ele vem do perfil das seções (mais gente votando no 2º turno), não do horário.', SM)]
    if (D / 'm6_controle_2022.csv').exists():
        k = r('m6_controle_2022.csv')
        t = [['Ano', 'Versão', 'Seções', 'Locais', 'Com voto\ndepois das 17h', 'Votos depois\ndas 17h', 'Efeito no PT\n(pontos)', 't']]
        for y in k.itertuples():
            t.append([y.ano, y.versao, n(y.secoes), n(y.locais), n(y.secoes_com_voto_apos_17h), n(y.votos_apos_17h),
                      f'{sn(y.efeito_pp, 3)} ± {n(y.ep_pp, 3)}', n(y.t, 1)])
        kk = k[k.versao == 'com tamanho'].set_index('ano')
        st += [Paragraph('Controle: a mesma medida em 2022', H2),
               Paragraph('Em 2022 não há o resumo de horário de todas as urnas; por isso a comparação usa, nos dois anos, a mesma regra: locais '
                         'em que alguma seção encerrou depois das 17h15 (filas no fim do dia). Nesses locais, o log de 2022 foi lido seção a seção '
                         'para contar os votos dados depois das 17h.', P),
               table(t, font=7.5, widths=[1.6 * cm, 3.2 * cm, 2.2 * cm, 2 * cm, 3 * cm, 2.8 * cm, 4.2 * cm, 1.6 * cm]),
               Paragraph(f'Com a mesma regra, seções com voto depois das 17h ficaram {sn(kk.loc[2022, "efeito_pp"], 2)} ponto em relação às vizinhas em '
                         f'2022 (t = {n(kk.loc[2022, "t"], 1)}) e {sn(kk.loc[2026, "efeito_pp"], 2)} em 2026 (t = {n(kk.loc[2026, "t"], 1)}).', SM)]

    # ---------- logs
    if (D / 'logs_eventos.csv').exists():
        e = r('logs_eventos.csv')
        c = r('logs_continuas.csv')
        rg = r('logs_resumo_grupos.csv').set_index('grupo')
        NG = {'fora_voto': 'voto fora dos modelos (M1 ou M2)', 'fora_multivariado': 'fora só no vetor de mudança (M3)',
              'tarde': 'período tardio', 'vizinhas': 'vizinhas do mesmo local'}
        st += [CondPageBreak(8 * cm), Paragraph('6. Perícia de log: seções destoantes e período tardio × vizinhas', H2),
               Paragraph('Logs lidos de três grupos e de vizinhas dos mesmos locais como controle: seções cujo voto saiu dos modelos (M1 ou M2), '
                         'seções que saíram só no vetor de mudança (M3: comparecimento, brancos/nulos, liberação manual) e seções do período '
                         'tardio (voto depois das 19h, 5 ou mais votos depois das 17h ou encerramento depois das 19h). Para cada tipo de evento do '
                         'log, o teste de Cochran-Mantel-Haenszel compara, local por local, a presença do evento no grupo e nas vizinhas; para ritmo, '
                         'pausas, habilitação manual, horário e resultado, a diferença média dentro do local. q = p corrigido para muitos testes '
                         '(Benjamini-Hochberg).', P)]
        t = [['Grupo', 'Seções', 'Troca de urna\n(contingência)', 'Cancelaram o\nencerramento', 'Fora a favor\ndo PT', 'Fora a favor\ndo adversário',
              'PT × vizinhas\n(pontos)']]
        for g in ('fora_voto', 'fora_multivariado', 'tarde', 'vizinhas'):
            if g not in rg.index:
                continue
            y = rg.loc[g]
            t.append([NG[g], n(y.secoes), n(y.contingencia_pct, 1) + '%', n(y.cancelou_encerramento_pct, 1) + '%',
                      n(y.a_favor_PT) if g != 'vizinhas' else '—', n(y.a_favor_adversario) if g != 'vizinhas' else '—',
                      f'{sn(y.diferenca_res_pp, 2)} ± {n(y.ep_res_pp, 2)}' if pd.notna(y.diferenca_res_pp) else '—'])
        st += [table(t, font=7.5, widths=[6.4 * cm, 2 * cm, 3.2 * cm, 3 * cm, 2.6 * cm, 2.8 * cm, 3.6 * cm]),
               Paragraph('Na última coluna, a diferença da fatia do PT (resíduo do modelo do local) entre o grupo e as vizinhas do mesmo local; '
                         'para o grupo “voto fora dos modelos” ela é grande por construção, porque foi assim que o grupo foi escolhido.', SM),
               fig_img(fig_perfil(), w=22)]
        for g, txt in (('fora_voto', 'voto fora dos modelos'), ('fora_multivariado', 'fora só no vetor de mudança'), ('tarde', 'período tardio')):
            x = e[(e.grupo == g)].sort_values('p').head(8)
            t = [['Evento do log', '% no grupo', '% vizinhas', 'z (CMH)', 'q']]
            for y in x.itertuples():
                t.append([y.evento.split(' | ')[-1], n(y.pct_grupo, 1), n(y.pct_vizinhas, 1), n(y.z, 1), n(y.q_bh, 3)])
            st += [CondPageBreak(5 * cm), Paragraph(f'Eventos que mais diferem: {txt}', H2),
                   table(t, font=7, widths=[13 * cm, 2.4 * cm, 2.4 * cm, 2 * cm, 2 * cm])]
            x = c[(c.grupo == g)].sort_values('p').head(8)
            t = [['Medida', 'Grupo', 'Vizinhas', 'Diferença\n(dentro do local)', 'Erro-padrão', 'q']]
            for y in x.itertuples():
                if y.variavel in HORA:
                    t.append([rotulo(y.variavel), hm(y.media_grupo), hm(y.media_vizinhas), sn(y.diferenca, 0) + ' min', n(y.ep, 1), n(y.q_bh, 3)])
                else:
                    t.append([rotulo(y.variavel), n(y.media_grupo, 2), n(y.media_vizinhas, 2), sn(y.diferenca, 2), n(y.ep, 2), n(y.q_bh, 3)])
            st += [table(t, font=7, widths=[7 * cm, 2.4 * cm, 2.4 * cm, 3.4 * cm, 2.4 * cm, 2 * cm])]

    # ---------- gatilho
    if (G / 'varredura_codigos_2026t2.csv').exists():
        v = pd.read_csv(G / 'varredura_codigos_2026t2.csv', dtype={'codigo': str}, **CSV)
        cb = pd.read_csv(G / 'calibracao_gatilho_plantado.csv', dtype={'codigo': str}, **CSV)
        cf = pd.read_csv(G / 'rdv_x_bu_2026t2.csv', **CSV).iloc[0]
        lim = float(v.limite_bonferroni_t.iloc[0])
        st += [CondPageBreak(6 * cm), Paragraph('7. Gatilho digitado (RDV)', H2),
               Paragraph(f'O RDV de presidente de {n(cf.secoes_com_rdv)} seções foi lido; em {n(cf.rdv_igual_bu)} ele soma exatamente o BU. No voto '
                         f'nulo, o RDV guarda o número digitado. Para cada um dos {len(v)} números digitados em 30+ seções, as seções com esse número '
                         f'foram comparadas com as vizinhas do mesmo local. {int((v.t.abs() > lim).sum())} códigos passam do limite '
                         f'(|t| > {n(lim, 2)}), com efeito de no máximo {n(v[v.t.abs() > lim].efeito_pp.abs().max(), 2)} ponto e t de no '
                         f'máximo {n(v.t.abs().max(), 1)}. Aparecem em dezenas de milhares de seções, vários coincidem com números de partido (11, 12, '
                         f'15; o 14 foi o de Renan Santos no 1º turno) e o efeito cresce com o número de vezes que o código foi digitado, o que aponta '
                         f'para o perfil do eleitor e não para um gatilho, que seria disparado por uma digitação só. Os gatilhos plantados (2 de cada 3 votos ou 1 em 3, em 20% ou mais das seções com o código) deram t '
                         f'entre {n(cb[cb.fracao_ativa >= .2].t.abs().min(), 0)} e {n(cb[cb.fracao_ativa >= .2].t.abs().max(), 0)}. Um gatilho '
                         f'usado em só 10 a 100 seções ficaria abaixo do limite. Detalhes em RDV_GATILHO.pdf.', P)]

    st += [CondPageBreak(5 * cm), Paragraph('8. Limites', H2),
           Paragraph('Os modelos medem se o resultado de cada seção, local, município ou UF segue o padrão do próprio 1º turno e das vizinhas. Uma '
                     'mudança suave, proporcional e igual em todo o país não deixa marca relativa e não seria vista; nenhuma das bases públicas tem '
                     'o voto com horário (o voto é secreto). O teste físico continua sendo o teste de integridade (cédulas × BU, e idealmente × RDV). '
                     'Seção destoante não significa irregularidade: é uma seção cujo resultado merece ser conferido nos documentos daquela urna.', P),
           Paragraph('Como repetir: scripts/anomalias_2t.py secoes; scripts/anomalias_logs.py coleta e compara; scripts/rdv_gatilho.py coleta e '
                     'analisa; scripts/make_anomalias_report.py. Tabelas em ANOMALIAS_2T.xlsx e nos CSVs da pasta.', SM)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7)
        cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(D / 'ANOMALIAS_2T.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='2º turno de 2026: padrão destoante em todas as urnas', author='AuditaBR').build(
        st, onFirstPage=footer, onLaterPages=footer)
    print('OK', D / 'ANOMALIAS_2T.pdf')

    lim = s26[(s26.z.abs() > 4) | (s26.z_m2.abs() > 4)].copy()
    lim['pt_1t_pct'] = 100 * lim.t1_X / lim.n1
    lim['pt_2t_pct'] = 100 * lim.t2_X / lim.n2
    lim['previsto_m2_pct'] = 100 * lim.p_m2
    lim.sort_values('z_m2', key=np.abs, ascending=False).drop(columns=['p_loo', 'p_m2']).to_csv(D / 'secoes_destoantes_2026.csv', sep=';',
                                                                                              decimal=',', index=False, encoding='utf-8-sig')
    from ultimo_voto_2026t2 import xlsx_leve
    xlsx_leve(D / 'ANOMALIAS_2T.xlsx', [(p.stem[:31], pd.read_csv(p, low_memory=False, **CSV)) for p in sorted(D.glob('*.csv'))])
    print('OK', D / 'ANOMALIAS_2T.xlsx')


if __name__ == '__main__':
    main()
