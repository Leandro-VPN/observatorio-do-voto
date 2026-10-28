"""Relatorio: cadencia de atendimento e liberacao manual por tipo (1o turno 2026), a partir de
relatorios/verificacoes/cadencia/ (scripts/verifica_cadencia.py). Saida: CADENCIA_E_LIBERACAO_MANUAL.pdf/.xlsx
"""
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('UF', 'BA')
from make_bahia_reports import P, H1, H2, SM, NOTE, table, n  # noqa: E402

D = ROOT / 'relatorios' / 'verificacoes' / 'cadencia'
GR = [('g1', 'G1 — 664 seções acima do limiar'), ('g2', 'G2 — com comportamento, abaixo do limiar'),
      ('g3', 'G3 — vizinhas comuns do G1'), ('g4', 'G4 — amostra aleatória (5 mil)'), ('local_alta', 'Locais de prioridade alta')]


def main():
    S = pd.read_parquet(D / 'secoes_cadencia.parquet')
    S = S[S.votos_log.notna()].copy()
    S['man'] = S.n_manual_identificado + S.n_manual_nao_associado + S.n_manual_outro
    P_ = pd.read_csv(D / 'pares_mesmo_predio.csv', sep=';', encoding='utf-8-sig', decimal=',')
    lim = float(S.limiar_rapido_s.iloc[0])

    rows = []
    for g, lab in GR:
        x = S[S[g]]
        t = x[x.tarde_votos >= 20]
        m = x[x.man >= 10]
        rows.append({'grupo': lab, 'secoes': len(x), 'votos': int(x.votos_log.sum()),
                     'atend_dia': x.dia_atend_med.median(), 'atend_tarde': x.tarde_atend_med.median(),
                     'cv_tarde': x.tarde_interv_cv.median(), 'ocioso_tarde': x.tarde_ocioso_med.median(),
                     'pct_rapido_tarde': 100 * x.tarde_frac_rapido.median(),
                     'pct_seq5': 100 * (t.tarde_maior_sequencia_rapida >= 5).mean(), 'pct_cv025': 100 * (t.tarde_interv_cv <= .25).mean(),
                     'manuais_100': 100 * x.man.sum() / x.votos_log.sum(),
                     'pct_nao_assoc': 100 * x.n_manual_nao_associado.sum() / x.man.sum(),
                     'pct_secoes_nao_assoc80': 100 * (m.frac_manual_nao_associado >= .8).mean(),
                     'atend_bio': x.atend_med_biometrica.median(), 'atend_man_id': x.atend_med_manual_identificado.median(),
                     'atend_man_na': x.atend_med_manual_nao_associado.median()})
    R = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(8.5, 3.3))
    for g, lab, cor in (('g1', 'G1 (664)', '#c0392b'), ('g3', 'G3 vizinhas', '#1a365d'), ('g4', 'G4 amostra', '#7f8c8d')):
        v = S[S[g] & (S.tarde_votos >= 20)].tarde_interv_cv.dropna().clip(0, 1.6)
        ax.hist(v, bins=np.arange(0, 1.61, .04), histtype='step', density=True, lw=1.6, color=cor, label=lab)
    ax.set(xlabel='coeficiente de variação dos intervalos entre votos após 16h (menor = ritmo mais regular)', ylabel='densidade')
    ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(D / 'cv_tarde.png', dpi=150); plt.close(fig)

    st = [Paragraph('Ritmo de atendimento e liberação manual: o que os logs mostram', H1),
          Paragraph('Hipótese testada: nas seções que votaram diferente das vizinhas do mesmo prédio, um ritmo de votação “mecânico” '
                    'depois das 16h (votos muito rápidos, a intervalos quase constantes) separaria uma fila real de atuação anormal na mesa. '
                    'E a liberação manual por digital que a urna não associa a um mesário (achado A-002) seria mais frequente nessas seções. '
                    f'Medimos {n(int(S.votos_log.sum()))} atendimentos em {n(len(S))} seções do 1º turno de 2026, lidos dos logs das urnas.', P),
          Paragraph('Como se mede', H2),
          Paragraph('Um atendimento vai da digitação do título pelo mesário até “O voto do eleitor foi computado”. Para cada um: tempo total, '
                    'tempo na cabine (da habilitação ao voto), intervalo até o voto anterior e tempo ocioso (do voto anterior à digitação do '
                    f'próximo título). “Atendimento muito curto” = até {n(lim)} s, o percentil 5 da amostra aleatória; é um limiar tirado dos '
                    'dados, não suposto. Períodos: antes das 16h e de 16h ao encerramento. O log não identifica eleitor; nenhum dado pessoal foi guardado.', SM),
          Paragraph('1. Os grupos lado a lado (medianas por seção)', H2)]
    t = [['Grupo', 'Seções', 'Atend.\nantes 16h (s)', 'Atend.\napós 16h (s)', 'CV interv.\napós 16h', 'Ocioso\napós 16h (s)',
          '% atend.\nmuito curtos', '% seções c/\n5+ curtos seguidos', '% seções\nCV ≤ 0,25']]
    for r in R.itertuples():
        t.append([r.grupo, n(r.secoes), n(r.atend_dia), n(r.atend_tarde), n(r.cv_tarde, 2), n(r.ocioso_tarde), n(r.pct_rapido_tarde, 1),
                  n(r.pct_seq5, 2), n(r.pct_cv025, 2)])
    st += [table(t, font=6.6, widths=[4.6 * cm, 1.3 * cm, 1.6 * cm, 1.6 * cm, 1.5 * cm, 1.5 * cm, 1.6 * cm, 2 * cm, 1.5 * cm]),
           Paragraph('As colunas de cauda (“5+ curtos seguidos”, “CV ≤ 0,25”) contam seções com pelo menos 20 votos após 16h.', SM),
           Image(str(D / 'cv_tarde.png'), width=17 * cm, height=17 * cm * 3.3 / 8.5)]
    difs = {c: P_[f'dif_{c}'].dropna() for c in ('tarde_interv_cv', 'tarde_frac_rapido', 'tarde_atend_med', 'dia_atend_med')}
    st += [Paragraph('2. Cada seção do G1 contra as vizinhas do próprio prédio', H2)]
    t = [['Medida', 'Mediana da diferença\n(G1 − vizinhas)', 'G1 acima das vizinhas', 'Pares']]
    for c, lab, d in (('tarde_interv_cv', 'CV dos intervalos após 16h', 2), ('tarde_frac_rapido', 'fração de atendimentos muito curtos após 16h', 3),
                      ('tarde_atend_med', 'tempo de atendimento após 16h (s)', 1), ('dia_atend_med', 'tempo de atendimento antes das 16h (s)', 1)):
        x = difs[c]
        t.append([lab, n(x.median(), d), n(100 * (x > 0).mean(), 0) + '%', n(len(x))])
    st += [table(t, font=7.5, widths=[7 * cm, 3.6 * cm, 3.4 * cm, 2 * cm]),
           Paragraph('<b>Resultado:</b> depois das 16h o ritmo das 664 seções não difere do das vizinhas do mesmo prédio. A regularidade dos intervalos '
                     'fica acima das vizinhas em metade dos pares, como no cara ou coroa, e a fração de atendimentos muito curtos é a mesma. '
                     'Sequências de 5 ou mais atendimentos muito curtos seguidos não aparecem no G1 (0 seções) e são raríssimas em todos os grupos. '
                     'Onde o G1 difere é antes das 16h, e no sentido oposto ao da hipótese: atende mais devagar (mediana de +8 s; mais lento que as vizinhas em 81% dos pares), '
                     'o que combina com mais liberações manuais e mais eleitores com dificuldade de biometria.', P),
           Paragraph('Por que o ritmo após 16h é mais regular em todos os grupos do que na amostra: com fila, o próximo eleitor já está pronto e o '
                     'intervalo entre votos passa a ser só o tempo de atendimento. Regularidade alta à tarde é a marca de fila, e aparece igual nas '
                     'vizinhas do mesmo prédio, que não foram sinalizadas.', SM), PageBreak()]

    st += [Paragraph('3. Liberação manual: mesário identificado ou digital não associada (A-002)', H2)]
    t = [['Grupo', 'Manuais por\n100 votos', '% das manuais por digital\nnão associada', '% das seções (10+ manuais)\ncom ≥ 80% não associadas',
          'Atend. biometria\n(s)', 'Atend. manual\nidentificado (s)', 'Atend. manual\nnão assoc. (s)']]
    for r in R.itertuples():
        t.append([r.grupo, n(r.manuais_100, 1), n(r.pct_nao_assoc, 1), n(r.pct_secoes_nao_assoc80, 1), n(r.atend_bio), n(r.atend_man_id), n(r.atend_man_na)])
    st += [table(t, font=6.8, widths=[4.6 * cm, 1.8 * cm, 2.8 * cm, 3 * cm, 1.8 * cm, 2 * cm, 2 * cm]),
           Paragraph('<b>Resultado:</b> cerca de 40% das liberações manuais saem por digital não associada em todos os grupos, inclusive na amostra '
                     'aleatória, e cerca de um quarto das seções tem quase todas as liberações assim. O G1 libera mais manualmente (8,6 por 100 votos '
                     'contra 6,5 nas vizinhas), por construção, já que foi selecionado em parte por isso. Mas a proporção não associada é a mesma. '
                     'Atendimento manual identificado e não associado levam o mesmo tempo (cerca de 2,5 min).', P),
           Paragraph('O mecanismo, visto no próprio log: na abertura, a urna registra a digital de cada mesário. Se a digital de quem libera não foi '
                     'registrada, a primeira liberação grava essa digital “em novo arquivo” e as seguintes saem como “não é possível associar a '
                     'habilitação a um mesário”. Uma seção com todas as liberações não associadas é, tipicamente, uma mesa em que quem liberou não '
                     'registrou a digital pela manhã. É uma lacuna de rastreabilidade, não um voto indevido. E é evitável no dia: basta acompanhar o registro '
                     'de mesários na abertura, passo que entrou no kit de campo.', SM),
           Paragraph('4. O que isso significa para o score de prioridade', H2)]
    for t_ in ['O indicador de “ritmo mecânico” não separa as 664 seções das vizinhas nem da amostra. Incluí-lo no score de prioridade alta só '
               'acrescentaria ruído. A recomendação é não incluir, e publicar o teste como resultado negativo.',
               'A proporção de liberações por digital não associada pode ir para o painel como dado descritivo do local, sempre ao lado da '
               'referência geral (39% na amostra aleatória). Sem a referência, um número como 60% parece alarmante quando está dentro do comum.',
               'O que esse indicador sustenta é uma ação preventiva, não uma suspeita: conferir na abertura que todos os mesários registraram a digital. '
               'Com isso, toda liberação manual passa a ter mesário identificado no log.']:
        st.append(Paragraph('• ' + t_, P))
    st += [Paragraph('Limites: só o 1º turno de 2026 e as 11 UFs com log no HD. O horário é o do relógio da urna, conferido contra o '
                     'servidor do TSE em outro teste. Tempos de atendimento variam com o número de cargos; por isso a comparação principal é '
                     'dentro do mesmo prédio e do mesmo pleito. Nada aqui é indício de irregularidade: são medidas descritivas de operação.', NOTE),
           Paragraph('Como repetir: scripts/cadencia_lib.py e scripts/verifica_cadencia.py; tabelas em relatorios/verificacoes/cadencia/.', SM)]

    def footer(c, d):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1.2 * cm, 'Análise independente e apartidária de dados públicos do TSE · descritivo — não indica irregularidade por si só')
        c.drawRightString(19 * cm, 1.2 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(D / 'CADENCIA_E_LIBERACAO_MANUAL.pdf'), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=2 * cm, title='Ritmo de atendimento e liberação manual', author='AuditaBR').build(st, onFirstPage=footer, onLaterPages=footer)
    la = pd.read_csv(D / 'locais_alta_habilitacao_manual.csv', sep=';', encoding='utf-8-sig', decimal=',')
    with pd.ExcelWriter(D / 'CADENCIA_E_LIBERACAO_MANUAL.xlsx') as xw:
        R.round(3).to_excel(xw, sheet_name='grupos', index=False)
        P_.to_excel(xw, sheet_name='pares_mesmo_predio', index=False)
        la.to_excel(xw, sheet_name='locais_alta_manual', index=False)
    print('OK', D / 'CADENCIA_E_LIBERACAO_MANUAL.pdf')


if __name__ == '__main__':
    main()
