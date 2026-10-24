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
    """SHA curto do commit atual: git do PATH, com o caminho padrão do Windows como alternativa; 'n/d' sem git ou com erro."""
    import shutil
    exe = shutil.which('git') or ('C:/Program Files/Git/cmd/git.exe' if Path('C:/Program Files/Git/cmd/git.exe').exists() else None)
    if not exe:
        return 'n/d'
    try:
        r = subprocess.run([exe, 'log', '--format=%h', '-1'], capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else 'n/d'
    except Exception:
        return 'n/d'


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


REQUIRED = [VAR / 'resumo_por_eleicao.csv', VAR / 'comparacao_por_nivel.csv', VAR / 'pres_x_pref_pareado.csv', VAR / 'pres_x_pref_mesmas_secoes.csv', VAR / 'recorrencia_condicional.csv', VAR / 'locais_risco.csv',
            VAR / 'prioridade_locais_2026_T2.csv', VAR / 'secoes_historico.csv', VAR / 'secoes_com_comportamento_por_eleicao.csv', VAR / 'zonas.csv', VAR / 'cidades.csv', VAR / 'VARREDURA_LOCAIS_RISCO.pdf',
            DOC / 'RESUMO_SIMPLES.pdf', DOC / 'GRAFICOS.pdf', DOC / 'METODO_E_DADOS.pdf', DOC / 'figuras/legendas.json', MAPA / 'resumo_por_uf.csv', MAPA / 'locais_todos.csv', MAPA / 'secoes_checklist_todas.csv',
            MAPA / 'zonas_todas.csv', MAPA / 'MAPA_FISCALIZACAO_2026T2_GERAL.pdf', FISC / 'resumo_indicadores.csv', FISC / 'testes_permutacao.csv', FISC / 'INCONSISTENCIAS_E_FISCALIZACAO.pdf',
            SITE / 'templates/index.template.html', SITE / 'templates/app.template.js', SITE / 'site_config.json']


def preflight():
    """Antes de tocar em qualquer saída: lista tudo o que falta e explica como restaurar."""
    missing = [str(p) for p in REQUIRED if not p.exists()]
    if missing:
        raise SystemExit('Entradas ausentes para montar o site:\n  ' + '\n  '.join(missing) +
                         '\nRestaure a edição publicada com: python scripts/restore_edicao.py --tag <dados-AAAA-MM-DD> [--parquet]\n'
                         'ou rode a cadeia de análise (make_fiscalizacao_study.py → make_varredura_locais.py → make_mapa_fiscalizacao_2026t2.py → make_documentos_metodo.py).')


def edition():
    """Data e código da edição a partir do manifesto escrito pela varredura (não do mtime de arquivos)."""
    m = VAR / 'edicao.json'
    if m.exists():
        ed = json.loads(m.read_text(encoding='utf-8'))
        return pd.Timestamp(ed['edicao']).strftime('%d/%m/%Y'), (ed.get('codigo_sha') or 'n/d')[:7], ed
    return pd.Timestamp((VAR / 'resumo_por_eleicao.csv').stat().st_mtime, unit='s').strftime('%d/%m/%Y'), 'n/d', {}


# --- dicionário de dados por arquivo/coluna --------------------------------------------------------------------------------
DESC = {
    'uf': 'Sigla da UF.', 'municipality': 'Código TSE do município (não é IBGE).', 'municipality_name': 'Nome do município (TSE).', 'zone': 'Zona eleitoral.', 'section': 'Número da seção.',
    'voting_place': 'Código do local de votação (único dentro do município).', 'place_name': 'Nome do local de votação (perfil do eleitorado 2022; vazio quando não cadastrado).',
    'eid': 'Identificador da eleição: P2022, P2022b, M2024, M2024b, P2026.', 'eleicao': 'Rótulo da eleição.', 'lab': 'Rótulo da eleição.', 'eligible': 'Eleitores aptos na seção (BU).', 'attendance': 'Comparecimento (BU).',
    'valid_votes': 'Votos válidos nominais da disputa (BU).', 'turnout': 'Comparecimento ÷ aptos.', 'manual_bu': 'Eleitores habilitados manualmente segundo o campo do BU.', 'opening_bu': 'Abertura da urna (BU).', 'closure_bu': 'Encerramento da urna (BU).',
    'vote_events': 'Votos computados no log da urna.', 'after_17_recorded': 'Votos computados após 17h (relógio da urna).', 'manual_sequence_votes': 'Votos com sequência completa de habilitação manual no log.',
    'after_17_manual_sequence': 'Votos com sequência manual após 17h.', 'manual_requests': 'Solicitações de dado pessoal para habilitação manual.', 'cancellations': 'Habilitações canceladas/suspensas pelo mesário.',
    'late_interval_median_seconds': 'Mediana dos intervalos entre votos após 17h (s).', 'last_vote': 'Horário do último voto computado.', 'first_vote': 'Horário do primeiro voto.', 'clock_reversals': 'Reversões de relógio detectadas no log.',
    'votes_a': 'Votos do lado A (PT / líder do município).', 'votes_b': 'Votos do lado B (PL / 2º colocado).', 'cand_a': 'Definição do lado A nesta eleição.', 'cand_b': 'Definição do lado B.', 'share_a': '% do lado A nos votos válidos.',
    'share_b': '% do lado B nos votos válidos.', 'diff_ab': 'share_a − share_b (p.p.).', 'swap': 'Troca de urna (CEFT: urna esperada ≠ efetivada).', 'red': 'Origem do voto RED (recuperação de dados) no CEFT.', 'contingency': 'Log de urna de contingência/recarregada (identidade pelo nome do arquivo).',
    'has_log': 'Há log vinculado à seção.', 'log_complete': 'Votos no log = comparecimento do BU.', 'late_share': 'after_17_recorded ÷ vote_events.', 'manual_share': 'manual_sequence_votes ÷ vote_events.', 'manual_resid': 'Resíduo da habilitação manual frente ao esperado (regressão por UF).',
    'f_late': 'Indicador: votos após 17h > P99 do estado e ≥20.', 'f_manual': 'Indicador: resíduo manual > P99.', 'f_manual_late': 'Indicador: ≥10 manuais após 17h.', 'f_fast': 'Indicador: mediana <40 s entre votos tardios (≥20).', 'f_last19': 'Indicador: último voto ≥19h.',
    'f_turnout': 'Indicador: comparecimento z>3 e ≥10 p.p. acima da mediana municipal.', 'f_close': 'Indicador: encerramento >60 min após 17h sem troca.', 'f_cancel': 'Indicador: cancelamentos > P99 e ≥5.', 'score': 'Soma dos 8 indicadores.',
    'LATE': 'Comportamento TARDIO = f_late ou f_last19 ou f_close.', 'MANUAL': 'Comportamento MANUAL = f_manual ou f_manual_late.', 'BEH': 'Comportamento = LATE ou MANUAL.', 'place': 'Chave do local (uf|município|zona|local).', 'mun': 'Chave do município (uf|município).',
    'cmp_level': 'Nível de comparação: local (≥3 pares), local (poucos pares), município.', 'origem_municipio': 'No nível município: seção única ou prédio sem par comum.', 'cmp_n': 'Número de pares usados.', 'cmp_a': '% do lado A nos pares (ponderado).', 'cmp_b': '% do lado B nos pares.',
    'diff_a': 'share_a − cmp_a (p.p.).', 'z_a': 'diff_a ÷ raiz(variância dos pares + erro binomial).', 'real': 'Diferença acima do limiar (|diff_a|≥5 e |z|≥2). Nome herdado.', 'dir': 'Lado favorecido quando real: A ou B.', 'big': '|diff_a| ≥ 10 p.p.',
    'excesso_alem_tardios': 'Excesso de votos A maior do que todos os votos após 17h poderiam explicar.', 'diff_turnout': 'Comparecimento − comparecimento dos pares (p.p.).', 'winner_ab': 'Lado vencedor na seção.', 'cmp_winner': 'Lado vencedor nos pares.',
    'excess_a_votes': 'diff_a/100 × votos válidos (ordem de grandeza).', 'local_inteiro': '≥50% das seções do local com comportamento.', 'diff_local_mun': '% A do local inteiro − % A das seções comuns do município.', 'z_local_mun': 'z da diferença do local inteiro frente ao município.',
    'pontos': 'Pontuação transparente 0–100 do local.', 'pts_operacional': 'Pontos operacionais (recorrência, volume, comportamento 2026, local inteiro sem desvio).', 'pts_resultado': 'Pontos de resultado (desvios acima do limiar, direção, local inteiro com |z|≥2).',
    'sinal_resultado': 'nenhum / só local (vs município) / seções / seções + local.', 'prioridade_observacao': 'alta ≥45; média 25–44; baixa <25. Ordem de observação, não probabilidade.', 'nivel_risco': 'Nome anterior de prioridade_observacao.', 'prioridade': 'Igual a prioridade_observacao.',
    'secoes_max': 'Maior número de seções do local entre as eleições.', 'secoes_com_comportamento': 'Seções do local com comportamento em alguma eleição.', 'recorrentes_2plus': 'Seções com comportamento em 2+ eleições.', 'recorrentes_3plus': 'Seções com comportamento em 3+ eleições.',
    'secoes_dif_real_pres': 'Seções com comportamento e diferença acima do limiar em alguma presidencial.', 'secoes_dif_real_pres_local': 'Idem, só no nível local.', 'secoes_dif_real_pref': 'Idem, nas eleições de prefeito.', 'direcao': 'Direção das diferenças nas presidenciais: sempre A / sempre B / mista.',
    'favor_A': 'Diferenças acima do limiar a favor de A (presidenciais).', 'favor_B': 'Idem a favor de B.', 'pref_favor_lider': 'Diferenças a favor do líder (prefeito).', 'pref_favor_segundo': 'Diferenças a favor do 2º (prefeito).', 'so_presidenciais': 'Seções com comportamento só nas presidenciais.',
    'pres_e_municipais': 'Seções com comportamento nos dois tipos.', 'so_municipais': 'Seções com comportamento só nas municipais.', 'desvio_so_pres': 'Seções com desvio acima do limiar só nas presidenciais.', 'dif_media_pres': 'Média de diff_a nas presidenciais com comportamento (p.p.).',
    'votos_tardios_total': 'Soma de votos após 17h das seções com comportamento, todas as eleições.', 'manuais_apos_17h_total': 'Soma de manuais após 17h.', 'secoes_a_checar': 'Seções com comportamento em 2026 T1 ou recorrentes.', 'n_eleicoes_comportamento': 'Nº de eleições (de 5) com comportamento.',
    'padrao_comportamento': 'Em que tipo de eleição o comportamento aparece.', 'padrao_desvio_resultado': 'Em que tipo de eleição a diferença acima do limiar aparece.', 'grupo': 'com comportamento / comuns.', 'nivel': 'Nível de comparação.', 'n': 'Seções no grupo/nível.', 'pct_real': '% com diferença acima do limiar.', 'pct_A': '% das diferenças a favor de A.',
    'recorte': 'todas / local (≥3 pares).', 'presentes': 'Seções presentes nas três eleições.', 'com_comportamento': 'Seções com comportamento.', 'p_mcnemar': 'p do teste de McNemar (binomial exato).', 'or_mantel_haenszel': 'Razão de chances de Mantel–Haenszel por nível.',
    'within_place_diff': 'Diferença (A−B) sinalizadas − demais, desvio da média ponderada do local (p.p.).', 'null_sd': 'Desvio-padrão do nulo (embaralhamento no município).', 'null_q025': 'Percentil 2,5 do nulo.', 'null_q975': 'Percentil 97,5 do nulo.', 'p_perm': 'p bilateral por permutação (município).',
    'p_perm_local': 'p por permutação dentro do local.', 'q': 'q de Benjamini–Hochberg (município).', 'q_local': 'q (local).', 'flag': 'Indicador testado.', 'n_flag': 'Seções sinalizadas.', 'raw_diff': 'Diferença bruta A−B (p.p.).', 'excess_votes_a': 'Excesso de votos A nas sinalizadas (média ponderada do local).',
    'fiscais_sugeridos': '1 por local de prioridade alta + 1 a cada 2 de média, arredondado para cima por zona.', 'motivos': 'Resumo textual dos sinais da seção.', 'o_que_observar': 'Orientação ao fiscal.', 'comportamento_2026_T1': 'tardia / manual / tardia+manual / não (recorrente).',
}


def describe(col):
    if col in DESC:
        return DESC[col]
    for pre, txt in (('BEH_', 'Comportamento na eleição '), ('LATE_', 'TARDIO na eleição '), ('MANUAL_', 'MANUAL na eleição '), ('dif_', 'diff_a na eleição '), ('z_', 'z na eleição '), ('real_', 'Acima do limiar na eleição '), ('dir_', 'Lado favorecido na eleição '),
                      ('big_', '|dif|≥10 na eleição '), ('dif_comp_', 'Comparecimento − pares na eleição '), ('tardios_', 'Votos após 17h na eleição '), ('manuais17_', 'Manuais após 17h na eleição '), ('venc_cmp_', 'Vencedor nos pares na eleição '), ('venc_', 'Vencedor na seção na eleição '),
                      ('cmp_', 'Nível de comparação na eleição '), ('A_', '% do lado A na eleição '), ('pts_', 'Pontos do componente '), ('secoes_', 'Seções na eleição '), ('comp_', 'Seções com comportamento na eleição '), ('real_local_', 'Acima do limiar no nível local na eleição '),
                      ('realA_', 'Acima do limiar favor A na eleição '), ('realB_', 'Acima do limiar favor B na eleição '), ('inteiro_', 'Local inteiro na eleição '), ('local_', 'Nível local: '), ('comuns_', 'Seções comuns: ')):
        if col.startswith(pre):
            return txt + col[len(pre):]
    return ''


def dicionario(dd):
    """Esquema por arquivo: coluna, tipo, % de nulos, exemplo, descrição. Lê os arquivos publicados (CSVs) e o esquema de um parquet."""
    rows = []

    def add(nome, df):
        for c in df.columns:
            s = df[c]
            ex = s.dropna().iloc[0] if s.notna().any() else ''
            rows.append(dict(arquivo=nome, coluna=c, tipo=str(s.dtype), nulos_pct=round(100 * s.isna().mean(), 1), exemplo=str(ex)[:40], descricao=describe(c)))
    for f in ['resumo_por_eleicao.csv', 'comparacao_por_nivel.csv', 'pres_x_pref_pareado.csv', 'pres_x_pref_mesmas_secoes.csv', 'recorrencia_condicional.csv', 'locais_risco.csv', 'prioridade_locais_2026_T2.csv', 'zonas.csv', 'cidades.csv',
              'secoes_historico.csv', 'secoes_com_comportamento_por_eleicao.csv']:
        add(f'varredura-locais.zip/{f}', pd.read_csv(VAR / f, low_memory=False, **CSV))
    for f in ['locais_todos.csv', 'secoes_checklist_todas.csv', 'zonas_todas.csv', 'resumo_por_uf.csv']:
        add(f'mapa-fiscalizacao-2026-t2.zip/{f}', pd.read_csv(MAPA / f, low_memory=False, **CSV))
    for f in ['resumo_indicadores.csv', 'testes_permutacao.csv']:
        add(f, pd.read_csv(FISC / f, **CSV))
    pq = FISC / 'secoes_indicadores_P2026.parquet'
    if pq.exists():
        add('secoes_indicadores_<eid>.parquet', pd.read_parquet(pq).head(2000))
    D = pd.DataFrame(rows)
    D.to_csv(dd / 'dicionario-de-campos.csv', index=False, **CSV, encoding='utf-8-sig')
    return D


COMO_USAR = """# Como usar os dados

Todos os CSV usam separador `;` e decimal `,` (abra com `pd.read_csv(f, sep=';', decimal=',', low_memory=False)` ou, no Excel, importação com ponto e vírgula).
Os parquet têm uma linha por seção e eleição; chave: `uf`, `municipality` (código TSE), `zone`, `section`. Códigos de município são do TSE, não do IBGE.

## Abrir um parquet com DuckDB (sem servidor)

```sql
INSTALL httpfs; LOAD httpfs;
CREATE VIEW p26 AS SELECT * FROM read_parquet('secoes_indicadores_P2026.parquet');
-- seções com comportamento e diferença acima do limiar, no mesmo prédio
SELECT uf, municipality_name, zone, section, share_a, cmp_a, diff_a, z_a, after_17_recorded
FROM p26 WHERE (f_late OR f_last19 OR f_close OR f_manual OR f_manual_late) AND eligible >= 50
ORDER BY uf, municipality, zone, section;
```
As colunas de comparação (`cmp_level`, `diff_a`, `z_a`, `real`) estão em `secoes_com_comportamento_por_eleicao.csv` (só seções com comportamento); para recalculá-las para todas as seções, use `scripts/make_varredura_locais.py` (funções `load` e `compare`).

## Juntar sem duplicar comparecimento

Comparecimento é por seção/turno (uma linha); votos por candidato estão em outra tabela. Agregue antes de juntar:

```sql
SELECT l.uf, l.municipality_name, l.zone, l.voting_place, l.pontos, l.prioridade_observacao,
       s.secoes, s.aptos
FROM read_csv('locais_risco.csv', delim=';', decimal_separator=',', header=true) l
JOIN (SELECT uf, municipality, zone, voting_place, count(*) secoes, sum(eligible) aptos FROM p26 GROUP BY ALL) s
  USING (uf, municipality, zone, voting_place)
ORDER BY l.pontos DESC LIMIT 50;
```

## Dicionário

`dicionario-de-campos.csv`: arquivo, coluna, tipo, % de nulos, exemplo e descrição. `manifesto-release.json`: SHA-256 de cada pacote, parâmetros e código produtor da edição.
Sinalização não é acusação: os indicadores medem desvio operacional e de resultado frente às seções vizinhas; não observam compra de voto nem em quem votaram os eleitores tardios.
"""



def search_index(dd, L):
    """Índice de busca por UF: um JSON compacto por estado com os locais com comportamento (para a busca no navegador, sem servidor)."""
    out = dd / 'locais'
    out.mkdir(exist_ok=True)
    cols = ['municipality_name', 'zone', 'voting_place', 'place_name', 'prioridade_observacao', 'pontos', 'sinal_resultado', 'secoes_com_comportamento', 'recorrentes_2plus', 'secoes_dif_real_pres', 'direcao', 'secoes_a_checar']
    for uf, g in L.groupby('uf'):
        g = g[cols].fillna('').sort_values('pontos', ascending=False)
        recs = [[str(r.municipality_name), int(r.zone), str(r.voting_place), str(r.place_name), str(r.prioridade_observacao), int(r.pontos), str(r.sinal_resultado), int(r.secoes_com_comportamento), int(r.recorrentes_2plus),
                 int(r.secoes_dif_real_pres), str(r.direcao), str(r.secoes_a_checar)] for r in g.itertuples()]
        (out / f'{uf}.json').write_text(json.dumps({'uf': uf, 'colunas': cols, 'locais': recs}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


def main():
    preflight()
    cfg = json.loads((SITE / 'site_config.json').read_text(encoding='utf-8-sig'))
    V = pd.read_csv(VAR / 'resumo_por_eleicao.csv', **CSV).set_index('eid')
    L = pd.read_csv(VAR / 'locais_risco.csv', low_memory=False, **CSV)
    ufs = [u for u in UF_ORDER if u in L.uf.unique()]
    edicao, codigo, ed = edition()
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
        gal.append(f'<figure id="fig-{i}"><button type="button" class="zoom-btn" aria-label="Ampliar gráfico {i}: {esc(titulo)}" data-fig="{i}"><img src="assets/figuras/{it["arquivo"]}" alt="Gráfico {i}: {esc(titulo)}" loading="lazy"></button>'
                   f'<figcaption><b>Gráfico {i} · {esc(titulo)}</b>{esc(it["legenda"])} <a href="documentos/GRAFICOS.pdf#page={i}" target="_blank" rel="noopener">Ver no caderno (PDF) ↗</a></figcaption></figure>')
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
        if old.is_file() and old.name != 'manifesto-release.json':
            old.unlink()
    shutil.copy2(VAR / 'resumo_por_eleicao.csv', dd / 'resumo-por-eleicao.csv')
    if (VAR / 'edicao.json').exists():
        shutil.copy2(VAR / 'edicao.json', dd / 'edicao.json')
    (dd / 'COMO-USAR.md').write_text(COMO_USAR, encoding='utf-8')
    search_index(dd, L)
    for f in ['comparacao_por_nivel.csv', 'pres_x_pref_pareado.csv', 'pres_x_pref_mesmas_secoes.csv', 'recorrencia_condicional.csv']:
        shutil.copy2(VAR / f, dd / f.replace('_', '-'))
    for f in ['resumo_indicadores.csv', 'testes_permutacao.csv']:
        shutil.copy2(FISC / f, dd / f.replace('_', '-'))

    pac = SITE / 'pacotes'   # pacotes grandes: gerados aqui, publicados como GitHub Release (publish_release.py), fora do git e do site
    pac.mkdir(exist_ok=True)

    def zipf(name, files):
        """Monta o pacote só quando todas as fontes existem (numa restauração a partir da release os pacotes já estão publicados; o site aponta para eles)."""
        files = [Path(f) for f in files]
        missing = [str(f) for f in files if not f.exists()]
        if missing:
            print(f'pacote {name} não montado (fontes ausentes: {len(missing)}); o site usa o da release', flush=True)
            return
        with zipfile.ZipFile(pac / name, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in files:
                z.write(f, f.name)
    zipf('varredura-locais.zip', [VAR / f for f in ['locais_risco.csv', 'prioridade_locais_2026_T2.csv', 'zonas.csv', 'cidades.csv', 'secoes_historico.csv', 'secoes_com_comportamento_por_eleicao.csv', 'padroes_pres_x_pref_por_uf.csv',
                                                    'resumo_por_eleicao.csv', 'comparacao_por_nivel.csv', 'pres_x_pref_pareado.csv', 'pres_x_pref_mesmas_secoes.csv', 'recorrencia_condicional.csv']])
    zipf('mapa-fiscalizacao-2026-t2.zip', [MAPA / f for f in ['locais_todos.csv', 'secoes_checklist_todas.csv', 'zonas_todas.csv', 'resumo_por_uf.csv', 'MAPA_FISCALIZACAO_2026T2_GERAL.pdf', 'MAPA_FISCALIZACAO_2026T2_GERAL.xlsx']]
         + sorted(MAPA.glob('MAPA_FISCALIZACAO_2026T2_??.pdf')) + sorted(MAPA.glob('MAPA_FISCALIZACAO_2026T2_??.xlsx')))
    zipf('planilhas-varredura-por-uf.zip', [VAR / 'VARREDURA_LOCAIS.xlsx'] + sorted(VAR.glob('LOCAIS_??.xlsx')))
    man_rel = json.loads((dd / 'manifesto-release.json').read_text(encoding='utf-8')) if (dd / 'manifesto-release.json').exists() else {'ativos': {}}

    def size_of(name):
        """Tamanho exibido: arquivo local (pacote ou parquet) ou, na falta, o registrado no manifesto da release."""
        for p in (pac / name, FISC / name):
            if p.exists():
                return sz(p)
        b = man_rel['ativos'].get(name, {}).get('bytes')
        return (f'{b / MB:,.1f} MB'.replace(',', 'X').replace('.', ',').replace('X', '.') if b else '')
    # dicionário de campos por arquivo/coluna (esquema lido dos próprios dados) + glossário metodológico dos leia_me
    dicionario(dd)
    sys.path.insert(0, 'scripts')
    import os
    os.environ.setdefault('UF', 'BA')
    import make_mapa_fiscalizacao_2026t2 as MM
    import make_varredura_locais as MV
    pd.concat([MV.readme().assign(origem='varredura'), MM.readme().assign(origem='mapa_2026_T2')]).to_csv(dd / 'glossario-metodologico.csv', index=False, **CSV, encoding='utf-8-sig')
    repo = cfg.get('repo_url') or ''
    tag = cfg.get('release_tag') or ''
    rel_base = f'{repo}/releases/download/{tag}/' if repo and tag else ''
    # (tipo, arquivo, título, descrição, origem): 'site' = pequeno, fica em site/dados; 'release' = grande, link para a GitHub Release
    downloads = [('CSV', 'resumo-por-eleicao.csv', 'Resumo por eleição e turno', 'Indicadores agregados, por nível de comparação', 'site'),
                 ('CSV', 'comparacao-por-nivel.csv', 'Comparação por nível', 'Com comportamento × comuns, por eleição e nível (local / poucos pares / município)', 'site'),
                 ('CSV', 'pres-x-pref-pareado.csv', 'Prefeito × presidente, mesmas seções', 'Taxas com denominadores; e pres-x-pref-mesmas-secoes.csv (McNemar)', 'site'),
                 ('CSV', 'pres-x-pref-mesmas-secoes.csv', 'Prefeito × presidente, comparação estrita', 'Mesmas seções com comportamento nos dois cargos; teste de McNemar', 'site'),
                 ('CSV', 'recorrencia-condicional.csv', 'Recorrência condicional', 'Probabilidade de repetir o comportamento entre eleições, nas seções presentes em ambas', 'site'),
                 ('CSV', 'testes-permutacao.csv', 'Testes de direção por permutação', 'Dois esquemas de embaralhamento, quantis do nulo, p e q', 'site'),
                 ('CSV', 'resumo-indicadores.csv', 'Cobertura e indicadores por eleição', 'Seções, logs, votos após 17h, sequências manuais, contagens por indicador', 'site'),
                 ('CSV', 'dicionario-de-campos.csv', 'Dicionário de campos', 'Por arquivo e coluna: tipo, % de nulos, exemplo e descrição', 'site'),
                 ('CSV', 'glossario-metodologico.csv', 'Glossário metodológico', 'Definições de comportamento, comparação, limiar, pontuação e prioridade', 'site'),
                 ('MD', 'COMO-USAR.md', 'Como usar os dados', 'Formato dos arquivos e consultas DuckDB de exemplo, incluindo junção sem duplicar comparecimento', 'site'),
                 ('ZIP', 'varredura-locais.zip', 'Varredura por local de votação', 'Locais com pontuação e motivos, prioridade 2026 T2, histórico por seção, seções por eleição', 'release'),
                 ('ZIP', 'mapa-fiscalizacao-2026-t2.zip', 'Mapa de fiscalização 2026 T2', 'Locais, checklist por seção, zonas; PDF e Excel geral e por estado', 'release'),
                 ('ZIP', 'planilhas-varredura-por-uf.zip', 'Planilhas da varredura', 'VARREDURA_LOCAIS.xlsx e LOCAIS_<UF>.xlsx', 'release')]
    for eid in ORDER_EIDS:
        name = f'secoes_indicadores_{eid}.parquet'
        if (FISC / name).exists() or name in man_rel['ativos']:
            downloads.append(('PARQUET', name, f'Indicadores por seção · {LAB[eid]}', 'Uma linha por seção: BU, log, perfil, indicadores, lado A/B', 'release'))
    dl = []
    for tipo, f, titulo, desc, origem in downloads:
        if origem == 'site':
            dl.append(f'<div><span class="file-type">{tipo}</span><div><h3>{esc(titulo)}</h3><p class="desc">{esc(desc)}</p></div><span class="size">{sz(dd / f)}</span><a href="dados/{f}" download aria-label="Baixar {esc(titulo)}">↧</a></div>')
        else:
            size = size_of(f)
            if rel_base:
                dl.append(f'<div><span class="file-type">{tipo}</span><div><h3>{esc(titulo)}</h3><p class="desc">{esc(desc)} · GitHub Release {esc(tag)}</p></div><span class="size">{size}</span><a href="{rel_base}{f}" aria-label="Baixar {esc(titulo)} (GitHub Release)">↧</a></div>')
            else:
                dl.append(f'<div><span class="file-type">{tipo}</span><div><h3>{esc(titulo)}</h3><p class="desc">{esc(desc)}</p></div><span class="size">{size}</span><span class="soon">EM PUBLICAÇÃO</span></div>')
    if rel_base:
        if (pac / 'edicao-editorial.zip').exists() or 'edicao-editorial.zip' in man_rel['ativos']:
            dl.append(f'<div><span class="file-type">ZIP</span><div><h3>Pacote editorial da edição</h3><p class="desc">Tudo o que o gerador do site lê (CSVs, PDFs, figuras); restaure com scripts/restore_edicao.py · GitHub Release {esc(tag)}</p></div><span class="size">{size_of("edicao-editorial.zip")}</span><a href="{rel_base}edicao-editorial.zip" aria-label="Baixar pacote editorial">↧</a></div>')
        if (dd / 'manifesto-release.json').exists():
            dl.append('<div><span class="file-type">JSON</span><div><h3>Manifesto da release</h3><p class="desc">SHA-256 de cada pacote, parâmetros, entradas e código produtor da edição</p></div>'
                      f'<span class="size">{sz(dd / "manifesto-release.json")}</span><a href="dados/manifesto-release.json" download aria-label="Baixar manifesto">↧</a></div>')
        dl.append(f'<div><span class="file-type">REL</span><div><h3>Todos os pacotes da edição</h3><p class="desc">Página da release no GitHub, com somas de verificação e notas</p></div><a href="{cfg.get("release_url") or repo + "/releases"}" target="_blank" rel="noopener" aria-label="Abrir a release no GitHub">↗</a></div>')
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
    rep = {'__DATA_EDICAO__': edicao, '__GERADO_EM__': pd.Timestamp.today().strftime('%d/%m/%Y %H:%M'), '__COMMIT__': codigo, '__COMMIT_SITE__': git_head(), '__N_UFS__': str(len(ufs)),
           '__N_SECOES_MIL__': f'{int(round(P26.secoes / 1000)):,}'.replace(',', '.'), '__N_LOCAIS__': f'{len(L):,}'.replace(',', '.'),
           '__OPCOES__': ''.join(f'<option value="{e}">{LAB[e]}</option>' for e in records), '__ESTADOS__': ' · '.join(ufs), '__ESTADOS_OPCOES__': ''.join(f'<option value="{u}">{u}</option>' for u in ufs),
           '__GALERIA__': ''.join(gal), '__DOWNLOADS__': ''.join(dl),
           '__REPO_BLOCO__': repo_bloco, '__REPO_LINK__': repo_link, '__META_APOIO__': cfg['meta_apoio'], '__PIX_TITULAR__': esc(cfg['pix_titular']), '__PIX_CHAVE__': esc(cfg['pix_chave']), '__CONTATO__': cfg['contato_email'],
           '__X_URL__': cfg['x_url'], '__INSTAGRAM_URL__': cfg['instagram_url'], '__PG_RESUMO__': f'{pg["RESUMO"]:02d}', '__PG_GRAFICOS__': f'{pg["GRAFICOS"]:02d}', '__PG_METODO__': f'{pg["METODO"]:02d}',
           '__PG_VARREDURA__': f'{pg["VARREDURA"]:02d}', '__PG_MAPA__': f'{pg["MAPA"]:02d}', '__PG_INCONS__': f'{pg["INCONS"]:02d}'}
    for k, v in rep.items():
        html = html.replace(k, v)
    assert '__' not in html.replace('__html', ''), 'placeholder não substituído'
    (SITE / 'index.html').write_text(html, encoding='utf-8')
    (SITE / '.nojekyll').write_text('', encoding='utf-8')
    total = sum(p.stat().st_size for p in SITE.rglob('*') if p.is_file() and 'pacotes' not in p.parts)
    print('ok site', len(ufs), 'UFs; edição', edicao, 'código', codigo, '; figuras', len(gal), '; downloads', len(dl), f'; total (sem pacotes) {total / MB:.0f} MB')


if __name__ == '__main__':
    main()
