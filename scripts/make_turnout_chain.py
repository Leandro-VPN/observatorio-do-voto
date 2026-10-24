"""Turnout / blank+null / high-turnout-flag chain across all eight elections 2012-2026 (municipal and general), same sections.
Uses only fields every BU has (2012 and 2014 included): attendance, valid vs total votes. No logs, no manual field, no closing time."""
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer
from PIL import Image as PI

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M

OUT = Path('relatorios/prefeito')
FIG = OUT / 'figuras'
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
KEY = ['uf', 'municipality', 'zone', 'section']
# id, label, year, office, type
EL = [('M2012', 'Prefeito 2012', 2012, 'PREFEITO', 'municipal'), ('P2014', 'Presidente 2014', 2014, 'PRESIDENTE', 'geral'), ('G2014', 'Governador 2014', 2014, 'GOVERNADOR', 'geral'),
      ('M2016', 'Prefeito 2016', 2016, 'PREFEITO', 'municipal'), ('P2018', 'Presidente 2018', 2018, 'PRESIDENTE', 'geral'), ('M2020', 'Prefeito 2020', 2020, 'PREFEITO', 'municipal'),
      ('P2022', 'Presidente 2022', 2022, 'PRESIDENTE', 'geral'), ('M2024', 'Prefeito 2024', 2024, 'PREFEITO', 'municipal'), ('P2026', 'Presidente 2026', 2026, 'PRESIDENTE', 'geral')]
rng = np.random.default_rng(20261016)
REPS = 1000


def n(x, d=0):
    return M.n(x, d)


def adir(office, uf, year):
    if office == 'PRESIDENTE' and year in (2022, 2026):
        return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / f'{year}-t1' / 'analysis'
    return Path('research/analysis') / office / uf / f'{year}-t1'


def load(office, year):
    fr = []
    for uf in ORDER:
        f = adir(office, uf, year) / 'sections.parquet'
        if not f.exists():
            continue
        d = pd.read_parquet(f, columns=['municipality', 'zone', 'section', 'voting_place', 'eligible', 'attendance', 'valid_votes', 'total_votes', 'raw_high_turnout'])
        d['uf'] = uf
        fr.append(d)
    d = pd.concat(fr, ignore_index=True)
    d['voting_place'] = d.voting_place.astype(str)
    d['turnout'] = 100 * d.attendance / d.eligible.where(d.eligible > 0)
    d['A'] = d.raw_high_turnout
    return d


def sp(x, y):
    ok = x.notna() & y.notna()
    return stats.spearmanr(x[ok], y[ok])[0] if ok.sum() > 30 else np.nan


def main():
    D = {e[0]: load(e[3], e[2]) for e in EL}
    rows = []
    for eid, lab, year, office, typ in EL:
        d = D[eid]
        rows.append(dict(eid=eid, lab=lab, typ=typ, sections=len(d), eligible=int(d.eligible.sum()), turnout=100 * d.attendance.sum() / d.eligible.sum(),
                         blank_null=100 * (1 - d.valid_votes.sum() / d.total_votes.sum()), A=int((d.A == True).sum()), A_pct=100 * (d.A == True).mean(),
                         turnout_p10=d.turnout.quantile(.1), turnout_p90=d.turnout.quantile(.9)))
    R = pd.DataFrame(rows)
    steps = [('M2012', 'P2014'), ('P2014', 'M2016'), ('M2016', 'P2018'), ('P2018', 'M2020'), ('M2020', 'P2022'), ('P2022', 'M2024'), ('M2024', 'P2026'),
             ('M2012', 'M2016'), ('P2014', 'P2018'), ('M2016', 'M2020'), ('P2018', 'P2022'), ('M2020', 'M2024'), ('P2022', 'P2026'), ('G2014', 'M2016'), ('P2014', 'G2014')]
    lab = {e[0]: e[1] for e in EL}
    P = []
    for a, b in steps:
        m = D[a].merge(D[b], on=KEY, suffixes=('_1', '_2'))
        m = m[(m.voting_place_1 == m.voting_place_2) & (m.eligible_2 / m.eligible_1).between(.6, 1.67)]
        m['place'] = m.uf + '|' + m.municipality.astype(str) + '|' + m.zone.astype(str) + '|' + m.voting_place_1
        w = m[m.groupby('place').turnout_1.transform('size') >= 2]
        f1, f2 = (m.A_1 == True).values, (m.A_2 == True).values
        g = pd.factorize(m.uf + '|' + m.municipality.astype(str))[0].astype(float)
        o0 = np.argsort(g, kind='stable')
        f1_0 = f1[o0]
        obs = int((f1 & f2).sum())
        null = np.array([(f1_0 & f2[np.argsort(g + rng.random(len(g)), kind='stable')]).sum() for _ in range(REPS)])
        P.append(dict(a=lab[a], b=lab[b], gap=int(b[1:]) - int(a[1:]), kind=('município' if a[0] == 'M' else 'geral') + '→' + ('município' if b[0] == 'M' else 'geral'),
                      n=len(m), rho_size=sp(m.eligible_1, m.eligible_2), rho_turnout=sp(m.turnout_1, m.turnout_2),
                      rho_turnout_place=sp(w.turnout_1 - w.groupby('place').turnout_1.transform('mean'), w.turnout_2 - w.groupby('place').turnout_2.transform('mean')),
                      A1=int(f1.sum()), A2=int(f2.sum()), A_obs=obs, A_exp=null.mean(), A_ratio=obs / null.mean() if null.mean() else np.nan, A_p=(1 + (null >= obs).sum()) / (REPS + 1)))
        print('step', lab[a], lab[b], flush=True)
    PC = pd.DataFrame(P)
    R.round(3).to_csv(OUT / 'cadeia_comparecimento_niveis.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    PC.round(4).to_csv(OUT / 'cadeia_comparecimento_persistencia.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    # figure
    f, ax = plt.subplots(1, 2, figsize=(12, 3.6))
    x = np.arange(len(R))
    ax[0].bar(x, R.turnout, color=['#e6550d' if t == 'municipal' else '#3182bd' for t in R.typ])
    ax[0].set_ylim(70, 85)
    ax[0].set_title('Comparecimento (%), 10 estados', fontsize=9)
    ax[1].bar(x, R.blank_null, color=['#e6550d' if t == 'municipal' else '#3182bd' for t in R.typ])
    ax[1].set_title('Brancos + nulos (% dos votos do cargo)', fontsize=9)
    for a in ax:
        a.set_xticks(x)
        a.set_xticklabels([l.replace(' ', '\n') for l in R.lab], fontsize=6.5)
    f.tight_layout()
    f.savefig(FIG / 'cadeia_niveis.png', dpi=150)
    plt.close(f)
    pr, hd, st = M.P, M.H2, []
    st += [Paragraph('Prefeito × presidente/governador, 2012 a 2026: o que é possível comparar em todos os anos', M.H1),
           Paragraph('Os boletins de 2012 e 2014 não têm horário de encerramento, não têm a contagem de habilitação manual e não há logs de urna (nem 2012, 2014, 2016, 2018 e 2020). '
                     'Por isso as comparações de votos tardios e de habilitação manual cobrem só 2018+ (manual e horário de encerramento) e 2022, 2024 e 2026 (logs). '
                     'O que existe em todos os anos é comparecimento, brancos e nulos e resultado por seção — é o que comparamos aqui, incluindo 2014 (presidente e governador) e 2012 e 2016 (prefeito).', pr),
           Paragraph('1. Níveis', hd)]
    t = [['Eleição', 'Tipo', 'Seções', 'Aptos', 'Comparecimento %', 'P10 seções %', 'P90 seções %', 'Brancos+nulos %', 'Sinal A (comparecimento alto)']]
    for r in R.itertuples():
        t.append([r.lab, r.typ, n(r.sections), n(r.eligible), n(r.turnout, 1), n(r.turnout_p10, 1), n(r.turnout_p90, 1), n(r.blank_null, 1), n(r.A)])
    st += [M.table(t, font=7), Image(str(FIG / 'cadeia_niveis.png'), width=24 * cm, height=24 * cm * 3.6 / 12),
           Paragraph('2. As mesmas seções repetem o comparecimento e o sinal A, passo a passo e entre tipos de eleição', hd)]
    t = [['De', 'Para', 'Anos', 'Tipo', 'Seções pareadas', 'ρ aptos', 'ρ comparecimento', '… desvio do local', 'A em y1', 'A em y2', 'A nos dois', 'Esperado ao acaso', 'Razão', 'p']]
    for r in PC.itertuples():
        t.append([r.a, r.b, n(r.gap), r.kind, n(r.n), n(r.rho_size, 2), n(r.rho_turnout, 2), n(r.rho_turnout_place, 2), n(r.A1), n(r.A2), n(r.A_obs), n(r.A_exp, 1), n(r.A_ratio, 1), n(r.A_p, 4)])
    st += [M.table(t, font=6.3),
           Paragraph('Seções pareadas: mesma chave município-zona-seção, mesmo local de votação e aptos entre 0,6× e 1,67×. Esperado ao acaso: permutação dentro do município (1.000 repetições). '
                     'Os dois turnos de um mesmo ano e o presidente e governador de 2014 são o mesmo eleitorado: não são réplicas independentes.', M.SM)]

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
    SimpleDocTemplate(str(OUT / 'CADEIA_COMPARECIMENTO_2012_2026.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)
    print('ok')


if __name__ == '__main__':
    main()
