"""Relatorio: encerramento x recebimento do BU no 2o turno de 2026 (prorrogacao ate 19h).
Le relatorios/verificacoes/fechamento_2026t2/ (scripts/fechamento_recebimento_2026t2.py analise).
Saida: FECHAMENTO_X_RECEBIMENTO_2026T2.pdf
"""
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('UF', 'BA')
from make_bahia_reports import P, H1, H2, SM, NOTE, table, n  # noqa: E402

D = ROOT / 'relatorios' / 'verificacoes' / 'fechamento_2026t2'
CSV = dict(sep=';', encoding='utf-8-sig', decimal=',')


def img(p, w):
    from PIL import Image as PI
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def main():
    tot = pd.read_csv(D / 'cenarios_total.csv', **CSV)
    uf = pd.read_csv(D / 'cenarios_por_uf.csv', **CSV)
    fx = pd.read_csv(D / 'faixas_encerramento.csv', **CSV)
    rr = pd.read_csv(D / 'recebimentos_por_15min.csv', sep=';', encoding='utf-8-sig')
    rs = pd.read_csv(D / 'resumo_recebimento_e_predio.csv', sep=';', encoding='utf-8-sig', index_col=0).valor
    S = pd.read_parquet(D / 'secoes_fechamento_recebimento.parquet', columns=['uf', 'cenario'])
    principais = tot[tot.cenario.isin(['A', 'B', 'C'])].copy()
    nsec = int(principais.secoes.sum())
    principais['pct_secoes'] = 100 * principais.secoes / nsec  # base: seções no Brasil (sem o exterior)

    rr['h'] = pd.to_datetime(rr.h)
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.bar(rr.h, rr.bus_recebidos, width=0.009, color='#1a365d', align='edge')
    ax.axvline(pd.Timestamp('2026-10-25 19:00'), color='#c0392b', lw=1)
    ax.set(ylabel='BUs recebidos por 15 min', xlabel='hora de recebimento no TSE (Brasília), 25/10/2026')
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter('%H:%M'))
    fig.tight_layout(); fig.savefig(D / 'recebimento.png', dpi=150); plt.close(fig)

    st = [Paragraph('2º turno de 2026: encerramento da urna × recebimento do boletim', H1),
          Paragraph('Com a votação prorrogada até as 19h, separamos as seções em três cenários pelo horário em que a urna encerrou e pelo '
                    'horário em que o TSE registrou o recebimento do boletim de urna (BU). Para cada um: volume, porcentagem e quem teve mais votos '
                    f'para presidente. Base: {n(nsec)} seções em {n(S[S.uf != "ZZ"].uf.nunique())} UFs; o exterior fica de fora porque vota no horário local de cada país.', P),
          Paragraph('Cenários (horário de Brasília)', H2)]
    t = [['Cenário', 'Seções', '% das\nseções', 'Votos Lula', 'Votos Flávio', '% Lula', '% Flávio', 'Mais votos', 'Seções\nLula / Flávio', 'Encerramento\n(mediana)']]
    for r in principais.itertuples():
        t.append([r.cenario_desc, n(r.secoes), n(r.pct_secoes, 2), n(r.votos_lula), n(r.votos_flavio), n(r.pct_lula, 2), n(r.pct_flavio, 2),
                  r.vencedor_votos, f'{n(r.secoes_lula)} / {n(r.secoes_flavio)}', str(r.mediana_encerramento)])
    st += [table(t, font=6.6, widths=[4.6 * cm, 1.4 * cm, 1.2 * cm, 1.9 * cm, 1.9 * cm, 1.1 * cm, 1.2 * cm, 1.7 * cm, 2 * cm, 1.6 * cm]),
           Paragraph('% Lula e % Flávio sobre os votos nos dois candidatos (brancos e nulos à parte, na planilha). “Seções Lula / Flávio” = seções em que cada '
                     'um teve mais votos. Os votos são do dia inteiro da seção: o BU não separa os votos dados depois das 17h, e o voto é secreto, '
                     'então não é possível saber em quem votaram os eleitores da prorrogação.', SM)]
    resto = tot[~tot.cenario.isin(['A', 'B', 'C'])]
    if len(resto):
        st.append(Paragraph('Fora dos cenários: ' + '; '.join(f'{r.cenario_desc}: {n(r.secoes)} seções' for r in resto.itertuples()) + '.', SM))

    st += [Paragraph('Por que quase tudo é cenário B', H2),
           img(D / 'recebimento.png', 17),
           Paragraph(f'O TSE registrou {n(int(float(rs["recebidos_antes_19h"])))} BUs recebidos antes das 19h, quase todos entre 17h00 e 17h15, e '
                     'nenhum entre 17h15 e 19h00. A partir das 19h o volume sobe e a mediana de recebimento fica em '
                     f'{str(rs["mediana_recebimento"])[11:16]}. É o padrão de recebimento suspenso até o fim da prorrogação: estar no cenário B '
                     'não diz nada sobre a seção, só que ela encerrou no horário normal e transmitiu quando o recebimento reabriu. '
                     'O cenário A são as poucas seções transmitidas nos primeiros minutos, antes da pausa.', P), PageBreak()]

    st += [Paragraph('Quando as urnas encerraram', H2)]
    t = [['Encerramento (Brasília)', 'Seções', '% Lula', '% Flávio']]
    for r in fx.itertuples():
        if r.secoes:
            t.append([str(r.faixa_encerramento), n(r.secoes), n(r.pct_lula, 2), n(r.pct_flavio, 2)])
    st += [table(t, font=7.5, widths=[5 * cm, 3 * cm, 3 * cm, 3 * cm]),
           Paragraph('A grande maioria encerrou entre 17h00 e 17h30, no horário normal. As que ficaram abertas até o fim da prorrogação encerram '
                     'entre 19h00 e 19h05. Encerramentos alguns minutos antes das 19h podem ser a mesma situação com o relógio da urna um pouco '
                     'atrasado; o relógio das urnas foi conferido contra o do TSE em outro teste e fica, em geral, a poucos minutos.', SM)]

    st += [Paragraph('A prorrogação mudou o voto? Comparação no mesmo prédio', H2),
           Paragraph('As seções do cenário C não estão espalhadas ao acaso: se concentram em alguns estados e municípios. Comparar o total do C '
                     'com o do B mistura o efeito do lugar com o do horário. A comparação justa é com as seções do mesmo prédio que encerraram no '
                     'horário normal, mesmo eleitorado de bairro.', P)]
    t = [['Medida', 'Valor'],
         ['Seções do cenário C', n(float(rs['secoes_C']))],
         ['… com seção vizinha no mesmo prédio que encerrou antes das 19h', n(float(rs['com_vizinhas_no_predio']))],
         ['Prédios comparados', n(float(rs['predios']))],
         ['% Lula nas seções C desses prédios', n(float(rs['pct_lula_C']), 2) + '%'],
         ['% Lula nas vizinhas que encerraram antes', n(float(rs['pct_lula_vizinhas']), 2) + '%'],
         ['Mediana da diferença por seção (C − vizinhas)', n(float(rs['mediana_dif_pp']), 2) + ' p.p.'],
         ['Seções C com mais Lula que as vizinhas', n(float(rs['C_mais_lula_que_vizinhas_pct']), 1) + '%'],
         ['Seções C sem vizinha comparável (prédio inteiro ficou aberto)', n(float(rs['secoes_C_sem_vizinha']))]]
    st += [table(t, font=7.5, widths=[11 * cm, 4 * cm]),
           Paragraph('<b>Resultado:</b> no mesmo prédio, as seções que ficaram abertas até as 19h votaram como as vizinhas que fecharam às 17h: diferença '
                     'mediana próxima de zero e metade acima, metade abaixo. A diferença entre os totais dos cenários vem de onde essas seções estão, '
                     'não do horário de encerramento.', P), PageBreak()]

    st += [Paragraph('Por estado', H2)]
    piv = uf[uf.cenario.isin(['A', 'B', 'C'])].pivot_table(index='uf', columns='cenario', values='secoes', aggfunc='sum', fill_value=0)
    pl = uf[uf.cenario == 'C'].set_index('uf')
    t = [['UF', 'A', 'B', 'C', '% C', '% Lula no C', '% Lula no B']]
    plb = uf[uf.cenario == 'B'].set_index('uf')
    for u, r in piv.sort_values('C', ascending=False).iterrows():
        tt = r.sum()
        t.append([u, n(r.get('A', 0)), n(r.get('B', 0)), n(r.get('C', 0)), n(100 * r.get('C', 0) / tt, 2),
                  n(pl.pct_lula.get(u), 2) if u in pl.index else '—', n(plb.pct_lula.get(u), 2) if u in plb.index else '—'])
    st += [table(t, font=7, widths=[1.5 * cm, 2 * cm, 2.5 * cm, 2 * cm, 1.8 * cm, 2.5 * cm, 2.5 * cm])]

    st += [Paragraph('Limites e o que pedir ao TSE', H2)]
    for t_ in ['Encerramento é o relógio da urna (hora local, convertida para Brasília pelo horário de abertura de cada município); recebimento é o '
               'relógio do servidor do TSE.',
               'Não é possível saber em quem votaram os eleitores depois das 17h: o BU traz o total do dia e o registro de votos (RDV) é embaralhado e sem horário.',
               'Para confirmar a pausa no recebimento entre 17h15 e 19h, cabe pedir ao TSE, por Lei de Acesso à Informação, a instrução de transmissão '
               'do 2º turno e o registro de recepção do JE-Connect com horário e ponto de transmissão.']:
        st.append(Paragraph('• ' + t_, P))
    st.append(Paragraph('Descritivo: nenhum número aqui indica irregularidade. Como repetir: scripts/fechamento_recebimento_2026t2.py (coleta, analise) '
                        'e scripts/make_fechamento_report.py; tabelas em FECHAMENTO_X_RECEBIMENTO_2026T2.xlsx.', NOTE))

    def footer(c, d):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1.2 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        c.drawRightString(19 * cm, 1.2 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(D / 'FECHAMENTO_X_RECEBIMENTO_2026T2.pdf'), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=2 * cm, title='Encerramento × recebimento do BU, 2º turno 2026', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', D / 'FECHAMENTO_X_RECEBIMENTO_2026T2.pdf')


if __name__ == '__main__':
    main()
