"""Renderiza o DFD do projeto: docs/dfd/*.dot -> .svg, e monta docs/DFD.pdf (texto em A4 + diagramas vetoriais no tamanho natural).

Renderizador Graphviz: `dot` se estiver no PATH; senão, node + @viz-js/viz (Graphviz em WebAssembly),
procurado em VIZJS_DIR ou em ./node_modules (instale com `npm i @viz-js/viz`).
PDF: reportlab (página de texto) + PyMuPDF (páginas dos diagramas). Uso: python scripts/make_dfd.py
"""
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DFD = ROOT / 'docs' / 'dfd'
FIGS = [('nivel0', 'Level 0 — context'), ('nivel1', 'Level 1 — processes and data stores')]
RENDER_MJS = '''import { instance } from "@viz-js/viz";
import { readFileSync, writeFileSync } from "node:fs";
const [dotPath, svgPath] = process.argv.slice(2);
const viz = await instance();
writeFileSync(svgPath, viz.renderString(readFileSync(dotPath, "utf8"), { format: "svg" }));
'''


def dot_para_svg(dot, svg):
    if shutil.which('dot'):
        subprocess.run(['dot', '-Tsvg', str(dot), '-o', str(svg)], check=True)
        return 'dot'
    base = Path(os.environ.get('VIZJS_DIR', ROOT))
    if not (base / 'node_modules' / '@viz-js' / 'viz').exists():
        sys.exit('nem `dot` nem @viz-js/viz encontrados (VIZJS_DIR ou ./node_modules)')
    script = base / 'render_dfd.mjs'
    script.write_text(RENDER_MJS, encoding='utf-8')
    subprocess.run(['node', str(script), str(dot), str(svg)], check=True, cwd=base)
    return 'viz.js'


def pagina_texto():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    H1 = ParagraphStyle('h1', fontName='Helvetica-Bold', fontSize=15, leading=19, textColor='#1a365d', spaceAfter=4)
    H2 = ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor='#1a365d', spaceBefore=10, spaceAfter=4)
    P = ParagraphStyle('p', fontName='Helvetica', fontSize=9.5, leading=13)
    S = ParagraphStyle('s', fontName='Helvetica', fontSize=8.5, leading=11.5, textColor='#555555')
    st = [Paragraph('Observatório do Voto — Data Flow Diagram', H1),
          Paragraph('A reproducible pipeline for Brazilian public election data, with tests and CI. The diagrams name the real scripts '
                    'and paths of the repository; the next pages hold them at natural size. Full description with tables: docs/DFD.md.', S),
          Paragraph('Reading guide', H2),
          Paragraph('Level 0: one system and two external parties, the TSE as the only data source and readers or researchers as '
                    'consumers. GitHub is not an external party: Releases (immutable data packages), Actions (the tests that gate the '
                    'deployment) and Pages (the static site) are infrastructure inside the boundary. Level 1: eight processes and six data '
                    'stores, plus the earlier regional scope in grey. Raw data and reports stay outside git; code, the generated site and the '
                    'release manifests are versioned.', P),
          Paragraph('Notation', H2),
          Paragraph('Rectangle = external entity (outside the system). Ellipse = process (the scripts that transform data). '
                    'Yellow box = data store, with its real path. Arrow = data flow, labelled with what moves. '
                    'Dashed arrow = a value handed back (the release URL) that triggers a second build. The dashed frame marks the parts '
                    'hosted on GitHub, which are inside the system boundary. Grey = earlier scope kept in the repository.', P),
          Paragraph('Where the guarantees live', H2),
          Paragraph('<b>Capture.</b> Every file is checked against the ZIP it came from (CRC, size) and gets a JSON receipt with its SHA-256. '
                    '<b>Edition.</b> edicao.json ties every result to the producing code SHA, the parameters and the hash of each input. '
                    '<b>Release.</b> A draft until each asset\'s local SHA-256 equals the digest GitHub reports; manifesto-release.json is '
                    'attached; an existing tag is never replaced, a new revision is created. <b>Deployment.</b> The site goes live only '
                    'when ruff and both pytest suites pass. <b>Reproduction.</b> restore_edicao.py rebuilds the site from a release, '
                    'hash-verified, without the raw data and without a token.', P)]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                      title='Observatório do Voto — DFD', author='Observatório do Voto').build(st)
    return buf.getvalue()


def pdf():
    import fitz
    out = fitz.open()
    out.insert_pdf(fitz.open('pdf', pagina_texto()))
    for nome, titulo in FIGS:
        svg = fitz.open(str(DFD / f'{nome}.svg'))
        fig = fitz.open('pdf', svg.convert_to_pdf())
        w, h = fig[0].rect.width, fig[0].rect.height
        m, top = 24, 44
        page = out.new_page(width=w + 2 * m, height=h + top + m)
        page.insert_text((m, 26), f'Observatório do Voto — DFD · {titulo}', fontsize=11, fontname='helv', color=(0.10, 0.21, 0.36))
        page.show_pdf_page(fitz.Rect(m, top, m + w, top + h), fig, 0)
    out.set_metadata({'title': 'Observatório do Voto — DFD', 'author': 'Observatório do Voto'})
    out.save(str(ROOT / 'docs' / 'DFD.pdf'), garbage=3, deflate=True)
    return len(out)


def main():
    for nome, _ in FIGS:
        motor = dot_para_svg(DFD / f'{nome}.dot', DFD / f'{nome}.svg')
        print(f'{nome}.svg ({motor})')
    print('OK', ROOT / 'docs' / 'DFD.pdf', pdf(), 'páginas')


if __name__ == '__main__':
    main()
