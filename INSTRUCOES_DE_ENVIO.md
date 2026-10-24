# Como enviar este projeto para uma IA programadora

## Rota recomendada (ferramenta com arquivos/projeto)

1. Anexe o arquivo ZIP `AUDITA_BR_PACOTE_ARQUITETURA_v1.zip` ou extraia a pasta do pacote em um repositório de trabalho.
2. Abra `PROMPT_MESTRE_CRIACAO.md`, copie todo o conteúdo e envie como primeira mensagem à ferramenta de desenvolvimento.
3. Instrua-a a ler e obedecer a todos os arquivos antes de implementar, **em especial** 02, 04, 05, 06, 07 e `db/schema.sql`.
4. Peça desenvolvimento **fase por fase**, começando pela Fase 0/1, com código real e testes.
5. Exija sempre que separe o que foi implementado/testado do que ainda depende de baixar arquivos oficiais do TSE.

## Rota alternativa (ferramenta aceita apenas texto)

Anexe/cole `DOCUMENTACAO_COMPLETA.md` se couber no limite de contexto, ou compartilhe `PROMPT_MESTRE_CRIACAO.md` primeiro e em seguida os documentos numerados como contexto. Em ferramenta com limite curto de contexto, solicite fasear a leitura; evite remover as regras de fuso, biometria, Senado e confiabilidade.

## O que conferir na primeira entrega

O desenvolvedor deve devolver uma estrutura de diretórios, contrato de eleicões/cargos, schema DuckDB executado, cliente CKAN real, testes automatizados com resultados e estado exato das fontes acessadas. O painel completo não deve ser a primeira entrega.

## Como usar o auxiliar incluído

```bash
python scripts/inventariar_ckan.py --year 2022 --out catalogo_2022.json
python scripts/inventariar_ckan.py --query 'resultados 2026' --out catalogo_resultados_2026.json
python -m unittest discover -s tests -p 'test_*.py' -v
```

Os comandos do inventário exigem acesso à internet no computador em que forem executados. O arquivo fornecido serve somente para **inventariar metadados**, não para fazer o download dos dados eleitorais nem implementar o sistema inteiro.

## Regras finais

- Compartilhar a arquitetura não equivale a autorização para copiar código de outro repositório sem licença verificada.
- Não divulgar dados oficiais como coletados antes de baixar e validar os arquivos.
- Não retirar ressalvas metodológicas para tornar indicadores 'mais fortes'.
- A especificação foi preparada no marco temporal de 12/10/2026; a IA deve verificar disponibilidade e regras no momento de codificar e registrar atualizações.
