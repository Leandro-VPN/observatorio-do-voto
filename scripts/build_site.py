"""Monta o site estático (site/) a partir dos resultados atuais: números do painel, galeria de gráficos com legendas, PDFs, pacotes de dados.

Uso: .\\.venv-report\\Scripts\\python.exe scripts\\build_site.py
Entradas: relatorios/fiscalizacao/{varredura,documentos,mapa_2026_T2}/..., site/templates/*, site/site_config.json
Saídas:   site/index.html, site/app.js, site/assets/figuras/, site/documentos/, site/dados/ (CSVs, zips, parquet opcional, dicionário)
Nada é digitado à mão: regenerar o site = rodar este script depois da cadeia de análise.
"""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd
from PIL import Image
from pypdf import PdfReader

ROOT = Path('.')
SITE = ROOT / 'site'
FISC = ROOT / 'relatorios/fiscalizacao'
VAR, DOC, MAPA = FISC / 'varredura', FISC / 'documentos', FISC / 'mapa_2026_T2'
CSV = dict(sep=';', decimal=',')
LAB = {'P2026': 'Presidencial · 2026 · 1º turno', 'P2022': 'Presidencial · 2022 · 1º turno', 'P2022b': 'Presidencial · 2022 · 2º turno', 'M2024': 'Municipal · 2024 · 1º turno', 'M2024b': 'Municipal · 2024 · 2º turno'}
ORDER_EIDS = ['P2026', 'P2022', 'P2022b', 'M2024', 'M2024b']
UF_ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC', 'MA']
MB = 1024 ** 2
TITULOS = {'01_comportamento': 'Seções com comportamento, por eleição', '02_diferenca_real': 'Diferença acima do limiar, por nível de comparação', '03_direcao': 'Direção das diferenças, por nível',
           '04_permutacao': 'Teste de direção por permutação', '05_locais_uf': 'Locais por estado e prioridade', '06_pontos': 'Distribuição dos pontos', '07_composicao_pontos': 'Composição dos pontos (prioridade alta)',
           '08_pres_x_pref': 'Prefeito × presidente, mesmas seções', '09_recorrencia': 'Recorrência entre eleições', '10_votos_apos_17h': 'Votos após as 17h', '11_mapa_uf': 'Mapa de fiscalização por estado', '12_cidades': 'Cidades com mais locais de prioridade alta'}


def sz(p):
    b = Path(p).stat().st_size
    return f'{b / MB:,.1f} MB'.replace(',', 'X').replace('.', ',').replace('X', '.') if b >= MB else f'{b / 1024:,.0f} KB'.replace(',', '.')


def pages(p):
    try:
        return len(PdfReader(str(p)).pages)
    except Exception:
        return 0


def git_head():
    try:
        return subprocess.run(['C:/Program Files/Git/cmd/git.exe', 'log', '--format=%h', '-1'], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return 'n/d'


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def main():
    cfg = json.loads((SITE / 'site_config.json').read_text(encoding='utf-8'))
    V = pd.read_csv(VAR / 'resumo_por_eleicao.csv', **CSV).set_index('eid')
    L = pd.read_csv(VAR / 'locais_risco.csv', low_memory=False, usecols=['uf', 'prioridade_observacao'], **CSV)
    ufs = [u for u in UF_ORDER if u in L.uf.unique()]
    edicao = pd.Timestamp((VAR / 'resumo_por_eleicao.csv').stat().st_mtime, unit='s').strftime('%d/%m/%Y')
    # --- painel: registros por eleição
    cols = ['secoes', 'com_comportamento', 'tardia', 'manual', 'local_com_comportamento', 'local_dif_real', 'local_comuns', 'local_comuns_real', 'local_favor_A', 'local_favor_B', 'local_comuns_favor_A', 'local_comuns_favor_B', 'cmp_municipio']
    records = {eid: {c: int(V.loc[eid, c]) for c in cols} for eid in ORDER_EIDS if eid in V.index}
    (SITE / 'app.js').write_text((SITE / 'templates/app.template.js').read_text(encoding='utf-8').replace('__RECORDS__', json.dumps(records, ensure_ascii=False)).replace('__PIX__', cfg['pix_chave']), encoding='utf-8')
    # --- figuras e legendas
    figdir = SITE / 'assets/figuras'
    figdir.mkdir(parents=True, exist_ok=True)
    legendas = json.loads((DOC / 'figuras/legendas.json').read_text(encoding='utf-8'))
    gal = []
    for i, it in enumerate(legendas, 1):
        shutil.copy2(DOC / 'figuras' / it['arquivo'], figdir / it['arquivo'])
        titulo = TITULOS.get(it['arquivo'][:-4], it['arquivo'][3:-4].replace('_', ' ').capitalize())
        gal.append(f'<figure><img src="assets/figuras/{it["arquivo"]}" alt="Gráfico {i}: {esc(titulo)}" loading="lazy"><figcaption><b>Gráfico {i} · {esc(titulo)}</b>{esc(it["legenda"])}</figcaption></figure>')
    # --- documentos
    (SITE / 'documentos').mkdir(exist_ok=True)
    docs = {'RESUMO': DOC / 'RESUMO_SIMPLES.pdf', 'GRAFICOS': DOC / 'GRAFICOS.pdf', 'METODO': DOC / 'METODO_E_DADOS.pdf', 'VARREDURA': VAR / 'VARREDURA_LOCAIS_RISCO.pdf',
            'MAPA': MAPA / 'MAPA_FISCALIZACAO_2026T2_GERAL.pdf', 'INCONS': FISC / 'INCONSISTENCIAS_E_FISCALIZACAO.pdf'}
    pg = {}
    for k, p in docs.items():
        shutil.copy2(p, SITE / 'documentos' / p.name)
        pg[k] = pages(p)
    # --- dados: CSVs pequenos diretos, zips por tema, parquet opcional, dicionário
    dd = SITE / 'dados'
    dd.mkdir(exist_ok=True)
    for old in dd.glob('*'):
        old.unlink()
    shutil.copy2(VAR / 'resumo_por_eleicao.csv', dd / 'resumo-por-eleicao.csv')
    for f in ['comparacao_por_nivel.csv', 'pres_x_pref_pareado.csv', 'pres_x_pref_mesmas_secoes.csv', 'recorrencia_condicional.csv']:
        shutil.copy2(VAR / f, dd / f.replace('_', '-'))
    for f in ['resumo_indicadores.csv', 'testes_permutacao.csv']:
        shutil.copy2(FISC / f, dd / f.replace('_', '-'))

    def zipf(name, files):
        with zipfile.ZipFile(dd / name, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in files:
                z.write(f, Path(f).name)
    zipf('varredura-locais.zip', [VAR / f for f in ['locais_risco.csv', 'prioridade_locais_2026_T2.csv', 'zonas.csv', 'cidades.csv', 'secoes_historico.csv', 'secoes_com_comportamento_por_eleicao.csv', 'padroes_pres_x_pref_por_uf.csv',
                                                    'resumo_por_eleicao.csv', 'comparacao_por_nivel.csv', 'pres_x_pref_pareado.csv', 'pres_x_pref_mesmas_secoes.csv', 'recorrencia_condicional.csv']])
    zipf('mapa-fiscalizacao-2026-t2.zip', [MAPA / f for f in ['locais_todos.csv', 'secoes_checklist_todas.csv', 'zonas_todas.csv', 'resumo_por_uf.csv', 'MAPA_FISCALIZACAO_2026T2_GERAL.pdf', 'MAPA_FISCALIZACAO_2026T2_GERAL.xlsx']]
         + sorted(MAPA.glob('MAPA_FISCALIZACAO_2026T2_??.pdf')) + sorted(MAPA.glob('MAPA_FISCALIZACAO_2026T2_??.xlsx')))
    zipf('planilhas-varredura-por-uf.zip', [VAR / 'VARREDURA_LOCAIS.xlsx'] + sorted(VAR.glob('LOCAIS_??.xlsx')))
    # dicionário de campos (do leia_me da varredura e do mapa)
    sys.path.insert(0, 'scripts')
    import os
    os.environ.setdefault('UF', 'BA')
    import make_mapa_fiscalizacao_2026t2 as MM
    import make_varredura_locais as MV
    dic = pd.concat([MV.readme().assign(origem='varredura'), MM.readme().assign(origem='mapa_2026_T2')])
    dic.to_csv(dd / 'dicionario-de-campos.csv', index=False, **CSV, encoding='utf-8-sig')
    downloads = [('CSV', 'resumo-por-eleicao.csv', 'Resumo por eleição e turno', 'Indicadores agregados, por nível de comparação'),
                 ('CSV', 'comparacao-por-nivel.csv', 'Comparação por nível', 'Com comportamento × comuns, por eleição e nível (local / poucos pares / município)'),
                 ('CSV', 'pres-x-pref-pareado.csv', 'Prefeito × presidente, mesmas seções', 'Taxas com denominadores; e pres-x-pref-mesmas-secoes.csv (McNemar)'),
                 ('CSV', 'testes-permutacao.csv', 'Testes de direção por permutação', 'Dois esquemas de embaralhamento, quantis do nulo, p e q'),
                 ('ZIP', 'varredura-locais.zip', 'Varredura por local de votação', 'Locais com pontuação e motivos, prioridade 2026 T2, histórico por seção, seções por eleição'),
                 ('ZIP', 'mapa-fiscalizacao-2026-t2.zip', 'Mapa de fiscalização 2026 T2', 'Locais, checklist por seção, zonas; PDF e Excel geral e por estado'),
                 ('ZIP', 'planilhas-varredura-por-uf.zip', 'Planilhas da varredura', 'VARREDURA_LOCAIS.xlsx e LOCAIS_<UF>.xlsx'),
                 ('CSV', 'dicionario-de-campos.csv', 'Dicionário de campos', 'Definição de cada coluna e critério')]
    if cfg.get('incluir_parquet'):
        for eid in ORDER_EIDS:
            f = FISC / f'secoes_indicadores_{eid}.parquet'
            if f.exists():
                shutil.copy2(f, dd / f'secoes-indicadores-{eid}.parquet')
                downloads.append(('PARQUET', f'secoes-indicadores-{eid}.parquet', f'Indicadores por seção · {LAB[eid]}', 'Uma linha por seção: BU, log, perfil, indicadores, lado A/B'))
    dl = []
    for tipo, f, titulo, desc in downloads:
        dl.append(f'<div><span class="file-type">{tipo}</span><div><h3>{esc(titulo)}</h3><p class="desc">{esc(desc)}</p></div><span class="size">{sz(dd / f)}</span><a href="dados/{f}" download aria-label="Baixar {esc(titulo)}">↧</a></div>')
    repo = cfg.get('repo_url') or ''
    repo_bloco = (f'<p class="repo-note">Código e reprodução: <a href="{repo}" target="_blank" rel="noopener">{repo}</a>. Os dados brutos (boletins, logs de urna, correspondências e perfil) são públicos no TSE e são baixados pelos scripts do repositório.</p>'
                  if repo else '<p class="repo-note">Código e reprodução: repositório em publicação; o link será incluído aqui.</p>')
    repo_link = f'<a href="{repo}" target="_blank" rel="noopener">Código ↗</a>' if repo else ''
    # --- logo leve
    logo = SITE / 'assets/logo.png'
    if logo.stat().st_size > 400 * 1024:
        im = Image.open(logo)
        im.thumbnail((256, 256))
        im.save(logo, optimize=True)
    # --- índice
    P26 = V.loc['P2026']
    html = (SITE / 'templates/index.template.html').read_text(encoding='utf-8')
    rep = {'__DATA_EDICAO__': edicao, '__GERADO_EM__': pd.Timestamp.today().strftime('%d/%m/%Y %H:%M'), '__COMMIT__': git_head(), '__N_UFS__': str(len(ufs)),
           '__N_SECOES_MIL__': f'{int(round(P26.secoes / 1000)):,}'.replace(',', '.'), '__N_LOCAIS__': f'{len(L):,}'.replace(',', '.'),
           '__OPCOES__': ''.join(f'<option value="{e}">{LAB[e]}</option>' for e in records), '__ESTADOS__': ' · '.join(ufs), '__GALERIA__': ''.join(gal), '__DOWNLOADS__': ''.join(dl),
           '__REPO_BLOCO__': repo_bloco, '__REPO_LINK__': repo_link, '__META_APOIO__': cfg['meta_apoio'], '__PIX_TITULAR__': esc(cfg['pix_titular']), '__CONTATO__': cfg['contato_email'],
           '__X_URL__': cfg['x_url'], '__INSTAGRAM_URL__': cfg['instagram_url'], '__PG_RESUMO__': f'{pg["RESUMO"]:02d}', '__PG_GRAFICOS__': f'{pg["GRAFICOS"]:02d}', '__PG_METODO__': f'{pg["METODO"]:02d}',
           '__PG_VARREDURA__': f'{pg["VARREDURA"]:02d}', '__PG_MAPA__': f'{pg["MAPA"]:02d}', '__PG_INCONS__': f'{pg["INCONS"]:02d}'}
    for k, v in rep.items():
        html = html.replace(k, v)
    assert '__' not in html.replace('__html', ''), 'placeholder não substituído'
    (SITE / 'index.html').write_text(html, encoding='utf-8')
    (SITE / '.nojekyll').write_text('', encoding='utf-8')
    total = sum(p.stat().st_size for p in SITE.rglob('*') if p.is_file())
    print('ok site', len(ufs), 'UFs; edição', edicao, '; figuras', len(gal), '; downloads', len(dl), f'; total {total / MB:.0f} MB')


if __name__ == '__main__':
    main()
