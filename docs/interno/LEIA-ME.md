# Material interno

Arquivos de planejamento e de operação local, guardados como histórico. Nenhum deles é necessário para instalar, testar ou reproduzir as análises.

- `PROMPT_MESTRE_CRIACAO.md`, `PROMPT_MESTRE_UNIFICADO.md`, `INSTRUCOES_DE_ENVIO.md` e `AUDITA_BR_PACOTE_ARQUITETURA_v1.zip`: especificação original da base regional (escopo 3) e o pacote de arquitetura que a acompanhou.
- `AUDITA_BR/`: o mesmo pacote extraído (documentos numerados, configuração, esquema SQL e o teste do inventário CKAN, que continua listado em `pyproject.toml`). `DOCUMENTACAO_COMPLETA.md` concatena esses documentos num arquivo só.
- `iniciar.ps1` e `parar.ps1`: atalhos do Windows para subir e encerrar o painel e a API locais (`python -m auditabr serve`). Funcionam a partir desta pasta; a raiz do projeto fica dois níveis acima.
