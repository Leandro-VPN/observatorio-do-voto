"""Kit de campo por local de votacao para os locais de prioridade alta (PDF de bolso + CSV).

Uma pagina por local: por que o local esta na lista, as secoes a checar com o historico de cada uma
(ultimo voto e encerramento, liberacoes manuais por tipo) e os passos de observacao no dia.
Prioridade e ordem de observacao presencial, nao indicio de irregularidade.

Fontes: relatorios/fiscalizacao/mapa_2026_T2 (locais e checklist por secao),
        relatorios/fiscalizacao/secoes_indicadores_<pleito>.parquet (encerramento por eleicao),
        relatorios/verificacoes/cadencia/secoes_cadencia.parquet (liberacoes manuais por tipo, 2026 T1).
Saida: relatorios/fiscalizacao/kit_campo/KIT_CAMPO_<UF>.pdf, KIT_CAMPO_<UF>.csv, KIT_CAMPO_GERAL.csv
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('UF', 'BA')
from make_bahia_reports import P, H2, SM, NOTE, table, n  # noqa: E402

FIS = ROOT / 'relatorios' / 'fiscalizacao'
OUT = FIS / 'kit_campo'
CSV = dict(sep=';', encoding='utf-8-sig', low_memory=False)
KEY = ['cod_municipio', 'zona', 'secao']
PASSOS = [
    'Na abertura (antes das 8h), acompanhar o registro de mesários e confirmar que cada mesário teve a digital registrada na urna. '
    'Sem esse registro, toda liberação manual que ele fizer aparece no log como “digital não associada a mesário”.',
    'Chegar até 16h30 e apresentar a credencial de fiscal ao presidente de cada mesa.',
    'Às 17h00 em ponto, contar as pessoas na fila de cada seção listada e anotar. Pedir ao presidente da mesa que registre em ata o número de eleitores na fila às 17h.',
    'Em cada habilitação sem biometria (liberação manual), anotar o horário e pedir que a ocorrência conste em ata com a identificação do mesário que liberou.',
    'Anotar o horário do último voto e do encerramento de cada seção.',
    'Fotografar o boletim de urna impresso e afixado de cada seção listada.',
    'Registrar troca de urna, urna de contingência ou interrupção, com horário.',
]


def build(path, title, story):
    def footer(c, d):
        c.setFont('Helvetica', 7); c.setFillColor(colors.grey)
        c.drawString(1.5 * cm, 1.0 * cm, 'Prioridade = ordem de observação presencial, não indício de irregularidade. Sinalização não é acusação.')
        c.drawRightString(19.5 * cm, 1.0 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm,
                      bottomMargin=1.6 * cm, title=title, author='AuditaBR').build(story, onFirstPage=footer, onLaterPages=footer)


def hhmm(min_apos_17):
    if pd.isna(min_apos_17):
        return '—'
    t = int(round(17 * 60 + float(min_apos_17)))
    return f'{t // 60:02d}h{t % 60:02d}'


def carrega():
    loc = pd.read_csv(FIS / 'mapa_2026_T2' / 'locais_todos.csv', **CSV)
    loc = loc[loc.prioridade_observacao == 'alta'].copy()
    chk = pd.read_csv(FIS / 'mapa_2026_T2' / 'secoes_checklist_todas.csv', **CSV)
    chk = chk[chk.prioridade_local == 'alta'].copy()
    for c in KEY:
        chk[c] = chk[c].astype(int)
    # encerramento por eleicao presidencial (minutos apos 17h, relogio da urna)
    for eid, lab in (('P2022', '2022 T1'), ('P2022b', '2022 T2'), ('P2026', '2026 T1')):
        ind = pd.read_parquet(FIS / f'secoes_indicadores_{eid}.parquet', columns=['municipality', 'zone', 'section', 'close_min', 'manual_share'])
        ind = ind.rename(columns={'municipality': 'cod_municipio', 'zone': 'zona', 'section': 'secao',
                                  'close_min': f'enc_{eid}', 'manual_share': f'pct_manual_{eid}'})
        for c in KEY:
            ind[c] = ind[c].astype(int)
        chk = chk.merge(ind.drop_duplicates(KEY), on=KEY, how='left')
    cad = ROOT / 'relatorios' / 'verificacoes' / 'cadencia' / 'secoes_cadencia.parquet'
    ref = None
    if cad.exists():
        c = pd.read_parquet(cad, columns=['municipality', 'zone', 'section', 'n_manual_identificado', 'n_manual_nao_associado',
                                          'n_manual_outro', 'n_manual_nao_associado_tarde', 'votos_log', 'g4'])
        a = c[c.g4]  # referencia: amostra aleatoria do pleito
        ref = 100 * a.n_manual_nao_associado.sum() / (a.n_manual_identificado + a.n_manual_nao_associado + a.n_manual_outro).sum()
        c = c.drop(columns='g4').rename(columns={'municipality': 'cod_municipio', 'zone': 'zona', 'section': 'secao'})
        chk = chk.merge(c.drop_duplicates(KEY), on=KEY, how='left')
    else:
        for col in ('n_manual_identificado', 'n_manual_nao_associado', 'n_manual_outro', 'n_manual_nao_associado_tarde', 'votos_log'):
            chk[col] = np.nan
    chk['enc_mais_tarde'] = chk[['enc_P2022', 'enc_P2022b', 'enc_P2026']].max(axis=1)
    chk['manuais_2026T1'] = chk[['n_manual_identificado', 'n_manual_nao_associado', 'n_manual_outro']].sum(axis=1, min_count=1)
    return loc, chk, ref


def pagina(L, S, ref):
    st = [Paragraph(f'<b>{L.local}</b>', H2),
          Paragraph(f'{L.municipio}/{L.uf} · zona {int(L.zona)} · local {int(L.cod_local)} · prioridade alta ({n(L.pontos)} pontos) · '
                    f'{n(L.secoes_no_local)} seções no prédio, {n(len(S))} a checar', P)]
    man = S.manuais_2026T1.sum()
    na = S.n_manual_nao_associado.sum()
    por = [f'{n(L.recorrentes_2plus)} seções com fila tardia ou liberação manual em 2 ou mais eleições',
           f'{n(L.votos_tardios_total)} votos após 17h e {n(L.manuais_apos_17h_total)} liberações manuais após 17h, somando as eleições analisadas']
    if pd.notna(man) and man > 0:
        por.append(f'1º turno de 2026: {n(man)} liberações manuais nas seções listadas; {n(na)} por digital que a urna não associa a mesário '
                   f'cadastrado ({n(100 * na / man, 0)}%, contra {n(ref, 0)}% numa amostra aleatória de 5 mil seções) e '
                   f'{n(S.n_manual_identificado.sum())} por mesário identificado')
    if str(L.sinal_resultado) not in ('nenhum', 'nan'):
        por.append(f'resultado: {L.sinal_resultado}')
    st.append(Paragraph('<b>Por que este local:</b> ' + '; '.join(por) + '.', SM))
    t = [['Seção', 'Último voto\n2026 T1', 'Encerramento\nmais tarde', 'Manuais 2026 T1\n(não assoc.)', 'Fila às 17h\n(nº)', 'Encerrou às']]
    for r in S.sort_values('secao').itertuples():
        mt = '—' if pd.isna(r.manuais_2026T1) else f'{n(r.manuais_2026T1)} ({n(r.n_manual_nao_associado)})'
        t.append([str(int(r.secao)), str(r.ultimo_voto_26) if pd.notna(r.ultimo_voto_26) else '—', hhmm(r.enc_mais_tarde), mt, '', ''])
    st.append(table(t, font=7.5, widths=[1.6 * cm, 2.4 * cm, 2.6 * cm, 3.4 * cm, 3 * cm, 3 * cm]))
    obs = '; '.join(sorted({o.strip() for x in S.o_que_observar.dropna() for o in str(x).split(';')}))[:600]
    st.append(Paragraph('<b>Observar:</b> ' + obs, SM))
    st.append(Paragraph('<b>No dia</b>', P))
    for p_ in PASSOS:
        st.append(Paragraph('[&nbsp;&nbsp;] ' + p_, SM))
    st.append(Paragraph('Anotações: ' + '_' * 95, SM))
    return [KeepTogether(st), PageBreak()]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    loc, chk, ref = carrega()
    cols = ['uf', 'cod_municipio', 'municipio', 'zona', 'cod_local', 'local', 'pontos_local', 'secao', 'comportamento_2026_T1',
            'ultimo_voto_26', 'enc_P2022', 'enc_P2022b', 'enc_P2026', 'manuais_2026T1', 'n_manual_identificado', 'n_manual_nao_associado',
            'n_manual_nao_associado_tarde', 'n_eleicoes_comportamento', 'motivos', 'o_que_observar']
    geral = chk[cols].copy()
    for c in ('enc_P2022', 'enc_P2022b', 'enc_P2026'):
        geral[c.replace('enc_', 'encerramento_')] = geral[c].map(hhmm)
    geral = geral.drop(columns=['enc_P2022', 'enc_P2022b', 'enc_P2026'])
    for c in ('fila_as_17h (nº)', 'manuais_observadas (nº)', 'mesario_identificado_em_ata (sim/não)', 'hora_ultimo_voto',
              'hora_encerramento', 'troca_de_urna (sim/não)', 'foto_bu (sim/não)', 'observacoes'):
        geral[c] = ''
    geral.to_csv(OUT / 'KIT_CAMPO_GERAL.csv', index=False, **{k: v for k, v in CSV.items() if k != 'low_memory'})
    aviso = Paragraph('Números de seção são os de 2026: confira a lista de seções do local antes da eleição. Os números históricos vêm dos '
                      'logs e boletins publicados pelo TSE. Prioridade é ordem de observação, não indício de irregularidade.', NOTE)
    mapa = []
    for uf, Lu in loc.groupby('uf'):
        st = [Paragraph(f'Kit de campo — {uf}: {n(len(Lu))} locais de prioridade alta', H2),
              Paragraph('Uma página por prédio, em ordem de pontos.', P), aviso, PageBreak()]
        (OUT / 'locais' / uf).mkdir(parents=True, exist_ok=True)
        for L in Lu.sort_values('pontos', ascending=False).itertuples():
            S = chk[(chk.uf == uf) & (chk.cod_municipio == L.cod_municipio) & (chk.zona == L.zona) & (chk.cod_local == L.cod_local)]
            st += pagina(L, S, ref)
            arq = f'{uf}/{int(L.cod_municipio)}-{int(L.zona)}-{int(L.cod_local)}.pdf'
            # flowables nao podem ser diagramados duas vezes: pagina nova para o PDF do local
            build(OUT / 'locais' / arq, f'Kit de campo · {L.local}', pagina(L, S, ref)[:-1] + [Paragraph(aviso.text, NOTE)])
            mapa.append({'uf': uf, 'municipality': int(L.cod_municipio), 'zone': int(L.zona), 'voting_place': int(L.cod_local), 'arquivo': arq})
        build(OUT / f'KIT_CAMPO_{uf}.pdf', f'Kit de campo {uf}', st)
        geral[geral.uf == uf].to_csv(OUT / f'KIT_CAMPO_{uf}.csv', index=False, **{k: v for k, v in CSV.items() if k != 'low_memory'})
        print(uf, len(Lu), 'locais', flush=True)
    pd.DataFrame(mapa).to_csv(OUT / 'kit_locais.csv', index=False, sep=';', encoding='utf-8-sig')
    print('OK', OUT, '| secoes', len(geral), '| locais', len(loc), '| referencia nao associada', round(ref, 1) if ref else None)


if __name__ == '__main__':
    main()
