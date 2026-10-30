"""Relatorio: presidente 2026, 1o x 2o turno por secao (le relatorios/verificacoes/virada_1t_2t_2026/, gerado por
scripts/virada_1t_2t_2026.py). Saida: VIRADA_1T_2T_2026.pdf
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('UF', 'BA')
from make_bahia_reports import P, H1, H2, SM, NOTE, table, n  # noqa: E402

D = ROOT / 'relatorios' / 'verificacoes' / 'virada_1t_2t_2026'
CSV = dict(sep=';', encoding='utf-8-sig', decimal=',')


def sn(x, d=1):
    """Numero com sinal (+/-) no padrao brasileiro."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return '—'
    return ('+' if x > 0 else '') + n(x, d)


CAB = ['', 'Seções', '% Lula\n1º t.', '% Flávio\n1º t.', '% outros\n1º t.', '% Lula\n2º t.', '% Flávio\n2º t.',
       'Votos Lula\n2º x 1º', 'Votos Flávio\n2º x 1º', 'Lula\n(p.p.)', 'Flávio\n(p.p.)', 'Viradas\n→ Lula', 'Viradas\n→ Flávio', '100%']
LARG = [3.6 * cm, 1.6 * cm] + [1.45 * cm] * 5 + [1.7 * cm] * 2 + [1.3 * cm] * 2 + [1.5 * cm] * 2 + [1.1 * cm]


def linha(nome, r):
    return [nome, n(r.secoes), n(r.t1_p13, 2), n(r.t1_p22, 2), n(r.t1_poutros, 2), n(r.t2_p13, 2), n(r.t2_p22, 2),
            sn(r.cresc_votos_13_pct) + '%', sn(r.cresc_votos_22_pct) + '%', sn(r.var_13_pp, 2), sn(r.var_22_pp, 2),
            n(r.viradas_para_13), n(r.viradas_para_22), n(r.secoes_100pct)]


def main():
    res = json.loads((D / 'resumo.json').read_text(encoding='utf-8'))
    reg = pd.read_csv(D / 'por_regiao.csv', **CSV)
    uf = pd.read_csv(D / 'por_uf.csv', **CSV)
    mun = pd.read_csv(D / 'por_municipio.csv', **CSV)
    vir = pd.read_csv(D / 'secoes_com_virada.csv', low_memory=False, **CSV)
    cem = pd.read_csv(D / 'secoes_100pct_um_candidato.csv', low_memory=False, **CSV)
    cand = pd.read_csv(D / 'candidatos_1o_turno.csv', **CSV)
    br = reg[reg.regiao == 'Brasil (sem exterior)'].iloc[0]

    st = [Paragraph('Presidente 2026: o que mudou do 1º para o 2º turno, seção por seção', H1),
          Paragraph('Para cada seção eleitoral, o voto para presidente no 1º turno (4/10) e no 2º turno (25/10), lido do boletim de urna (BU) '
                    'de cada urna nos arquivos de dados abertos do TSE. Lula (13) e Flávio Bolsonaro (22) disputaram o 2º turno; no 1º turno os '
                    'demais candidatos estão somados em “outros”. Percentuais sobre os votos válidos (branco e nulo à parte).', P),
          Paragraph(f'Cobertura: {n(res["secoes_nos_dois_turnos"])} seções com BU nos dois turnos ({n(res["so_no_1o_turno"])} só no 1º turno e '
                    f'{n(res["so_no_2o_turno"])} só no 2º ficam de fora). Conferência: a soma das seções bate voto a voto com o total oficial do '
                    f'sistema de resultados em {n(res["municipios_batem"])} de {n(res["municipios_conferidos"])} municípios.'
                    + (' Seções fora: ' + '; '.join(f'{x["municipio"]}/{x["uf"]}, zona {x["zona"]}, seção {x["secao"]} (BU só no {x["so_no"]} '
                                                    'nos dados abertos)' for x in res['secoes_fora']) + '.' if res['secoes_fora'] else '')
                    + (f' Os municípios que não batem ({", ".join(res["municipios_que_nao_batem"])}) são os dessas seções.'
                       if res['municipios_que_nao_batem'] and set(res['municipios_que_nao_batem']) <= {x['municipio'] for x in res['secoes_fora']} else
                       f' Não batem: {", ".join(res["municipios_que_nao_batem"])}.' if res['municipios_que_nao_batem'] else ''), NOTE),
          Paragraph('Como ler', H2),
          Paragraph('<b>Votos 2º x 1º</b>: quanto os votos do candidato cresceram do 1º para o 2º turno, em % dos votos que ele teve no 1º turno. '
                    '<b>p.p.</b>: diferença, em pontos percentuais, entre a fatia dos válidos no 2º turno e no 1º. '
                    '<b>Virada</b>: na seção, quem estava à frente no confronto Lula x Flávio no 1º turno perdeu no 2º turno. '
                    '<b>100%</b>: seção em que um candidato teve todos os votos válidos no 2º turno. '
                    'No 2º turno os eleitores dos demais candidatos escolhem entre os dois, e quem não votou no 1º turno pode votar no 2º: '
                    'crescimento dos dois e viradas em seções de margem apertada são o esperado. Nada aqui indica irregularidade por si só.', SM),
          Paragraph('Por região', H2)]
    t = [CAB] + [linha(r.regiao, r) for r in reg.itertuples()]
    st += [table(t, font=7, widths=LARG),
           Paragraph(f'No Brasil (sem exterior), Lula teve {n(br.t1_v13)} votos no 1º turno e {n(br.t2_v13)} no 2º ({sn(br.cresc_votos_13_pct)}%); '
                     f'Flávio, {n(br.t1_v22)} e {n(br.t2_v22)} ({sn(br.cresc_votos_22_pct)}%). Centro-Oeste aparece sem o DF, que tem linha própria.', SM),
           Paragraph('1º turno: votos por candidato', H2)]
    ct = cand[cand.uf == 'Total (com exterior)']
    t = [['Nº', 'Candidato', 'Votos', '% dos válidos']] + [[r.numero, r.candidato, n(r.votos), n(r.pct_validos, 2)] for r in ct.itertuples()]
    out = cand[(cand.uf != 'Total (com exterior)') & ~cand.numero.astype(str).isin(['13', '22'])]
    o_uf = out.groupby('uf').pct_validos.sum().sort_values(ascending=False)
    top = out[out.uf == o_uf.index[0]].iloc[0]
    u0 = uf[uf.uf == o_uf.index[0]].iloc[0]
    st += [table(t, font=7.5, widths=[1.2 * cm, 6 * cm, 3 * cm, 2.5 * cm]),
           Paragraph(f'Maior fatia de “outros” no 1º turno: {o_uf.index[0]} ({n(o_uf.iloc[0], 2)}%), puxada por {top.candidato} ({top.numero}), '
                     f'com {n(top.pct_validos, 2)}% no estado. Lá os dois finalistas ganham fatia no 2º turno (Lula {sn(u0.var_13_pp, 2)} p.p., '
                     f'Flávio {sn(u0.var_22_pp, 2)} p.p.).', SM),
           PageBreak(), Paragraph('Por estado', H2)]
    t = [CAB] + [linha(r.uf, r) for r in uf.itertuples()]
    st += [table(t, font=6.8, widths=LARG), PageBreak()]

    # viradas
    nv = len(vir)
    m = vir.margem_t1_pp.abs()
    faixas = pd.cut(m, [-.01, 5, 10, 20, 100], labels=['até 5 p.p.', '5 a 10 p.p.', '10 a 20 p.p.', 'mais de 20 p.p.'])
    terceiro = (~vir.lider_t1_geral.astype(str).isin(['13', '22'])).sum()
    st += [Paragraph('Seções com virada', H2),
           Paragraph(f'{n(nv)} seções viraram ({n(100 * nv / res["secoes_nos_dois_turnos"], 2)}% das seções): {n(res["viradas_para_13"])} de Flávio para Lula '
                     f'e {n(res["viradas_para_22"])} de Lula para Flávio. Em {n(res["secoes_lideradas_por_terceiro_no_1o_turno"])} seções do país o mais votado '
                     f'do 1º turno foi um terceiro candidato; {n(terceiro)} delas estão entre as viradas.', P)]
    t = [['Margem Lula x Flávio, 1º t.', 'Seções que viraram', '% das viradas']]
    for k, v in faixas.value_counts(sort=False).items():
        t.append([k, n(v), n(100 * v / nv, 1)])
    st += [table(t, font=7.5, widths=[6 * cm, 3 * cm, 3 * cm]),
           Paragraph('Margem = diferença entre a fatia de Lula e a de Flávio nos válidos do 1º turno, na própria seção.', SM),
           Paragraph('A virada contra as outras seções do mesmo local de votação', H2)]
    t = [['No local de votação', 'Seções que viraram', '% das viradas']]
    for k, v in vir.virada_no_local.value_counts().items():
        t.append([k, n(v), n(100 * v / nv, 1)])
    dif = vir.dif_var_13_pp_vs_local.dropna()
    st += [table(t, font=7.5, widths=[9 * cm, 3 * cm, 3 * cm]),
           Paragraph(f'Na mediana, a fatia de Lula numa seção que virou variou {sn(dif.median(), 2)} p.p. a mais que nas outras seções do mesmo local '
                     f'(metade das seções entre {sn(dif.quantile(.25), 2)} e {sn(dif.quantile(.75), 2)} p.p.). '
                     'A lista completa, com município, UF, zona, local e seção, está em VIRADA_1T_2T_2026.xlsx (aba secoes_com_virada).', P),
           Paragraph('As 25 viradas que mais se afastam das outras seções do local (seções com 50 ou mais válidos nos dois turnos)', H2)]
    top = vir[(vir.local_outras_secoes > 0) & (vir.t1_validos >= 50) & (vir.t2_validos >= 50)].dropna(subset=['dif_var_13_pp_vs_local'])
    top = top.loc[top.dif_var_13_pp_vs_local.abs().sort_values(ascending=False).index].head(25)
    t = [['UF', 'Município', 'Zona', 'Local', 'Seção', 'Sentido', 'Válidos\n1º / 2º', '% Lula\n1º → 2º', 'Outras seções:\n% Lula 1º→2º',
          'Outras\nviraram', 'Dif.\n(p.p.)']]
    for r in top.itertuples():
        t.append([r.uf, str(r.municipio)[:24], r.zone, r.voting_place, r.section, r.sentido, f'{n(r.t1_validos)} / {n(r.t2_validos)}',
                  f'{n(r.t1_p13, 1)} → {n(r.t2_p13, 1)}', f'{n(r.local_outras_t1_p13, 1)} → {n(r.local_outras_t2_p13, 1)}',
                  f'{n(r.local_outras_viradas_mesmo_sentido)} de {n(r.local_outras_secoes)}', sn(r.dif_var_13_pp_vs_local, 1)])
    st += [table(t, font=6.6, widths=[0.9 * cm, 3.6 * cm, 1 * cm, 1.1 * cm, 1.1 * cm, 2.8 * cm, 2 * cm, 2 * cm, 3.2 * cm, 1.8 * cm, 1.3 * cm]),
           Paragraph('Dif. = variação da fatia de Lula na seção menos a variação nas outras seções do mesmo local. Seções pequenas oscilam mais: '
                     'poucos votos mudam muito a porcentagem.', SM), PageBreak()]

    # 100%
    st += [Paragraph('Seções em que um candidato teve 100% dos válidos no 2º turno', H2)]
    if len(cem):
        cand = cem.cem_pct_para.value_counts()
        p1 = np.where(cem.cem_pct_para == 'LULA', cem.t1_p13, cem.t1_p22)
        cem = cem.assign(p_t1_mesmo=p1)
        tam = pd.cut(cem.t2_validos, [0, 10, 50, 100, 200, 10_000], labels=['1 a 10', '11 a 50', '51 a 100', '101 a 200', 'mais de 200'])
        st += [Paragraph(f'{n(len(cem))} seções: ' + ', '.join(f'{n(v)} para {k}' for k, v in cand.items()) +
                         f'. No 1º turno, o mesmo candidato teve, na mediana, {n(np.nanmedian(p1), 1)}% dos válidos nessas seções; '
                         f'{n(int((p1 >= 99.999).sum()))} delas já tinham dado 100% a ele no 1º turno.', P)]
        t = [['Válidos no 2º turno', 'Seções']] + [[k, n(v)] for k, v in tam.value_counts(sort=False).items()]
        lim = 200
        st += [table(t, font=7.5, widths=[5 * cm, 3 * cm]),
               Paragraph('Lista completa, das maiores para as menores' if len(cem) <= lim else f'Lista (as {lim} maiores; todas no XLSX)', H2)]
        t = [['UF', 'Município', 'Zona', 'Local', 'Seção', '100% para', 'Válidos\n2º t.', 'Branco+\nnulo 2º', 'No 1º t.:\nLula/Flávio/outros',
              '% do mesmo\ncand. no 1º', 'Outras do local:\n% no 2º']]
        for r in cem.sort_values('t2_validos', ascending=False).head(lim).itertuples():
            outras = r.local_outras_t2_p13 if r.cem_pct_para == 'LULA' else 100 - r.local_outras_t2_p13 if pd.notna(r.local_outras_t2_p13) else np.nan
            t.append([r.uf, str(r.municipio)[:24], r.zone, r.voting_place, r.section, r.cem_pct_para, n(r.t2_validos), n(r.t2_branco + r.t2_nulo),
                      f'{n(r.t1_v13)} / {n(r.t1_v22)} / {n(r.t1_outros)}', n(r.p_t1_mesmo, 1), n(outras, 1) if r.local_outras_secoes else 'seção única'])
        st += [table(t, font=6.6, widths=[0.9 * cm, 3.6 * cm, 1 * cm, 1.1 * cm, 1.1 * cm, 2.9 * cm, 1.5 * cm, 1.5 * cm, 3.4 * cm, 1.8 * cm, 2.6 * cm])]
    else:
        st += [Paragraph('Nenhuma seção.', P)]

    # municipios
    mm = mun[mun.t1_validos >= 1000]
    st += [PageBreak(), Paragraph('Municípios: maiores variações da fatia de cada candidato', H2),
           Paragraph(f'Entre os {n(len(mm))} municípios e cidades do exterior com pelo menos 1.000 votos válidos no 1º turno. Todos os '
                     f'{n((mun.uf != "ZZ").sum())} municípios do Brasil, as {n((mun.uf == "ZZ").sum())} cidades do exterior e todas as zonas estão '
                     'no XLSX (abas municipios e zonas).', SM)]
    for c, nome in (('13', 'Lula'), ('22', 'Flávio')):
        t = [['UF', 'Município', 'Válidos 1º t.', f'% {nome} 1º', f'% {nome} 2º', 'p.p.', f'Votos {nome}\n2º x 1º', 'Vencedor\n1º (confronto)', 'Vencedor\n2º']]
        for r in mm.sort_values(f'var_{c}_pp', ascending=False).head(15).itertuples():
            t.append([r.uf, str(r.municipio)[:30], n(r.t1_validos), n(getattr(r, f't1_p{c}'), 2), n(getattr(r, f't2_p{c}'), 2),
                      sn(getattr(r, f'var_{c}_pp'), 2), sn(getattr(r, f'cresc_votos_{c}_pct')) + '%',
                      {'13': 'Lula', '22': 'Flávio'}.get(str(r.lider_t1_confronto), 'empate'), {'13': 'Lula', '22': 'Flávio'}.get(str(r.vencedor_t2), 'empate')])
        st += [Paragraph(f'Maior ganho de fatia: {nome}', H2), table(t, font=7, widths=[1 * cm, 5 * cm, 2.2 * cm, 2 * cm, 2 * cm, 1.6 * cm, 2.4 * cm, 2.4 * cm, 2 * cm])]
    vm = mun[mun.unidade_virou]
    st += [Paragraph(f'{n(len(vm))} municípios viraram no confronto Lula x Flávio ({n((vm.vencedor_t2.astype(str) == "13").sum())} para Lula e '
                     f'{n((vm.vencedor_t2.astype(str) == "22").sum())} para Flávio); lista no XLSX (aba municipios, coluna unidade_virou).', P),
           Paragraph('Limites: compara a mesma seção nos dois turnos; seções agregadas ou criadas entre os turnos podem mudar de eleitorado. '
                     'O voto é secreto: a mudança de uma seção não diz quem mudou o voto. Exterior aparece em linha própria. '
                     'Como repetir: scripts/virada_1t_2t_2026.py (coleta e analise) e scripts/make_virada_report.py. '
                     'Arquivos: VIRADA_1T_2T_2026.xlsx, por_secao.csv, secoes_com_virada.csv, secoes_100pct_um_candidato.csv, por_zona.csv, '
                     'por_municipio.csv, por_uf.csv, por_regiao.csv, conferencia_municipios.csv.', SM)]

    def footer(cv, doc):
        cv.setFont('Helvetica', 7); cv.setFillColor(colors.grey)
        cv.drawString(1.5 * cm, 1 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        cv.drawRightString(28.2 * cm, 1 * cm, f'pág. {doc.page}')
    SimpleDocTemplate(str(D / 'VIRADA_1T_2T_2026.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title='Presidente 2026: 1º x 2º turno por seção', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    print('OK', D / 'VIRADA_1T_2T_2026.pdf')


if __name__ == '__main__':
    main()
