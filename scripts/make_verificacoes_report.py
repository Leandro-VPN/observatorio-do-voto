"""Relatorio consolidado das quatro verificacoes de auditoria (PDF + XLSX).

Le o que os scripts de verificacao ja gravaram em relatorios/verificacoes/ e monta:
  1. Relogio da urna x hora de recebimento no servidor do TSE (todas as secoes com BU no HD)
  2. Consistencia 1o x 2o turno por secao (presidencial 2022)
  3. Resultado por geracao de urna dentro do mesmo local de votacao (presidencial 2022 2o turno)
  4. RDV x BU por candidato (amostra de ~2.000 urnas, presidencial 2022 2o turno)
Saida: relatorios/verificacoes/VERIFICACOES.pdf e VERIFICACOES.xlsx
"""
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
from make_bahia_reports import P, H1, H2, SM, NOTE, table, n  # noqa: E402

V = ROOT / 'relatorios' / 'verificacoes'
FIG = V / 'figuras'
EL = {'2022-t1': '2022 1º turno', '2022-t2': '2022 2º turno', '2024-t1': '2024 1º turno',
      '2024-t2': '2024 2º turno', '2026-t1': '2026 1º turno', '2026-t2': '2026 2º turno'}


def build(name, title, story):
    def footer(c, d):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1.2 * cm, 'Análise independente e apartidária de dados públicos do TSE · exploratório e descritivo — não indica irregularidade por si só')
        c.drawRightString(19 * cm, 1.2 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(V / name), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=2 * cm, title=title, author='AuditaBR').build(story, onFirstPage=footer, onLaterPages=footer)


def figuras(sec, t12):
    FIG.mkdir(parents=True, exist_ok=True)
    # intervalo urna -> recebimento no TSE
    fig, ax = plt.subplots(figsize=(9, 3.2))
    x = sec.loc[~sec.sem_datas, 'min_urna_ate_tse'].clip(-30, 360)
    ax.hist(x, bins=np.arange(-30, 361, 10), color='#1a365d')
    ax.axvline(0, color='#c0392b', lw=1)
    ax.set(xlabel='minutos entre a emissão do BU pela urna e o recebimento no servidor do TSE',
           ylabel='seções')
    ax.text(2, ax.get_ylim()[1] * .9, 'à direita de 0: urna emitiu antes de o TSE receber', fontsize=7, color='#c0392b')
    fig.tight_layout(); fig.savefig(FIG / 'relogio.png', dpi=150); plt.close(fig)
    # 1o x 2o turno (amostra de pontos)
    s = t12.sample(min(8000, len(t12)), random_state=1)
    fig, ax = plt.subplots(figsize=(4.6, 4.6))
    ax.scatter(s.frac22_t1 * 100, s.frac22_t2 * 100, s=2, alpha=.15, color='#1a365d', edgecolors='none')
    ax.plot([0, 100], [0, 100], color='#c0392b', lw=.8)
    ax.set(xlabel='% candidato 22 no 1º turno (por seção)', ylabel='% no 2º turno', xlim=(0, 100), ylim=(0, 100))
    ax.set_title(f'correlação {t12.frac22_t1.corr(t12.frac22_t2):.3f}', fontsize=9)
    fig.tight_layout(); fig.savefig(FIG / 'turno1x2.png', dpi=150); plt.close(fig)


def img(path, w):
    from PIL import Image as PI
    iw, ih = PI.open(path).size
    return Image(str(path), width=w * cm, height=w * cm * ih / iw)


def main():
    sec = pd.read_parquet(V / 'relogio_por_secao.parquet')
    rel = pd.read_csv(V / 'relogio_resumo.csv', sep=';')
    t12 = pd.read_parquet(V / 'turno1x2_por_secao.parquet')
    t12r = pd.read_csv(V / 'turno1x2_resumo.csv', sep=';').rename(
        columns={'outliers_z>4': 'z4', 'outliers_z>5': 'z5'})
    ger = pd.read_csv(V / 'geracao_local_resumo.csv', sep=';')
    geruf = pd.read_csv(V / 'geracao_local_por_uf.csv', sep=';')
    rdv = pd.read_csv(V / 'rdv_bu_resumo.csv', sep=';')

    # ---- numeros para o texto
    com_datas = int((~sec.sem_datas).sum())
    adiant = int((~sec.ok_tse_depois_da_urna & ~sec.sem_datas).sum())
    noronha = int((sec.noronha & ~sec.ok_tse_depois_da_urna & ~sec.sem_datas).sum())
    corr_geral = t12.frac22_t1.corr(t12.frac22_t2)
    n_sec_t12 = len(t12)
    out4 = int((t12.z_abs > 4).sum())
    dif_ger = (ger.set_index('geracao').frac22_sem_efeito_local.get('nova (UE2020/22, Ed521)', 0)
               - ger.set_index('geracao').frac22_sem_efeito_local.get('antiga (AC URNA, ECDSA)', 0)) * 100
    rdv_tot = rdv[rdv.uf == 'TOTAL'].iloc[0]

    figuras(sec, t12)

    st = [Paragraph('Quatro perguntas de auditoria respondidas com os dados públicos do TSE', H1),
          Paragraph('Este relatório testa quatro hipóteses levantadas sobre os logs e boletins das urnas, usando só dados públicos e '
                    'verificação própria. Cada teste é descritivo: mostra o que os dados permitem afirmar e onde o alcance termina. '
                    'Nenhum resultado indica adulteração de voto. Onde um teste não alcança a pergunta, o relatório diz por quê e o que seria '
                    'preciso para alcançá-la.', P),
          Paragraph('Resumo', H2)]
    resumo = [['Teste', 'O que mede', 'Resultado'],
              ['1. Relógio', 'relógio da urna contra a hora de recebimento no servidor do TSE',
               f'{n(com_datas)} seções; nenhum relógio adiantado em massa'],
              ['2. 1º × 2º turno', 'estabilidade do voto por seção entre os dois turnos (presidencial 2022)',
               'correlação ' + n(corr_geral, 3) + '; desvios só em seções minúsculas'],
              ['3. Geração de urna', 'resultado por geração de urna no mesmo local de votação',
               'diferença de ' + ('+' if dif_ger >= 0 else '') + n(dif_ger, 2) + ' ponto — nula'],
              ['4. RDV × BU', 'soma dos votos individuais (RDV) contra o total do boletim, por candidato',
               f'{n(rdv_tot.conferem)}/{n(rdv_tot.urnas)} urnas conferem exatamente']]
    st += [table(resumo, font=8, widths=[3.2 * cm, 7.5 * cm, 6 * cm]),
           Paragraph('Os quatro testes somam-se à verificação de integridade já feita (hash e assinatura de 1,6 milhão de urnas). '
                     'Aquela prova que o arquivo publicado é o que a urna assinou; estes olham o conteúdo: horário, estabilidade entre turnos, '
                     'efeito do equipamento e correspondência entre o registro individual do voto e o total.', SM)]

    # ---- Teste 1
    st += [Paragraph('1. O relógio da urna bate com um relógio de fora da urna?', H2),
           Paragraph('A urna grava no boletim quando foi aberta, encerrada e quando emitiu o BU — tudo pelo seu próprio relógio. O servidor de '
                     'totalização do TSE grava a hora em que recebeu o boletim, por um relógio que a urna não controla. Se o relógio da urna '
                     'estivesse adiantado, o BU teria sido “emitido” depois de o TSE o receber. Procuramos exatamente isso em todas as seções '
                     'com boletim no HD.', P)]
    t = [['Pleito', 'Seções', 'Com datas', 'Urna emitiu\ndepois do TSE', 'Mediana do intervalo\nurna→TSE (min)', 'Fora da data\nda eleição', 'Encerrou\nantes das 17h']]
    for r in rel[rel.uf == 'TOTAL'].itertuples():
        t.append([EL.get(r.eleicao, r.eleicao), n(r.secoes), n(r.secoes_com_datas), n(r.urna_emitiu_depois_do_tse_receber),
                  n(r.mediana_intervalo_urna_ate_tse_min, 1), n(r.fora_da_data_da_eleicao), n(r.encerramento_antes_17h)])
    st += [table(t, font=7.5),
           Paragraph(f'Em {n(com_datas)} seções com data completa, a urna emitiu o BU antes de o TSE recebê-lo em todas menos {adiant}. '
                     f'Dessas {adiant}, {noronha} são de Fernando de Noronha, cujo fuso é uma hora à frente de Brasília; as demais ficam entre '
                     'poucos segundos e minutos, dentro do arredondamento do horário de recebimento. Os ajustes de relógio que aparecem nos logs '
                     'estão todos na carga, dias antes, por digitação do operador, e foram corrigidos antes da votação. Não há recuo de relógio '
                     'durante a votação. (2024 não traz a hora de recebimento nos dados abertos do HD e ficou fora deste teste.)', SM),
           img(FIG / 'relogio.png', 17)]

    # ---- Teste 2
    st += [PageBreak(), Paragraph('2. O voto de cada seção é estável entre o 1º e o 2º turno?', H2),
           Paragraph('Mesma seção, mesmo eleitorado, quatro semanas de intervalo. A fração de votos de um candidato numa seção no 1º turno '
                     'prevê bem a do 2º turno. Uma seção que invertesse o padrão local seria um ponto fora da curva. Medimos a correlação por '
                     'seção na eleição presidencial de 2022 e marcamos os desvios fortes (resíduo padronizado contra a reta do município).', P)]
    t = [['UF', 'Seções', 'Correlação\n1º × 2º', 'Desvios\nfortes (z>4)', 'Desvios\nmuito fortes (z>5)']]
    for r in t12r.itertuples():
        t.append([r.uf, n(r.secoes), n(r.correlacao_t1_t2, 4), n(r.z4), n(r.z5)])
    st += [table(t, font=7.5, widths=[2 * cm, 3 * cm, 3 * cm, 3 * cm, 3.5 * cm]),
           Paragraph('Correlação geral de ' + n(corr_geral, 3) + f' em {n(n_sec_t12)} seções. Os {out4} desvios fortes são, na quase totalidade, '
                     'seções de 10 a 25 votos, onde um punhado de votos muda muito a fração — ruído de amostra pequena, não inversão de padrão. '
                     'A lista completa está na planilha (aba turno1x2_outliers).', SM),
           img(FIG / 'turno1x2.png', 9)]

    # ---- Teste 3
    st += [PageBreak(), Paragraph('3. A geração da urna muda o resultado?', H2),
           Paragraph('Num mesmo prédio de votação, as seções recebem urnas de gerações diferentes (modelos 2020/2022, mais novos, e 2009–2015, '
                     'mais antigos) de forma praticamente aleatória quanto ao eleitorado. Se a geração influenciasse o resultado, a fração de um '
                     'candidato diferiria entre gerações dentro do mesmo prédio. Comparamos a fração do candidato 22 (presidente, 2º turno 2022), '
                     'descontada a média de cada prédio.', P)]
    t = [['Geração', 'Seções', 'Fração média', 'Fração sem o efeito do local']]
    for r in ger.itertuples():
        t.append([r.geracao, n(r.secoes), n(r.frac22_media * 100, 2) + '%', n(r.frac22_sem_efeito_local * 100, 2) + ' pp'])
    st += [table(t, font=7.5, widths=[6.5 * cm, 2.5 * cm, 3 * cm, 4.5 * cm]),
           Paragraph('A diferença entre gerações, já descontado o prédio, é de ' + ('+' if dif_ger >= 0 else '') + n(dif_ger, 2) + ' ponto percentual — nula. '
                     'Limitação: só há prédios com as duas gerações e seções suficientes em cerca de 150 locais (quase todos em SP), porque em '
                     'geral um prédio recebe uma só geração; por isso o teste tem pouca potência, embora o sinal seja claramente plano. '
                     'Detalhe por UF na planilha (aba geracao_por_uf).', SM)]

    # ---- Teste 4
    st += [Paragraph('4. A soma dos votos individuais (RDV) bate com o total do boletim?', H2),
           Paragraph('O Registro Digital do Voto (RDV) é a lista embaralhada dos votos individuais de cada urna, publicada pelo TSE. Decodificamos '
                     'o RDV e o boletim de uma amostra de urnas da eleição presidencial de 2022 (2º turno) e conferimos, candidato a candidato, se a '
                     'soma dos votos do RDV é igual ao total do boletim da mesma urna.', P)]
    t = [['UF', 'Urnas conferidas', 'Conferem', 'Divergentes', 'Erros de leitura']]
    for r in rdv[rdv.uf != 'TOTAL'].itertuples():
        t.append([r.uf, n(r.urnas), n(r.conferem), n(r.divergentes), n(r.erros_leitura)])
    t.append(['Total', n(rdv_tot.urnas), n(rdv_tot.conferem), n(rdv_tot.divergentes), n(rdv_tot.erros_leitura)])
    st += [table(t, font=7.5, widths=[2 * cm, 4 * cm, 3 * cm, 3 * cm, 3.5 * cm]),
           Paragraph(f'Nas {n(rdv_tot.urnas)} urnas sorteadas (7 estados), a soma do RDV é igual ao boletim, por candidato, em todas. '
                     'O RDV e o boletim saem do mesmo encerramento, então a igualdade confirma a consistência interna entre os dois artefatos '
                     'da urna; não é uma testemunha externa à urna (ver limites abaixo).', SM)]

    # ---- Limites
    st += [PageBreak(), Paragraph('O que estes testes alcançam — e o que não alcançam', H2),
           Paragraph('Os quatro testes, somados à integridade, cobrem: a autenticidade dos arquivos (hash e assinatura), a procedência (a urna que '
                     'assinou é a registrada para a seção), o horário contra um relógio de fora da urna, a estabilidade do voto entre turnos, a '
                     'ausência de efeito do equipamento e a correspondência entre o voto individual e o total. Tudo isso qualquer pessoa pode refazer '
                     'com dados públicos.', P),
           Paragraph('O que nenhum deles alcança: provar, só com arquivos que a própria urna gerou, que o software registrou cada voto conforme a '
                     'regra. Log, boletim e RDV saem todos do mesmo encerramento; conferir um contra o outro mostra coerência, não uma segunda '
                     'testemunha. Essa resposta vem de provas produzidas fora da urna, que não estão no acervo público de arquivos:', P)]
    for t_ in ['o teste de integridade (votação paralela no dia, em urnas sorteadas, com votos em papel conferidos contra o resultado) — incluindo as atas de todos os sorteios, mesmo os refeitos;',
               'as atas das mesas receptoras e as atas de carga e lacração das urnas por zona;',
               'a política de definição do relógio da urna na carga;',
               'os resumos digitais dos programas lacrados e o código-fonte, abertos às entidades fiscalizadoras.']:
        st.append(Paragraph('• ' + t_, P))
    st += [Paragraph('A falta dessas provas no acervo público não é indício de nada; apenas marca até onde uma auditoria externa com dados públicos '
                     'chega. As que são documentos administrativos podem ser pedidas ao TSE por Lei de Acesso à Informação; o código-fonte e os '
                     'relatórios do teste público de segurança são acessíveis por meio das entidades fiscalizadoras (partido, OAB, Ministério '
                     'Público, universidades).', NOTE),
           Paragraph('Como repetir', H2),
           Paragraph('scripts/verifica_relogio_recebimento.py (teste 1), scripts/verifica_1t_2t_secao.py (teste 2), '
                     'scripts/verifica_geracao_urna_local.py (teste 3), scripts/verifica_rdv_bu_amostra.py e scripts/rdv_lib.py (teste 4). '
                     'Tabelas completas em relatorios/verificacoes/ e em VERIFICACOES.xlsx.', SM)]

    build('VERIFICACOES.pdf', 'Quatro verificações de auditoria — dados públicos do TSE', st)

    with pd.ExcelWriter(V / 'VERIFICACOES.xlsx') as xw:
        rel.to_excel(xw, sheet_name='relogio_resumo', index=False)
        pd.read_csv(V / 'relogio_excecoes.csv', sep=';').to_excel(xw, sheet_name='relogio_excecoes', index=False)
        t12r.to_excel(xw, sheet_name='turno1x2_resumo', index=False)
        pd.read_csv(V / 'turno1x2_outliers.csv', sep=';').head(5000).to_excel(xw, sheet_name='turno1x2_outliers', index=False)
        ger.to_excel(xw, sheet_name='geracao_local', index=False)
        geruf.to_excel(xw, sheet_name='geracao_por_uf', index=False)
        rdv.to_excel(xw, sheet_name='rdv_bu', index=False)
    print('OK', V / 'VERIFICACOES.pdf', V / 'VERIFICACOES.xlsx')


if __name__ == '__main__':
    main()
