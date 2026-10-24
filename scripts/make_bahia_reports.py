"""PDF reports + static charts for BA presidential 2022 T1/T2 and 2026 T1. Descriptive only; no causal claims."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import os
UF = os.environ.get('UF', 'BA').upper()
NAMES = {'BA': 'Bahia', 'SP': 'São Paulo', 'MG': 'Minas Gerais', 'RJ': 'Rio de Janeiro', 'PR': 'Paraná', 'RS': 'Rio Grande do Sul',
         'PE': 'Pernambuco', 'CE': 'Ceará', 'PA': 'Pará', 'SC': 'Santa Catarina'}
UFNAME = NAMES[UF]
OFFICE = os.environ.get('OFFICE', 'PRESIDENTE').upper()
OFFICE_LABEL = {'PRESIDENTE': 'Presidente', 'GOVERNADOR': 'Governador'}[OFFICE]
ROOT = Path('research/bahia-presidente-2022-2026') if UF == 'BA' else Path('research/estados') / UF
OUT = Path('relatorios') / UF if OFFICE == 'PRESIDENTE' else Path('relatorios/governador') / UF


def analysis_dir(uf, k):
    if OFFICE == 'PRESIDENTE':
        return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / k / 'analysis'
    return Path('research/analysis/GOVERNADOR') / uf / k
FIG = OUT / 'figuras'
RUNS = [r for r in [('2022-t1', '2022 · 1º turno'), ('2022-t2', '2022 · 2º turno'), ('2026-t1', '2026 · 1º turno')] if (analysis_dir(UF, r[0]) / 'summary.json').exists()]
COL = {'2022-t1': '#2b6cb0', '2022-t2': '#dd6b20', '2026-t1': '#2f855a'}
plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True,
                     'grid.alpha': .25, 'figure.dpi': 150})
ss = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=ss['Title'], fontSize=18, spaceAfter=8)
H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=13, spaceBefore=10, spaceAfter=4)
P = ParagraphStyle('P', parent=ss['BodyText'], fontSize=9.5, leading=13)
SM = ParagraphStyle('SM', parent=P, fontSize=8, leading=10, textColor=colors.HexColor('#555555'))
NOTE = ParagraphStyle('NOTE', parent=P, backColor=colors.HexColor('#fff7e6'), borderColor=colors.HexColor('#e0b050'),
                      borderWidth=.6, borderPadding=5, spaceBefore=6, spaceAfter=6)
CELL = ParagraphStyle('CELL', parent=P, fontSize=7.5, leading=9)


def n(x, d=0):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return '—'
    return f'{x:,.{d}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def table(rows, widths=None, header=True, font=8):
    rows = [[Paragraph(str(c), CELL) if isinstance(c, str) and len(c) > 28 else c for c in r] for r in rows]
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [('FONTSIZE', (0, 0), (-1, -1), font), ('GRID', (0, 0), (-1, -1), .25, colors.HexColor('#cccccc')),
          ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f8fa')])]
    if header:
        st += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
               ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
    t.setStyle(TableStyle(st))
    return t


def fig_img(path, w=17):
    from PIL import Image as PI
    iw, ih = PI.open(path).size
    return Image(str(path), width=w * cm, height=w * cm * ih / iw)


def build(name, title, story):
    def footer(c, d):
        c.setFont('Helvetica', 7);c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1.2 * cm, f'{UFNAME} · {OFFICE_LABEL} · exploratório e descritivo — não indica irregularidade por si só')
        c.drawRightString(19 * cm, 1.2 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / name), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=2 * cm, title=title, author='AuditaBR').build(story, onFirstPage=footer, onLaterPages=footer)


def load():
    data = {}
    for k, label in RUNS:
        folder = analysis_dir(UF, k)
        s = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
        sec = pd.read_parquet(folder / 'sections.parquet')
        data[k] = dict(label=label, summary=s, sec=sec, has_log='after_17_recorded' in sec.columns)
        if not data[k]['has_log']:
            raise SystemExit(f'{k}: análise sem logs; rode analyze_bahia_documents.py completo antes')
        d = sec.copy()
        d['linked'] = d['member'].notna()
        d['recon'] = d['vote_events'].eq(d['attendance'])
        d['manual_log_share'] = d['manual_sequence_votes'] / d['vote_events'].where(d['vote_events'] > 0)
        d['manual_bu_share'] = d['manual_bu'] / d['attendance'].where(d['attendance'] > 0)
        d['any_late'] = d['after_17_recorded'] > 0
        data[k]['sec'] = d
    return data


def charts(data):
    FIG.mkdir(parents=True, exist_ok=True)
    # turnout distribution
    f, ax = plt.subplots(1, 2, figsize=(10, 3.4))
    for k, v in data.items():
        d = v['sec']; d = d[d.eligible >= 50]
        ax[0].hist(100 * d.turnout, bins=np.arange(0, 101, 1.5), histtype='step', lw=1.6, color=COL[k], label=v['label'])
        m = d.groupby('municipality').agg(a=('attendance', 'sum'), e=('eligible', 'sum'))
        ax[1].hist(100 * m.a / m.e, bins=np.arange(55, 100, 1.5), histtype='step', lw=1.6, color=COL[k], label=v['label'])
    ax[0].set(title='Comparecimento por seção (≥50 aptos)', xlabel='% comparecimento', ylabel='seções')
    ax[1].set(title='Comparecimento por município', xlabel='% comparecimento', ylabel='municípios'); ax[0].legend()
    f.tight_layout(); f.savefig(FIG / 'turnout_dist.png'); plt.close(f)
    # candidates
    f, ax = plt.subplots(1, max(len(data), 2), figsize=(10, 3.4))
    for a, (k, v) in zip(ax, data.items()):
        c = pd.DataFrame(v['summary']['candidates']).head(5)
        a.barh(c.candidate[::-1], c.share_pct[::-1], color=COL[k]); a.set_title(v['label'], fontsize=9)
        a.set_xlabel('% votos válidos')
        for i, x in enumerate(c.share_pct[::-1]): a.text(x + .5, i, f'{x:.1f}', va='center', fontsize=7)
        a.set_xlim(0, 85)
    f.tight_layout(); f.savefig(FIG / 'candidates.png'); plt.close(f)
    # turnout high: per-section scatter turnout vs municipal median
    f, ax = plt.subplots(1, max(len(data), 2), figsize=(10, 3.4), sharey=True)
    for a, (k, v) in zip(ax, data.items()):
        d = v['sec']; d = d[d.eligible >= 50]; h = d[d.raw_high_turnout == True]
        a.scatter(100 * d.municipal_median, 100 * d.turnout, s=1, alpha=.15, color='#999')
        a.scatter(100 * h.municipal_median, 100 * h.turnout, s=10, color='#c53030', label=f'sinalizadas: {len(h)}')
        a.plot([40, 100], [40, 100], 'k--', lw=.6); a.set_title(v['label'], fontsize=9); a.legend(fontsize=7, loc='lower right')
        a.set_xlabel('mediana municipal (%)')
    ax[0].set_ylabel('comparecimento da seção (%)')
    f.tight_layout(); f.savefig(FIG / 'turnout_flags.png'); plt.close(f)
    # late share
    f, ax = plt.subplots(1, max(len(data), 2), figsize=(10, 3.4), sharey=True)
    for a, (k, v) in zip(ax, data.items()):
        d = v['sec']; d = d[d.operational_eligible == True]
        a.scatter(d.vote_events, d.after_17_recorded, s=3, alpha=.3, color=COL[k])
        h = d[d.raw_high_late == True]; a.scatter(h.vote_events, h.after_17_recorded, s=14, color='#c53030', label=f'sinalizadas: {len(h)}')
        a.set_yscale('symlog'); a.set_title(v['label'], fontsize=9); a.set_xlabel('votos concluídos na seção'); a.legend(fontsize=7)
    ax[0].set_ylabel('votos após 17h (escala symlog)')
    f.tight_layout(); f.savefig(FIG / 'late_scatter.png'); plt.close(f)
    f, ax = plt.subplots(figsize=(8, 3.2))
    for k, v in data.items():
        d = v['sec']; d = d[d.operational_eligible == True]
        x = np.sort(d.after_17_recorded.values); y = 1 - np.arange(len(x)) / len(x)
        ax.step(x, y, where='post', color=COL[k], label=v['label'])
    ax.set_xscale('symlog'); ax.set_yscale('log'); ax.set(xlabel='votos após 17h na seção', ylabel='fração de seções com ≥ x', title='Cauda da distribuição de votos após 17h')
    ax.legend(); f.tight_layout(); f.savefig(FIG / 'late_ccdf.png'); plt.close(f)
    # last vote hour
    f, ax = plt.subplots(figsize=(8, 3.2))
    for k, v in data.items():
        d = v['sec']; d = d[d.vote_events > 0]
        h = pd.to_datetime(d.last_vote.astype(str).str[-8:], format='%H:%M:%S', errors='coerce')
        hr = (h.dt.hour + h.dt.minute / 60).dropna()
        ax.hist(hr, bins=np.arange(14, 24, .25), weights=np.full(len(hr), 100 / len(hr)), histtype='step', lw=1.6, color=COL[k], label=v['label'])
    ax.axvline(17, color='k', ls='--', lw=.8); ax.set(xlabel='hora do último voto registrado na seção', ylabel='% das seções', title='Horário do último voto por seção')
    ax.legend(); f.tight_layout(); f.savefig(FIG / 'last_vote.png'); plt.close(f)
    # manual
    f, ax = plt.subplots(1, max(len(data), 2), figsize=(10, 3.4), sharey=True, sharex=True)
    for a, (k, v) in zip(ax, data.items()):
        d = v['sec']; d = d[d.linked & (d.vote_events > 0)]
        a.scatter(100 * d.manual_bu_share, 100 * d.manual_log_share, s=2, alpha=.25, color=COL[k])
        a.plot([0, 100], [0, 100], 'k--', lw=.6); a.set_title(v['label'], fontsize=9); a.set_xlabel('BU: sem habilitação biométrica (%)')
    ax[0].set_ylabel('log: sessão manual completa (%)')
    f.tight_layout(); f.savefig(FIG / 'manual_scatter.png'); plt.close(f)
    f, ax = plt.subplots(1, 2, figsize=(10, 3.4))
    for k, v in data.items():
        d = v['sec']; d = d[d.linked & (d.vote_events > 0)]
        ax[0].hist(100 * d.manual_log_share, bins=np.arange(0, 101, 2), histtype='step', lw=1.6, color=COL[k], label=v['label'])
        t = d.groupby('municipality').agg(m=('manual_sequence_votes', 'sum'), e=('vote_events', 'sum'))
        ax[1].hist(100 * t.m / t.e, bins=np.arange(0, 60, 1.5), histtype='step', lw=1.6, color=COL[k], label=v['label'])
    ax[0].set(title='Proporção manual por seção (log)', xlabel='%', ylabel='seções', yscale='log'); ax[0].legend()
    ax[1].set(title='Proporção manual por município (log)', xlabel='%', ylabel='municípios')
    f.tight_layout(); f.savefig(FIG / 'manual_dist.png'); plt.close(f)


def pct(a, b):
    return 100 * a / b if b else np.nan


def stats(data):
    out = {}
    for k, v in data.items():
        d = v['sec']; t = v['summary']['totals']; lc = v['summary']['log_counts']; cov = v['summary']['coverage']
        e = d[d.operational_eligible == True]
        out[k] = dict(t=t, lc=lc, cov=cov, late_p99=v['summary']['late_p99'], elig=len(e),
                      late_total=int(e.after_17_recorded.sum()), vote_total=int(e.vote_events.sum()),
                      sections_late=int(e.any_late.sum()), manual_log=int(d.manual_sequence_votes.fillna(0).sum()),
                      manual_bu=int(d.manual_bu.sum()), manual_late=int(e.after_17_manual_sequence.sum()))
    return out


def report_overview(data, st):
    n_mun = st['2026-t1']['t']['municipalities']
    s = [Paragraph(f'{UFNAME} · {OFFICE_LABEL} · 2022 e 2026', H1),
         Paragraph('Relatório 1 — Panorama da apuração e dos dados coletados', H2),
         Paragraph(f'Fonte: Boletins de Urna (BU) e logs oficiais das urnas publicados pelo TSE. Recorte: {n_mun} municípios, seções de {UFNAME}, '
                   f'cargo {OFFICE_LABEL}. Este documento apenas descreve; não afirma irregularidade.', P)]
    rows = [['Indicador'] + [v['label'] for v in data.values()]]
    for lab, f in [('Seções (BUs)', lambda t: n(t['bu_units'])), ('Municípios', lambda t: n(t['municipalities'])),
                   ('Aptos', lambda t: n(t['eligible'])), ('Comparecimento', lambda t: n(t['attendance'])),
                   ('Abstenções', lambda t: n(t['absent'])), ('% comparecimento', lambda t: n(t['turnout_pct'], 2) + '%'),
                   ('Votos válidos', lambda t: n(t['valid_votes'])), ('Brancos+nulos', lambda t: n(t['blank_null_votes'])),
                   ('Vencedor', lambda t: f"{t['winner']} ({n(t['winner_pct'], 1)}%)"), ('Margem 1º–2º (p.p.)', lambda t: n(t['margin_pp'], 1))]:
        rows.append([lab] + [f(st[k]['t']) for k in data])
    s += [table(rows, [5 * cm, 4 * cm, 4 * cm, 4 * cm]), Spacer(1, 6), fig_img(FIG / 'candidates.png'),
          Paragraph('Os totais do BU foram conferidos internamente: aptos = comparecimento + abstenções, e soma de votos = comparecimento em todas as seções.', SM),
          Paragraph('Comparecimento', H2), fig_img(FIG / 'turnout_dist.png')]
    # volume of data
    s += [PageBreak(), Paragraph('Volume de dados em disco', H2)]
    rows = [['Recorte', 'Logs (arquivos)', 'Logs (GB)', 'Logs processados', 'Casados ao BU', 'Contagem log = BU']]
    for k, v in data.items():
        folder = ROOT / k if (k != '2022-t2' or UF != 'BA') else Path('research/piloto-ba-2022-t2')
        logs = [p for p in (folder / 'logs').glob('*') if not p.name.endswith(('.json', '.part'))]
        gb = sum(p.stat().st_size for p in logs) / 1024 ** 3
        c = st[k]['cov']
        rows.append([v['label'], n(len(logs)), n(gb, 2), n(st[k]['lc']['files']), n(c['linked']), n(c['reconciled'])])
    s += [table(rows, [3.3 * cm, 2.6 * cm, 2.2 * cm, 3 * cm, 2.8 * cm, 3.2 * cm]),
          Paragraph('Os logs registram a sessão inteira da urna (todos os cargos). Foram preservados compactados, sem separar eventos por cargo. '
                    'Arquivos sem identificação segura de seção (ambíguos) não são casados ao BU e ficam fora das medidas por seção.', SM)]
    build('01_panorama_apuracao.pdf', 'Panorama da apuração', s)


def sect_rows(d, cols):
    return [[str(x) if not isinstance(x, (int, float, np.integer, np.floating)) else n(x, 0 if float(x).is_integer() else 2) for x in r] for r in d[cols].values.tolist()]


def report_turnout(data, st):
    s = [Paragraph('Relatório 2 — Baixa abstenção (comparecimento atipicamente alto)', H1),
         Paragraph('Pergunta: onde o comparecimento foi muito acima do padrão estadual e do próprio município? '
                   '<b>Regra A (bruta)</b>: seção com ≥50 aptos, desvio z &gt; 3 em relação à mediana estadual (MAD bruto) '
                   'e pelo menos 10 p.p. acima da mediana do município.', P),
         Paragraph('Atenção: seção sinalizada não é prova de nada. Seções pequenas, locais com público cativo (quartéis, presídios, '
                   'comunidades isoladas) ou agregação de seções produzem comparecimento alto legítimo. Exclusões e controles ainda pendentes.', NOTE),
         fig_img(FIG / 'turnout_flags.png')]
    rows = [['Recorte', 'Mediana estadual', 'MAD', 'Seções sinalizadas', 'Municípios', 'Aptos nelas', '% do total de seções']]
    for k, v in data.items():
        d = v['sec']; h = d[d.raw_high_turnout == True]
        rows.append([v['label'], n(100 * d.state_median.iloc[0], 1) + '%', n(100 * d.state_mad.iloc[0], 2) + ' p.p.',
                     n(len(h)), n(h.municipality.nunique()), n(h.eligible.sum()), n(pct(len(h), len(d)), 2) + '%'])
    s += [table(rows), Paragraph('Comparação com a média estadual e nacional', H2),
          Paragraph('A média estadual ponderada é a da tabela do relatório 1. A média nacional exige cobertura nacional e '
                    'ainda não foi coletada; será incluída quando os demais estados forem processados.', P)]
    for k, v in data.items():
        d = v['sec']; h = d[d.raw_high_turnout == True].copy()
        s += [Paragraph(f'{v["label"]} — 15 maiores desvios', H2)]
        if h.empty:
            s.append(Paragraph('Nenhuma seção sinalizada.', P)); continue
        h['turnout_pct'] = 100 * h.turnout; h['mun_med'] = 100 * h.municipal_median
        h = h.sort_values('turnout', ascending=False).head(15)
        s.append(table([['Município', 'Zona', 'Seção', 'Aptos', 'Compar.', '% seção', '% mediana mun.', 'Vencedor']] +
                       sect_rows(h, ['municipality_name', 'zone', 'section', 'eligible', 'attendance', 'turnout_pct', 'mun_med', 'winner_party'])))
        cm_ = h.groupby('municipality_name').size().sort_values(ascending=False).head(5)
    s += [PageBreak(), Paragraph('Reincidência por município (seções sinalizadas)', H2)]
    allh = pd.concat([v['sec'][v['sec'].raw_high_turnout == True].assign(r=v['label']) for v in data.values()])
    piv = allh.pivot_table(index='municipality_name', columns='r', values='section', aggfunc='count', fill_value=0)
    piv['total'] = piv.sum(axis=1); piv = piv.sort_values('total', ascending=False).head(20)
    s.append(table([['Município'] + list(piv.columns)] + [[i] + [n(x) for x in r] for i, r in piv.iterrows()]))
    s.append(Paragraph('Mesmo município aparecer em vários pleitos indica um padrão local de comparecimento alto (geografia, perfil do eleitorado), '
                       'não necessariamente algo anômalo. Seções não são comparadas entre anos: a mesma chave de seção não garante o mesmo local físico.', SM))
    build('02_baixa_abstencao.pdf', 'Baixa abstenção', s)


def late_context(data, st):
    parts = []
    for k, v in data.items():
        d = v['sec']; d = d[d.vote_events > 0]
        lv = pd.to_datetime(d.last_vote.astype(str).str[-8:], format='%H:%M:%S', errors='coerce')
        after = (lv.dt.hour >= 17) & ~((lv.dt.hour == 17) & (lv.dt.minute == 0) & (lv.dt.second == 0))
        parts.append(f"{v['label']}: {n(100 * after.mean(), 0)}% das seções com último voto após 17h00, {n(100 * (lv.dt.hour >= 19).mean(), 0)}% após 19h00 "
                     f"({n(pct(st[k]['late_total'], st[k]['vote_total']), 2)}% dos votos)")
    return ('<b>Contexto essencial.</b> ' + '; '.join(parts) + '. Votar depois das 17h é permitido a quem já estava na fila; a regra B sinaliza apenas a cauda '
            '<i>relativa</i> (o 1% mais tardio de cada pleito), não votos “fora do normal” em termos absolutos. Pleitos com mais cargos na urna tendem a ter mais fila, '
            'então pleitos diferentes não são comparáveis diretamente.')


def report_late(data, st):
    s = [Paragraph('Relatório 3 — Votação após as 17 horas', H1),
         Paragraph('Pergunta: quais seções registraram muitos votos <i>concluídos</i> depois das 17h00? A medida é o evento de log '
                   '“O voto do eleitor foi computado” com horário estritamente posterior a 17:00:00 no relógio da própria urna. '
                   'Em 2022 e 2026 o horário de votação foi unificado (Brasília); este estado usa o mesmo fuso, então não há conversão.', P),
         Paragraph('Atenção: quem estava na fila às 17h tem direito de votar até o fim — votos depois das 17h são esperados em seções com fila. '
                   'O relógio é o registrado na urna, não calibrado de forma independente. <b>Regra B (bruta)</b>: fração de votos após 17h acima do '
                   'P99 estadual e ≥20 votos após 17h, apenas em seções com log unicamente identificado, contagem de votos = comparecimento do BU, '
                   'sem reversão de relógio.', NOTE)]
    rows = [['Recorte', 'Seções elegíveis', 'Votos (log)', 'Votos após 17h', '% após 17h', 'Seções com ≥1', 'P99 fração', 'Sinalizadas B']]
    for k, v in data.items():
        x = st[k]; sflag = int((v['sec'].raw_high_late == True).sum())
        rows.append([v['label'], n(x['elig']), n(x['vote_total']), n(x['late_total']), n(pct(x['late_total'], x['vote_total']), 3) + '%',
                     n(x['sections_late']), n(100 * x['late_p99'], 2) + '%', n(sflag)])
    s += [table(rows), Spacer(1, 6),
          Paragraph(late_context(data, st), NOTE),
          fig_img(FIG / 'last_vote.png', 13), fig_img(FIG / 'late_scatter.png'), fig_img(FIG / 'late_ccdf.png', 13)]
    for k, v in data.items():
        d = v['sec']; h = d[d.raw_high_late == True].copy()
        s += [Paragraph(f'{v["label"]} — seções sinalizadas ({len(h)}); 15 com mais votos após 17h', H2)]
        if h.empty:
            s.append(Paragraph('Nenhuma seção sinalizada.', P)); continue
        h['late_pct'] = 100 * h.late_share; h['last'] = h['last_vote'].astype(str).str[-8:]
        h = h.sort_values('after_17_recorded', ascending=False).head(15)
        s.append(table([['Município', 'Zona', 'Seção', 'Aptos', 'Votos', 'Após 17h', '% após', 'Último voto', 'Mediana int. (s)']] +
                       sect_rows(h, ['municipality_name', 'zone', 'section', 'eligible', 'vote_events', 'after_17_recorded', 'late_pct', 'last', 'late_interval_median_seconds'])))
    s += [PageBreak(), Paragraph('Municípios com mais seções sinalizadas', H2)]
    for k, v in data.items():
        d = v['sec']; h = d[d.raw_high_late == True]
        g = h.groupby('municipality_name').agg(secoes=('section', 'count'), tarde=('after_17_recorded', 'sum')).sort_values(['secoes', 'tarde'], ascending=False).head(10)
        s += [Paragraph(v['label'], P), table([['Município', 'Seções sinalizadas', 'Votos após 17h']] + [[i, n(r.secoes), n(r.tarde)] for i, r in g.iterrows()], [7 * cm, 4 * cm, 4 * cm])]
    s.append(Paragraph('Leitura: a diferença entre seção sinalizada e comum pode refletir fila, atraso na abertura, substituição de urna ou contingência. '
                       'Esses fatores ainda não foram controlados — por isso o resultado é descritivo.', SM))
    build('03_votacao_apos_17h.pdf', 'Votação após as 17h', s)


def agree_text(data):
    t = []
    for k, v in data.items():
        d = v['sec']; d = d[d.linked & (d.vote_events > 0)]
        t.append(f"{v['label']}: correlação {n(d.manual_log_share.corr(d.manual_bu_share), 3)}, log = BU em {n(100 * (d.manual_sequence_votes == d.manual_bu).mean(), 1)}% das seções")
    return 'Concordância BU×log — ' + '; '.join(t) + '.'


def report_manual(data, st):
    s = [Paragraph('Relatório 4 — Habilitação manual pelo mesário', H1),
         Paragraph('Duas medidas independentes. <b>BU</b>: eleitores com biometria cadastrada que <i>não foram habilitados pela biometria</i> (campo oficial). '
                   '<b>Log</b>: votos cuja sessão completa na urna seguiu a sequência “solicitação de dado pessoal → autorização do mesário → eleitor habilitado → voto computado”. '
                   'Eleitores sem biometria cadastrada usam outra rotina e não entram como “manual”.', P),
         Paragraph('Atenção: habilitação manual ocorre legitimamente por falha de leitura da digital, mãos desgastadas, etc. Em 2026, o log distingue '
                   'registros em que a digital do mesário foi coletada mas não associada a um mesário; esses não são tratados como “assinatura confirmada”. '
                   'Sem controles (idade, biometria cadastrada, modelo de urna), não há “excesso ajustado” — só quantidades observadas.', NOTE)]
    rows = [['Recorte', 'Manual (BU)', '% do comparecimento', 'Manual (log)', 'Seções com log = BU', 'Seções log ≠ BU', 'Manual após 17h']]
    for k, v in data.items():
        x = st[k]; c = x['cov']
        rows.append([v['label'], n(x['manual_bu']), n(pct(x['manual_bu'], x['t']['attendance']), 2) + '%', n(x['manual_log']),
                     n(c['manual_equal_bu']), n(c['manual_different_bu']), n(x['manual_late'])])
    un = ' · '.join(f"{v['label']}: {n(st[k]['lc']['unclassified_votes'])} ({n(pct(st[k]['lc']['unclassified_votes'], st[k]['lc']['vote_events']), 1)}%)" for k, v in data.items())
    s += [table(rows), Spacer(1, 4),
          Paragraph('Votos cuja sequência de eventos não foi classificada pelo leitor de logs (não são “manuais” nem “biométricos” confirmados): ' + un +
                    '. Proporções muito diferentes entre pleitos indicam possível mudança nos eventos do log; a causa não foi determinada. '
                    'Isso impede classificar esses votos como biométricos ou sem biometria, mas não altera a medida manual, que é comparada ao BU.', SM),
          fig_img(FIG / 'manual_dist.png'), fig_img(FIG / 'manual_scatter.png')]
    s.append(Paragraph('Pontos sobre a diagonal = proporção manual do log igual à do BU. ' + agree_text(data) +
                       ' Seções com proporção próxima de 100% (cauda do histograma) são compatíveis com falha do leitor biométrico, que obriga a habilitação manual de todos; isso não foi verificado.', SM))
    for k, v in data.items():
        d = v['sec']; d = d[d.linked & (d.vote_events >= 50)].copy()
        p99 = d.manual_log_share.quantile(.99)
        h = d[d.manual_log_share > p99].copy()
        s += [Paragraph(f'{v["label"]} — maior proporção manual (acima do P99 = {n(100 * p99, 1)}%, seções com ≥50 votos): {len(h)} seções', H2)]
        h['ml'] = 100 * h.manual_log_share; h['mb'] = 100 * h.manual_bu_share
        h = h.sort_values('ml', ascending=False).head(12)
        s.append(table([['Município', 'Zona', 'Seção', 'Votos', 'Manual log', '% log', 'Manual BU', '% BU']] +
                       sect_rows(h, ['municipality_name', 'zone', 'section', 'vote_events', 'manual_sequence_votes', 'ml', 'manual_bu', 'mb'])))
    if 'manual_unattributed_votes' in data['2026-t1']['sec'].columns:
        d = data['2026-t1']['summary'].get('unattributed_manual')
        if d: s.append(Paragraph(f'2026: {n(d["votes"])} votos tiveram digital coletada sem associação a mesário ({n(d["late_votes"])} após 17h).', P))
    build('04_habilitacao_manual.pdf', 'Habilitação manual', s)


def report_cross(data, st):
    s = [Paragraph('Relatório 5 — Cruzamento dos três indicadores e limites', H1),
         Paragraph('Quantas seções cumprem mais de um critério bruto (A: comparecimento alto; B: votos tardios; C: proporção manual acima do P99)? '
                   'Comparamos o observado com o esperado se os critérios fossem independentes (N × pA × pB × pC). Descritivo, sem teste de hipótese.', P)]
    rows = [['Recorte', 'N elegível', 'A', 'B', 'C', 'A∩B', 'B∩C', 'A∩C', 'A∩B∩C', 'Esperado B∩C', 'Esperado A∩B∩C']]
    for k, v in data.items():
        d = v['sec']; d = d[(d.operational_eligible == True) & d.raw_high_turnout.notna() & d.raw_high_late.notna() & (d.vote_events >= 50)].copy()
        p99 = d.manual_log_share.quantile(.99); d['C'] = d.manual_log_share > p99
        A, B, C = d.raw_high_turnout == True, d.raw_high_late == True, d.C
        N = len(d); pa, pb, pc = A.mean(), B.mean(), C.mean()
        rows.append([v['label'], n(N), n(A.sum()), n(B.sum()), n(C.sum()), n((A & B).sum()), n((B & C).sum()), n((A & C).sum()),
                     n((A & B & C).sum()), n(N * pb * pc, 1), n(N * pa * pb * pc, 2)])
    s += [table(rows, font=7), Paragraph('Limites desta análise', H2)]
    for t in ['Nenhum voto individual é ligado a uma sessão de log; o log não identifica eleitor nem candidato.',
              'Sem controles obrigatórios (idade, biometria cadastrada, escolaridade, modelo de urna, urbano/rural, substituição, atraso de abertura, contingência), C ajustado e associações com votação em candidatos não são estimados.',
              'A mesma chave município-zona-seção em anos distintos não prova o mesmo local físico; não há análise de persistência entre anos nesta fase.',
              'Relógios das urnas são os registrados, não certificados.',
              'Seções especiais, de trânsito e agregadas ainda não foram excluídas/separadas; o piso de 50 aptos é aplicado.',
              'Sinalizações são triagem para investigação documental, não evidência de irregularidade, fraude ou favorecimento.']:
        s.append(Paragraph('• ' + t, P))
    build('05_cruzamento_e_limites.pdf', 'Cruzamento e limites', s)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    data = load(); charts(data); st = stats(data)
    report_overview(data, st); report_turnout(data, st); report_late(data, st); report_manual(data, st); report_cross(data, st)
    (OUT / 'estatisticas.json').write_text(json.dumps(st, default=float, ensure_ascii=False, indent=1), encoding='utf-8')
    print('ok', [p.name for p in OUT.glob('*.pdf')])
