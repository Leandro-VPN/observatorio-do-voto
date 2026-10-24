# Como usar os dados

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
