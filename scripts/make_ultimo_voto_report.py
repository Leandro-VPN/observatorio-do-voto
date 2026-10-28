"""Relatorio: horario do ultimo voto por secao, 2o turno de 2026 (le relatorios/verificacoes/ultimo_voto_2026t2/).
Saida: ULTIMO_VOTO_2026T2.pdf
"""
import os
import sys
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('UF', 'BA')
from make_bahia_reports import P, H1, H2, SM, NOTE, table, n  # noqa: E402

D = ROOT / 'relatorios' / 'verificacoes' / 'ultimo_voto_2026t2'
CSV = dict(sep=';', encoding='utf-8-sig', decimal=',')


def main():
    F = pd.read_csv(D / 'faixas.csv', **CSV)
    FF = pd.read_csv(D / 'faixas_finas.csv', **CSV)
    X = pd.read_csv(D / 'cenario_x_faixa.csv', **CSV)
    cob = pd.read_csv(D / 'cobertura.csv', **CSV)
    d = pd.read_csv(D / 'ultimo_voto_por_secao.csv', low_memory=False, **CSV)
    w = d.peso
    v17, v19, vt = (w * d.votos_apos_17h).sum(), (w * d.votos_apos_19h).sum(), (w * d.votos_log).sum()
    c = d[d.cenario == 'C']
    ufs = sorted(cob[cob.com_log_usado > 0].uf)
    completa = bool((cob.com_log_usado >= .99 * cob.secoes).all())

    st = [Paragraph('2º turno de 2026: a que horas foi o último voto de cada seção', H1),
          Paragraph('O boletim de urna traz o horário de encerramento, não o do último voto. O último voto está no log da urna: é a última linha '
                    '“O voto do eleitor foi computado” do dia. Convertemos para hora de Brasília e separamos as seções em três faixas: último voto até 17h00, '
                    'entre 17h00 e 19h00 e depois das 19h00.', P),
          Paragraph(('Cobertura: todas as seções com log. ' if completa else
                     f'Cobertura: {len(ufs)} UFs ({", ".join(ufs)}), {n(int(cob[cob.uf.isin(ufs)].secoes.sum()))} seções. Todas as seções que encerraram a partir de 17h10 têm log; '
                     f'as que encerraram antes entram por uma amostra aleatória de {n(int(d[d.estrato == "encerrou_antes_17h10"].shape[0]))} seções, com peso por UF. '
                     + ('As demais UFs entram quando o download dos logs do 2º turno terminar.' if len(ufs) < 27 else
                        'Com o download completo dos logs, a conta passa a usar todas as seções, sem peso.')), NOTE),
          Paragraph('Último voto por faixa', H2)]
    t = [['Último voto', 'Seções', '% das\nseções', 'Último voto\nmédio', 'Último voto\nmediano', 'Votos após\n17h (média)', 'Min. do último\nvoto ao encerr.', '% Lula', '% Flávio', 'Mais votos']]
    for r in F.itertuples():
        t.append([r.faixa, n(r.secoes_estimadas), n(r.pct_secoes, 2), r.ultimo_voto_medio, r.ultimo_voto_mediano, n(r.votos_apos_17h_media, 1),
                  n(r.min_entre_ultimo_voto_e_encerramento_mediana, 1), n(r.pct_lula, 2), n(r.pct_flavio, 2), r.vencedor_votos])
    st += [table(t, font=6.8, widths=[2.6 * cm, 1.6 * cm, 1.2 * cm, 1.5 * cm, 1.5 * cm, 1.6 * cm, 1.9 * cm, 1.3 * cm, 1.3 * cm, 2.2 * cm]),
           Paragraph(f'<b>Votos depois das 17h:</b> cerca de {n(v17)} em {n(vt)} ({n(100 * v17 / vt, 3)}%). <b>Depois das 19h:</b> {n(v19)} votos, um em cada '
                     f'seção, todos até poucos minutos depois das 19h (eleitores que estavam na fila). % Lula e % Flávio são do total da seção no dia: '
                     'o voto é secreto e o registro de votos não tem horário, então não há como saber em quem votaram os eleitores depois das 17h.', SM),
           Paragraph('Detalhe entre 17h e 19h', H2)]
    t = [['Último voto', 'Seções', '% das seções', '% Lula']]
    for r in FF.itertuples():
        t.append([r.faixa_fina, n(r.secoes_estimadas), n(r.pct_secoes, 2), n(r.pct_lula, 2)])
    st += [table(t, font=7.5, widths=[4 * cm, 3 * cm, 3 * cm, 3 * cm]),
           Paragraph('A maior parte das seções com voto depois das 17h termina até 17h15: é a fila que já estava formada às 17h.', SM),
           Paragraph('Seções que ficaram abertas até as 19h: quando foi o último voto?', H2)]
    t = [['Cenário', 'Último voto', 'Seções', 'Último voto médio', 'Votos após 17h (média)', '% Lula']]
    nome = {'A': 'A · fechou e BU recebido antes das 19h', 'B': 'B · fechou antes das 19h, BU depois', 'C': 'C · fechou às 19h ou depois'}
    for r in X.itertuples():
        t.append([nome.get(r.cenario, r.cenario), r.faixa, n(r.secoes_estimadas), r.ultimo_voto_medio, n(r.votos_apos_17h_media, 1), n(r.pct_lula, 2)])
    st += [table(t, font=7, widths=[5 * cm, 2.6 * cm, 1.8 * cm, 2.4 * cm, 2.6 * cm, 1.6 * cm]),
           Paragraph(f'<b>Ficar aberta até as 19h não quer dizer que houve votação até as 19h.</b> Das {n(len(c))} seções que encerraram às 19h ou depois, '
                     f'{n(int((c.votos_apos_17h == 0).sum()))} ({n(100 * (c.votos_apos_17h == 0).mean(), 0)}%) não tiveram nenhum voto depois das 17h. '
                     f'As demais somaram {n(int(c.votos_apos_17h.sum()))} votos depois das 17h (no máximo {n(int(c.votos_apos_17h.max()))} numa seção), '
                     f'e só {n(int((c.votos_apos_19h > 0).sum()))} tiveram voto depois das 19h.', P),
           Paragraph('Limites: horário do relógio da urna, convertido para Brasília pelo fuso estimado de cada município (o relógio das urnas foi '
                     'conferido contra o servidor do TSE e fica, em geral, a poucos minutos). Exterior fora. Descritivo: nada aqui indica irregularidade. '
                     'Tabela por seção em ULTIMO_VOTO_2026T2.xlsx. Como repetir: scripts/ultimo_voto_2026t2.py e scripts/make_ultimo_voto_report.py.', SM)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7); cv.setFillColor(colors.grey)
        cv.drawString(2 * cm, 1.2 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(19 * cm, 1.2 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(D / 'ULTIMO_VOTO_2026T2.pdf'), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
                      title='Último voto por seção, 2º turno 2026', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', D / 'ULTIMO_VOTO_2026T2.pdf')


if __name__ == '__main__':
    main()
