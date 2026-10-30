"""Relatorio do teste de "gatilho" no RDV (2o turno de 2026): o RDV guarda o numero digitado em cada voto nulo; as secoes
onde cada codigo aparece destoam das vizinhas do mesmo local? Le relatorios/verificacoes/rdv_gatilho/ (scripts/rdv_gatilho.py).
Saida: RDV_GATILHO.pdf, RDV_GATILHO.xlsx e figuras/.
"""
import json
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
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

D = ROOT / 'relatorios' / 'verificacoes' / 'rdv_gatilho'
FIG = D / 'figuras'
CSV = dict(sep=';', encoding='utf-8-sig', decimal=',')
AZUL, LARANJA, CINZA = '#2a78d6', '#eb6834', '#9a9993'   # paleta validada (categorica, ordem fixa)


def r(nome):
    return pd.read_csv(D / nome, dtype={'codigo': str}, **CSV)


def exemplo_rdv():
    """Uma secao real de AC: o RDV de presidente, agrupado como vem no arquivo."""
    x = pd.read_parquet(ROOT / 'research' / 'rdv_gatilho' / '2026-t2' / 'AC.parquet')
    x = x[x.nulo >= 5].sort_values(['municipio', 'zona', 'secao']).iloc[0]
    nul = json.loads(x.nulos)
    linhas = [['13 (nominal)', n(x.v13)], ['22 (nominal)', n(x.v22)], ['branco', n(x.branco)]]
    linhas += [[f'nulo, digitado “{k}”', n(v)] for k, v in sorted(nul.items(), key=lambda kv: -kv[1])]
    return x, linhas


def figura(v, c):
    FIG.mkdir(parents=True, exist_ok=True)
    lim = float(v.limite_bonferroni_t.iloc[0])
    fig, ax = plt.subplots(figsize=(9.6, 3.8), dpi=160)
    ax.axvspan(-lim, lim, color='#f1f0ec', zorder=0)
    rng = np.random.default_rng(0)
    ax.scatter(v.t, rng.uniform(.6, 1.4, len(v)), s=16, color=CINZA, edgecolor='white', lw=.6, zorder=3,
               label=f'{len(v)} códigos reais (2º turno 2026)')
    for i, (regra, txt, cor) in enumerate((('2_para_1', 'gatilho plantado: 2 de cada 3 votos', AZUL),
                                          ('um_em_tres', 'gatilho plantado: 1 em 3 votos do outro', LARANJA))):
        g = c[c.regra == regra]
        ax.scatter(g.t, rng.uniform(2.1, 2.9, len(g)) + 1.2 * i, s=22, color=cor, edgecolor='white', lw=.6, zorder=3, label=txt)
    for s in (-lim, lim):
        ax.axvline(s, color=TINTA2, lw=.8, ls='--', zorder=2)
    ax.text(lim, 4.6, f'  limite (Bonferroni) ±{n(lim, 2)}', fontsize=7, color=TINTA2, va='top')
    ax.set_yticks([])
    ax.set_ylim(0, 4.8)
    _eixos(ax, 'quanto as seções com o código destoam das vizinhas do mesmo local (estatística t)', '')
    ax.legend(fontsize=7.5, frameon=False, loc='upper center', bbox_to_anchor=(.5, -.3), ncol=3, labelcolor=TINTA)
    fig.tight_layout()
    p = FIG / 'varredura_x_plantado.png'
    fig.savefig(p)
    plt.close(fig)
    return p


def main():
    conf = r('rdv_x_bu_2026t2.csv').iloc[0]
    v = r('varredura_codigos_2026t2.csv')
    c = r('calibracao_gatilho_plantado.csv')
    lim = float(v.limite_bonferroni_t.iloc[0])
    acima = v[v.t.abs() > lim]
    st = [Paragraph('RDV: um código digitado muda os votos que vêm depois?', H1),
          Paragraph('2º turno de 2026, presidente, todas as urnas. A pergunta: se a urna tivesse um “gatilho” (por exemplo, alguém digita 99 '
                    'e, a partir dali, os votos passam a seguir uma proporção), dá para perceber nos dados publicados? RDV e BU continuariam batendo, '
                    'porque os dois saem do mesmo programa. Mas a seção onde o gatilho foi digitado ficaria diferente das vizinhas do mesmo prédio.', P)]

    x, linhas = exemplo_rdv()
    st += [Paragraph('1. O que o RDV guarda', H2),
           Paragraph('O RDV (registro digital do voto) é a lista de votos individuais da urna. Cada voto tem só o tipo e o número digitado. Não tem '
                     'horário, título nem posição na fila: no arquivo de 2026 os votos vêm agrupados por número, não na ordem em que foram dados. No '
                     'voto nulo, o RDV guarda o número que o eleitor digitou. É isso que permite procurar um gatilho. Exemplo real, uma seção de '
                     f'{x.uf} (município {x.municipio}, zona {int(x.zona)}, seção {int(x.secao)}):', P),
           table([['Voto para presidente no RDV', 'Quantidade']] + linhas, font=7.5, widths=[7 * cm, 3 * cm])]

    st += [Paragraph('2. RDV × BU em todas as urnas', H2),
           Paragraph(f'O RDV de presidente foi lido em {n(conf.secoes_com_rdv)} das {n(conf.secoes_base)} seções da base. Em {n(conf.rdv_igual_bu)} '
                     f'o RDV soma exatamente o BU (13, 22, brancos e nulos); em {n(conf.rdv_diferente_bu)}, não. Isso confirma que o BU é a soma do RDV, '
                     'mas não prova que o voto gravado é o voto digitado: os dois saem do mesmo programa.', P)]

    st += [CondPageBreak(7 * cm), Paragraph('3. Varredura: cada código nulo contra as vizinhas', H2),
           Paragraph(f'Para cada número digitado como nulo em pelo menos 30 seções ({len(v)} códigos), comparamos as seções onde ele aparece com '
                     'as outras seções do mesmo local de votação. A comparação desconta o 1º turno de cada seção (incluindo os votos dos candidatos '
                     'eliminados), brancos e nulos, abstenção, liberação manual e tamanho. Se um código ligasse uma regra, as seções com ele '
                     f'teriam o voto deslocado para um dos lados. O limite, já corrigido para {len(v)} testes, é |t| > {n(lim, 2)}. '
                     + (f'Nenhum código passou do limite; o maior foi “{v.codigo.iloc[0]}”, com t = {n(v.t.iloc[0], 2)}.' if acima.empty else
                        f'{len(acima)} código(s) passaram do limite: ' + ', '.join(f'“{k}” (t = {n(t, 2)}, {sn(e, 2)} ponto)' for k, t, e in
                                                                                zip(acima.codigo, acima.t, acima.efeito_pp)) +
                        '. A parte “Os códigos acima do limite”, logo abaixo, mostra o tamanho e a natureza desses efeitos.'), P),
           fig_img(figura(v, c), w=24),
           Paragraph('Cada ponto cinza é um código real. Os pontos coloridos são o mesmo teste com um gatilho plantado nos dados (seção 4). A faixa '
                     'clara é o que o acaso explica.', SM)]
    t = [['Código', 'Seções com\no código', 'Votos nulos\ncom ele', 'Diferença na\nfatia de Lula', 'Erro-padrão', 't', 'q (BH)']]
    for y in v.head(12).itertuples():
        t.append([y.codigo, n(y.secoes_com_codigo), n(y.votos_nulos_com_codigo), sn(y.efeito_pp, 2) + ' pt', n(y.ep_pp, 2), n(y.t, 2), n(y.q_bh, 3)])
    if (D / 'codigos_acima_do_limite.csv').exists() and not acima.empty:
        dd = r('codigos_acima_do_limite.csv')
        cresce = ((np.sign(dd.efeito_2_ou_mais_pp) == np.sign(dd.efeito_1_vez_pp)) & (dd.efeito_2_ou_mais_pp.abs() > dd.efeito_1_vez_pp.abs())).sum()
        cp = c[c.fracao_ativa >= .2]
        td = [['Código', 'Seções com\n1 ocorrência', 'Efeito\n(pontos)', 'Seções com\n2 ou mais', 'Efeito\n(pontos)', 'Onde se concentra']]
        for y in dd.itertuples():
            td.append([y.codigo, n(y.secoes_1_vez), f'{sn(y.efeito_1_vez_pp, 2)} ± {n(y.ep_1_vez, 2)}', n(y.secoes_2_ou_mais),
                      f'{sn(y.efeito_2_ou_mais_pp, 2)} ± {n(y.ep_2_ou_mais, 2)}', y.ufs_principais])
        st += [CondPageBreak(7 * cm), Paragraph('Os códigos acima do limite', H2),
               Paragraph(f'Os {len(acima)} códigos acima do limite aparecem em dezenas de milhares de seções e mudam a fatia de Lula em cerca de '
                         f'{n(acima.efeito_pp.abs().median(), 2)} ponto (mediana), uns para um lado e outros para o outro: '
                         + ', '.join(f'“{k}” {sn(e_, 2)}' for k, e_ in zip(acima.codigo, acima.efeito_pp)) +
                         '. Com tantas seções, até uma diferença desse tamanho passa do limite. Um gatilho como o descrito (2 de cada 3 votos, '
                         f'ou 1 em 3 do outro lado) daria t entre {n(cp.t.abs().min(), 0)} e {n(cp.t.abs().max(), 0)} nos cenários plantados '
                         f'em 20% ou mais das seções com o código; os códigos reais ficam em no máximo {n(acima.t.abs().max(), 1)}. Vários '
                         'coincidem com números de partido (11, 12 e 15 são PP, PDT e MDB; 14 foi o número de Renan Santos no 1º turno): quem '
                         'digita um número desses diz algo sobre o perfil político da seção. Um gatilho seria disparado por uma digitação, e o '
                         'efeito seria o mesmo com 1 ou com 5 ocorrências; o perfil cresce com o número de eleitores que digitam. Em '
                         f'{int(cresce)} dos {len(dd)} códigos o efeito com 2 ou mais ocorrências é maior, no mesmo sentido, que com 1.', P),
               table(td, font=7.5, widths=[1.8 * cm, 2.8 * cm, 3.2 * cm, 2.8 * cm, 3.2 * cm, 6.4 * cm])]
    st += [CondPageBreak(7 * cm), Paragraph('Os 12 códigos com maior diferença', H2), table(t, font=7.5, widths=[2.4 * cm, 3 * cm, 3 * cm, 3.4 * cm, 2.6 * cm, 2 * cm, 2.2 * cm])]

    st += [CondPageBreak(8 * cm), Paragraph('4. O teste pegaria um gatilho? (gatilho plantado)', H2),
           Paragraph('Para medir o poder do teste, plantamos um gatilho nos próprios dados de 2026. Escolhemos códigos que aparecem de verdade (o 99 '
                     'e códigos presentes em cerca de 100, 1.000 e 10.000 seções). Nas seções onde o código aparece (todas, metade ou 20% delas), '
                     'a partir de um momento sorteado do dia, aplicamos uma de duas regras: “2 de cada 3 votos para o beneficiado” ou “1 em cada 3 '
                     'votos do outro vira do beneficiado”. Testamos cada lado como beneficiado. Depois rodamos a mesma varredura.', P)]
    t = [['Código', 'Seções com\no código', 'Regra', 'Fração\nativa', 'Beneficiado', 'Seções\nalteradas', 't', 'Posição na\nvarredura', 'Passa o\nlimite']]
    for y in c.itertuples():
        t.append([y.codigo, n(y.secoes_com_codigo), '2 de 3' if y.regra == '2_para_1' else '1 em 3', f'{n(100 * y.fracao_ativa)}%' if y.fracao_ativa >= .01 else '<1%',
                  'Lula' if y.beneficiado == 'X' else 'Flávio', n(y.secoes_ativas), n(y.t, 1), f'{y.posicao_na_varredura}º de {y.codigos_na_varredura}',
                  'sim' if y.passa_bonferroni else 'não'])
    st += [table(t, font=7, widths=[1.8 * cm, 2.4 * cm, 1.8 * cm, 1.8 * cm, 2.2 * cm, 2.2 * cm, 1.6 * cm, 3 * cm, 1.8 * cm]),
           Paragraph(f'Detectado (passou do limite) em {int(c.passa_bonferroni.sum())} de {len(c)} cenários. ' +
                     ('Os que passaram despercebidos: ' + '; '.join(sorted({f'código “{y.codigo}” ({n(y.secoes_com_codigo)} seções) com '
                                                                         f'{n(100 * y.fracao_ativa)}% ativas'
                                                                         for y in c[~c.passa_bonferroni].itertuples()})) + '.'
                      if (~c.passa_bonferroni).any() else ''), SM)]

    det = pd.read_csv(ROOT / 'relatorios' / 'verificacoes' / 'padroes_2t' / 'detectores_por_uf.csv', **CSV)
    det = det[det.ano == 2026]
    st += [CondPageBreak(6 * cm), Paragraph('5. O que este teste não pega', H2),
           Paragraph('O programa que obedecesse a um gatilho também é o que escreve o RDV. Ele poderia gravar o próprio gatilho como um voto comum, e '
                     'então o código não apareceria no arquivo. Um gatilho feito de teclas que não viram voto (corrigir, por exemplo) também não fica '
                     'no RDV. Nesses casos sobra o efeito no resultado, que os testes de vizinhas do relatório de padrões medem seção a seção: em 2026, '
                     f'{n(det.fora4_obs.sum())} seções fora do modelo em {n(det.secoes.sum())} e {n(det.trocas_obs.sum())} com cara de inversão. Um gatilho usado em poucas seções, com efeito pequeno, pode '
                     'ficar abaixo do que a estatística vê.', P),
           Paragraph('<b>Como refinar no teste de integridade.</b> Ali existe a testemunha que falta: a cédula de papel. Os partidos podem incluir nas '
                     'cédulas números estranhos (99, 00, sequências repetidas) e, no fim, comparar não só o BU, mas o RDV da urna testada, voto a voto, '
                     'com as cédulas, incluindo cada nulo digitado. Um gatilho que dependa de uma digitação só seria pego se essa digitação estivesse '
                     'nas cédulas; por isso a escolha dos números deve ser livre e não anunciada.', P),
           Paragraph('Como repetir: scripts/rdv_gatilho.py coleta (lê o RDV de cada urna do zip oficial do TSE) e scripts/rdv_gatilho.py analisa; '
                     'scripts/make_rdv_gatilho_report.py. Tabelas completas em RDV_GATILHO.xlsx e nos CSVs da pasta.', SM)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7)
        cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(D / 'RDV_GATILHO.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='RDV: teste de gatilho', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', D / 'RDV_GATILHO.pdf')
    from ultimo_voto_2026t2 import xlsx_leve
    xlsx_leve(D / 'RDV_GATILHO.xlsx', [(p.stem[:31], pd.read_csv(p, dtype={'codigo': str}, **CSV)) for p in sorted(D.glob('*.csv'))])
    print('OK', D / 'RDV_GATILHO.xlsx')


if __name__ == '__main__':
    main()
