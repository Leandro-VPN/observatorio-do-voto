"""Registro de achados, esqueletos de dossiê e lista de dados externos da varredura forense.

Entrada: os resultados estruturados dos agentes da varredura (research/varredura_forense/resultados/*.json, um por camada, com as
chaves 'camada', 'checagens' e 'achados') e os mapas por camada (research/varredura_forense/mapa/mapa_C*.json, chave 'lacunas_de_dados').
Saída (relatorios/verificacoes/varredura_forense/): registro_de_achados.csv/.parquet (um achado por linha, id A-<camada>-<nnn>),
checagens_feitas.csv (status de cada checagem por camada), dados_externos_necessarios.csv e dossies/<id>.md (esqueleto preenchido com
o que o agente apurou; os itens 2-5 e o status final são fechados na fase de dossiês).
Como repetir: python scripts/varredura_forense_registro.py
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'research' / 'varredura_forense' / 'resultados'
MAPA = ROOT / 'research' / 'varredura_forense' / 'mapa'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'varredura_forense'
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)
STATUS = {'EXPLICADO', 'ARTEFATO', 'PLAUSIVEL-EXPLICAVEL', 'INEXPLICADO', 'NAO_TESTAVEL'}
CAMADAS = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8']
RODAPE = 'Sinalização não é acusação. Este dossiê é descritivo e não indica irregularidade por si só.'


def normaliza_status(s):
    """Mapeia variantes ('PLAUSÍVEL-EXPLICÁVEL', 'não testável', ...) para o conjunto fixo do protocolo."""
    t = (s or '').strip().upper().replace('Í', 'I').replace('Á', 'A').replace('Ã', 'A').replace('Ç', 'C').replace(' ', '_')
    if t.startswith('NAO_TEST') or 'TESTAVEL' in t and t.startswith('NAO'):
        return 'NAO_TESTAVEL'
    if t.startswith('PLAUS'):
        return 'PLAUSIVEL-EXPLICAVEL'
    if t.startswith('INEXPL'):
        return 'INEXPLICADO'
    if t.startswith('EXPLIC'):
        return 'EXPLICADO'
    if t.startswith('ARTEF'):
        return 'ARTEFATO'
    return 'INDETERMINADO'


def carrega_resultados(pasta=None):
    """Lista de dicts (um por arquivo), ordenada por camada; aceita vários arquivos da mesma camada (C5A, C5B)."""
    out = []
    for p in sorted(Path(pasta or RES).glob('*.json')):
        d = json.loads(p.read_text(encoding='utf-8'))
        if isinstance(d, dict) and 'camada' in d:
            d['_arquivo'] = p.name
            out.append(d)
    return sorted(out, key=lambda d: (str(d['camada'])[:2], d['_arquivo']))


def monta_registro(resultados, hoje=None):
    """DataFrame do registro: um achado por linha, ids A-<camada>-<nnn> por ordem de prioridade e de chegada dentro da camada."""
    hoje = hoje or date.today().isoformat()
    linhas = []
    for r in resultados:
        cam = str(r['camada'])[:2]
        for a in r.get('achados', []):
            linhas.append(dict(
                camada=cam, titulo=a.get('titulo', ''), pleito=a.get('pleito', ''), cargo=a.get('cargo', ''), uf=a.get('uf', ''),
                escopo=a.get('escopo', ''), tipo=a.get('tipo', ''), efeito=a.get('efeito', ''), efeito_num=a.get('efeito_num'),
                materialidade_min=a.get('materialidade_min'), materialidade_max=a.get('materialidade_max'),
                margem_referencia=a.get('margem_referencia', ''), status=normaliza_status(a.get('status_sugerido')),
                status_sugerido=a.get('status_sugerido', ''), exploratorio=True, artefato_excluido=a.get('artefato_excluido', ''),
                controles=a.get('controles', ''), hipoteses=' | '.join(a.get('hipoteses', []) or []),
                dados_externos=a.get('dados_externos', ''), fonte=' | '.join(a.get('fonte', []) or []),
                prioridade=int(a.get('prioridade') or 3), id_sugerido=a.get('id_sugerido', ''), origem=r['_arquivo'],
                altera_publicado=False, errata='', data=hoje))
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    df = df.sort_values(['camada', 'prioridade', 'origem']).reset_index(drop=True)
    df.insert(0, 'id', [f'A-{c}-{i + 1:03d}' for c, i in zip(df.camada, df.groupby('camada').cumcount())])
    df.insert(1, 'dossie', ['dossies/' + i + '.md' for i in df.id])
    return df


def monta_checagens(resultados):
    linhas = []
    for r in resultados:
        for c in r.get('checagens', []):
            linhas.append(dict(camada=str(r['camada'])[:2], id=c.get('id', ''), status=c.get('status', ''),
                               resultado=c.get('resultado_resumo', ''), numeros=c.get('numeros_chave', ''),
                               arquivos=' | '.join(c.get('arquivos', []) or []), motivo=c.get('motivo', ''), origem=r['_arquivo']))
    return pd.DataFrame(linhas)


def dados_externos(mapas, registro):
    """Lista única de dados externos: lacunas dos mapas por camada + o que cada achado diz que resolveria o caso."""
    linhas = []
    for cam, m in mapas.items():
        for g in m.get('lacunas_de_dados', []):
            linhas.append(dict(camada=cam, dado=g.get('dado', ''), para_que=g.get('para_que', ''),
                               fonte_possivel=g.get('fonte_possivel', ''), achados=''))
    if registro is not None and not registro.empty:
        for _, a in registro.iterrows():
            if str(a.dados_externos).strip():
                linhas.append(dict(camada=a.camada, dado=a.dados_externos, para_que=f'fechar {a.id}: {a.titulo}',
                                   fonte_possivel='', achados=a.id))
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    df['chave'] = df.dado.str.lower().str.replace(r'\W+', ' ', regex=True).str.strip().str[:80]
    agg = df.groupby('chave', sort=False).agg(camadas=('camada', lambda s: ','.join(sorted(set(s)))), dado=('dado', 'first'),
                                              para_que=('para_que', lambda s: ' | '.join(x for x in dict.fromkeys(s) if x)),
                                              fonte_possivel=('fonte_possivel', lambda s: ' | '.join(x for x in dict.fromkeys(s) if x)),
                                              achados=('achados', lambda s: ','.join(x for x in dict.fromkeys(s) if x))).reset_index(drop=True)
    return agg


def texto_dossie(a):
    """Esqueleto do dossiê (markdown) preenchido com o que o agente apurou; marcações {…} ficam para a fase de dossiês."""
    def v(x, vazio='{a preencher}'):
        s = '' if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)
        return s if s.strip() else vazio
    mat = f"mínimo {v(a.materialidade_min, '?')} / máximo {v(a.materialidade_max, '?')} votos"
    fontes = '\n'.join(f'- `{f.strip()}`' for f in str(a.fonte).split('|') if f.strip()) or '- {a preencher}'
    hips = [h.strip() for h in str(a.hipoteses).split('|') if h.strip()] or ['{H1}', '{H2}']
    tab_h = '\n'.join(f'| {h} | {{previsão observável}} | {{o que os dados mostram}} |' for h in hips)
    return f"""# Dossiê {a.id} — {a.titulo}

| Campo | Valor |
|---|---|
| Camada | {a.camada} |
| Pleito / cargo | {v(a.pleito)} / {v(a.cargo, '-')} |
| UF / escopo | {v(a.uf, '-')} / {v(a.escopo)} |
| Tipo | {v(a.tipo)} |
| Status (provisório, sugerido pela varredura) | {a.status} |
| Exploratório ou confirmatório | exploratório |
| Altera algo publicado? | {{não / sim → errata}} |
| Prioridade | {a.prioridade} |

{RODAPE}

## 0. Efeito observado
{v(a.efeito)}

## 1. Reprodução a partir do dado bruto
Arquivos com os números (ver também os CSVs da camada):
{fontes}
- Consulta/comando que reproduz: {{comando ou SQL}}
- Hash SHA-256 dos arquivos de origem: {{a preencher na fase de dossiês}}

## 2. Exclusão de artefato
O que a varredura já verificou: {v(a.artefato_excluido, 'nada registrado ainda')}

| Hipótese de artefato | Teste | Resultado |
|---|---|---|
| Parser / decodificação | {{}} | {{}} |
| Formato / mudança de layout entre anos | {{}} | {{}} |
| Fuso / relógio da urna | {{}} | {{}} |
| Quarentena (aptos ≠ presentes + ausentes) | {{}} | {{}} |
| Vínculo de seção entre pleitos | {{}} | {{}} |
| Duplicata / pacote aninhado / arquivo de outra seção | {{}} | {{}} |

## 3. Delimitação
{v(a.escopo)} — pleito {v(a.pleito)}, UF {v(a.uf, 'várias')}. Atributo técnico (modelo/série/versão/TRE/carga): {{a preencher}}

## 4. Hipóteses concorrentes
| Hipótese | Previsão observável distinta | O que os dados mostram |
|---|---|---|
{tab_h}

## 5. Controles
{v(a.controles, '{vizinhas do prédio, outros cargos, outras UFs, outros pleitos, placebo}')}

## 6. Materialidade
{mat}; margem de referência: {v(a.margem_referencia)}.

## 7. O que resolveria o caso e não está nos dados
{v(a.dados_externos, '{a preencher}')}

## 8. Status e errata
Status provisório: {a.status} (sugerido: {v(a.status_sugerido)}). Fechamento na fase de dossiês, depois dos itens 2–5.
Errata: {{não se aplica / texto}}.

Gerado por scripts/varredura_forense_registro.py em {a.data} a partir de {a.origem} (id sugerido pelo agente: {v(a.id_sugerido, '-')}).
"""


def escreve_dossies(registro, pasta):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    for _, a in registro.iterrows():
        (pasta / f'{a.id}.md').write_text(texto_dossie(a), encoding='utf-8')
    return len(registro)


def main():
    resultados = carrega_resultados()
    if not resultados:
        print('nenhum resultado em', RES)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    reg = monta_registro(resultados)
    chk = monta_checagens(resultados)
    mapas = {p.stem.replace('mapa_', ''): json.loads(p.read_text(encoding='utf-8')) for p in sorted(MAPA.glob('mapa_C*.json'))}
    ext = dados_externos(mapas, reg)
    reg.to_csv(OUT / 'registro_de_achados.csv', **CSV)
    reg.to_parquet(OUT / 'registro_de_achados.parquet', index=False)
    chk.to_csv(OUT / 'checagens_feitas.csv', **CSV)
    ext.to_csv(OUT / 'dados_externos_necessarios.csv', **CSV)
    n = escreve_dossies(reg, OUT / 'dossies')
    print(f'registro: {len(reg)} achados ({reg.status.value_counts().to_dict() if len(reg) else {}}); checagens: {len(chk)} '
          f'({chk.status.value_counts().to_dict() if len(chk) else {}}); dados externos: {len(ext)}; dossiês: {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
