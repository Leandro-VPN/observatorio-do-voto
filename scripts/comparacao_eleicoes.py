"""Comparação das quatro eleições presidenciais (2014, 2018, 2022, 2026) nas medidas do estudo de horário e do estudo de cidades.

O que cada eleição publicada permite: logs de urna com a hora de cada voto só em 2022 e 2026 (pacotes por UF dos dados abertos;
o sistema de resultados serve só os ciclos 2024 e 2026); em 2018 o boletim de urna traz a hora de abertura e de encerramento e a
habilitação sem biometria por seção; em 2014, só os votos.

1. Horário por procuração. Dentro do prédio, a seção que encerrou mais tarde teve mais votos no fim do dia (fila às 17h). A reta do
   resíduo M1 (% do PT observada − prevista pelas vizinhas e pelo próprio 1º turno) na cauda de encerramento (minutos depois da hora
   legal: 17h local em 2018, 17h de Brasília em 2022 e 2026; teto de 60 min) é refeita com a mesma especificação nas três eleições
   com hora, com os controles e o erro-padrão agrupado por prédio do estudo de janelas. Em 2022 e 2026 a mesma reta na fração de
   votos do log na última hora legal (16h–17h de Brasília e depois) e na tarde inteira diz quanto a procuração enxerga do gradiente.
2. Cidades. A régua de Campos (d = fatia dos votos em disputa que foi para o PT, cidade − estado; cidades com 10 mil votos em disputa
   ou mais; UFs com denominador degenerado fora) nas quatro eleições: quantas cidades ficam a 10 ou 20 pontos do estado em cada uma.
3. Dispersão. O resíduo padronizado z do modelo do prédio nas quatro eleições (variância, caudas), por fatia de votos de terceiros no
   1º turno, que é o que muda de 2014/2018 para 2022/2026.

Saída: relatorios/verificacoes/comparacao_eleicoes/COMPARACAO_ELEICOES.pdf e comparacao_*.csv.
Como repetir: python scripts/comparacao_eleicoes.py
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
import padroes_lib as L  # noqa: E402
from campos_2t import CAMPOS, UF as UF_CAMPOS  # noqa: E402
from janelas_destoantes import AZUL, CINZA, JANELA, LARANJA, TINTA, TINTA2, _eixos, b as bin_, por_grupo, reta  # noqa: E402
from janelas_horario import Exposicoes, Teste, res_m1  # noqa: E402
from padroes_2t import HORA_BSB, NOMES  # noqa: E402

OUT = ROOT / 'relatorios' / 'verificacoes' / 'comparacao_eleicoes'
BASE = ROOT / 'research' / 'padroes_2t'
BINS = ROOT / 'research' / 'janelas_horario'
PADROES = ROOT / 'relatorios' / 'verificacoes' / 'padroes_2t'
ANOS = (2014, 2018, 2022, 2026)
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
LEGAL = 17 * 60           # hora legal de encerramento (minutos)
CAUDA_MAX = 60            # teto da cauda de encerramento (min): além disso é contingência ou relógio, não fila
MIN_DISPUTA = 10_000
ROTULO = {a: f'{NOMES[a][0]} × {NOMES[a][1]} ({a})' for a in ANOS}
COR = {2014: '#b7b7b7', 2018: '#7f9fbf', 2022: '#9ecae1', 2026: AZUL}
TEM = {2014: 'votos por seção (boletim de urna)',
       2018: 'votos, hora de abertura e de encerramento e habilitação sem biometria por seção (boletim de urna)',
       2022: 'tudo isso e os logs de urna com a hora de cada voto (dados abertos, pacote por UF)',
       2026: 'tudo isso e os logs de urna com a hora de cada voto (dados abertos e sistema de resultados)'}


# ----------------------------------------------------------------------------------------------------------------------- bases
def _carrega(ano):
    b = pd.read_parquet(BASE / f'base_{ano}.parquet')
    d = L.prepara(L.formato_comum(b))
    for c in ('municipality', 'zone', 'section'):
        d[c] = d[c].astype(int)
    for c in ('municipio', 't1_validos', 't2_validos', 'desloc_h'):
        d[c] = b[c].to_numpy()
    if 't2_enc_min' in b:
        ref = b.t2_enc_bsb if HORA_BSB[ano] else b.t2_enc_min      # 2018: votação em hora local; 2022+: hora de Brasília
        d['cauda'] = (ref - LEGAL).clip(0, CAUDA_MAX).to_numpy()
    return d


def _arruma(e):
    """Prédios contíguos (k >= 3 seções), controles do estudo de janelas e resíduo M1 recalculado no subconjunto."""
    e = e.sort_values(jh.LOC + ['section']).reset_index(drop=True)
    e['place'] = e.groupby(jh.LOC, sort=False).ngroup()
    e['k'] = e.groupby('place').section.transform('size')
    e = e[e.k >= 3].sort_values('place', kind='stable').reset_index(drop=True)
    e['ctl_logn'] = np.log(e.n2)
    e['ctl_manual'] = (e.t2_manual / e.t2_comp.where(e.t2_comp > 0)).fillna(0)
    e['ctl_dcomp'] = (e.t2_comp / e.t2_aptos.where(e.t2_aptos > 0) - e.t1_comp / e.t1_aptos.where(e.t1_aptos > 0)).fillna(0)
    e['ctl_tx'] = (e.t2_comp / e.t2_aptos.where(e.t2_aptos > 0)).fillna(0)
    e['ctl_tx2'] = e.ctl_tx ** 2
    e['sinal_t1'] = np.sign(2 * e.t1_X / e.n1 - 1).replace(0, 1)
    e['sinal_tx'] = e.sinal_t1 * e.ctl_tx
    e['sinal_tx2'] = e.sinal_t1 * e.ctl_tx2
    res, z = res_m1(e, e.t2_X.to_numpy(float), e.t2_Y.to_numpy(float), com_z=True)
    e['res_pp'], e['z'] = res, z
    return e


def prepara(ano, com_bins=False):
    d = _carrega(ano)
    e = d[(d.n1 >= L.MIN_N) & (d.n2 >= L.MIN_N)].copy()
    if com_bins:
        h = pd.read_parquet(BINS / f'bins_{ano}.parquet', columns=jh.CHAVE + jh.BINS)
        for c in ('municipality', 'zone', 'section'):
            h[c] = h[c].astype(int)
        e = e.merge(h, on=jh.CHAVE, how='inner')
        votos_log = e[jh.BINS].sum(axis=1)
        e = e[(votos_log >= 20) & ((votos_log - e.t2_comp).abs() <= 5)].copy()     # mesmo filtro do estudo de janelas
    return _arruma(e)


# ----------------------------------------------------------------------------------------------------------------------- 1. horário por procuração
def horario(ano, e):
    e = _arruma(e[e.cauda.notna()])
    x = e.cauda.to_numpy(float) / 10                      # pontos por 10 minutos de cauda
    y = e.res_pp.to_numpy(float)
    s = e.sinal_t1.to_numpy(float)
    beta, ep, t, T = reta(e, x, y)
    bi, epi, ti, _ = reta(e, x, y, s)
    uf = por_grupo(e, x, y, 'uf')
    lider = por_grupo(e, x, y, e.sinal_t1.map({1: 'PT liderava a seção no 1º turno', -1: 'adversário liderava'}).rename('lider'))
    xr = T.residualiza(x[:, None])[:, 0]
    r = dict(ano=ano, secoes=len(e), predios=int(e.place.nunique()), cauda_media_min=float(e.cauda.mean()),
             pct_cauda_0=100 * float((e.cauda == 0).mean()), pct_cauda_10mais=100 * float((e.cauda >= 10).mean()),
             dp_cauda_dentro_predio_min=10 * float(xr.std()), beta_pp_10min=beta, ep_pp=ep, t=t, beta_inv_pp_10min=bi, ep_inv=epi, t_inv=ti,
             ufs=len(uf), ufs_mesmo_sinal_t2=int(((np.sign(uf.beta_pp) == np.sign(beta)) & (uf.t.abs() > 2)).sum()),
             ufs_sinal_contrario_t2=int(((np.sign(uf.beta_pp) == -np.sign(beta)) & (uf.t.abs() > 2)).sum()),
             ufs_sinal_igual=int((np.sign(uf.beta_pp) == np.sign(beta)).sum()))
    return r, uf, lider


def validacao(ano, e):
    """2022/2026: a cauda de encerramento contra o que o log mede na mesma seção (última hora legal e tarde inteira)."""
    e = _arruma(e[e.cauda.notna()])
    H = e[jh.BINS].to_numpy(float)
    tot = H.sum(1)
    Cum = np.c_[np.zeros(len(H)), np.cumsum(H, 1)]
    i0 = bin_('16:00') - 4 * e.desloc_h.fillna(0).astype(int).to_numpy()      # 16h de Brasília em hora local da urna
    ult = (Cum[:, -1] - Cum[np.arange(len(H)), i0]) / tot
    tarde = Exposicoes(e, [(bin_(JANELA[ano][0]), bin_(JANELA[ano][1]))]).coluna(0)
    x = e.cauda.to_numpy(float) / 10
    y = e.res_pp.to_numpy(float)
    T = Teste(e)
    out = dict(ano=ano, secoes=len(e))
    for nome, v in (('cauda_10min', x), ('log_ultima_hora', ult), ('log_tarde', tarde)):
        r = T.roda(y, [v[:, None]]).iloc[0]
        out[f'beta_{nome}'], out[f'ep_{nome}'], out[f't_{nome}'] = float(r.beta_pp), float(r.ep_pp), float(r.t)
    xr = T.residualiza(x[:, None])[:, 0]
    for nome, v in (('log_ultima_hora', ult), ('log_tarde', tarde)):
        vr = T.residualiza(v[:, None])[:, 0]
        out[f'corr_cauda_{nome}'] = float(np.corrcoef(xr, vr)[0, 1])
    ufs = por_grupo(e, x, y, 'uf').merge(por_grupo(e, ult, y, 'uf'), on='grupo', suffixes=('_cauda', '_log'))
    out['corr_uf_cauda_log'] = float(np.corrcoef(ufs.beta_pp_cauda, ufs.beta_pp_log)[0, 1])
    out['ufs_mesmo_sinal_cauda_log'] = int((np.sign(ufs.beta_pp_cauda) == np.sign(ufs.beta_pp_log)).sum())
    out['ufs'] = len(ufs)
    return out, ufs


# ----------------------------------------------------------------------------------------------------------------------- 2. cidades
def cidades(ano):
    b = pd.read_parquet(BASE / f'base_{ano}.parquet', columns=['uf', 'municipality', 'municipio', 'section', 't1_A', 't1_B', 't2_A', 't2_validos'])
    b['disputa'] = b.t2_validos - b.t1_A - b.t1_B           # outros do 1º turno + variação dos válidos
    b['ganho'] = b.t2_A - b.t1_A
    u = b.groupby('uf').agg(disputa=('disputa', 'sum'), ganho=('ganho', 'sum'), validos=('t2_validos', 'sum'))
    u['f_uf'] = u.ganho / u.disputa
    u['degenerada'] = (u.disputa < .03 * u.validos) | (u.f_uf < 0) | (u.f_uf > 1.5)
    m = b.groupby(['uf', 'municipality']).agg(municipio=('municipio', 'first'), secoes=('section', 'size'), disputa=('disputa', 'sum'),
                                              ganho=('ganho', 'sum')).reset_index()
    m = m[m.disputa >= MIN_DISPUTA].merge(u[['f_uf', 'degenerada']], left_on='uf', right_index=True)
    m['f_pct'] = 100 * m.ganho / m.disputa
    m['d_pp'] = m.f_pct - 100 * m.f_uf
    m = m[~m.degenerada].drop(columns='degenerada')
    return m.assign(ano=ano).reset_index(drop=True), u.assign(ano=ano).reset_index()


def resumo_cidades(m, ano):
    d = m.d_pp
    k = m[(m.uf == UF_CAMPOS) & (m.municipality == CAMPOS)]
    r = dict(ano=ano, cidades=len(m), ufs_degeneradas='', dp_d=float(d.std()), mad_d=float(1.4826 * np.median(np.abs(d - d.median()))),
             d_mais10=int((d >= 10).sum()), d_menos10=int((d <= -10).sum()), d_mais20=int((d >= 20).sum()), d_menos20=int((d <= -20).sum()),
             maior=f'{m.loc[d.idxmax(), "municipio"].title()} ({m.loc[d.idxmax(), "uf"]}) {d.max():+.1f}',
             menor=f'{m.loc[d.idxmin(), "municipio"].title()} ({m.loc[d.idxmin(), "uf"]}) {d.min():+.1f}')
    if len(k):
        r.update(campos_d=float(k.d_pp.iloc[0]), campos_posicao=int((d >= k.d_pp.iloc[0]).sum()))
    return r


# ----------------------------------------------------------------------------------------------------------------------- 3. dispersão
def dispersao(ano, e):
    z = e.z.to_numpy(float)
    outros = ((e.t1_validos - e.n1) / e.t1_validos.where(e.t1_validos > 0)).fillna(0).to_numpy(float)
    phi = (1.4826 * np.median(np.abs(z - np.median(z)))) ** 2
    r = dict(ano=ano, secoes=len(e), terceiros_t1_pct=100 * float(outros.mean()), var_z=float(z.var()), phi_robusto=float(phi),
             pct_z_maior_3=100 * float((np.abs(z) > 3).mean()), pct_z_maior_5=100 * float((np.abs(z) > 5).mean()),
             assimetria_z=float(pd.Series(z).clip(-10, 10).skew()))
    q = pd.qcut(pd.Series(outros).rank(method='first'), 3, labels=['baixo', 'médio', 'alto'])
    for lab in ('baixo', 'médio', 'alto'):
        idx = (q == lab).to_numpy()
        r[f'terceiros_{lab}_pct'] = 100 * float(outros[idx].mean())
        r[f'var_z_terceiros_{lab}'] = float(z[idx].var())
    return r


# ----------------------------------------------------------------------------------------------------------------------- figuras
def fig_horario(UFS, VUF):
    fig, axs = plt.subplots(1, 2, figsize=(14, 6))
    ax = axs[0]
    anos = sorted(UFS.ano.unique())
    ordem = UFS[UFS.ano == anos[-1]].sort_values('beta_pp').grupo.tolist()
    yy = {u: i for i, u in enumerate(ordem)}
    for j, ano in enumerate(anos):
        g = UFS[UFS.ano == ano]
        g = g[g.grupo.isin(yy)]
        ax.errorbar(g.beta_pp, [yy[u] + (j - 1) * .25 for u in g.grupo], xerr=1.96 * g.ep_pp, fmt='o', ms=3.5, color=COR[ano], ecolor=COR[ano],
                    lw=.7, label=ROTULO[ano])
    ax.set_yticks(range(len(ordem)))
    ax.set_yticklabels(ordem, fontsize=7)
    ax.axvline(0, color=CINZA, lw=.7)
    ax.set_xlabel('reta por UF: pontos do resíduo por 10 min de cauda de encerramento', fontsize=8, color=TINTA2)
    ax.set_title('Cauda de encerramento × resíduo, dentro do prédio, por UF', fontsize=9, color=TINTA)
    ax.legend(fontsize=7, frameon=False)
    _eixos(ax)
    ax = axs[1]
    for ano in sorted(VUF.ano.unique()):
        g = VUF[VUF.ano == ano]
        ax.scatter(g.beta_pp_log, g.beta_pp_cauda, s=18, color=COR[ano], label=ROTULO[ano])
        for r in g.itertuples():
            ax.annotate(r.grupo, (r.beta_pp_log, r.beta_pp_cauda), xytext=(3, 2), textcoords='offset points', fontsize=6, color=TINTA2)
    ax.axhline(0, color=CINZA, lw=.7)
    ax.axvline(0, color=CINZA, lw=.7)
    ax.set_xlabel('reta por UF na fração de votos do log na última hora legal (pontos por 100%)', fontsize=8, color=TINTA2)
    ax.set_ylabel('reta por UF na cauda de encerramento (pontos por 10 min)', fontsize=8, color=TINTA2)
    ax.set_title('2022 e 2026: a procuração (boletim) contra a medida direta (log), UF a UF', fontsize=9, color=TINTA)
    ax.legend(fontsize=7, frameon=False)
    _eixos(ax)
    fig.tight_layout()
    p = OUT / 'figuras' / 'horario_procuracao.png'
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def fig_cidades(C):
    fig, axs = plt.subplots(2, 2, figsize=(14, 8))
    for ax, ano in zip(axs.ravel(), ANOS):
        g = C[C.ano == ano]
        ax.hist(g.d_pp, bins=np.arange(-50, 51, 2.5), color=COR[ano], alpha=.9)
        k = g[(g.uf == UF_CAMPOS) & (g.municipality == CAMPOS)]
        if len(k):
            ax.axvline(float(k.d_pp.iloc[0]), color=LARANJA, lw=1.6)
            ax.text(float(k.d_pp.iloc[0]) + .8, ax.get_ylim()[1] * .9, f'Campos {k.d_pp.iloc[0]:+.1f}', color=LARANJA, fontsize=7.5)
        for lim in (-20, -10, 10, 20):
            ax.axvline(lim, color=CINZA, lw=.6, ls='--')
        ax.set_title(f'{ROTULO[ano]}: {len(g)} cidades com 10 mil votos em disputa ou mais', fontsize=8.5, color=TINTA)
        ax.set_xlabel('d = fatia dos votos em disputa para o PT, cidade − estado (pontos)', fontsize=7.5, color=TINTA2)
        ax.set_ylabel('cidades', fontsize=7.5, color=TINTA2)
        _eixos(ax)
    fig.tight_layout()
    p = OUT / 'figuras' / 'cidades_regua.png'
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def fig_z(Z):
    fig, axs = plt.subplots(1, 4, figsize=(14, 3.6), sharey=True)
    xx = np.linspace(-6, 6, 241)
    for ax, ano in zip(axs, ANOS):
        z = np.clip(Z[ano], -6, 6)
        ax.hist(z, bins=np.arange(-6, 6.01, .2), density=True, color=COR[ano], alpha=.9)
        ax.plot(xx, np.exp(-xx ** 2 / 2) / np.sqrt(2 * np.pi), color=LARANJA, lw=1, label='normal (0, 1)')
        ax.set_title(f'{ROTULO[ano]}: var {z.var():.2f}', fontsize=8.5, color=TINTA)
        ax.set_xlabel('z do modelo do prédio', fontsize=7.5, color=TINTA2)
        _eixos(ax)
    axs[0].legend(fontsize=7, frameon=False)
    fig.tight_layout()
    p = OUT / 'figuras' / 'dispersao_z.png'
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


# ----------------------------------------------------------------------------------------------------------------------- relatório
def _corte17h():
    """Da alegação do corte das 17h (relatório PADRÕES): % do PT nas seções encerradas até 17h00min59s e depois, hora local da urna."""
    p = PADROES / 'alegacao_encerramento.csv'
    if not p.exists():
        return None
    a = pd.read_csv(p, sep=';', decimal=',', encoding='utf-8-sig')
    a = a[a.criterio.eq('hora local da urna') & a.grupo.str.contains('corte da alegação')]
    return a


def relatorio(Hs, VAL, RES, TOPS, DISP, figs):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate
    from make_bahia_reports import H1, H2, P, SM, fig_img, n, table
    from make_padroes_report import sn

    H = Hs.set_index('ano')
    V = VAL.set_index('ano')
    R = RES.set_index('ano')
    D = DISP.set_index('ano')
    st = [Paragraph('As quatro eleições presidenciais nas mesmas medidas (2014, 2018, 2022, 2026)', H1),
          Paragraph('O estudo de janelas de horário e o de cidades compararam 2026 com 2022 porque só essas duas eleições têm os logs de urna '
                    'publicados com a hora de cada voto. Este relatório leva as mesmas medidas para 2018 e 2014 até onde os dados publicados '
                    'permitem: a hora de encerramento do boletim de urna (2018 em diante) é testada como procuração do horário dos votos, com a '
                    'validação em 2022 e 2026, onde as duas medidas existem; a régua de cidades e a dispersão dentro do prédio usam só os votos '
                    'por seção (as quatro eleições). Descritivo: nenhuma medida isolada afirma irregularidade; o que se compara é a forma do sinal '
                    'entre eleições.', P),
          Paragraph('O que cada eleição publicada tem', H2),
          table([['Eleição', 'Dados por seção disponíveis', 'Horário dos votos']] +
                [[ROTULO[a], TEM[a], 'logs (hora de cada voto)' if a >= 2022 else ('hora de encerramento (boletim)' if a == 2018 else 'nenhum')]
                 for a in ANOS], widths=[5 * cm, 15 * cm, 6 * cm]),
          Paragraph('Logs de urna: os pacotes por UF dos dados abertos (bu_imgbu_logjez_rdv_vscmr) existem a partir de 2022; o sistema de resultados '
                    'serve arquivos de urna só dos ciclos 2024 e 2026; para 2014 e 2018 os dados abertos têm o boletim de urna (BWEB) e as '
                    'correspondências esperadas e efetivadas. O BWEB de 2018 já traz data e hora de abertura e encerramento e eleitores sem '
                    'biometria habilitados; o de 2014 não.', SM),
          CondPageBreak(8 * cm), Paragraph('1. Horário por procuração: a cauda de encerramento', H2),
          Paragraph('Dentro do mesmo prédio, a seção que encerrou mais tarde é a que ainda tinha fila às 17h: mais votos no fim do dia. A cauda '
                    f'(minutos depois da hora legal, teto de {CAUDA_MAX} min) é regredida no resíduo M1 dentro do prédio, com os controles e o '
                    'erro-padrão agrupado do estudo de janelas, do mesmo jeito em 2018, 2022 e 2026. A reta é em pontos de resíduo por 10 minutos '
                    'de cauda. A inversão usa a cauda × sinal de quem liderava a seção no 1º turno.', P)]
    t = [['Eleição', 'Seções', 'Cauda média\n(min)', 'Cauda 0', 'Cauda\n≥ 10 min', 'DP da cauda\nno prédio (min)', 'Reta\n(pts/10 min)', 't',
          'UFs mesmo\nsinal (|t|>2)', 'UFs\ncontrário', 'Inversão\n(pts/10 min)', 't inv.']]
    for a in H.index:
        r = H.loc[a]
        t.append([ROTULO[a], n(r.secoes), n(r.cauda_media_min, 1), f'{n(r.pct_cauda_0, 0)}%', f'{n(r.pct_cauda_10mais, 1)}%', n(r.dp_cauda_dentro_predio_min, 1),
                  sn(r.beta_pp_10min, 3), sn(r.t, 1), f'{n(r.ufs_mesmo_sinal_t2)} de {n(r.ufs)}', n(r.ufs_sinal_contrario_t2), sn(r.beta_inv_pp_10min, 3), sn(r.t_inv, 1)])
    st += [table(t, widths=[3.6 * cm, 1.7 * cm, 1.9 * cm, 1.4 * cm, 1.9 * cm, 2.2 * cm, 2.1 * cm, 1.2 * cm, 2.6 * cm, 1.6 * cm, 2.3 * cm, 1.3 * cm], font=7),
           Paragraph('Sinal positivo: dentro do prédio, a seção que encerrou mais tarde ficou mais para o PT do que as vizinhas e o próprio 1º turno '
                     'previam. "UFs mesmo sinal": retas por UF com o sinal da nacional e |t| > 2.', SM)]
    # validação
    t = [['Eleição', 'Seções', 'Reta na cauda\n(pts/10 min)', 't', 'Reta na última hora\ndo log (pts/100%)', 't',
          'Reta na tarde\ninteira (log)', 't', 'Corr. cauda ×\núltima hora', 'Corr. cauda\n× tarde', 'UFs: corr. das\nretas cauda × log', 'UFs mesmo\nsinal']]
    for a in V.index:
        v = V.loc[a]
        t.append([ROTULO[a], n(v.secoes), sn(v.beta_cauda_10min, 3), sn(v.t_cauda_10min, 1), sn(v.beta_log_ultima_hora, 2), sn(v.t_log_ultima_hora, 1),
                  sn(v.beta_log_tarde, 2), sn(v.t_log_tarde, 1), sn(v.corr_cauda_log_ultima_hora, 3), sn(v.corr_cauda_log_tarde, 3), sn(v.corr_uf_cauda_log, 2),
                  f'{n(v.ufs_mesmo_sinal_cauda_log)} de {n(v.ufs)}'])
    st += [CondPageBreak(6 * cm), Paragraph('O que a procuração enxerga (2022 e 2026, mesmas seções, boletim contra log)', H2),
           table(t, widths=[3.4 * cm, 1.6 * cm, 2.2 * cm, 1.1 * cm, 2.9 * cm, 1.1 * cm, 2.2 * cm, 1.1 * cm, 2.4 * cm, 2 * cm, 2.3 * cm, 1.8 * cm], font=7),
           Paragraph('"Última hora legal": fração dos votos da seção registrados no log das 16h de Brasília em diante (inclui a fila depois das 17h). '
                     '"Tarde inteira": a janela da reta nacional do estudo de janelas (2026: 10h45 em diante; 2022: 10h30–17h15). Correlações dentro '
                     'do prédio, controles descontados.', SM),
           fig_img(figs['horario'], w=24)]
    # leitura do horário: a procuração passa se, em 2022 e 2026, a reta na cauda tem o sinal da reta do log com |t| > 2 e a correlação
    # dentro do prédio com a fração do log na última hora é pelo menos 0,2
    passa = all(np.sign(V.loc[a].beta_cauda_10min) == np.sign(V.loc[a].beta_log_ultima_hora) and abs(V.loc[a].t_cauda_10min) > 2
                and V.loc[a].corr_cauda_log_ultima_hora >= .2 for a in V.index)
    comp = '; '.join(f'em {a}, reta na cauda {sn(V.loc[a].beta_cauda_10min, 3)} pontos por 10 min (t {sn(V.loc[a].t_cauda_10min, 1)}) contra '
                     f'{sn(V.loc[a].beta_log_ultima_hora, 2)} pontos por 100% da última hora do log (t {sn(V.loc[a].t_log_ultima_hora, 1)}) e '
                     f'{sn(V.loc[a].beta_log_tarde, 2)} na tarde inteira (t {sn(V.loc[a].t_log_tarde, 1)})' for a in V.index)
    corr = ' e '.join(f'{sn(V.loc[a].corr_cauda_log_ultima_hora, 3)} ({a})' for a in V.index)
    dp = ' e '.join(f'{n(H.loc[a].dp_cauda_dentro_predio_min, 1)} min ({a})' for a in H.index)
    r18 = H.loc[2018] if 2018 in H.index else None
    if passa:
        leitura = (f'Leitura. A procuração reproduz o que o log mede: {comp}. A correlação dentro do prédio entre a cauda e a fração do log na última '
                   f'hora é {corr}. A reta de 2018 ({sn(r18.beta_pp_10min, 3)} pontos por 10 min, t {sn(r18.t, 1)}) é comparável às duas.')
    else:
        leitura = (f'Leitura. A procuração não reproduz o que o log mede: {comp}. A correlação dentro do prédio entre a cauda e a fração do log na '
                   f'última hora é {corr}: a hora de encerramento mede a fila às 17h, que varia poucos minutos entre seções do mesmo prédio (desvio-padrão '
                   f'de {dp}) e quase não acompanha o perfil de horário dos votos da seção. Como a cauda não enxerga o gradiente conhecido de 2026 nem o '
                   f'de 2022, a reta de 2018 ({sn(r18.beta_pp_10min, 3)} pontos por 10 min, t {sn(r18.t, 1)}) não informa sobre o gradiente do dia em '
                   f'2018: com os dados publicados, o horário dos votos de 2018 e 2014 não é comparável ao de 2022 e 2026.')
    st += [Paragraph(leitura, P)]
    c17 = _corte17h()
    if c17 is not None and len(c17):
        t = [['Eleição', 'Seções encerradas até 17h00min59s (hora local): % do PT', 'Encerradas depois: % do PT', 'Diferença (pontos)']]
        for a, g in c17.groupby('ano'):
            ate = g[g.grupo.str.startswith('até')].iloc[0]
            dep = g[g.grupo.str.startswith('depois')].iloc[0]
            t.append([ROTULO[int(a)], f'{n(ate.pct_A, 2)}% ({n(ate.secoes)} seções)', f'{n(dep.pct_A, 2)}% ({n(dep.secoes)} seções)', sn(dep.pct_A - ate.pct_A, 2)])
        st += [CondPageBreak(5 * cm), Paragraph('O corte das 17h, nas três eleições com hora de encerramento', H2),
               table(t, widths=[4 * cm, 7 * cm, 6 * cm, 3.5 * cm]),
               Paragraph('Do relatório PADRÕES (alegacao_encerramento.csv): o corte da alegação viral de 2026 (seções encerradas até 17h00min59s no relógio '
                         'local da urna) refeito em 2018 e 2022. Em 2018 a votação era em hora local, então "até 17h00min59s" é a seção sem fila; em 2022 e '
                         '2026 o corte mistura os estados de fuso −1 h/−2 h (encerram às 16h/15h locais) com as seções sem fila.', SM)]
    # cidades
    t = [['Eleição', 'Cidades (≥ 10 mil em disputa)', 'DP de d', 'MAD de d', 'd ≥ +10', 'd ≤ −10', 'd ≥ +20', 'd ≤ −20', 'Maior d', 'Menor d', 'Campos (RJ)']]
    for a in R.index:
        r = R.loc[a]
        campos = f'{sn(r.campos_d, 1)} ({n(r.campos_posicao)}ª de {n(r.cidades)})' if pd.notna(r.get('campos_d', np.nan)) else '—'
        t.append([ROTULO[a], n(r.cidades), n(r.dp_d, 1), n(r.mad_d, 1), n(r.d_mais10), n(r.d_menos10), n(r.d_mais20), n(r.d_menos20), r.maior, r.menor, campos])
    st += [CondPageBreak(8 * cm), Paragraph('2. Cidades: a régua de Campos nas quatro eleições', H2),
           Paragraph('d = fatia dos votos em disputa (válidos do 2º turno menos os votos dos dois finalistas no 1º) que foi para o candidato do PT, na '
                     'cidade menos no estado. Cidades com 10 mil votos em disputa ou mais; UFs em que a disputa é menor que 3% dos válidos ou a fatia '
                     'estadual sai de 0–150% ficam fora (denominador degenerado). Em 2014 e 2018 a disputa é grande (Marina, Ciro, Alckmin e outros no 1º '
                     'turno); em 2022 e 2026 é pequena, e d fica mais sensível.', P),
           table(t, widths=[3.6 * cm, 2.2 * cm, 1.4 * cm, 1.5 * cm, 1.4 * cm, 1.4 * cm, 1.4 * cm, 1.4 * cm, 4 * cm, 4 * cm, 3 * cm], font=7),
           fig_img(figs['cidades'], w=22)]
    t = [['Eleição', 'Cidades mais acima do estado (d)', 'Cidades mais abaixo do estado (d)']]
    for a in ANOS:
        g = TOPS[TOPS.ano == a]
        cima = ', '.join(f'{r.municipio.title()} ({r.uf}) {sn(r.d_pp, 1)}' for r in g[g.lado == 'acima'].itertuples())
        baixo = ', '.join(f'{r.municipio.title()} ({r.uf}) {sn(r.d_pp, 1)}' for r in g[g.lado == 'abaixo'].itertuples())
        t.append([ROTULO[a], cima, baixo])
    st += [CondPageBreak(5 * cm), table(t, widths=[4 * cm, 11 * cm, 11 * cm], font=7)]
    # dispersão
    t = [['Eleição', 'Seções', 'Terceiros\nno 1º turno', 'Var. de z', 'φ robusto', '|z| > 3', '|z| > 5', 'Assimetria',
          'Var. z: terceiros\nbaixo', 'médio', 'alto']]
    for a in D.index:
        r = D.loc[a]
        t.append([ROTULO[a], n(r.secoes), f'{n(r.terceiros_t1_pct, 1)}%', n(r.var_z, 2), n(r.phi_robusto, 2), f'{n(r.pct_z_maior_3, 2)}%', f'{n(r.pct_z_maior_5, 2)}%',
                  sn(r.assimetria_z, 2), f'{n(r.var_z_terceiros_baixo, 2)} ({n(r.terceiros_baixo_pct, 1)}%)', f'{n(r["var_z_terceiros_médio"], 2)} ({n(r["terceiros_médio_pct"], 1)}%)',
                  f'{n(r.var_z_terceiros_alto, 2)} ({n(r.terceiros_alto_pct, 1)}%)'])
    st += [CondPageBreak(8 * cm), Paragraph('3. Dispersão dentro do prédio nas quatro eleições', H2),
           Paragraph('z = (% do PT observada − prevista pelo próprio 1º turno e pela mudança das vizinhas do prédio) / desvio binomial. Se a seção fosse só '
                     'ruído de amostragem em torno do previsto, z teria variância 1. φ robusto é a variância estimada pela mediana dos desvios (sem as '
                     'caudas). "Terceiros": fatia dos válidos do 1º turno que não foi aos dois finalistas, em tercis dentro de cada eleição.', P),
           table(t, widths=[3.6 * cm, 1.7 * cm, 2 * cm, 1.5 * cm, 1.6 * cm, 1.5 * cm, 1.5 * cm, 1.6 * cm, 3 * cm, 2.6 * cm, 2.6 * cm], font=7),
           fig_img(figs['z'], w=24),
           CondPageBreak(5 * cm), Paragraph('4. Leitura', H2),
           Paragraph(('O que 2018 e 2014 acrescentam é controle nas medidas que usam só votos. ' +
                      ('A hora de encerramento do boletim serve de procuração para o horário dos votos, e 2018 entra na comparação do gradiente. '
                       if passa else
                       'A hora de encerramento do boletim não serve de procuração para o horário dos votos (a validação em 2022 e 2026 falha), então o '
                       'gradiente do dia só é medível onde há logs: 2022 e 2026. ') +
                      'A régua de cidades mostra em cada eleição quantas cidades grandes ficam longe do estado e onde Campos cai; em 2014 e 2018, com '
                      'muitos votos de terceiros no 1º turno, o espalhamento de d é maior, e Campos não se destaca. A dispersão dentro do prédio mostra '
                      'que a variância do resíduo acompanha a fatia de terceiros no 1º turno (grande em 2014 e 2018, pequena em 2022 e 2026): é a razão '
                      'de 2022 ser o controle natural de 2026 e de 2014/2018 não serem comparáveis seção a seção sem essa conta. Nada aqui é conclusão '
                      'sobre causa. Como repetir: scripts/comparacao_eleicoes.py (e "relatorio" para só remontar o PDF dos CSVs).'), P)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7)
        cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(OUT / 'COMPARACAO_ELEICOES.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='As quatro eleições presidenciais nas mesmas medidas', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', OUT / 'COMPARACAO_ELEICOES.pdf', flush=True)


def main():
    from baixa_pais import prioridade_baixa
    prioridade_baixa()
    (OUT / 'figuras').mkdir(parents=True, exist_ok=True)
    Hs, UFS, LID, VAL, VUF, DISP, CID, UFC, RES, TOPS, Z = [], [], [], [], [], [], [], [], [], [], {}
    for ano in ANOS:
        m, u = cidades(ano)
        CID.append(m)
        UFC.append(u)
        r = resumo_cidades(m, ano)
        r['ufs_degeneradas'] = ', '.join(u[u.degenerada].uf)
        RES.append(r)
        top = m.sort_values('d_pp', ascending=False)
        TOPS.append(pd.concat([top.head(4).assign(lado='acima'), top.tail(4).iloc[::-1].assign(lado='abaixo')]))
        print(ano, 'cidades', len(m), {k: r[k] for k in ('d_mais20', 'd_menos20', 'd_mais10', 'd_menos10')}, 'degeneradas', r['ufs_degeneradas'], flush=True)
        e = prepara(ano)
        DISP.append(dispersao(ano, e))
        Z[ano] = e.z.to_numpy(float)
        print(ano, 'dispersão', {k: round(DISP[-1][k], 3) for k in ('var_z', 'phi_robusto', 'pct_z_maior_3')}, flush=True)
        if 'cauda' in e:
            r, uf, lider = horario(ano, e)
            Hs.append(r)
            UFS.append(uf.assign(ano=ano))
            LID.append(lider.assign(ano=ano))
            print(ano, 'cauda', {k: round(r[k], 3) for k in ('beta_pp_10min', 't', 't_inv', 'cauda_media_min', 'dp_cauda_dentro_predio_min')},
                  'UFs', r['ufs_mesmo_sinal_t2'], r['ufs_sinal_contrario_t2'], flush=True)
        del e
        if ano in (2022, 2026):
            e = prepara(ano, com_bins=True)
            v, ufs = validacao(ano, e)
            VAL.append(v)
            VUF.append(ufs.assign(ano=ano))
            print(ano, 'validação', {k: round(v[k], 3) for k in v if k not in ('ano', 'secoes')}, flush=True)
            del e
    Hs, VAL, RES, DISP = (pd.DataFrame(x) for x in (Hs, VAL, RES, DISP))
    UFS, LID, VUF, CID, UFC, TOPS = (pd.concat(x, ignore_index=True) for x in (UFS, LID, VUF, CID, UFC, TOPS))
    Hs.to_csv(OUT / 'comparacao_horario_eleicoes.csv', **CSV)
    UFS.to_csv(OUT / 'comparacao_horario_uf.csv', **CSV)
    LID.to_csv(OUT / 'comparacao_horario_lider.csv', **CSV)
    VAL.to_csv(OUT / 'comparacao_horario_validacao.csv', **CSV)
    VUF.to_csv(OUT / 'comparacao_horario_validacao_uf.csv', **CSV)
    CID.to_csv(OUT / 'comparacao_cidades.csv', **CSV)
    UFC.to_csv(OUT / 'comparacao_cidades_uf.csv', **CSV)
    RES.to_csv(OUT / 'comparacao_cidades_resumo.csv', **CSV)
    TOPS.to_csv(OUT / 'comparacao_cidades_topo.csv', **CSV)
    DISP.to_csv(OUT / 'comparacao_dispersao.csv', **CSV)
    pd.DataFrame({'ano': np.repeat(list(Z), [len(Z[a]) for a in Z]), 'z': np.concatenate([Z[a] for a in Z])}).to_parquet(OUT / 'comparacao_z.parquet', index=False)
    figs = dict(horario=fig_horario(UFS, VUF), cidades=fig_cidades(CID), z=fig_z(Z))
    relatorio(Hs, VAL, RES, TOPS, DISP, figs)


def relatorio_dos_arquivos():
    """Só remonta as figuras e o PDF a partir dos CSVs já calculados."""
    le = dict(sep=';', decimal=',', encoding='utf-8-sig')
    Hs, VAL, RES, TOPS, DISP, UFS, VUF, CID = (pd.read_csv(OUT / f'comparacao_{k}.csv', **le) for k in
                                               ('horario_eleicoes', 'horario_validacao', 'cidades_resumo', 'cidades_topo', 'dispersao', 'horario_uf',
                                                'horario_validacao_uf', 'cidades'))
    RES['ufs_degeneradas'] = RES.ufs_degeneradas.fillna('')
    z = pd.read_parquet(OUT / 'comparacao_z.parquet')
    Z = {int(a): g.z.to_numpy(float) for a, g in z.groupby('ano')}
    figs = dict(horario=fig_horario(UFS, VUF), cidades=fig_cidades(CID), z=fig_z(Z))
    relatorio(Hs, VAL, RES, TOPS, DISP, figs)


if __name__ == '__main__':
    relatorio_dos_arquivos() if 'relatorio' in sys.argv[1:] else main()
