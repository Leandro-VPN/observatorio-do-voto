"""Relatorio: busca de padrao algoritmico, inversoes e conferencia das alegacoes sobre o 2o turno de 2026, com 2014, 2018 e 2022 de controle
(le relatorios/verificacoes/padroes_2t/, gerado por scripts/padroes_2t.py e scripts/padroes_aberta.py).
Saida: PADROES_1T_2T.pdf, PADROES_1T_2T.xlsx e figuras/.
"""
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import CondPageBreak, PageBreak, Paragraph, SimpleDocTemplate

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('UF', 'BA')
from make_bahia_reports import P, H1, H2, SM, NOTE, table, n, fig_img  # noqa: E402

D = ROOT / 'relatorios' / 'verificacoes' / 'padroes_2t'
FIG = D / 'figuras'
CSV = dict(sep=';', encoding='utf-8-sig', decimal=',')
COR = {2014: '#2a78d6', 2018: '#eb6834', 2022: '#1baf7a', 2026: '#eda100'}  # paleta validada (categorica, ordem fixa)
MARCA = {2014: 'o', 2018: 's', 2022: '^', 2026: 'D'}
TINTA, TINTA2, GRADE = '#0b0b0b', '#52514e', '#e4e3df'
NOME = {2014: 'Dilma × Aécio (2014)', 2018: 'Haddad × Bolsonaro (2018)', 2022: 'Lula × Bolsonaro (2022)', 2026: 'Lula × Flávio (2026)'}


def r(nome):
    return pd.read_csv(D / nome, low_memory=False, **CSV)


def sn(x, d=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return '—'
    return ('+' if x > 0 else '') + n(x, d)


def _eixos(ax, xl, yl):
    ax.grid(True, color=GRADE, lw=.6)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#b9b8b3')
    ax.tick_params(colors=TINTA2, labelsize=8)
    ax.set_xlabel(xl, color=TINTA2, fontsize=8.5)
    ax.set_ylabel(yl, color=TINTA2, fontsize=8.5)


def _linhas(ax, series, rotulo_fim=True):
    for ano, (x, y, txt) in series.items():
        ax.plot(x, y, color=COR[ano], lw=1.6, marker=MARCA[ano], ms=5, mec='white', mew=1, label=txt, zorder=3)
        if rotulo_fim:
            ax.annotate(txt.split(' (')[0] + f' {ano}', (x[-1], y[-1]), xytext=(4, 0), textcoords='offset points', fontsize=7, color=TINTA, va='center')
    ax.legend(fontsize=7.5, frameon=False, loc='best', labelcolor=TINTA)


def nomes_1t(ano):
    """Numero -> nome dos candidatos do 1o turno (BU em CSV de SP; 2026 vem do proprio grupo)."""
    f = ROOT / 'research' / 'bu' / f'{ano}-t1' / 'SP_PRESIDENTE.parquet'
    if not f.exists():
        return {}
    b = pd.read_parquet(f, columns=['NR_VOTAVEL', 'NM_VOTAVEL']).drop_duplicates('NR_VOTAVEL')
    return {f'candidato {k}': str(v).title() for k, v in zip(b.NR_VOTAVEL.astype(str), b.NM_VOTAVEL)}


def figuras():
    FIG.mkdir(parents=True, exist_ok=True)
    out = {}
    c = r('curva_ganho_por_fatia_1t.csv')
    c['meio'] = c.faixa_A_1t.str.extract(r'[\(\[]\s*(-?[\d.]+),\s*([\d.]+)').astype(float).mean(axis=1).clip(lower=0)
    fig, ax = plt.subplots(figsize=(8.6, 3.6), dpi=160)
    _linhas(ax, {a: (g.sort_values('meio').meio.to_numpy(), g.sort_values('meio').var_A_pp_media.to_numpy(), NOME[a])
                 for a, g in c[c.secoes >= 200].groupby('ano')}, rotulo_fim=False)
    _eixos(ax, 'Fatia do candidato do PT no 1º turno, na seção (% dos válidos)', 'Ganho médio no 2º turno (pontos)')
    ax.set_xlim(0, 108)
    fig.tight_layout()
    out['curva'] = FIG / 'ganho_por_fatia_1t.png'
    fig.savefig(out['curva'])
    plt.close(fig)

    m = r('alegacao_manual_curva.csv')
    fig, ax = plt.subplots(figsize=(8.6, 3.4), dpi=160)
    _linhas(ax, {a: (g.manual_medio_pct.to_numpy(), g.pct_A.to_numpy(), NOME[a]) for a, g in m[m.secoes >= 500].groupby('ano')})
    _eixos(ax, 'Habilitação sem digital na seção (% do comparecimento, faixas)', '% do candidato do PT no 2º turno')
    fig.tight_layout()
    out['manual'] = FIG / 'manual_x_voto.png'
    fig.savefig(out['manual'])
    plt.close(fig)

    if (D / 'idosos_comparecimento_pais.csv').exists():
        t = r('idosos_comparecimento_pais.csv')
        ordem = ['até 79 anos', '80 a 84 anos', '85 a 89 anos', '90 a 94 anos', '95 a 99 anos', '100 anos ou mais']
        fig, ax = plt.subplots(figsize=(8.6, 3.4), dpi=160)
        cor = {2018: COR[2018], 2022: COR[2022], 2026: COR[2026]}
        for (a, tu), g in t.groupby(['ano', 'NR_TURNO']):
            g = g.set_index('faixa').reindex(ordem)
            ax.plot(range(len(ordem)), g.comparecimento_pct, color=cor[a], lw=1.6, ls='-' if tu == 1 else '--', marker=MARCA[a], ms=5,
                    mec='white', mew=1, label=f'{a} · {tu}º turno', zorder=3)
        ax.set_xticks(range(len(ordem)), [o.replace(' anos', '').replace(' ou mais', '+') for o in ordem])
        _eixos(ax, 'Idade', 'Comparecimento (%)')
        ax.legend(fontsize=7.5, frameon=False, labelcolor=TINTA)
        fig.tight_layout()
        out['idosos'] = FIG / 'comparecimento_por_idade.png'
        fig.savefig(out['idosos'])
        plt.close(fig)

    if (D / 'teste_cego' / 'resultado_aberto.csv').exists():
        k = pd.read_csv(D / 'teste_cego' / 'resultado_aberto.csv', **CSV).sort_values('regra_maior_z')
        fig, ax = plt.subplots(figsize=(8.6, 3.6), dpi=160)
        real = k.tipo == 'real'
        y = np.arange(len(k))
        ax.barh(y, k.regra_maior_z.clip(upper=60), color=np.where(real, '#2a78d6', '#eb6834'), height=.62, zorder=3)
        ax.axvline(4, color=TINTA2, lw=1, ls='--', zorder=4)
        ax.set_yticks(y, [f'{c} · ' + (f'real {b}' if t == 'real' else f'{t} ({b})') for c, t, b in zip(k.conjunto, k.tipo, k.base)])
        for yi, v in zip(y, k.regra_maior_z):
            ax.annotate(n(v, 1), (min(v, 60), yi), xytext=(3, 0), textcoords='offset points', fontsize=7, color=TINTA, va='center')
        _eixos(ax, 'Maior z robusto entre as métricas decisivas (limite pré-registrado = 4; barras cortadas em 60)', '')
        ax.grid(axis='y', visible=False)
        from matplotlib.patches import Patch
        ax.legend(handles=[Patch(color='#2a78d6', label='eleição real'), Patch(color='#eb6834', label='manipulação plantada')],
                  fontsize=7.5, frameon=False, loc='lower right', labelcolor=TINTA)
        fig.tight_layout()
        out['cego'] = FIG / 'teste_cego.png'
        fig.savefig(out['cego'])
        plt.close(fig)
    return out


ROTULO_DET = [
    ('fora4_por_10mil', 'Seções fora do modelo do local (|z| > 4), por 10 mil', 1),
    ('fora4_razao_obs_sim', '… observado ÷ esperado na simulação', 2),
    ('fora4_saldo_X_por_10mil', '… a favor do PT menos a favor do adversário, por 10 mil', 1),
    ('trocas_por_10mil', 'Seções com cara de inversão (X↔Y), por 10 mil', 2),
    ('phi', 'Dispersão da mudança ÷ binomial (piso 1)', 2),
    ('ganho_pct_uniforme_demais', 'Locais com seções parecidas demais na mudança (%)', 1),
    ('ganho_pct_disperso_demais', 'Locais com seções diferentes demais na mudança (%)', 1),
    ('fatia_pct_uniforme_demais', 'Locais com fatia do 2º turno parecida demais (%)', 1),
    ('razao_picos_z6', 'Picos na razão votos 2º/1º turno (z > 6)', 0),
    ('fatia_picos_z6', 'Picos na fatia do 2º turno (z > 6)', 0),
    ('viradas_razao_obs_sim', 'Viradas observadas ÷ esperadas', 2),
    ('dentro_local_sobre_piso', 'Variação dentro do local ÷ piso binomial', 2),
    ('corr_com_vizinhas', 'Correlação do ganho com as vizinhas do prédio', 2),
    ('transf_rmse_municipio_pp', 'Erro por município ao prever pelas transferências (p.p.)', 2),
    ('transf_erro_nacional_pp_medio', 'Erro nacional, metade prevista pela outra (p.p.)', 2),
    ('ultimo_dig_X_desvio_max_pp', 'Último dígito, PT: maior desvio do uniforme (p.p.)', 2),
    ('ultimo_dig_Y_desvio_max_pp', 'Último dígito, adversário: maior desvio (p.p.)', 2),
    ('benford2_X_mad', 'Benford 2º dígito, PT: desvio médio', 4),
    ('benford2_Y_mad', 'Benford 2º dígito, adversário: desvio médio', 4),
    ('manual_mudanca_mesmo_local_incl', 'Manual: mudança na taxa × ganho do PT, mesmo local', 3),
    ('manual_nivel_mesmo_local_incl', 'Manual: taxa × fatia do PT no 2º turno, mesmo local', 3),
]


def main():
    fg = figuras()
    enc = r('alegacao_encerramento.csv')
    man = r('alegacao_manual_totais.csv')
    ext = r('alegacao_extremos.csv')
    dig = r('alegacao_digitos_benford.csv')
    logs = r('alegacao_votos_apos_17h_logs.csv').iloc[0]
    det = r('detectores_por_eleicao.csv').set_index('ano')
    duf = r('detectores_por_uf.csv')
    esp = r('espelho_resumo.csv')
    espuf = r('espelho_secoes_por_uf.csv')
    viz = r('vizinhas_tarde_x_cedo.csv')
    qt = r('crescimento_por_secao_quantis.csv')

    def g(ano, crit, grupo):
        x = enc[(enc.ano == ano) & (enc.criterio == crit) & (enc.grupo == grupo)]
        return x.iloc[0] if len(x) else None
    a26 = g(2026, 'hora local da urna', 'até 17h00min59s (corte da alegação)')
    d26 = g(2026, 'hora local da urna', 'depois de 17h00min59s (corte da alegação)')
    b26 = g(2026, 'hora de Brasília', 'até 17h00min59s (corte da alegação)')
    a22 = g(2022, 'hora local da urna', 'até 17h00min59s (corte da alegação)')
    d22 = g(2022, 'hora local da urna', 'depois de 17h00min59s (corte da alegação)')
    l26 = g(2026, 'hora local da urna', 'até 17h00')
    p19 = g(2026, 'hora de Brasília', 'depois das 19h00')
    m = man.set_index(['ano', 'turno'])
    ex = ext.set_index(['ano', 'criterio'])

    st = [Paragraph('1º × 2º turno: padrão algorítmico, inversões de voto e as alegações sobre 2026', H1),
          Paragraph('Seção por seção, a mudança do 1º para o 2º turno em quatro eleições para presidente: 2014 (Dilma × Aécio), 2018 (Haddad × Bolsonaro), '
                    '2022 (Lula × Bolsonaro) e 2026 (Lula × Flávio Bolsonaro). As três primeiras servem de controle: o que aparece em 2026 e também '
                    'aparece nelas não é marca de 2026. Fontes: boletim de urna de cada seção (BU) dos dados abertos do TSE, logs das urnas de 2026 '
                    'e o comparecimento por idade publicado pelo TSE.', P),
          Paragraph('O que este estudo consegue e o que não consegue. Ele procura marcas que uma alteração de votos deixaria nos números: seções que '
                    'fogem do padrão do próprio prédio, seções com os votos dos dois candidatos trocados, proporções e dígitos que se repetem demais, '
                    'mudanças que não seguem a composição do 1º turno. Uma mudança suave e uniforme numa região inteira não deixa marca estatística '
                    'seção a seção (o teste cego mostra isso); para ela, a verificação é física: o BU impresso e afixado na seção, o registro de cada '
                    'voto (RDV) e a assinatura digital de cada urna, já conferidos em outros relatórios do projeto. Nada aqui, sozinho, indica ou descarta irregularidade.', NOTE)]

    # ---------------- alegacoes
    st += [Paragraph('1. As alegações, uma por uma', H2)]
    lin = [['Alegação', 'O que os dados mostram', 'Mesma conta em outra eleição']]
    lin.append(['Seções fechadas até 17h: oposição com 52,39% e quase 1,8 milhão de vantagem; depois das 17h, +6,1 milhões para o incumbente.',
                f'Reproduzido: o corte é “fechou até 17h00min59s no relógio da urna”. São {n(a26.secoes)} seções, Flávio com {n(a26.pct_B, 2)}% e '
                f'{n(-a26.margem_A_menos_B)} votos de vantagem; nas {n(d26.secoes)} restantes, Lula com {sn(d26.margem_A_menos_B, 0)}. '
                f'O grupo junta dois tipos de seção: todas as de MT, AM, MS, RO, AC e RR ({n(l26.secoes)} seções), que fecham às 16h no relógio local '
                f'porque a votação foi pelo horário de Brasília, e as seções que fecharam no primeiro minuto. Em hora de Brasília, a vantagem de Flávio '
                f'nesse grupo cai para {n(-b26.margem_A_menos_B)}. E o grupo “depois” não quer dizer voto depois das 17h: '
                f'pelos logs de todas as urnas, só {n(logs.votos_apos_17h)} votos foram dados depois das 17h no país ({n(logs.votos_apos_19h)} depois das 19h).',
                f'2022, mesmo corte: Bolsonaro (então incumbente) com {n(a22.pct_B, 2)}% e {n(-a22.margem_A_menos_B)} de vantagem no grupo “até 17h”; '
                f'Lula com {sn(d22.margem_A_menos_B, 0)} no grupo “depois”. O padrão é de fuso e de composição, não de 2026.'])
    lin.append(['348.398 seções fecharam depois das 17h; 6.333 depois das 19h.',
                f'{n(d26.secoes)} pelo mesmo corte; {n(p19.secoes)} encerraram às 19h ou depois (hora de Brasília), as que ficaram abertas com a '
                f'prorrogação. Fechar depois das 17h é o normal: o mesário encerra depois do último eleitor da fila. Das seções que ficaram até as 19h, '
                'mais da metade não teve nenhum voto depois das 17h e só 11 tiveram voto depois das 19h (relatório do último voto).',
                'Em 2022, sem prorrogação, 21 seções fecharam depois das 19h.'])
    lin.append(['Fiscais do PL credenciados só até 17h; seções sem fiscal da oposição.',
                'Não verificável com dados públicos: o BU e o log não registram fiscais. Pode ser checado nas atas das mesas e nos credenciamentos dos TREs.', '—'])
    lin.append([f'QT_ELEI_BIOM_SEM_HABILITACAO: 8.632.488 votos liberados só com o ano de nascimento (6,73%), 194,86% da margem.',
                f'O número bate: {n(m.loc[(2026, 2), "habilitados_sem_digital"])} ({n(m.loc[(2026, 2), "pct_do_comparecimento"], 2)}%) no 2º turno. '
                'É o eleitor que tem biometria cadastrada e cuja digital não foi reconhecida; o mesário confere o documento e libera. '
                f'No 1º turno de 2026 foram {n(m.loc[(2026, 1), "habilitados_sem_digital"])} ({n(m.loc[(2026, 1), "pct_do_comparecimento"], 2)}%): '
                'não houve salto no 2º turno.',
                f'2022, 2º turno: {n(m.loc[(2022, 2), "habilitados_sem_digital"])} ({n(m.loc[(2022, 2), "pct_do_comparecimento"], 2)}%), '
                f'{n(m.loc[(2022, 2), "manual_sobre_margem_pct"], 0)}% da margem. 2018: {n(m.loc[(2018, 2), "habilitados_sem_digital"])}. '
                'Comparar com a margem não tem sentido: são eleitores reais, de todos os lados.'])
    lin.append(['Com taxa manual alta, o voto do incumbente sobe linearmente acima de 61%.',
                f'A curva existe em 2026 (ver gráfico), mas é ainda mais íngreme em 2022, quando o incumbente era Bolsonaro, e em 2018 com Haddad: a '
                f'taxa manual é alta no Nordeste, onde o PT é forte. Dentro do mesmo prédio, a mudança da taxa manual do 1º para o 2º turno não '
                f'acompanha o ganho de Lula (inclinação {n(det.loc[2026, "manual_mudanca_mesmo_local_incl"], 3)} ponto por ponto).',
                f'2022: {n(det.loc[2022, "manual_mudanca_mesmo_local_incl"], 3)}; 2018: {n(det.loc[2018, "manual_mudanca_mesmo_local_incl"], 3)}.'])
    lin.append(['100% dos válidos: 106 × 4 (26,5:1). Mais de 90%: 6.899 × 384 (18:1).',
                f'Confirmado: 100%, {n(ex.loc[(2026, "100%"), "secoes_A"])} × {n(ex.loc[(2026, "100%"), "secoes_B"])}; 90% ou mais, '
                f'{n(ex.loc[(2026, "90% ou mais"), "secoes_A"])} × {n(ex.loc[(2026, "90% ou mais"), "secoes_B"])}. É o retrato de onde cada lado é '
                'forte: os redutos do PT no interior do Norte e do Nordeste são muito mais homogêneos que os do adversário.',
                '; '.join(f'{a}: 100% {n(ex.loc[(a, "100%"), "secoes_A"])} × {n(ex.loc[(a, "100%"), "secoes_B"])}, 90%+ '
                          f'{n(ex.loc[(a, "90% ou mais"), "secoes_A"])} × {n(ex.loc[(a, "90% ou mais"), "secoes_B"])}' for a in (2014, 2018, 2022))
                + '. Em 2022 a razão foi maior que em 2026.'])
    k26 = 'manual: secoes com 90%+ para {} menos mediana do municipio (p.p.)'
    lin.append(['Seções extremas concentradas em zonas com alta liberação manual.',
                f'Nas seções com 90%+ para Lula, a taxa manual fica {sn(ex.loc[(2026, k26.format("A")), "secoes_A"], 2)} ponto acima da mediana do '
                f'município; nas com 90%+ para Flávio, {sn(ex.loc[(2026, k26.format("B")), "secoes_B"], 2)}. A diferença é maior no lado de Flávio.',
                f'2022: {sn(ex.loc[(2022, k26.format("A")), "secoes_A"], 2)} (PT) e {sn(ex.loc[(2022, k26.format("B")), "secoes_B"], 2)} (Bolsonaro).'])
    dg = dig.set_index('ano')
    lin.append(['Lei de Benford confirma a quebra dos controles.',
                f'Benford não se aplica a contagens por seção (limitadas pelo tamanho da seção). Os desvios aparecem nas quatro eleições, do mesmo '
                f'tamanho: 2º dígito do PT, desvio médio {n(dg.loc[2026, "benford2_X_mad"], 4)} em 2026 e {n(dg.loc[2022, "benford2_X_mad"], 4)} em 2022. '
                f'O último dígito também se afasta do uniforme em ~0,5 ponto em todas, pelo formato da distribuição.',
                '; '.join(f'{a}: {n(dg.loc[a, "benford2_X_mad"], 4)}' for a in (2014, 2018)) + ' (2º dígito, PT).'])
    st += [table(lin, font=7, widths=[5.6 * cm, 12.6 * cm, 8.3 * cm])]
    st += [Paragraph('Habilitação sem digital e voto no candidato do PT, por faixa de taxa manual da seção', H2), fig_img(fg['manual'], 21),
           Paragraph('Cada ponto é uma faixa de seções. A subida aparece nas três eleições com o dado; em 2022 o incumbente era Bolsonaro.', SM)]

    # ---------------- teste cego
    st += [PageBreak(), Paragraph('2. Teste duplo-cego', H2)]
    proto = (D / 'teste_cego' / 'PROTOCOLO.md').read_text(encoding='utf-8')
    hsh = proto.split('`')[1] if '`' in proto else '—'
    st += [Paragraph('Antes de olhar qualquer resultado das eleições reais, as quatro eleições foram misturadas com sete cópias de eleições reais '
                     'sorteadas, cada uma com uma manipulação plantada, e tudo recebeu nomes neutros (D01 a D11; candidatos X e Y, com troca sorteada). '
                     f'A chave ficou lacrada; o hash dela (SHA-256 {hsh[:16]}…) foi registrado no protocolo antes da análise. Os mesmos detectores '
                     'rodaram nos 11 conjuntos. Duas decisões foram tomadas às cegas: uma regra mecânica fixada antes (algum detector com z robusto '
                     'acima de 4 entre os conjuntos) e a classificação de um avaliador independente, que só viu a tabela mascarada. Só então a chave foi aberta.', P)]
    rc = D / 'teste_cego' / 'resultado_aberto.csv'
    if rc.exists():
        k = pd.read_csv(rc, **CSV)
        t = [['Conjunto', 'O que era', 'Votos movidos\n(líquido)', 'Regra:\nanômalo?', 'Métrica que\nmais subiu', 'z', 'Avaliador', 'Tipo que o\navaliador viu']]
        k['_o'] = (k.tipo != 'real').astype(int)
        for x in k.sort_values(['_o', 'base', 'tipo']).itertuples():
            uf_txt = str(getattr(x, 'ufs', '')).strip("[]").replace("'", '').replace(', ', ' e ')
            alvo = (f' em {uf_txt}' if isinstance(getattr(x, 'ufs', None), str) else '') + (f' ({x.regiao})' if isinstance(getattr(x, 'regiao', None), str) else '')
            t.append([x.conjunto, ('eleição real ' if x.tipo == 'real' else f'{x.tipo} sobre ') + str(x.base) + alvo,
                      n(x.votos_movidos_liquido_X) if x.tipo != 'real' else '—', 'sim' if x.regra_anomalo else 'não', str(x.regra_metrica),
                      n(x.regra_maior_z, 1), str(getattr(x, 'avaliador_classificacao', '—')),
                      x.avaliador_tipo_provavel if isinstance(getattr(x, 'avaliador_tipo_provavel', None), str) else '—'])
        st += [table(t, font=7, widths=[1.6 * cm, 5.4 * cm, 2.2 * cm, 1.6 * cm, 5.2 * cm, 1.2 * cm, 2.4 * cm, 5 * cm])]
        if 'cego' in fg:
            st += [fig_img(fg['cego'], 20)]
        real = k.tipo == 'real'
        av = k.get('avaliador_classificacao', pd.Series('', index=k.index)).fillna('')
        acerto_av = int(((av == 'real') == real).sum())
        tipo_ok = int((k.avaliador_tipo_provavel == k.tipo)[~real].sum()) if 'avaliador_tipo_provavel' in k else 0
        fp = k[real & k.regra_anomalo]
        fn = k[~real & ~k.regra_anomalo]
        d26 = k[real & (k.base == 2026)].iloc[0]
        st += [Paragraph(f'<b>Resultado.</b> O avaliador independente acertou {acerto_av} de {len(k)} conjuntos e o tipo de {tipo_ok} das {int((~real).sum())} '
                         f'manipulações; a eleição real de 2026 ({d26.conjunto}) foi classificada como “{d26.avaliador_classificacao}”, com confiança '
                         f'{d26.avaliador_confianca}. A regra mecânica marcou {int(k.regra_anomalo[~real].sum())} das {int((~real).sum())} manipulações e '
                         f'também {len(fp)} eleições reais ({", ".join(str(x) for x in fp.base)}), pela métrica “seções parecidas demais na mudança”: '
                         'é um traço de 2022 e 2026, quando quase todo eleitor já votava num dos finalistas no 1º turno e repetiu o voto (a cópia manipulada '
                         'de cada uma herdou o mesmo valor). '
                         + (f'Deixou passar: {", ".join(fn.tipo)}. ' if len(fn) else '')
                         + 'Limites do teste: o avaliador comparou cada cópia com a eleição real de onde ela veio, uma vantagem que não existe no mundo real; '
                         'a manipulação “regional suave” só foi percebida por um efeito colateral do modo como foi plantada (seções do perdedor com menos de 4% '
                         'zeradas). Uma mudança suave e proporcional numa região inteira não seria vista por estes detectores.', P)]
    st += [Paragraph('Manipulações plantadas: inversão de X e Y em 10% das seções vencidas por Y em 2 UFs sorteadas; inversão em 0,5% das seções '
                     'vencidas por Y no país; 8% dos votos de Y passados a X em 20% dos municípios; 15% de Y passados a X em 10% das seções; X fixado em 60% '
                     'em 5% das seções; metade da habilitação sem digital passada a X nas seções do décimo mais alto; 4% dos válidos passados a X numa região '
                     'inteira. Protocolo, métricas mascaradas e a avaliação independente em teste_cego/.', SM)]

    # ---------------- detectores
    st += [PageBreak(), Paragraph('3. Há cara de regra fixa (“algoritmo”) na mudança?', H2),
           Paragraph('Modelo de referência: cada seção repete o próprio 1º turno (fatia entre os dois finalistas) mais a mudança que as outras seções do '
                     'mesmo prédio tiveram. O “esperado” vem de simulação (Monte Carlo) com a dispersão de cada eleição. Uma regra que somasse votos a um '
                     'candidato em parte das seções deixaria seções fora do modelo e um saldo para um lado; uma regra que calculasse o resultado a partir '
                     'do 1º turno deixaria as seções parecidas demais entre si e picos em proporções fixas; uma inversão deixaria seções que só cabem no '
                     'modelo com os candidatos trocados.', P)]
    t = [['Detector'] + [NOME[a] for a in det.index]]
    for c, nome, dd in ROTULO_DET:
        if c in det:
            t.append([nome] + [n(v, dd) if pd.notna(v) else '—' for v in det[c]])
    st += [table(t, font=7, widths=[9.6 * cm] + [4.2 * cm] * len(det))]
    st += [Paragraph(f'Leitura. 2022 e 2026 são parecidos entre si e diferentes de 2014 e 2018: em 2014 e 2018 o 1º turno teve terceiros fortes '
                     '(Marina, Ciro, Alckmin), e a redistribuição desses votos espalha a mudança; em 2022 e 2026 quase todos já votavam num dos dois '
                     'finalistas e repetiram o voto, então as seções mudam menos do que um sorteio binomial preveria (dispersão abaixo de 1, “parecidas '
                     f'demais” em 13% a 16% dos locais nos dois anos). Em 2026: {n(duf[duf.ano == 2026].trocas_obs.sum())} seções com cara de inversão, '
                     f'{n(duf[duf.ano == 2026].fora4_obs.sum())} fora do modelo em {n(duf[duf.ano == 2026].secoes.sum())}, nenhum pico em proporção fixa, e a menor diferença '
                     f'entre previsto e observado das quatro eleições ({n(det.loc[2026, "transf_rmse_municipio_pp"], 2)} ponto por município).', P),
           Paragraph('Ganho médio do candidato do PT pela fatia que ele tinha no 1º turno, na mesma seção', H2), fig_img(fg['curva'], 21),
           Paragraph('Nas quatro eleições, o ganho é maior onde a disputa estava aberta e quase zero onde o candidato já tinha mais de 95%: é o desenho '
                     'de votos de terceiros e de quem não votou no 1º turno sendo redistribuídos. Uma regra que somasse uma proporção fixa aos votos do '
                     'candidato faria o ganho crescer com a fatia do 1º turno.', SM)]
    t = [['Eleição', 'Candidato', 'Seções', 'Votos 2º÷1º\np5', 'p25', 'mediana', 'p75', 'p95', 'Variação (p.p.)\np5', 'mediana', 'p95']]
    for x in qt.itertuples():
        t.append([NOME[x.ano], x.A if x.candidato == 'A' else x.B, n(x.secoes), n(x.p5, 3), n(x.p25, 3), n(x.p50, 3), n(x.p75, 3), n(x.p95, 3),
                  sn(x.var_pp_p5, 1), sn(x.var_pp_mediana, 1), sn(x.var_pp_p95, 1)])
    st += [CondPageBreak(5 * cm), Paragraph('Crescimento de cada candidato por seção (seções com 20+ votos no 1º turno)', H2),
           table(t, font=7, widths=[4.6 * cm, 2.2 * cm, 1.8 * cm] + [1.6 * cm] * 5 + [2.2 * cm, 1.8 * cm, 1.8 * cm])]

    # ---------------- inversoes
    st += [PageBreak(), Paragraph('4. Votos invertidos? Espelho com a eleição anterior e RJ/GO', H2),
           Paragraph('Se os votos de uma seção ou município tivessem sido trocados entre os candidatos, o resultado ficaria perto do “espelho” do que se '
                     'esperava: 1 − (fatia na eleição anterior + mudança nacional). Contamos as unidades em que o espelho explica muito melhor (resíduo '
                     'de 15+ pontos no normal e de até 5 no espelho), só onde a eleição anterior não foi meio a meio. A comparação entre eleições mostra '
                     'o que é normal: realinhamento político de verdade produz “espelhos”.', P)]
    t = [['De', 'Para', 'Nível', 'Unidades', 'Mudança\nnacional (p.p.)', 'Correlação', 'Resíduo dp\n(p.p.)', 'Espelho forte', 'por 10 mil']]
    for x in esp.itertuples():
        t.append([x.de, x.para, x.nivel.replace('secao', 'seção').replace('municipio', 'município'), n(x.unidades), sn(x.mudanca_nacional_pp, 2),
                  n(x.correlacao, 3), n(x.residuo_dp_pp, 2), n(x.espelho_forte), n(x.espelho_forte_por_10mil, 2)])
    st += [table(t, font=7.5, widths=[1.5 * cm, 1.5 * cm, 2.2 * cm, 2.4 * cm, 2.8 * cm, 2.2 * cm, 2.4 * cm, 2.6 * cm, 2.2 * cm])]
    eu = espuf[espuf.uf.isin(['RJ', 'GO'])]
    st += [Paragraph('Espelho forte por seção em RJ e GO: ' + '; '.join(f'{x.uf} {x.de}→{x.para}: {n(x.espelho_forte)} de {n(x.visiveis)}'
                                                                       for x in eu.itertuples()) + '.', SM)]
    foco = duf[duf.uf.isin(['RJ', 'GO']) & duf.ano.isin([2022, 2026])]
    t = [['UF', 'Ano', '% PT\n1º t.', '% adv.\n1º t.', '% outros\n1º t.', 'PT\n(p.p.)', 'Adversário\n(p.p.)', 'Votos PT\n2º÷1º', 'Votos adv.\n2º÷1º',
          'Compareci-\nmento', 'Viradas\n→ PT', 'Viradas\n→ adv.', 'Fora do\nmodelo', 'Com cara de\ninversão', '% Caiado\n1º t.']]
    for x in foco.sort_values(['uf', 'ano']).itertuples():
        t.append([x.uf, x.ano, n(x.pct_A_1t, 1), n(x.pct_B_1t, 1), n(x.pct_outros_1t, 1), sn(x.var_A_pp, 2), sn(x.var_B_pp, 2), sn(x.cresc_votos_A_pct, 1) + '%',
                  sn(x.cresc_votos_B_pct, 1) + '%', sn(x.var_comparecimento_pct, 1) + '%', n(x.viradas_para_A), n(x.viradas_para_B), n(x.fora4_obs),
                  n(x.trocas_obs), n(x.pct_caiado_1t, 1)])
    st += [CondPageBreak(5 * cm), Paragraph('RJ e GO, 2022 e 2026', H2), table(t, font=7, widths=[1 * cm, 1.2 * cm] + [1.7 * cm] * 13)]
    u26 = duf[duf.ano == 2026].set_index('uf')
    rk = u26.var_A_pp.rank(ascending=False)
    st += [Paragraph(f'Em 2026, GO teve a maior mudança do país ({sn(u26.loc["GO", "var_A_pp"], 2)} ponto para Lula e {sn(u26.loc["GO", "var_B_pp"], 2)} para '
                     f'Flávio) porque Caiado, candidato de lá, teve {n(u26.loc["GO", "pct_caiado_1t"], 1)}% no 1º turno e esses votos foram redistribuídos. '
                     f'No RJ, Lula ganhou {sn(u26.loc["RJ", "var_A_pp"], 2)} ponto ({int(rk["RJ"])}º maior ganho entre as UFs) e Flávio ficou praticamente '
                     f'igual ({sn(u26.loc["RJ", "var_B_pp"], 2)}): Lula ficou com quase todos os {n(u26.loc["RJ", "pct_outros_1t"], 1)}% dos outros candidatos. '
                     'Nos dois estados, nenhuma seção fica fora do modelo do próprio prédio nem tem cara de inversão: a mudança foi do mesmo tamanho nas '
                     'seções vizinhas.', P)]

    # ---------------- Monte Carlo
    st += [PageBreak(), Paragraph('5. Monte Carlo: a virada cabe no 1º turno?', H2)]
    if (D / 'mc_transferencias.csv').exists():
        tr = r('mc_transferencias.csv')
        mc = r('mc_nacional.csv').set_index('ano')
        inv = r('mc_inversoes_necessarias.csv').set_index('ano')
        ufp = r('mc_uf_prevista_pelas_outras.csv')
        ct = r('origem_contas_nacionais.csv').set_index('ano').loc[2026]
        og = r('origem_ganho_mesmo_predio.csv')
        st += [Paragraph(f'<b>A conta da virada (exata).</b> Do 1º para o 2º turno de 2026, Lula ganhou {n(ct.ganho_A)} votos e Flávio {n(ct.ganho_B)}. '
                         f'A soma ({n(ct.ganho_A + ct.ganho_B)}) é exatamente o que ficou disponível: {n(ct.outros_candidatos_1t)} votos dos candidatos '
                         f'eliminados, {n(ct.branco_nulo_1t - ct.branco_nulo_2t)} brancos e nulos a menos ({n(ct.branco_nulo_1t)} → {n(ct.branco_nulo_2t)}) '
                         f'e {n(ct.comparecimento_2t - ct.comparecimento_1t)} eleitores a mais. Como isso se dividiu entre os dois é estimativa.', P)]
        t = [['Eleição', 'Origem do voto a mais', 'Para o PT', 'Para o adversário']]
        for y in og.itertuples():
            t.append([NOME[y.ano], y.fonte, n(100 * y.para_A, 0) + '%', n(100 * y.para_B, 0) + '%'])
        st += [Paragraph('Dentro do mesmo prédio: para onde foi cada voto a mais', H2), table(t, font=7.5, widths=[5.2 * cm, 7 * cm, 3 * cm, 3.4 * cm]),
               Paragraph('Comparando seções do mesmo local de votação (mesmo bairro, mesmo perfil), quanto do ganho de cada candidato acompanha os votos '
                         'que estavam com outros candidatos, os brancos e nulos que deixaram de ser e a abstenção que caiu. É a estimativa menos sujeita '
                         'ao efeito da geografia.', SM),
               Paragraph('Transferências estimadas no país (regressão ecológica com restrições: cada grupo do 1º turno se divide entre o PT, o adversário, '
                         'branco/nulo e abstenção, com partes entre 0 e 1 que somam 100%; por região; intervalo de 95% por reamostragem dos locais de '
                         'votação). Mostra o movimento líquido que melhor explica as seções, não o voto de cada pessoa; entre regiões, parte do efeito é '
                         'geografia (o branco/nulo do 1º turno era mais alto onde o PT é forte). A troca dentro da mesma seção (um eleitor sai, outro entra) '
                         'não aparece nos totais: os entrantes brutos são um mínimo.', SM)]
        for ano in (2026, 2022):
            x = tr[tr.ano == ano].copy()
            x['grupo_1t'] = x.grupo_1t.replace(nomes_1t(ano))
            t = [['Grupo do 1º turno', 'Votos no\ngrupo', f'Para {NOMES_A[ano]}', 'IC 95%', f'Para {NOMES_B[ano]}', 'IC 95%', 'Branco/nulo', 'Abstenção']]
            for y in x.itertuples():
                if pd.isna(y.votos_no_grupo):
                    t.append([y.grupo_1t, '', n(y.para_A), f'{n(y.para_A_ic_baixo)} a {n(y.para_A_ic_alto)}', '', '', '', ''])
                    continue
                t.append([y.grupo_1t, n(y.votos_no_grupo), n(y.para_A), f'{n(y.para_A_ic_baixo)} a {n(y.para_A_ic_alto)}', n(y.para_B),
                          f'{n(y.para_B_ic_baixo)} a {n(y.para_B_ic_alto)}', n(y.para_branco_nulo), n(y.para_abstencao)])
            st += [CondPageBreak(6 * cm), Paragraph(NOME[ano], H2), table(t, font=7, widths=[6.4 * cm, 2.4 * cm, 2.4 * cm, 3.6 * cm, 2.4 * cm, 3.6 * cm, 2.3 * cm, 2.3 * cm])]
        t = [['Eleição', 'PT entre os dois\nno 1º turno', 'PT no 2º turno\n(observado)', 'Previsto pelas\noutras UFs', 'Faixa 95%', 'P(PT vence)']]
        for a, y in mc.iterrows():
            t.append([NOME[a], n(y.pct_A_1t_entre_A_e_B, 2) + '%', n(y.pct_A_observado, 2) + '%', n(y.pct_A_previsto, 2) + '%',
                      f'{n(y.previsto_p2_5, 2)} a {n(y.previsto_p97_5, 2)}%', n(y.prob_A_vence_pct, 0) + '%'])
        st += [CondPageBreak(6 * cm), Paragraph('Cada UF prevista só com o que as outras UFs da região mostraram', H2), table(t, font=7.5, widths=[5 * cm] + [3.4 * cm] * 5),
               Paragraph('Para cada UF, as transferências (mínimos quadrados não negativos, seção a seção) são estimadas nas outras UFs da mesma região, '
                         'sem a própria UF, e aplicadas ao 1º turno dela; somando as UFs, sai a previsão nacional. O Monte Carlo repete isso reamostrando os '
                         'locais de votação; a faixa estreita reflete só essa amostragem, e o erro típico do modelo é o das outras eleições na mesma tabela '
                         '(0,1 a 0,4 ponto).', SM)]
        u = ufp[ufp.ano == 2026].set_index('uf')
        u22 = ufp[ufp.ano == 2022].set_index('uf')
        st += [Paragraph('Resíduo (observado − previsto pelas outras UFs), 2026: ' + ', '.join(
            f'{uf} {sn(u.loc[uf, "residuo_pp"], 1)}' for uf in u.residuo_pp.abs().sort_values(ascending=False).index[:8]) +
            f'. RJ {sn(u.loc["RJ", "residuo_pp"], 1)} (2022: {sn(u22.loc["RJ", "residuo_pp"], 1)}); GO {sn(u.loc["GO", "residuo_pp"], 1)} '
            f'(2022: {sn(u22.loc["GO", "residuo_pp"], 1)}).', P)]
        t = [['Eleição', 'Margem', 'Vencidas pelo\nperdedor', 'Inversões\n(mínimo)', 'Inversões\n(típico)']]
        for a, y in inv.iterrows():
            t.append([NOME[a], n(y.margem), n(y.secoes_vencidas_pelo_perdedor), n(y.invertidas_minimo), n(y.invertidas_tipico)])
        st += [CondPageBreak(5 * cm), Paragraph('Quantas seções precisariam estar invertidas para mudar o resultado', H2), table(t, font=7.5, widths=[5 * cm] + [3.6 * cm] * 4),
               Paragraph(f'Mínimo: invertendo as seções mais desequilibradas a favor do perdedor; típico: seções comuns. Em 2026, o detector de inversão '
                         f'encontrou {n(duf[duf.ano == 2026].trocas_obs.sum())} seções com esse perfil. No teste cego, inversões plantadas em 0,5% das seções '
                         'vencidas por um candidato (cerca de mil seções) saltaram centenas de vezes acima do esperado.', SM)]

    # ---------------- horario e vizinhas
    st += [CondPageBreak(7 * cm), Paragraph('6. Seções abertas até tarde × vizinhas do mesmo prédio', H2)]
    t = [['Eleição', 'Grupo', 'Seções', 'Locais com\nos dois tipos', 'PT: marcadas\n− vizinhas', 'IC 95%', 'Marcadas\nganham mais']]
    for x in viz.itertuples():
        t.append([x.ano, x.grupo, n(x.secoes_marcadas), n(x.locais_com_os_dois_tipos), sn(x.dif_ganho_A_pp_media, 2) + ' p.p.', '± ' + n(x.dif_ic95_pp, 2),
                  n(x.pct_locais_marcadas_ganham_mais, 1) + '%'])
    st += [table(t, font=7.5, widths=[1.6 * cm, 7 * cm, 2.2 * cm, 2.6 * cm, 3.6 * cm, 2 * cm, 4 * cm]),
           Paragraph('Se as seções que ficaram abertas até mais tarde tivessem recebido votos de outra natureza, o ganho do PT nelas seria diferente '
                     'do das seções vizinhas do mesmo prédio, que têm o mesmo perfil de eleitor. A diferença é de centésimos de ponto.', SM)]

    # ---------------- idosos
    st += [PageBreak(), Paragraph('7. Títulos de falecidos: o que os dados públicos permitem ver', H2),
           Paragraph('O voto não é ligado ao eleitor em nenhum arquivo público: o BU traz totais, o RDV embaralha os votos e o log registra a habilitação '
                     'sem o número do título. Não há, portanto, como saber se um título específico (de alguém falecido ou não) votou. O que o TSE publica é '
                     'o comparecimento por idade, por zona. Se títulos de falecidos tivessem sido usados em volume, o comparecimento das faixas mais '
                     'velhas, onde se concentram os óbitos ainda não baixados no cadastro, subiria. A publicação do TSE com o 2º turno de 2026 ainda não '
                     'saiu (o arquivo disponível é de 21/10/2026 e traz só o 1º turno).', P)]
    if 'idosos' in fg:
        ip = r('idosos_comparecimento_pais.csv')
        st += [fig_img(fg['idosos'], 21)]
        ordem = ['até 79 anos', '80 a 84 anos', '85 a 89 anos', '90 a 94 anos', '95 a 99 anos', '100 anos ou mais']
        piv = ip.assign(col=ip.ano.astype(str) + ' · ' + ip.NR_TURNO.astype(str) + 'º t.').pivot(index='faixa', columns='col', values='comparecimento_pct').reindex(ordem)
        apt = ip.assign(col=ip.ano.astype(str) + ' · ' + ip.NR_TURNO.astype(str) + 'º t.').pivot(index='faixa', columns='col', values='QT_APTOS').reindex(ordem)
        t = [['Idade'] + list(piv.columns)]
        for f in ordem:
            t.append([f] + [f'{n(piv.loc[f, c], 1)}% ({n(apt.loc[f, c])})' for c in piv.columns])
        st += [table(t, font=7, widths=[3.6 * cm] + [4.4 * cm] * len(piv.columns)),
               Paragraph('Comparecimento (%) e, entre parênteses, eleitores aptos na faixa. Fonte: perfil de comparecimento e abstenção do TSE.', SM)]
        cem = piv.loc['100 anos ou mais']
        st += [Paragraph(f'Dos {n(apt.loc["100 anos ou mais", "2026 · 1º t."])} títulos de pessoas com 100 anos ou mais, a faixa onde mais se acumulam '
                         f'óbitos não baixados, {n(cem["2026 · 1º t."], 2)}% votaram no 1º turno de 2026 ({n(cem["2022 · 1º t."], 2)}% em 2022). '
                         'Não há sinal de uso em massa de títulos nessa faixa.', P)]
        if (D / 'idosos_80a99_zona_x_lula.csv').exists():
            uu = r('idosos_80a99_por_uf.csv')
            zq = r('idosos_80a99_zona_x_lula.csv')
            st += [Paragraph(f'O comparecimento de 80 a 99 anos subiu do 1º turno de 2022 para o de 2026 em {int((uu.variacao_2022_2026_pp > 0).sum())} de '
                             f'{int(uu.variacao_2022_2026_pp.notna().sum())} UFs (maiores altas: ' + ', '.join(
                                 f'{x.SG_UF} {sn(x.variacao_2022_2026_pp, 1)}' for x in uu.nlargest(4, 'variacao_2022_2026_pp').itertuples()) +
                             f' ponto). Por zona, a alta não acompanha o voto em Lula: correlação de {n(zq.correlacao_com_lula_1t.iloc[0], 2)} com a fatia '
                             f'dele no 1º turno e de {n(zq.correlacao_com_ganho_lula.iloc[0], 2)} com o ganho dele no 2º turno. O 2º turno de 2026 por idade '
                             'entra quando o TSE publicar.', P)]

    # ---------------- limites
    st += [CondPageBreak(6 * cm), Paragraph('8. Limites e o que fica em aberto', H2),
           Paragraph('Uma mudança suave e igual numa região inteira não deixa marca seção a seção: no teste cego, a manipulação “regional suave” serve para '
                     'mostrar esse limite. Para isso, a verificação é física (BU impresso × BU publicado, RDV × BU, assinatura digital, teste de '
                     'integridade). O horário de cada voto existe no log, mas não o candidato: o voto é secreto e o registro de votos não tem horário. '
                     'Fiscais não aparecem nos dados públicos. A “seção de SC relatada” não foi identificada: com município, zona e seção, a conferência '
                     'BU × RDV × log daquela urna pode ser feita como nos outros relatórios. O comparecimento por idade do 2º turno de 2026 entra quando o TSE publicar.', P),
           Paragraph('Como repetir: scripts/padroes_2t.py (coleta_2026, base, cego_prepara, cego_avalia, cego_abre), scripts/padroes_aberta.py e '
                     'scripts/make_padroes_report.py; detectores em scripts/padroes_lib.py. Todas as tabelas em PADROES_1T_2T.xlsx e nos CSVs da pasta.', SM)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7)
        cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(D / 'PADROES_1T_2T.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='1º × 2º turno: padrão algorítmico, inversões e alegações', author='AuditaBR').build(
        st, onFirstPage=footer, onLaterPages=footer)
    print('OK', D / 'PADROES_1T_2T.pdf')

    from ultimo_voto_2026t2 import xlsx_leve
    abas = []
    for nome in sorted(D.glob('*.csv')):
        abas.append((nome.stem[:31], pd.read_csv(nome, low_memory=False, **CSV)))
    for nome in sorted((D / 'teste_cego').glob('*.csv')):
        abas.append((('cego_' + nome.stem)[:31], pd.read_csv(nome, **CSV)))
    xlsx_leve(D / 'PADROES_1T_2T.xlsx', abas)
    print('OK', D / 'PADROES_1T_2T.xlsx')


NOMES_A = {2014: 'Dilma', 2018: 'Haddad', 2022: 'Lula', 2026: 'Lula'}
NOMES_B = {2014: 'Aécio', 2018: 'Bolsonaro', 2022: 'Bolsonaro', 2026: 'Flávio'}

if __name__ == '__main__':
    main()
