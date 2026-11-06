"""Relatório da varredura forense (PDF + XLSX + edicao.json) a partir dos CSVs já gravados em relatorios/verificacoes/varredura_forense/.

Lê registro_de_achados.csv, checagens_feitas.csv, dados_externos_necessarios.csv (de scripts/varredura_forense_registro.py), os
<Cx>_resumo.json de cada camada quando existirem e PROTOCOLO.md; monta RELATORIO_VARREDURA.pdf (o que foi checado, o que passou, o que
falhou, o que não foi testável, achados por status e por camada, dados externos) e RELATORIO_VARREDURA.xlsx (aba leia_me primeiro) e
escreve edicao.json (data, SHA do código, parâmetros, hashes das entradas, versão e SHA do protocolo). Como repetir:
python scripts/make_varredura_forense_report.py
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts')]
from make_bahia_reports import H1, H2, NOTE, SM, P, table  # noqa: E402
from make_varredura_locais import git_info, sha256_file  # noqa: E402

OUT = ROOT / 'relatorios' / 'verificacoes' / 'varredura_forense'
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig')
CAMADAS = {'C1': 'Aquisição e formato', 'C2': 'Consistência interna da urna (BU × RDV × log)', 'C3': 'Cronologia e processo da seção',
           'C4': 'Totalização', 'C5': 'Padrões estatísticos entre seções', 'C6': 'Entre eleições: estabilidade e regimes',
           'C7': 'Espelhamento e duplicidade', 'C8': 'Clusters'}
ORDEM_STATUS = ['INEXPLICADO', 'PLAUSIVEL-EXPLICAVEL', 'NAO_TESTAVEL', 'EXPLICADO', 'ARTEFATO', 'INDETERMINADO']
ALTERACOES = ['05/11/2026 — Protocolo v1.0 travado antes das checagens; mapa do existente (Workflow 1) e checagens leves (Workflow 2).']
RODAPE = 'Varredura forense · análise independente e apartidária de dados públicos do TSE · exploratório e descritivo — não indica irregularidade por si só'


def n(x, d=0):
    if x is None or (isinstance(x, float) and pd.isna(x)) or x == '':
        return '—'
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    s = f'{v:,.{d}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return s


def cut(s, k=140):
    s = ' '.join(str(s if s is not None and not (isinstance(s, float) and pd.isna(s)) else '').split())
    return s if len(s) <= k else s[:k - 1] + '…'


def versao_protocolo(texto):
    m = re.search(r'vers[aã]o\s+(\d+\.\d+)', texto, re.I)
    return m.group(1) if m else 'n/d'


def resumo_checagens(chk):
    """Tabela camada × status (feita/parcial/nao_feita) com totais."""
    if chk.empty:
        return pd.DataFrame(columns=['camada', 'feita', 'parcial', 'nao_feita', 'total'])
    t = chk.pivot_table(index='camada', columns='status', values='id', aggfunc='count', fill_value=0)
    for c in ['feita', 'parcial', 'nao_feita']:
        if c not in t.columns:
            t[c] = 0
    t = t[['feita', 'parcial', 'nao_feita']].astype(int)
    t['total'] = t.sum(axis=1)
    t.loc['total'] = t.sum()
    return t.reset_index()


def resumo_achados(reg):
    """Tabela status × prioridade com totais; status na ordem do protocolo."""
    if reg.empty:
        return pd.DataFrame(columns=['status', '1', '2', '3', 'total'])
    t = reg.pivot_table(index='status', columns='prioridade', values='id', aggfunc='count', fill_value=0)
    for p in [1, 2, 3]:
        if p not in t.columns:
            t[p] = 0
    t = t[[1, 2, 3]].astype(int)
    t = t.reindex([s for s in ORDEM_STATUS if s in t.index] + [s for s in t.index if s not in ORDEM_STATUS])
    t['total'] = t.sum(axis=1)
    t.loc['total'] = t.sum()
    t.columns = [str(c) for c in t.columns]
    return t.reset_index()


def manifesto(entradas, protocolo, parametros):
    man = {'edicao': pd.Timestamp.now().strftime('%Y-%m-%d'), 'gerado_em': pd.Timestamp.now().isoformat(timespec='seconds'), **git_info(),
           'script': 'scripts/make_varredura_forense_report.py', 'parametros': parametros,
           'protocolo_versao': versao_protocolo(protocolo.read_text(encoding='utf-8')) if protocolo.exists() else 'n/d',
           'protocolo_sha256': sha256_file(protocolo) if protocolo.exists() else None,
           'entradas': {p.name: sha256_file(p) for p in entradas if p.exists()}}
    return man


def story_relatorio(reg, chk, ext, resumos, proto_versao, man):
    s = [Paragraph('Varredura forense das eleições — relatório da varredura', H1),
         Paragraph(f"Protocolo v{proto_versao} · edição {man['edicao']} · código {str(man.get('codigo_sha'))[:12]}"
                   f"{' (árvore com alterações não commitadas)' if man.get('codigo_sujo') else ''}", SM),
         Paragraph('Sinalização não é acusação. Tudo neste relatório é exploratório e descritivo: lista o que foi checado em cada camada, o que '
                   'passou, o que falhou e o que não pôde ser testado com os dados disponíveis, e registra cada achado com materialidade e status '
                   'provisório. Nenhum achado, isoladamente, indica irregularidade.', NOTE), Spacer(1, 6)]
    s += [Paragraph('1. O que foi checado', H2)]
    rc = resumo_checagens(chk)
    if not rc.empty:
        rows = [['camada', 'feitas', 'parciais', 'não feitas', 'total']] + [[CAMADAS.get(r.camada, r.camada) if r.camada != 'total' else 'total',
                                                                             n(r.feita), n(r.parcial), n(r.nao_feita), n(r.total)] for r in rc.itertuples()]
        s += [table(rows, [9 * cm, 2.2 * cm, 2.2 * cm, 2.5 * cm, 2 * cm]), Spacer(1, 6)]
        s += [Paragraph('"Não feita" significa que a checagem depende de uma passada pesada sobre os arquivos de urna, de rede ou de um dado externo; '
                        'o motivo está na tabela abaixo e no XLSX.', SM)]
        rows = [['id', 'status', 'resultado', 'números-chave / motivo']]
        for r in chk.sort_values(['camada', 'id']).itertuples():
            rows.append([r.id, r.status, cut(r.resultado, 190), cut(r.numeros if r.status != 'nao_feita' else r.motivo, 120)])
        s += [table(rows, [1.8 * cm, 1.8 * cm, 13.5 * cm, 8.5 * cm], font=7)]
    else:
        s += [Paragraph('Nenhuma checagem registrada.', P)]
    s += [PageBreak(), Paragraph('2. Achados por status e prioridade', H2)]
    ra = resumo_achados(reg)
    if not ra.empty:
        rows = [['status (provisório)', 'prioridade 1', 'prioridade 2', 'prioridade 3', 'total']] + \
               [[r.status, n(r._2), n(r._3), n(r._4), n(r.total)] for r in ra.itertuples()]
        s += [table(rows, [6 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2 * cm]), Spacer(1, 6),
              Paragraph('Status: EXPLICADO (causa documentada nos dados), ARTEFATO (parser, formato, fuso, quarentena, vínculo), PLAUSÍVEL-EXPLICÁVEL '
                        '(hipótese compatível, não comprovada), INEXPLICADO (controles e hipóteses não explicam), NÃO TESTÁVEL (falta dado externo nomeado). '
                        'Prioridade 1 = materialidade ou falha de reconciliação.', SM)]
        rows = [['id', 'pleito', 'UF', 'título', 'escopo', 'efeito', 'votos mín–máx', 'status']]
        for r in reg.sort_values(['prioridade', 'camada', 'id']).itertuples():
            rows.append([r.id, cut(r.pleito, 14), cut(r.uf, 10), cut(r.titulo, 70), cut(r.escopo, 40), cut(r.efeito, 80),
                         f'{n(r.materialidade_min)}–{n(r.materialidade_max)}', r.status])
        s += [table(rows, [1.9 * cm, 1.8 * cm, 1.4 * cm, 6.3 * cm, 3.6 * cm, 6.2 * cm, 2.4 * cm, 2.6 * cm], font=6.5)]
    else:
        s += [Paragraph('Nenhum achado registrado.', P)]
    for cam, nome in CAMADAS.items():
        rcam = reg[reg.camada == cam] if not reg.empty else reg
        ccam = chk[chk.camada == cam] if not chk.empty else chk
        if rcam.empty and ccam.empty:
            continue
        s += [PageBreak(), Paragraph(f'3.{cam[1]}. {cam} — {nome}', H2)]
        for r in ccam.sort_values('id').itertuples():
            s += [Paragraph(f'<b>{r.id}</b> [{r.status}] {cut(r.resultado, 900)} {("— " + cut(r.numeros, 400)) if str(r.numeros).strip() else ""}', P)]
        for r in rcam.sort_values(['prioridade', 'id']).itertuples():
            s += [Paragraph(f'<b>{r.id} — {r.titulo}</b> ({r.pleito}; {cut(r.escopo, 80)}; prioridade {r.prioridade}; status provisório {r.status}). '
                            f'{cut(r.efeito, 500)} Materialidade: {n(r.materialidade_min)}–{n(r.materialidade_max)} votos; margem de referência: '
                            f'{cut(r.margem_referencia, 120)}. Controles: {cut(r.controles, 400)} Artefato excluído: {cut(r.artefato_excluido, 300)} '
                            f'Hipóteses: {cut(r.hipoteses, 300)} Dossiê: {r.dossie}.', P)]
        resumo = resumos.get(cam)
        if resumo:
            s += [Paragraph(f'Notas do agente da camada: {cut(resumo, 1200)}', SM)]
    s += [PageBreak(), Paragraph('4. Dados externos necessários para fechar os casos', H2)]
    if not ext.empty:
        rows = [['camadas', 'dado', 'para quê', 'fonte possível', 'achados']] + \
               [[cut(r.camadas, 12), cut(r.dado, 90), cut(r.para_que, 110), cut(r.fonte_possivel, 70), cut(r.achados, 30)] for r in ext.itertuples()]
        s += [table(rows, [1.6 * cm, 7 * cm, 8.2 * cm, 5.6 * cm, 3.2 * cm], font=6.5)]
    s += [Paragraph('5. Limites e leitura', H2),
          Paragraph('As checagens desta edição usam os parquet/CSV já existentes no repositório; as passadas únicas sobre os arquivos de urna (logs e BUs) '
                    'entram nas edições seguintes e podem alterar status. Todo teste de 2026 é lido ao lado do mesmo teste em 2022 (e 2014/2018/2024 '
                    'quando há dado); seções do exterior, especiais e com menos de 50 aptos ficam fora das referências estatísticas. Os status são '
                    'provisórios até o fechamento do dossiê (itens 2–5). Nada é corrigido por suposição; linhas que falham invariantes ficam em quarentena '
                    'identificada.', P),
          Paragraph('6. Registro de alterações', H2)] + [Paragraph('• ' + a, P) for a in ALTERACOES]
    return s


def build_pdf(path, story):
    def footer(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(1.5 * cm, 1 * cm, RODAPE)
        c.drawRightString(28.2 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.6 * cm,
                      title='Varredura forense — relatório', author='AuditaBR').build(story, onFirstPage=footer, onLaterPages=footer)


def build_xlsx(path, reg, chk, ext, man):
    leia = pd.DataFrame({'leia_me': [
        'Varredura forense das eleições (C1 aquisição, C2 urna, C3 cronologia, C4 totalização, C5 padrões, C6 regimes, C7 duplicidade, C8 clusters).',
        'Sinalização não é acusação: tudo é exploratório e descritivo; nenhum achado isolado indica irregularidade.',
        f"Protocolo v{man.get('protocolo_versao')} (sha256 {man.get('protocolo_sha256')}); edição {man['edicao']}; código {man.get('codigo_sha')}.",
        'registro: um achado por linha (id, camada, pleito, escopo, efeito, materialidade mín/máx, status provisório, fonte, dossiê).',
        'checagens: cada checagem do mapa com status feita/parcial/nao_feita, resultado, números e motivo.',
        'dados_externos: o que falta e não está nos dados públicos usados, por camada e por achado.']})
    with pd.ExcelWriter(path, engine='xlsxwriter') as w:
        leia.to_excel(w, sheet_name='leia_me', index=False)
        reg.to_excel(w, sheet_name='registro', index=False)
        chk.to_excel(w, sheet_name='checagens', index=False)
        ext.to_excel(w, sheet_name='dados_externos', index=False)


def main(out=None):
    out = Path(out or OUT)
    reg = pd.read_csv(out / 'registro_de_achados.csv', **CSV) if (out / 'registro_de_achados.csv').exists() else pd.DataFrame()
    chk = pd.read_csv(out / 'checagens_feitas.csv', **CSV) if (out / 'checagens_feitas.csv').exists() else pd.DataFrame()
    ext = pd.read_csv(out / 'dados_externos_necessarios.csv', **CSV) if (out / 'dados_externos_necessarios.csv').exists() else pd.DataFrame()
    for df in (reg, chk, ext):
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].fillna('')
    resumos = {}
    for cam in CAMADAS:
        p = out / cam / f'{cam}_resumo.json'
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding='utf-8'))
                resumos[cam] = d.get('notas', '') if isinstance(d, dict) else ''
            except json.JSONDecodeError:
                resumos[cam] = ''
    proto = out / 'PROTOCOLO.md'
    man = manifesto([out / 'registro_de_achados.csv', out / 'checagens_feitas.csv', out / 'dados_externos_necessarios.csv'], proto,
                    {'ordem_status': ORDEM_STATUS, 'camadas': list(CAMADAS)})
    build_pdf(out / 'RELATORIO_VARREDURA.pdf', story_relatorio(reg, chk, ext, resumos, man['protocolo_versao'], man))
    build_xlsx(out / 'RELATORIO_VARREDURA.xlsx', reg, chk, ext, man)
    (out / 'edicao.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
    print('OK', out / 'RELATORIO_VARREDURA.pdf', '| achados', len(reg), '| checagens', len(chk), '| dados externos', len(ext))
    return 0


if __name__ == '__main__':
    sys.exit(main())
