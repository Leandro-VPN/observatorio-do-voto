"""Investigação dos itens "destoantes" da varredura por janelas (passo seguinte previsto na seção 7 do protocolo).

1. Gradiente do dia inteiro (reta 10:45–fim; UF SP; inversão nacional), destoante por ter sinal contrário em 2022:
   (a) a reta por UF e por tamanho de município, 2026 × 2022: um programa uniforme daria a mesma reta em todo lugar;
   (b) a reta por hora do dia (fatias horárias, multivariado), 2026 × 2022;
   (c) a cópia plantada mais parecida: regra "2 para 1" fraca e uniforme em todas as seções do país, a tarde inteira,
       calibrada para dar a mesma reta nacional de 2026 — o que a bateria (curvatura, dispersão, por UF) vê nela e no real.
2. Inversão na UF PR, 12:00–17:00 (t −7,9; 2022: 3,7): por município, influência de cada município (deixa um fora) e
   robustez sem as seções mais extremas.
3. Dispersão da inversão, 07:00–15:30 (t 4,1, limite 3,9): por UF e robustez sem as seções de maior z².

Saída: relatorios/verificacoes/janelas_horario/DESTOANTES.pdf e destoantes_*.csv. Como repetir: python scripts/janelas_destoantes.py
"""
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
import janelas_horario as jh  # noqa: E402
from janelas_horario import MIN_PREDIOS, Exposicoes, Teste, _curvatura, _planta, prepara, res_m1  # noqa: E402

OUT = ROOT / 'relatorios' / 'verificacoes' / 'janelas_horario'
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
JANELA = {2026: ('10:45', '18:45'), 2022: ('10:30', '17:15')}     # pico da reta em cada ano (mesma região da grade)
JANELA_PR = ('12:00', '17:00')
JANELA_DISP = ('07:00', '15:30')
HORAS = list(range(7, 18))                                        # fatias 07h–08h ... 17h–18h (resto do dia = referência)
NOME = {2026: 'Lula × Flávio (2026)', 2022: 'Lula × Bolsonaro (2022)'}
TINTA, TINTA2, AZUL, LARANJA, CINZA = '#1a365d', '#6b7280', '#2b6cb0', '#dd6b20', '#9ca3af'


def b(hhmm):
    h, m = hhmm.split(':')
    return (int(h) * 60 + int(m) - 300) // 15


def coluna(e, jan):
    return Exposicoes(e, [(b(jan[0]), b(jan[1]))]).coluna(0)


def reta(e, x, y, sinal=None):
    """beta (pontos por 100% de exposição), ep, t da reta dentro do prédio com controles, no subconjunto e."""
    T = Teste(e)
    r = T.roda(y, [x[:, None]], sinal).iloc[0]
    return float(r.beta_pp), float(r.ep_pp), float(r.t), T


def ols_agrupado(T, X, y, sinal=None):
    """Regressão multivariada de y nas colunas de X, dentro do prédio, com controles e erro-padrão agrupado por prédio."""
    Xr = T.residualiza(X, sinal)
    yr = T.yres(y, sinal)
    beta = np.linalg.lstsq(Xr, yr, rcond=None)[0]
    u = yr - Xr @ beta
    S = np.add.reduceat(Xr * u[:, None], T.starts, axis=0)
    inv = np.linalg.pinv(Xr.T @ Xr)
    V = inv @ (S.T @ S) @ inv
    return beta, np.sqrt(np.diag(V))


def por_grupo(e, x, y, chave, sinal=None, minimo=MIN_PREDIOS):
    """A reta refeita dentro de cada grupo (UF, faixa de tamanho, município) com pelo menos `minimo` prédios."""
    out = []
    for g, idx in e.groupby(chave, sort=True).indices.items():
        sub = e.iloc[idx]
        if sub.place.nunique() < minimo:
            continue
        s = None if sinal is None else sinal[idx]
        beta, ep, t, _ = reta(sub, x[idx], y[idx], s)
        out.append(dict(grupo=g, secoes=len(idx), predios=int(sub.place.nunique()), beta_pp=beta, ep_pp=ep, t=t))
    return pd.DataFrame(out)


def heterogeneidade(df, sinal_nacional):
    """Como as retas por UF se espalham: quantas têm o sinal nacional (com |t| > 2), quantas o contrário, amplitude, e a
    correlação com a fatia do adversário na UF (numa regra "2 para 1" uniforme, o efeito é proporcional a essa fatia)."""
    w = 1 / df.ep_pp ** 2
    m = (w * df.beta_pp).sum() / w.sum()
    Q = float((w * (df.beta_pp - m) ** 2).sum())
    k = len(df)
    I2 = max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0.0
    mesmo = int(((np.sign(df.beta_pp) == sinal_nacional) & (df.t.abs() > 2)).sum())
    contra = int(((np.sign(df.beta_pp) == -sinal_nacional) & (df.t.abs() > 2)).sum())
    corr_adv = float(np.corrcoef(df.beta_pp, df.fatia_adversario)[0, 1]) if 'fatia_adversario' in df else np.nan
    return dict(media_ponderada=float(m), Q=Q, gl=k - 1, I2=I2, mesmo_sinal=mesmo, sinal_contrario=contra, minimo=float(df.beta_pp.min()),
                maximo=float(df.beta_pp.max()), corr_fatia_adversario=corr_adv, n=k)


def fatia_adversario(e):
    g = e.groupby('uf')
    return (g.t2_Y.sum() / (g.t2_X.sum() + g.t2_Y.sum())).rename('fatia_adversario')


def faixa_tamanho(e):
    n = e.groupby(['uf', 'municipality']).section.transform('size')
    return pd.cut(n, [0, 50, 200, 1000, 10**6], labels=['até 50 seções', '50–200', '200–1.000', 'mais de 1.000']).astype(str)


def fatias_horarias(e):
    H = e[jh.BINS].to_numpy(float)
    tot = H.sum(1)
    cols = []
    for h in HORAS:
        i0, i1 = b(f'{h:02d}:00'), b(f'{h + 1:02d}:00')
        cols.append(H[:, i0:i1].sum(1) / tot)
    return np.column_stack(cols)


# ----------------------------------------------------------------------------------------------------------------------- 1. gradiente
def gradiente(ano, e):
    y = e.res_pp.to_numpy(float)
    x = coluna(e, JANELA[ano])
    beta, ep, t, T = reta(e, x, y)
    uf = por_grupo(e, x, y, 'uf').merge(fatia_adversario(e), left_on='grupo', right_index=True, how='left')
    e = e.assign(faixa=faixa_tamanho(e))
    fx = por_grupo(e, x, y, 'faixa')
    lider = por_grupo(e, x, y, e.sinal_t1.map({1: 'Lula liderava no 1º turno', -1: 'adversário liderava'}).rename('lider'))
    Xh = fatias_horarias(e)
    bh, eh = ols_agrupado(T, Xh, y)
    horas = pd.DataFrame({'hora': [f'{h:02d}h–{h + 1:02d}h' for h in HORAS], 'beta_pp': bh, 'ep_pp': eh, 't': bh / eh, 'fatia_media': Xh.mean(0)})
    return dict(beta=beta, ep=ep, t=t, uf=uf, faixa=fx, lider=lider, horas=horas, het_uf=heterogeneidade(uf, np.sign(beta)))


def plantada(e, alvo_beta):
    """Regra '2 para 1' uniforme na janela 10:45–fim, fraca: a fração q da exposição que reproduz a reta real de 2026."""
    y = e.res_pp.to_numpy(float)
    x = coluna(e, JANELA[2026])
    T = Teste(e)
    # a cópia plantada guarda o gradiente real por baixo; o que interessa é a contribuição da regra = cópia − real
    d1 = np.asarray(_planta(e, x, '2_para_1'), float) - y        # regra cheia (metade dos votos do adversário na janela)
    b1 = T.roda(d1, [x[:, None]]).iloc[0].beta_pp
    q = float(alvo_beta / b1)
    yq, zq = _planta(e, q * x, '2_para_1', com_z=True)
    d = np.asarray(yq, float) - y
    beta, ep, t, _ = reta(e, x, d)
    yr = T.yres(d)
    c, perfil = _curvatura(T, x, yr)
    xr = T.residualiza(x[:, None])[:, 0]
    z2r = T.yres(np.asarray(zq) ** 2)
    _, _, td = jh._ols1(xr, z2r, T.starts)
    uf = por_grupo(e, x, d, 'uf').merge(fatia_adversario(e), left_on='grupo', right_index=True, how='left')
    Xh = fatias_horarias(e)
    bh, eh = ols_agrupado(T, Xh, d)
    horas = pd.DataFrame({'hora': [f'{h:02d}h–{h + 1:02d}h' for h in HORAS], 'beta_pp': bh, 'ep_pp': eh, 't': bh / eh})
    # o real, para comparar na mesma base
    yr_real = T.yres(y)
    c_real, _ = _curvatura(T, x, yr_real)
    _, z_real = res_m1(e, e.t2_X.to_numpy(float), e.t2_Y.to_numpy(float), com_z=True)
    _, _, td_real = jh._ols1(xr, T.yres(np.asarray(z_real) ** 2), T.starts)
    return dict(q=q, beta_cheia=float(b1), beta=beta, ep=ep, t=t, t_curvatura=c['t_curvatura'], t_dispersao=float(td), uf=uf, horas=horas,
                het_uf=heterogeneidade(uf, np.sign(beta)), real_t_curvatura=c_real['t_curvatura'], real_t_dispersao=float(td_real),
                votos_convertidos=float(0.5 * q * (x * e.t2_Y.to_numpy(float)).sum()), votos_adversario_janela=float((x * e.t2_Y.to_numpy(float)).sum()))


# ----------------------------------------------------------------------------------------------------------------------- 2. inversão PR
def inversao_pr(e):
    pr = e[e.uf == 'PR']
    y = pr.res_pp.to_numpy(float)
    s = pr.sinal_t1.to_numpy(float)
    x = coluna(pr, JANELA_PR)
    beta, ep, t, T = reta(pr, x, y, s)
    mun = por_grupo(pr, x, y, 'municipality', s)
    nomes = pd.read_parquet(jh.BASE / 'base_2026.parquet', columns=['uf', 'municipality', 'municipio'])
    nomes = nomes[nomes.uf == 'PR'].drop_duplicates('municipality').set_index('municipality').municipio
    mun['municipio'] = mun.grupo.map(nomes)
    # deixa um município fora de cada vez: quanto o t da UF depende dele
    loo = []
    for m, idx in pr.groupby('municipality').indices.items():
        if len(idx) < 50:
            continue
        keep = np.ones(len(pr), bool)
        keep[idx] = False
        sub = pr[keep]
        _, _, t_sem, _ = reta(sub, x[keep], y[keep], s[keep])
        loo.append(dict(municipality=m, municipio=nomes[m], secoes=len(idx), t_sem_ele=t_sem))
    loo = pd.DataFrame(loo).sort_values('t_sem_ele', ascending=False)
    # robustez: sem as seções de resíduo mais extremo (1% de cada lado)
    yr = T.yres(y, s)
    lo, hi = np.quantile(yr, [.01, .99])
    keep = (yr > lo) & (yr < hi)
    _, _, t_rob, _ = reta(pr[keep], x[keep], y[keep], s[keep])
    # a mesma janela nos outros estados do Sul e no país
    outros = por_grupo(e[e.uf.isin(['PR', 'SC', 'RS', 'SP'])], coluna(e[e.uf.isin(['PR', 'SC', 'RS', 'SP'])], JANELA_PR),
                       e[e.uf.isin(['PR', 'SC', 'RS', 'SP'])].res_pp.to_numpy(float), 'uf', e[e.uf.isin(['PR', 'SC', 'RS', 'SP'])].sinal_t1.to_numpy(float))
    return dict(beta=beta, ep=ep, t=t, mun=mun.sort_values('t'), loo=loo, t_robusto=float(t_rob), secoes_fora=int((~keep).sum()), outros=outros,
                lider=pd.Series(s).value_counts().to_dict())


# ----------------------------------------------------------------------------------------------------------------------- 3. dispersão
def dispersao(e):
    y = e.res_pp.to_numpy(float)
    s = e.sinal_t1.to_numpy(float)
    x = coluna(e, JANELA_DISP)
    _, z = res_m1(e, e.t2_X.to_numpy(float), e.t2_Y.to_numpy(float), com_z=True)
    z2 = np.asarray(z) ** 2
    beta, ep, t, T = reta(e, x, z2, s)
    uf = por_grupo(e, x, z2, 'uf', s)
    lo = np.quantile(z2, .99)
    keep = z2 < lo
    _, _, t_rob, _ = reta(e[keep], x[keep], z2[keep], s[keep])
    beta_r, ep_r, t_r, _ = reta(e, x, y, s)
    return dict(beta=beta, ep=ep, t=t, uf=uf.sort_values('t'), t_robusto=float(t_rob), secoes_fora=int((~keep).sum()), t_reta=t_r)


# ----------------------------------------------------------------------------------------------------------------------- figuras
def _eixos(ax):
    ax.tick_params(colors=TINTA2, labelsize=7)
    for sp in ax.spines.values():
        sp.set_color('#cccccc')
    ax.grid(True, color='#eeeeee', lw=.5)


def fig_uf(G, Pl):
    fig, axs = plt.subplots(1, 2, figsize=(14, 5.5))
    ax = axs[0]
    m = G[2026]['uf'].merge(G[2022]['uf'], on='grupo', suffixes=('_26', '_22'))
    ax.errorbar(m.beta_pp_22, m.beta_pp_26, xerr=1.96 * m.ep_pp_22, yerr=1.96 * m.ep_pp_26, fmt='o', ms=4, color=AZUL, ecolor=CINZA, lw=.7)
    for r in m.itertuples():
        ax.annotate(r.grupo, (r.beta_pp_22, r.beta_pp_26), xytext=(3, 3), textcoords='offset points', fontsize=7, color=TINTA2)
    ax.axhline(0, color=CINZA, lw=.7); ax.axvline(0, color=CINZA, lw=.7)
    ax.set_xlabel('2022: reta por UF (pontos por 100% de exposição à tarde)', fontsize=8, color=TINTA2)
    ax.set_ylabel('2026: reta por UF', fontsize=8, color=TINTA2)
    ax.set_title(f'Reta por UF: 2026 × 2022 (correlação {np.corrcoef(m.beta_pp_22, m.beta_pp_26)[0, 1]:+.2f})', fontsize=9, color=TINTA)
    _eixos(ax)
    ax = axs[1]
    u26, up = G[2026]['uf'].sort_values('beta_pp'), Pl['uf'].set_index('grupo')
    yy = np.arange(len(u26))
    ax.errorbar(u26.beta_pp, yy, xerr=1.96 * u26.ep_pp, fmt='o', ms=4, color=AZUL, ecolor=CINZA, lw=.7, label='2026 real')
    ax.errorbar(up.loc[u26.grupo].beta_pp, yy + .25, xerr=1.96 * up.loc[u26.grupo].ep_pp, fmt='s', ms=3, color=LARANJA, ecolor='#f6c9a8', lw=.7,
                label='cópia plantada (regra uniforme)')
    ax.set_yticks(yy); ax.set_yticklabels(u26.grupo, fontsize=7)
    ax.axvline(0, color=CINZA, lw=.7)
    ax.set_xlabel('reta por UF (pontos por 100% de exposição)', fontsize=8, color=TINTA2)
    ax.set_title('2026 real × cópia com regra uniforme calibrada na mesma reta nacional', fontsize=9, color=TINTA)
    ax.legend(fontsize=7, frameon=False); _eixos(ax)
    fig.tight_layout(); p = OUT / 'figuras' / 'destoantes_uf.png'; fig.savefig(p, dpi=130); plt.close(fig)
    return p


def fig_horas(G, Pl):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    xx = np.arange(len(HORAS))
    for nome, h, cor, dx in ((NOME[2026], G[2026]['horas'], AZUL, -.2), (NOME[2022], G[2022]['horas'], '#9ecae1', 0), ('cópia plantada (2026 + regra uniforme)', Pl['horas'], LARANJA, .2)):
        ax.errorbar(xx + dx, h.beta_pp, yerr=1.96 * h.ep_pp, fmt='o-', ms=3.5, lw=1, color=cor, ecolor=cor, label=nome)
    ax.axhline(0, color=CINZA, lw=.7)
    ax.set_xticks(xx); ax.set_xticklabels(G[2026]['horas'].hora, fontsize=7)
    ax.set_ylabel('pontos por 100% da fatia da seção naquela hora\n(em relação ao resto do dia)', fontsize=8, color=TINTA2)
    ax.set_title('A reta hora a hora, dentro do prédio e com controles', fontsize=9, color=TINTA)
    ax.legend(fontsize=7, frameon=False); _eixos(ax)
    fig.tight_layout(); p = OUT / 'figuras' / 'destoantes_horas.png'; fig.savefig(p, dpi=130); plt.close(fig)
    return p


def fig_pr(I):
    fig, axs = plt.subplots(1, 2, figsize=(14, 5))
    ax = axs[0]
    m = I['mun']
    ax.errorbar(m.t, np.arange(len(m)), fmt='o', ms=3.5, color=AZUL)
    ax.set_yticks(np.arange(len(m))); ax.set_yticklabels([f'{r.municipio.title()} ({r.secoes})' for r in m.itertuples()], fontsize=6)
    ax.axvline(0, color=CINZA, lw=.7)
    ax.set_xlabel('t da inversão no município (12:00–17:00)', fontsize=8, color=TINTA2)
    ax.set_title('PR: a inversão por município (30 prédios ou mais)', fontsize=9, color=TINTA); _eixos(ax)
    ax = axs[1]
    l = I['loo'].head(12)
    ax.barh(np.arange(len(l)), l.t_sem_ele, color=AZUL)
    ax.set_yticks(np.arange(len(l))); ax.set_yticklabels([f'sem {r.municipio.title()}' for r in l.itertuples()], fontsize=7)
    ax.axvline(I['t'], color=LARANJA, lw=1, label=f't da UF com todos: {I["t"]:.1f}')
    ax.set_xlabel('t da UF deixando o município de fora', fontsize=8, color=TINTA2)
    ax.set_title('Quanto o t da UF depende de cada município (os 12 que mais pesam)', fontsize=9, color=TINTA)
    ax.legend(fontsize=7, frameon=False); _eixos(ax)
    fig.tight_layout(); p = OUT / 'figuras' / 'destoantes_pr.png'; fig.savefig(p, dpi=130); plt.close(fig)
    return p


# ----------------------------------------------------------------------------------------------------------------------- relatório
def relatorio(G, Pl, I, D, figs):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate
    from make_bahia_reports import H1, H2, P, SM, fig_img, n, table
    from make_padroes_report import sn

    g26, g22 = G[2026], G[2022]
    m = g26['uf'].merge(g22['uf'], on='grupo', suffixes=('_26', '_22'))
    corr_uf = float(np.corrcoef(m.beta_pp_22, m.beta_pp_26)[0, 1])
    h26, h22, hp = g26['het_uf'], g22['het_uf'], Pl['het_uf']
    ufs_pos_26 = int((m.beta_pp_26 > 0).sum())
    ufs_neg_22 = int((m.beta_pp_22 < 0).sum())
    hr26, hr22, hrp = g26['horas'], g22['horas'], Pl['horas']
    st = [Paragraph('Os itens destoantes da varredura por janelas: o passo seguinte do protocolo', H1),
          Paragraph('O PROTOCOLO (seção 7) manda, para o que fica “destoante”, comparar com o cenário plantado mais parecido e ler o que as seções '
                    'apontadas têm. Este relatório faz isso para os três itens da tabela de vereditos: o gradiente do dia inteiro (reta, UF SP e inversão '
                    'nacional, com sinal contrário em 2022), a inversão na UF PR entre 12h e 17h e a dispersão da inversão entre 7h e 15h30. Descritivo: '
                    'nenhuma medida aqui afirma irregularidade; o que se mede é se o sinal tem a forma de uma regra de programa ou a forma de comportamento.', P),
          Paragraph('1. O gradiente do dia inteiro', H2),
          Paragraph(f'Reta nacional na janela do pico: 2026 {sn(g26["beta"], 2)} pontos por 100% de exposição (t {n(g26["t"], 1)}); 2022 {sn(g22["beta"], 2)} '
                    f'(t {n(g22["t"], 1)}). <b>Por UF</b> (gráfico à esquerda e tabela): o gradiente é nacional nos dois anos — em 2026 a reta é positiva em '
                    f'{ufs_pos_26} das {len(m)} UFs ({h26["mesmo_sinal"]} com |t| > 2), de {sn(h26["minimo"], 1)} a {sn(h26["maximo"], 1)}; em 2022 é negativa em '
                    f'{ufs_neg_22} das {len(m)} ({h22["mesmo_sinal"]} com |t| > 2), de {sn(h22["minimo"], 1)} a {sn(h22["maximo"], 1)}. O tamanho por UF não se '
                    f'repete espelhado (correlação entre os anos {sn(corr_uf, 2)}), mas o sinal troca em todas. Por tamanho de município e por quem liderava a seção '
                    f'no 1º turno (tabela adiante), os valores de 2022 são o espelho dos de 2026.', P),
          Paragraph(f'<b>Cópia plantada mais parecida</b> (gráfico à direita): regra “2 para 1” uniforme em todas as seções do país, só nos votos da tarde '
                    f'(10:45 até o fim), fraca o bastante para dar a mesma reta nacional de 2026: converte {n(100 * Pl["q"] * .5, 1)}% dos votos do adversário '
                    f'dados à tarde ({n(Pl["votos_convertidos"] / 1e3, 0)} mil votos de {n(Pl["votos_adversario_janela"] / 1e6, 1)} milhões). O que se mede na '
                    f'cópia é só a contribuição da regra (cópia menos real, porque a cópia guarda o gradiente real por baixo): reta {sn(Pl["beta"], 2)} '
                    f'(t {n(Pl["t"], 1)}), igual à real por construção. Por UF, a regra também dá o mesmo sinal em toda parte, de {sn(hp["minimo"], 1)} a '
                    f'{sn(hp["maximo"], 1)}, e o tamanho acompanha a fatia do adversário na UF (correlação {sn(hp["corr_fatia_adversario"], 2)}; no real, '
                    f'{sn(h26["corr_fatia_adversario"], 2)}). Ou seja: o corte por UF não separa regra uniforme de comportamento nacional; o que separa é a hora a '
                    f'hora (adiante) e o fato de 2022 ter a mesma forma com o sinal trocado. Curvatura da contribuição da regra t equiv. {n(Pl["t_curvatura"], 1)} '
                    f'(o efeito de “2 para 1” é proporcional à fatia do adversário em cada seção, não só à exposição); real {n(Pl["real_t_curvatura"], 1)}. '
                    f'Dispersão da cópia completa t {n(Pl["t_dispersao"], 1)} (real {n(Pl["real_t_dispersao"], 1)}: uma regra uniforme não muda a dispersão).', P),
          fig_img(figs['uf'], w=25)]
    t = [['Grupo', '2026: reta', 'ep', 't', '2022: reta', 'ep', 't', 'Plantada: reta', 't']]
    pl = Pl['uf'].set_index('grupo')
    for r in m.itertuples():
        t.append([r.grupo, sn(r.beta_pp_26, 2), n(r.ep_pp_26, 2), n(r.t_26, 1), sn(r.beta_pp_22, 2), n(r.ep_pp_22, 2), n(r.t_22, 1),
                  sn(pl.loc[r.grupo, 'beta_pp'], 2) if r.grupo in pl.index else '–', n(pl.loc[r.grupo, 't'], 1) if r.grupo in pl.index else '–'])
    st += [CondPageBreak(8 * cm), Paragraph('Reta por UF (pontos por 100% de exposição à janela do pico)', H2),
           table(t, font=6.5, widths=[1.6 * cm, 2 * cm, 1.4 * cm, 1.4 * cm, 2 * cm, 1.4 * cm, 1.4 * cm, 2.4 * cm, 1.4 * cm])]
    t = [['Corte', 'Grupo', '2026: reta', 't', '2022: reta', 't']]
    for nome, k in (('tamanho do município', 'faixa'), ('quem liderava no 1º turno', 'lider')):
        a, c = g26[k].set_index('grupo'), g22[k].set_index('grupo')
        for gr in a.index:
            t.append([nome, gr, sn(a.loc[gr, 'beta_pp'], 2), n(a.loc[gr, 't'], 1), sn(c.loc[gr, 'beta_pp'], 2) if gr in c.index else '–', n(c.loc[gr, 't'], 1) if gr in c.index else '–'])
    st += [CondPageBreak(6 * cm), Paragraph('Reta por tamanho de município e por quem liderava a seção no 1º turno', H2),
           table(t, font=7, widths=[4.5 * cm, 4.5 * cm, 2.2 * cm, 1.6 * cm, 2.2 * cm, 1.6 * cm]),
           CondPageBreak(13 * cm), Paragraph('Hora a hora', H2),
           Paragraph(f'Em vez de uma janela, todas as fatias horárias de uma vez: o coeficiente de cada hora é o quanto a seção anda por ter mais votos '
                     f'naquela hora, em relação ao resto do dia (antes das 7h e depois das 18h), dentro do prédio e com controles. A regra uniforme da tarde '
                     f'dá degrau (linha laranja): {sn(hrp.beta_pp.iloc[1], 1)} às 8h, {sn(hrp.beta_pp.iloc[3], 1)} às 10h e um patamar de '
                     f'{sn(hrp.beta_pp.iloc[4:10].mean(), 1)} das 11h às 17h. O real de 2026 é uma rampa que sobe o dia inteiro, já de manhã: '
                     f'{sn(hr26.beta_pp.iloc[0], 1)} às 7h, {sn(hr26.beta_pp.iloc[3], 1)} às 10h, {sn(hr26.beta_pp.iloc[6], 1)} às 13h, '
                     f'{sn(hr26.beta_pp.iloc[9], 1)} às 16h e {sn(hr26.beta_pp.iloc[10], 1)} às 17h; não há degrau às 10h45 — a janela “10:45 até o fim” é só a '
                     f'janela da grade que melhor aproxima uma rampa. O de 2022 é a rampa espelhada: {sn(hr22.beta_pp.iloc[0], 1)} às 7h, '
                     f'{sn(hr22.beta_pp.iloc[6], 1)} às 13h, {sn(hr22.beta_pp.iloc[10], 1)} às 17h. Quanto mais tarde a seção vota, mais ela anda numa direção, '
                     f'e a direção é a oposta de 2022: isso tem a forma de quem vota em cada hora, não de uma regra ligada numa hora.', P),
           fig_img(figs['horas'], w=16)]
    # 2. PR
    top = I['mun'].head(5)
    st += [CondPageBreak(8 * cm), Paragraph('2. Inversão na UF PR, 12:00–17:00', H2),
           Paragraph(f'No PR, a seção com mais votos à tarde andou contra quem liderava nela no 1º turno: {sn(I["beta"], 2)} pontos por 100% de exposição '
                     f'(t {n(I["t"], 1)}); em 2022 a mesma janela no PR dá 3,7. Dentro do estado (gráfico à esquerda), {n(len(I["mun"]))} municípios têm 30 '
                     f'prédios ou mais; os de maior |t|: ' + '; '.join(f'{r.municipio.title()} ({n(r.t, 1)})' for r in top.itertuples()) +
                     f'. Deixando cada município de fora (gráfico à direita), o t da UF fica entre {n(I["loo"].t_sem_ele.min(), 1)} e '
                     f'{n(I["loo"].t_sem_ele.max(), 1)}: nenhum município sozinho faz o sinal. Sem as {n(I["secoes_fora"])} seções de resíduo mais extremo '
                     f'(1% de cada lado), t = {n(I["t_robusto"], 1)}. Nos vizinhos, a mesma janela dá: ' +
                     ', '.join(f'{r.grupo} {n(r.t, 1)}' for r in I['outros'].itertuples()) + '.', P),
           fig_img(figs['pr'], w=25),
           Paragraph('O que a inversão mede: a seção anda contra o seu líder do 1º turno na proporção dos votos da tarde. Como quem liderava em cada seção '
                     'do PR é, na maioria, o adversário de Lula, o sinal negativo é, na prática, parte do mesmo gradiente nacional (seções com mais votos à '
                     'tarde mais para Lula), concentrado num estado em que o líder de seção é quase sempre o mesmo. A régua plantada (inversão só em MG, '
                     '14h–15h) dá t da UF de −13,8 para uma inversão completa numa hora; o PR tem −7,9 numa janela de cinco horas. Sem candidato no log nem '
                     'ordem no RDV, não há como ler mais do que isso nas seções: fica registrado, sem conclusão.', P)]
    # 3. dispersão
    st += [CondPageBreak(6 * cm), Paragraph('3. Dispersão da inversão, 07:00–15:30', H2),
           Paragraph(f'O quadrado do resíduo de Pearson regredido na exposição × sinal dá t {n(D["t"], 1)} (limite por permutação 3,9); sem o 1% de seções de '
                     f'maior z² ({n(D["secoes_fora"])} seções), t = {n(D["t_robusto"], 1)}. Por UF, os maiores valores: ' +
                     ', '.join(f'{r.grupo} {n(r.t, 1)}' for r in D['uf'].tail(4).itertuples()) + '; os menores: ' +
                     ', '.join(f'{r.grupo} {n(r.t, 1)}' for r in D['uf'].head(3).itertuples()) +
                     '. Uma mistura (regra num subconjunto de seções) aparece como dispersão que cresce com a exposição em toda parte; aqui o valor é marginal, '
                     'muda com 1% das seções e não se repete por UF. Fica como está na tabela de vereditos: destoante por não ter contraparte em 2022, sem '
                     'forma de regra.', P),
           CondPageBreak(5 * cm), Paragraph('4. Leitura', H2),
           Paragraph('O gradiente do dia inteiro tem a forma de comportamento, não de regra ligada numa hora: é uma rampa contínua da manhã ao fim da tarde, '
                     'nacional (mesmo sinal em todas as UFs), com o mesmo desenho por tamanho de município e por líder de seção em 2022, espelhado. Uma regra '
                     'uniforme calibrada na mesma reta nacional também seria nacional, mas em degrau nas horas, e não existiria em 2022 com o sinal trocado. '
                     'A inversão no PR é o mesmo gradiente visto num estado onde o líder de seção é quase sempre o mesmo, sem município que a produza '
                     'sozinho e com o mesmo sinal nos vizinhos. A dispersão da inversão é marginal e some sem 1% das seções. Nada disso é conclusão sobre '
                     'causa; é a forma do sinal, que é o que os dados publicados permitem medir. Como repetir: scripts/janelas_destoantes.py.', P)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7)
        cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(OUT / 'DESTOANTES.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='Itens destoantes das janelas', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', OUT / 'DESTOANTES.pdf', flush=True)


def main():
    (OUT / 'figuras').mkdir(parents=True, exist_ok=True)
    G = {}
    e26 = prepara(2026)
    G[2026] = gradiente(2026, e26)
    print('2026 reta', round(G[2026]['beta'], 3), 't', round(G[2026]['t'], 1), '| I² UF', round(G[2026]['het_uf']['I2'], 3), flush=True)
    Pl = plantada(e26, G[2026]['beta'])
    print('plantada q', round(Pl['q'], 4), 'reta', round(Pl['beta'], 3), 't', round(Pl['t'], 1), '| I² UF', round(Pl['het_uf']['I2'], 3),
          '| curvatura', round(Pl['t_curvatura'], 1), 'real', round(Pl['real_t_curvatura'], 1), '| dispersão', round(Pl['t_dispersao'], 1), 'real', round(Pl['real_t_dispersao'], 1), flush=True)
    I = inversao_pr(e26)
    print('PR t', round(I['t'], 1), '| robusto', round(I['t_robusto'], 1), '| loo', round(I['loo'].t_sem_ele.min(), 1), round(I['loo'].t_sem_ele.max(), 1), flush=True)
    D = dispersao(e26)
    print('dispersão t', round(D['t'], 1), '| robusto', round(D['t_robusto'], 1), flush=True)
    del e26
    e22 = prepara(2022)
    G[2022] = gradiente(2022, e22)
    print('2022 reta', round(G[2022]['beta'], 3), 't', round(G[2022]['t'], 1), '| I² UF', round(G[2022]['het_uf']['I2'], 3), flush=True)
    del e22
    for ano in (2026, 2022):
        for k in ('uf', 'faixa', 'lider', 'horas'):
            G[ano][k].assign(ano=ano).to_csv(OUT / f'destoantes_gradiente_{k}_{ano}.csv', **CSV)
    Pl['uf'].to_csv(OUT / 'destoantes_plantada_uf.csv', **CSV)
    Pl['horas'].to_csv(OUT / 'destoantes_plantada_horas.csv', **CSV)
    I['mun'].to_csv(OUT / 'destoantes_pr_municipios.csv', **CSV)
    I['loo'].to_csv(OUT / 'destoantes_pr_deixa_um_fora.csv', **CSV)
    D['uf'].to_csv(OUT / 'destoantes_dispersao_uf.csv', **CSV)
    figs = dict(uf=fig_uf(G, Pl), horas=fig_horas(G, Pl), pr=fig_pr(I))
    relatorio(G, Pl, I, D, figs)


if __name__ == '__main__':
    main()
