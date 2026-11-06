"""Passada única de logs da varredura forense: linha do tempo, cabeçalho técnico, taxonomia de habilitação,
intervalos entre votos, monotonicidade do relógio, erros/alertas e hash de cada logd.dat, para todas as urnas de
um pleito (checagens C3-04, C3-05, C3-10, C3-12, C3-16, C2-02, C6-05, C7-08 e C8-07 do mapa da varredura).

Leitura: cada pacote de log da seção (zip -log.jez em 2024/2026, 7z .logjez em 2022) com todos os logd.dat,
inclusive os aninhados (urnas anteriores quando houve troca; o log da urna original dentro do pacote da urna de
contingência). Identidade de um log = sua primeira linha; entre cópias fica a com mais votos no dia (depois a mais
longa), as outras ficam registradas com papel 'copia'; o log de urna de OUTRA seção embalado no mesmo pacote fica
com papel 'outra_secao' e não entra na soma da seção (mesma regra de auditabr.logs.section_logs, com a seção do
nome do arquivo como desempate quando o log externo declara mais de uma seção). Nada some em silêncio: todo
logd.dat vira uma linha, e todo pacote ilegível ou nome não reconhecido vira uma linha com status de quarentena.
Cada log é reduzido dentro do processo (a lista de instantes nunca volta). Cache por bloco de 500 pacotes em
research/varredura_forense/logs/<pleito>/part-<hash>.parquet (+ recibo .json; .tmp -> .parquet): retomável.
2 processos de prioridade baixa; pausa entre blocos se faltar RAM. Nunca lista pastas de logs recursivamente:
a pasta de uma UF é lida uma única vez com os.scandir (2026-t2 usa os caminhos já gravados em
relatorios/verificacoes/ultimo_voto_2026t2/ultimo_voto_por_secao.csv) e a lista fica em cache.

Uso: python scripts/varredura_forense_logs.py passada <pleito> [--ufs AC,AL] [--limite N] [--procs 2] [--min-livre-mb 700]
     python scripts/varredura_forense_logs.py consolida <pleito> [--ufs AC,AL]
     python scripts/varredura_forense_logs.py catalogo <pleito>
Pleitos: 2022-t1 2022-t2 2024-t1 2024-t2 2026-t1 2026-t2.
Saídas (research/varredura_forense/logs/): <pleito>/part-*.parquet (uma linha por logd.dat), <pleito>/msgs-*.parquet
(frequência das mensagens do dia), logs_<pleito>.parquet, secoes_<pleito>.parquet, catalogo_mensagens_<pleito>.csv
(consolida: frequência real + classe), catalogo_mensagens_<pleito>_exemplos.csv (catalogo: só os logs de exemplo),
resumo_<pleito>.json; quarentena em research/varredura_forense/quarentena/.
Sinalização não é acusação: tudo aqui é descritivo e não indica irregularidade por si só.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import date, datetime
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from baixa_pais import memoria_livre_mb, prioridade_baixa  # noqa: E402
from export_logs_exemplo import pasta_logs  # noqa: E402

from auditabr.logs import SECTION_LINE, VOTE_LINE, read_log_members, state_machine  # noqa: E402

PARSER_VERSION = 'varredura-logs-1.0.2'
WORK = ROOT / 'research' / 'varredura_forense' / 'logs'
QUAR = ROOT / 'research' / 'varredura_forense' / 'quarentena'
EXEMPLOS = ROOT / 'relatorios' / 'logs_exemplo'
ULTIMO_VOTO = ROOT / 'relatorios' / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv'
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')
CHAVE = ['uf', 'municipality', 'zone', 'section']
BLOCO = 500
PLEITOS = ('2022-t1', '2022-t2', '2024-t1', '2024-t2', '2026-t1', '2026-t2')
DIA = {'2022-t1': '02/10/2022', '2022-t2': '30/10/2022', '2024-t1': '06/10/2024', '2024-t2': '27/10/2024',
       '2026-t1': '04/10/2026', '2026-t2': '25/10/2026'}
# total de pacotes por pleito segundo o mapa (mapa_C3.json, C3-04), só para estimar o tempo total
TOTAL_MAPA = {'2026-t2': 499177, '2022-t2': 471983}
# nome do pacote publicado: o<pleito>-<mun5><zona4><sec4>.logjez (2022) ou o<pleito><uf><mun5><zona4><sec4>-log.jez (2024/2026)
NOME = re.compile(r'^o0*(?P<pl>\d+)(?:-|(?P<uf>[a-z]{2}))(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})(?:-log)?\.(?:jez|logjez)$',
                  re.IGNORECASE)
PAUSA_MIN = 15 * 60       # pausa entre votos computados: 15 min
RAPIDO_S = 30             # intervalo entre votos computados abaixo de 30 s
TARDE_17 = 17 * 3600      # hora local da urna
TARDE_19 = 19 * 3600


def _l(s):
    return s.encode('latin-1')


# ---------------------------------------------------------------- catálogo de mensagens (texto exato dos logs)
VOTO = _l('O voto do eleitor foi computado')
INICIO_ATEND = (_l('Identificador do eleitor digitado pelo mesário'), _l('Título digitado pelo mesário'))
HAB = _l('Eleitor foi habilitado')
BIO = _l('Tipo de habilitação do eleitor [biométrica]')
SEM_BIO = _l('O eleitor não possui biometria')                       # 2022 (ALERTA): eleitor sem biometria cadastrada
BIOGRAFICA = _l('Ano de nascimento digitado é igual ao do cadastro')  # 2024/2026: eleitor sem biometria, confirmado pelo ano
MANUAL = _l('Solicitação de dado pessoal do eleitor para habilitação manual')
MESARIO_HAB_FIM = _l(' habilitou o eleitor')
NAO_ASSOC = (_l('Digital coletada bate com uma digital gravada após o registro inicial de mesário. '
                'Não é possível associar a habilitação a um mesário.'),
             _l('Não encontrou digital coletada em nenhum dos arquivos, vai salvar a digital em novo arquivo.'))
CANCELA_PREFIXO = _l('Habilitação cancelada')
SUSPENSO = _l('Eleitor foi suspenso pelo mesário')
TENTATIVA = _l('Solicita digital. Tentativa [')
CORRIGIU = _l('Eleitor corrigiu na tela de confirmação de candidato')
VOTO_CARGO = _l('Voto confirmado para [')
NAO_REGISTRADO = _l('foi registrado')
ERRO_INESPERADO = _l('Erro inesperado durante a votação')
PRONTA = _l('Urna pronta para receber votos')
ZERESIMA_ESPERA = _l('Aguardando confirmação para emissão da zerésima')
ZERESIMA_GERA = _l('Gerando relatório [ZERÉSIMA] [INÍCIO]')
ENC_SELEC = _l('Operador selecionou: Encerrar votação')
ENC_CONF = _l('Procedimento de encerramento confirmado')
ENC_INICIO = _l('Inicio do Encerramento')
ENC_CANCEL = _l('Operador cancelou o encerramento da votação')
BU_RELATORIO = _l('Gerando relatório [BU] [INÍCIO]')
BU_IMPRIME = _l('Imprimindo relatório [BU]')
ARQ_RESULTADO = _l('Gerando arquivo de resultado [')
ASSINA_INICIO = _l('Início do procedimento de assinatura dos arquivos de resultados')
ASSINA_FIM = _l('Término do procedimento de assinatura dos arquivos de resultados')
SUSPENSA = _l('Votação suspensa')
CHAVE_DESLIGADA = _l('Mudança do estado da chave: URNA DESLIGADA')
REINICIO_PEDIDO = _l('Solicitado código de reinício')
REINICIO_OK = _l('Código de reinício conferido')
LIGADA = _l('Urna ligada em ')
DESLIGANDO = _l('Desligando a urna')
BATERIA = _l('Urna operando na bateria interna')
CONTING_MARCA = _l('Urna de conting')
CONTING_INSTANTES = (_l('Início do procedimento de contingência'), _l('Identificada uma urna de contingência'),
                     _l('Detectada MV em Urna de contingência'))
CARREGADA = _l('Urna carregada com sucesso')
# última linha de um log completo (como verifica_auditoria_logs_exemplo.FIM): o próprio pacote do log está sendo gerado
FIM_LOG = re.compile(rb'Gerando arquivo de resultado \[\.?log(?:jez|\.jez)\] \+ \[In\xedcio\]')
# cabeçalho técnico (carga): prefixo -> campo. 'gerada pelo usuário' (título do operador) não é extraído.
CABECALHO = [(_l('Identificação do Modelo de Urna: '), 'modelo_urna'), (_l('Versão da aplicação: '), 'versao_aplicacao'),
             (_l('Versão do UEFI: '), 'versao_uefi'), (_l('Identificador da mídia de carga: '), 'id_midia_carga'),
             (_l('Mídia de carga gerada pelo computador'), 'midia_carga_computador'),
             (_l('Data e hora da geração da mídia de carga: '), 'data_midia_carga'),
             (_l('Código de carga '), 'codigo_carga'), (_l('Detectada impressora com serial '), 'serial_impressora'),
             (_l('Serial da MV: '), 'serial_mv'), (_l('Mídia de votação gerada pelo computador'), 'midia_votacao_computador'),
             (_l('Data e hora da geração da mídia de votação: '), 'data_midia_votacao'),
             (_l('Turno da UE: '), 'turno_ue'), (_l('Fase da UE: '), 'fase_ue'), (_l('Modo de carga da UE - '), 'modo_carga'),
             (_l('Município: '), 'municipio_declarado'), (_l('Zona Eleitoral: '), 'zona_declarada'),
             (_l('Local de Votação: '), 'local_declarado')]
# mapa exato mensagem -> kind da máquina de estados de auditabr.logs.classify_message (mesmas frases; o teste confere)
KIND = {VOTO: 'VOTE', _l('Aguardando digitação do título'): 'START',
        _l('Aguardando digitação do identificador do eleitor'): 'START', BIO: 'BIO', SEM_BIO: 'NO_ENROLLMENT',
        MANUAL: 'MANUAL_REQUEST', BIOGRAFICA: 'BIOGRAPHIC_EVIDENCE', _l('Habilitação manual confirmada'): 'MANUAL_APPROVED',
        _l('Habilitação do eleitor cancelada'): 'CANCEL', _l('Votação encerrada'): 'CLOSE',
        _l('Encerramento da votação'): 'CLOSE', _l('Boletim de urna gerado'): 'BU'}
SM_KINDS = {'BIO_CONFIRMED': 'sm_biometrica', 'ALT_MANUAL_CONFIRMED': 'sm_manual',
            'NO_BIOMETRIC_ENROLLMENT_CONFIRMED': 'sm_sem_biometria', 'BIOGRAPHIC_ALTERNATIVE_CONFIRMED': 'sm_biografica',
            'HABILITATION_CONFLICT': 'sm_conflito', 'HABILITATION_UNCLASSIFIED': 'sm_nao_classificada'}
TIPOS = ('biometrica', 'manual_identificado', 'manual_nao_associado', 'manual_outro', 'sem_biometria', 'biografica',
         'conflito', 'nao_classificada', 'sem_inicio')
# classe de cada mensagem normalizada (dígitos -> #, [..] -> []) para o catálogo; o resto é 'OUTRA'
CLASSES = {
    'O voto do eleitor foi computado': 'VOTO', 'Voto confirmado para []': 'VOTO_CARGO',
    'Eleitor corrigiu na tela de confirmação de candidato': 'VOTO_CORRIGIU',
    'Aguardando digitação do título': 'INICIO_ESPERA', 'Aguardando digitação do identificador do eleitor': 'INICIO_ESPERA',
    'Título digitado pelo mesário': 'INICIO_ATENDIMENTO', 'Identificador do eleitor digitado pelo mesário': 'INICIO_ATENDIMENTO',
    'Identificador digitado pelo mesário foi: (Título de eleitor)': 'INICIO_TIPO_IDENTIFICADOR',
    'Identificador digitado pelo mesário foi: (CPF)': 'INICIO_TIPO_IDENTIFICADOR',
    'Foto do eleitor apresentada': 'INICIO_FOTO',
    'Tipo de habilitação do eleitor []': 'HAB_BIOMETRICA (BU hab_1)',
    'O eleitor não possui biometria': 'HAB_SEM_BIOMETRIA_2022 (BU sem biometria)',
    'Ano de nascimento digitado é igual ao do cadastro': 'HAB_BIOGRAFICA_2024_2026 (BU hab_0)',
    'Ano de nascimento digitado é diferente do cadastro': 'HAB_BIOGRAFICA_FALHA',
    'Solicitação de dado pessoal do eleitor para habilitação manual': 'HAB_MANUAL_PEDIDO (BU hab_2)',
    'Dado digitado confere': 'HAB_MANUAL_DADO_CONFERE', 'Mesário # habilitou o eleitor': 'HAB_MANUAL_MESARIO',
    'Solicita digital do mesário': 'HAB_MANUAL_DIGITAL_MESARIO', 'Capturada a digital do mesário': 'HAB_MANUAL_DIGITAL_MESARIO',
    'Biometria do mesário # encontrada nos arquivos coletados (#)': 'HAB_MANUAL_MESARIO_IDENTIFICADO',
    'Biometria coletada não é do mesário # (#)': 'HAB_MANUAL_MESARIO_NAO_CONFERE',
    'Eleitor foi habilitado': 'HABILITADO', 'Eleitor foi suspenso pelo mesário': 'CANCELAMENTO',
    'Solicita digital. Tentativa [] de []': 'BIO_TENTATIVA', 'Capturada a digital. Tentativa [] de []': 'BIO_CAPTURA',
    'Número de tentativas de reconhecimento do dedo. Tentativa [] de []': 'BIO_FALHA',
    'Timeout de reconhecimento do dedo. Tentativa [] de []': 'BIO_TIMEOUT',
    'Batimento de digitais retornou o score #': 'BIO_SCORE',
    'Urna pronta para receber votos': 'MARCO_ABERTURA', 'Aguardando confirmação para emissão da zerésima': 'MARCO_ZERESIMA',
    'Gerando relatório [ZERÉSIMA] [INÍCIO]': 'MARCO_ZERESIMA', 'Gerando relatório [ZERÉSIMA] [TÉRMINO]': 'ZERESIMA',
    'Gerando relatório [RESUMO DA ZERÉSIMA] [INÍCIO]': 'ZERESIMA', 'Gerando relatório [RESUMO DA ZERÉSIMA] [TÉRMINO]': 'ZERESIMA',
    'Imprimindo relatório [ZERÉSIMA] via nº []': 'ZERESIMA', 'Imprimindo relatório [RESUMO DA ZERÉSIMA] via nº []': 'ZERESIMA',
    'Operador selecionou: Encerrar votação': 'MARCO_ENCERRAMENTO_SELECIONADO',
    'Título digitado para encerramento: #': 'ENCERRAMENTO_TITULO',
    'Procedimento de encerramento confirmado': 'MARCO_ENCERRAMENTO_CONFIRMADO', 'Inicio do Encerramento': 'MARCO_ENCERRAMENTO_INICIO',
    'Operador cancelou o encerramento da votação': 'ENCERRAMENTO_CANCELADO',
    'Operador indagado se todas as pessoas presentes votaram': 'ENCERRAMENTO', 'Todas as pessoas presentes já votaram? SIM': 'ENCERRAMENTO',
    'Gerando relatório [BU] [INÍCIO]': 'MARCO_BU_RELATORIO', 'Gerando relatório [BU] [TÉRMINO]': 'BU',
    'Gerando relatório [BUJ] [INÍCIO]': 'BU', 'Gerando relatório [BUJ] [TÉRMINO]': 'BU',
    'Gerando relatório [BIM] [INÍCIO]': 'BU', 'Gerando relatório [BIM] [TÉRMINO]': 'BU',
    'Gerando relatório [ELEITORES HABILITADOS BIOGRAFICAMENTE] [INÍCIO]': 'BU_2026', 'Gerando relatório [ELEITORES HABILITADOS BIOGRAFICAMENTE] [TÉRMINO]': 'BU_2026',
    'Imprimindo relatório [BU] via nº []': 'BU_IMPRESSAO', 'Mesário indagado sobre qualidade do Boletim de Urna': 'BU_QUALIDADE',
    'Mesário indicou qualidade OK para Boletim de Urna': 'BU_QUALIDADE', 'Gerando arquivo de resultado [] + []': 'RESULTADO_ARQUIVO',
    'Preparando para assinatura dos arquivos de resultados': 'MARCO_ASSINATURA',
    'Início do procedimento de assinatura dos arquivos de resultados': 'MARCO_ASSINATURA',
    'Término do procedimento de assinatura dos arquivos de resultados': 'MARCO_ASSINATURA',
    'Urna ligada em #/#/# às #:#:#': 'LIGAMENTO', 'Desligando a urna': 'DESLIGAMENTO', 'Início das operações do logd': 'LOGD_INICIO',
    'Fechando o arquivo de Log': 'LOGD_FIM', 'Iniciando registro do log na MI e na ME': 'LOGD',
    'Solicitado código de reinício': 'REINICIO', 'Código de reinício digitado': 'REINICIO', 'Código de reinício conferido': 'REINICIO',
    'Mudança do estado da chave: URNA DESLIGADA': 'SUSPENSAO', 'Votação suspensa': 'SUSPENSAO',
    'Modo de carga da UE - Votação': 'CARGA_MODO_VOTACAO', 'Modo de carga da UE - Urna de contingência': 'CONTINGENCIA',
    'Início do procedimento de contingência': 'CONTINGENCIA', 'Identificada uma urna de contingência': 'CONTINGENCIA',
    'Detectada MV em Urna de contingência': 'CONTINGENCIA', 'Urna de contingência pronta para eleição': 'CONTINGENCIA',
    'Identificado arquivo de log corrompido na ME': 'CONTINGENCIA_LOG_ME (A-001)',
    'Identificação do Modelo de Urna: UE#': 'CARGA_MODELO', 'Versão do UEFI: IYEA#_P': 'CARGA_UEFI',
    'Identificador da mídia de carga: #': 'CARGA_MIDIA_ID', 'Código de carga #.#.#.#.#.#.#.# gravado na tabela de correspondência': 'CARGA_CODIGO',
    'Data e hora da geração da mídia de carga: #/#/# #:#:#': 'CARGA_MIDIA_DATA', 'Mídia de carga gerada pelo usuário: #': 'CARGA_USUARIO (não extraído)',
    'Urna carregada com sucesso': 'CARGA_FIM', 'Seção Eleitoral: #': 'CARGA_SECAO', 'Município: #': 'CARGA_MUNICIPIO',
    'Zona Eleitoral: #': 'CARGA_ZONA', 'Local de Votação: #': 'CARGA_LOCAL', 'Detectada impressora com serial #': 'CARGA_IMPRESSORA',
    'Urna ligada conectada na rede CA em [] e na Bateria Interna com []': 'ENERGIA_PERIODICO', 'Urna operando na bateria interna': 'ENERGIA_BATERIA',
    'Urna operando na rede elétrica': 'ENERGIA_REDE', 'Urna operando com rede elétrica': 'ENERGIA_REDE',
    'Identificador do eleitor digitado inválido': 'ALERTA_IDENTIFICADOR_INVALIDO', 'Título inválido': 'ALERTA_IDENTIFICADOR_INVALIDO',
    'O eleitor identificado já votou': 'ALERTA_JA_VOTOU', 'Eleitor não encontrado para o identificador informado': 'ALERTA_NAO_ENCONTRADO',
    'Problema ao desmontar a MR': 'ERRO_MR_ROTINEIRO (100% dos logs de 2º turno 2024/2026 na amostra)',
    'Justificativa recebida': 'JUSTIFICATIVA', 'Tecla indevida pressionada': 'TECLA_INDEVIDA',
    'Mesário indagado se eleitor está votando': 'ALERTA_ELEITOR_VOTANDO', 'Eleitor não está votando': 'ALERTA_ELEITOR_VOTANDO',
}
CLASSES_PREFIXO = (('Habilitação cancelada', 'CANCELAMENTO'), ('Impressora com', 'ALERTA_IMPRESSORA'),
                   ('Quantidade de memória', 'MEMORIA_PERIODICO'), ('Espaço livre na M', 'MEMORIA_PERIODICO'),
                   ('Espaço utilizado na M', 'MEMORIA_PERIODICO'), ('Espaço Utilizado na M', 'MEMORIA_PERIODICO'),
                   ('Inspeção da urna', 'INSPECAO'), ('Início de impressão', 'IMPRESSAO'), ('Fim de impressão', 'IMPRESSAO'),
                   ('Operador indagado se', 'MESARIO_REGISTRO'), ('Operador confirmou', 'MESARIO_REGISTRO'),
                   ('Operador encerrou ciclo de registro', 'MESARIO_REGISTRO'), ('Registrando mesários', 'MESARIO_REGISTRO'),
                   ('Pedido de leitura da biometria do mesário', 'MESARIO_REGISTRO'), ('Realizada a conferência da biometria do mesário', 'MESARIO_REGISTRO'),
                   ('Biometria coletada não é do mesário', 'HAB_MANUAL_MESARIO_NAO_CONFERE'), ('Eleitor sem atividade por', 'ELEITOR_SEM_ATIVIDADE'),
                   ('Digitado título inválido para o registro de mesário', 'MESARIO_REGISTRO_INVALIDO'), ('Turno da UE: ', 'CARGA_TURNO'),
                   ('Tamanho da ', 'GAP_INICIALIZACAO'), ('Resultado da verificação da mídia', 'GAP_INICIALIZACAO'), ('Fase da UE: ', 'GAP_INICIALIZACAO'),
                   ('Dados carregados da geração de MR', 'GAP_INICIALIZACAO'), ('Data e hora da geração da MR', 'GAP_INICIALIZACAO'),
                   ('MR gerada pelo', 'GAP_INICIALIZACAO'), ('Número de série da MR', 'GAP_INICIALIZACAO'), ('Mídia de resultado de', 'GAP_INICIALIZACAO'),
                   ('Mídia de votação gerada pelo usuário', 'CARGA_USUARIO (não extraído)'), ('Lendo ', 'GAP_INICIALIZACAO'),
                   ('Mídia externa presente', 'GAP_INICIALIZACAO'), ('Estrutura de diretórios da ME', 'GAP_INICIALIZACAO'),
                   ('Iniciando aplicação', 'APLICACAO'), ('Solicitação ao INIT', 'APLICACAO'), ('Finalização de aplicativo', 'APLICACAO'),
                   ('Aplicativo presente na MR', 'GAP_INICIALIZACAO'), ('Impressora OK', 'GAP_INICIALIZACAO'), ('Bateria interna', 'ENERGIA'),
                   ('Serial da MI', 'GAP_INICIALIZACAO'), ('Serial de votação da MV', 'GAP_INICIALIZACAO'), ('Sincronismo de mídia', 'GAP_INICIALIZACAO'),
                   ('Origem da sincronização', 'GAP_INICIALIZACAO'), ('Instalada ou alterada informação complementar', 'GAP_INICIALIZACAO'),
                   ('Data e hora da geração da mídia de votação', 'CARGA_MIDIA_VOTACAO'), ('Falha do teste: Tecla', 'TESTE_TECLADO'),
                   ('Início do teste de Teclado', 'TESTE_TECLADO'), ('Fim do teste de Teclado', 'TESTE_TECLADO'), ('Ciclo de teste', 'TESTE_TECLADO'),
                   ('Operador escolheu reprovar o teste', 'TESTE_TECLADO'), ('Operador escolheu a opção de reiniciar o ciclo', 'TESTE_TECLADO'),
                   ('N#api#C', 'ERRO_EXCECAO'), ('St#', 'ERRO_EXCECAO'), ('Erro na verificação de assinatura', 'ERRO_VERIFICACAO_ASSINATURA'),
                   ('Eleitor impedido', 'ELEITOR_IMPEDIDO'), ('Urna desligada', 'DESLIGAMENTO'), ('Biometria do mesário # encontrada em eleitores', 'HAB_MANUAL_MESARIO_EM_ELEITORES'),
                   ('Código de encerramento digitado', 'ENCERRAMENTO'), ('Eleitor voltou a digitar', 'SUSPENSAO_ELEITOR'), ('Eleitor está votando', 'SUSPENSAO_ELEITOR'),
                   ('Solicitado título eleitoral para suspensão', 'SUSPENSAO_ELEITOR'), ('Mesário digitou o título para suspender', 'SUSPENSAO_ELEITOR'),
                   ('Título # é válido para suspender', 'SUSPENSAO_ELEITOR'), ('Título # é inválido para suspender', 'SUSPENSAO_ELEITOR'),
                   ('Eleitor foi suspenso', 'SUSPENSAO_ELEITOR'), ('Atribuido voto nulo por suspensão', 'SUSPENSAO_ELEITOR'), ('Eleitor votou parcialmente', 'SUSPENSAO_ELEITOR'),
                   ('Solicitado código de suspensão', 'SUSPENSAO_ELEITOR'), ('Código de suspensão', 'SUSPENSAO_ELEITOR'), ('Carga da []', 'ENERGIA'),
                   ('Urna operando', 'ENERGIA'), ('Áudio', 'ACESSIBILIDADE'), ('Fone de ouvido', 'ACESSIBILIDADE'), ('Solicitado ao mesário que', 'ACESSIBILIDADE'),
                   ('Mesário cancelou entrada dos dados', 'CANCELAMENTO'), ('Operador cancelou', 'MESARIO_REGISTRO'), ('Operador selecionou: Registrar mesários', 'MESARIO_REGISTRO'),
                   ('Mesário indicou reimprimir Boletim', 'BU_REIMPRESSAO'), ('Aguardando data e hora para emissão da zerésima', 'ZERESIMA'),
                   ('Mesário indagado se quer imprimir a zerésima', 'ZERESIMA'), ('Imprimindo relatório de estado', 'RELATORIO'), ('Ano de nascimento inválido', 'HAB_BIOGRAFICA_FALHA'),
                   ('Dado digitado não confere', 'HAB_MANUAL_DADO_NAO_CONFERE'), ('Dado digitado está incompleto', 'HAB_MANUAL_DADO_NAO_CONFERE'),
                   ('Eleitor já justificou', 'ALERTA_JA_JUSTIFICOU'), ('Operador selecionou: Exibir contadores', 'OPERADOR'),
                   ('Digital coletada bate com uma digital gravada', 'HAB_MANUAL_NAO_ASSOCIADA (A-002)'),
                   ('Não encontrou digital coletada em nenhum dos arquivos', 'HAB_MANUAL_NAO_ASSOCIADA (A-002)'),
                   ('Digital capturada não corresponde', 'BIO_FALHA'),
                   ('Versão da aplicação: ', 'CARGA_VERSAO'), ('Mídia de carga gerada pelo computador', 'CARGA_MIDIA_MAQUINA'),
                   ('Mídia de votação gerada pelo computador', 'CARGA_MIDIA_VOTACAO'), ('Serial da MV', 'CARGA_SERIAL_MV'),
                   ('Verificação de assinatura', 'VERIFICACAO_ASSINATURA'), ('Gerando relatório [', 'RELATORIO'),
                   ('Imprimindo relatório [', 'RELATORIO'), ('Dedo reconhecido e o score', 'BIO_SCORE'),
                   ('Mesário # ', 'MESARIO_REGISTRO'), ('Erro inesperado durante a votação', 'ERRO_VOTO_NAO_REGISTRADO (C2-15)'))


def classe_mensagem(msg_norm):
    c = CLASSES.get(msg_norm)
    if c:
        return c
    for p, c in CLASSES_PREFIXO:
        if msg_norm.startswith(p):
            return c
    return 'OUTRA'


def norm(msg):
    """Normalização de anomalias_logs: dígitos -> #, conteúdo entre colchetes -> [], 90 caracteres."""
    return re.sub(r'\d+', '#', re.sub(r'\[[^\]]*\]', '[]', msg))[:90]


# ---------------------------------------------------------------- extração de um logd.dat
_ORD = {}


def _seg(ts):
    return int(ts[11:13]) * 3600 + int(ts[14:16]) * 60 + int(ts[17:19])


def _abs(ts):
    """Segundos absolutos de 'DD/MM/AAAA HH:MM:SS' (bytes); ValueError se malformado."""
    d = ts[:10]
    o = _ORD.get(d)
    if o is None:
        if len(ts) != 19 or ts[2:3] != b'/' or ts[5:6] != b'/' or ts[10:11] != b' ':
            raise ValueError(ts)
        o = _ORD[d] = date(int(d[6:10]), int(d[3:5]), int(d[0:2])).toordinal() * 86400
    return o + _seg(ts)


def _hms(s):
    return None if s is None else f'{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}'


def _mudanca_de_ritmo(v):
    """Como anomalias_logs: maior razão de log-verossimilhança 'uma taxa' x 'duas taxas antes/depois de um ponto'."""
    g = np.diff(v)
    g = g[g > 0]
    m = len(g)
    if m < 30:
        return None, None
    c = np.cumsum(g)
    k = np.arange(10, m - 10)
    s1, s2 = c[k - 1], c[-1] - c[k - 1]
    ll = k * np.log(k / s1) + (m - k) * np.log((m - k) / s2) - m * np.log(m / c[-1])
    i = int(np.argmax(ll))
    return float(ll[i]), int(v[0] + c[k[i] - 1])


def _tipo(cur):
    if cur['manual']:
        return 'manual_nao_associado' if cur['nao_assoc'] else 'manual_identificado' if cur['mesario'] else 'manual_outro'
    sem = cur['sem_bio'] or cur['biografica']
    if cur['bio'] and not sem:
        return 'biometrica'
    if cur['sem_bio'] and not cur['bio']:
        return 'sem_biometria'
    if cur['biografica'] and not cur['bio']:
        return 'biografica'
    return 'conflito' if cur['bio'] else 'nao_classificada'


def _novo_atend(t):
    return {'t_id': t, 't_hab': None, 'tent': 0, 'bio': False, 'sem_bio': False, 'biografica': False,
            'manual': False, 'mesario': False, 'nao_assoc': False}


def extrai_log(raw, dia):
    """Reduz um logd.dat (bytes, latin-1) a um dicionário de agregados e instantes-marco. dia = 'DD/MM/AAAA'."""
    dia_b = dia.encode()
    r = {'logd_bytes': len(raw), 'logd_sha256': hashlib.sha256(raw).hexdigest()}
    lines = raw.split(b'\n')
    if lines and not lines[-1]:
        lines.pop()
    r['linhas'] = len(lines)
    f = lines[0].split(b'\t', 5) if lines else []
    r['chave_log'] = hashlib.sha256(lines[0] if lines else b'').hexdigest()[:16]
    r['primeira_linha'] = f[0].decode('latin-1') if f else None
    r['serial'] = f[2].decode('latin-1') if len(f) > 2 else None
    r['ultima_linha'] = lines[-1].split(b'\t', 1)[0].decode('latin-1') if lines else None
    r['termina_gerando_log'] = bool(lines) and FIM_LOG.search(lines[-1]) is not None
    r['contingencia'] = CONTING_MARCA in raw
    cab = {}
    niveis = Counter()
    dias, votos_dia_cnt, cargos = set(), Counter(), Counter()
    votos, manual_t = [], []
    eventos = []
    cnt = Counter()
    cnt_vot = Counter()
    rejeitadas = retro_n = retro_max = saltos_1h = iguais = outro_dia_apos = 0
    prev = None
    em_votacao = False
    lig_total = lig_dia = deslig = rein_pedido = rein_ok = suspensa = chave = bateria = 0
    lig_dia_t = []
    marco = {k: None for k in ('carga', 'zeresima', 'abertura', 'encerramento_selecionado', 'encerramento_confirmado',
                               'encerramento_inicio', 'bu_relatorio', 'bu_arquivo', 'hash_arquivo', 'assinatura_inicio',
                               'assinatura_fim', 'contingencia_instante')}
    n_pronta = enc_cancel = bu_impresso = corrigiu = nao_reg = erro_inesp = tent_4 = cancelamentos = suspensos = 0
    retro_dia_n = retro_dia_max = 0
    prev_no_dia = False
    secoes = set()
    atend, cur = [], None
    modo_cont_instante = None
    for line in lines:
        p = line.split(b'\t', 5)
        if len(p) < 5:
            rejeitadas += 1
            continue
        ts = p[0]
        try:
            a = _abs(ts)
        except ValueError:
            rejeitadas += 1
            continue
        no_dia = ts.startswith(dia_b)
        if prev is not None:
            if a < prev:
                retro_n += 1
                retro_max = max(retro_max, prev - a)
                if no_dia and prev_no_dia:
                    retro_dia_n += 1
                    retro_dia_max = max(retro_dia_max, prev - a)
            elif a == prev:
                iguais += 1
            elif a - prev > 3600:
                saltos_1h += 1
        prev, prev_no_dia = a, no_dia
        nivel, app, msg = p[1], p[3], p[4]
        niveis[nivel] += 1
        dias.add(ts[:10])
        if no_dia:
            cnt[(nivel, app, msg)] += 1
            if em_votacao and nivel != b'INFO':
                cnt_vot[(nivel, app, msg)] += 1
        elif em_votacao:
            outro_dia_apos += 1
        if msg == DESLIGANDO:                      # registrado pelo VOTA (dia da eleição) e pelo SCUE/GAP (carga)
            deslig += 1
            continue
        if app == b'VOTA':
            if msg == VOTO:
                votos_dia_cnt[ts[:10]] += 1
                if not no_dia:
                    continue
                t = a % 86400
                votos.append(t)
                if cur is None:
                    atend.append({'t_id': None, 't_hab': None, 't_voto': t, 'tipo': 'sem_inicio', 'tent': 0})
                else:
                    atend.append({'t_id': cur['t_id'], 't_hab': cur['t_hab'], 't_voto': t, 'tipo': _tipo(cur), 'tent': cur['tent']})
                    tent_4 += cur['tent'] >= 4
                    cur = None
                eventos.append({'device': r['serial'], 'kind': 'VOTE'})
                continue
            if not no_dia:
                # a assinatura dos arquivos de resultado é registrada depois de o pacote do log ser gerado: no log
                # publicado ela só aparece para o turno anterior (log de 2º turno guarda o 1º); guardada com data
                if msg == ASSINA_INICIO:
                    marco['assinatura_inicio'] = ts.decode('latin-1')
                elif msg == ASSINA_FIM:
                    marco['assinatura_fim'] = ts.decode('latin-1')
                continue
            t = a % 86400
            k = KIND.get(msg)
            if k is not None:
                eventos.append({'device': r['serial'], 'kind': k})
            if msg in INICIO_ATEND:
                cur = _novo_atend(t)
            elif msg == HAB:
                if cur is not None:
                    cur['t_hab'] = t
            elif msg == BIO:
                if cur is not None:
                    cur['bio'] = True
            elif msg == BIOGRAFICA:
                if cur is not None:
                    cur['biografica'] = True
            elif msg == SEM_BIO:
                if cur is not None:
                    cur['sem_bio'] = True
            elif msg == MANUAL:
                manual_t.append(t)
                if cur is not None:
                    cur['manual'] = True
            elif msg in NAO_ASSOC:
                if cur is not None:
                    cur['nao_assoc'] = True
            elif msg.startswith(TENTATIVA):
                if cur is not None:
                    try:
                        cur['tent'] = max(cur['tent'], int(msg[len(TENTATIVA):].split(b']')[0]))
                    except ValueError:
                        pass
            elif msg.startswith(VOTO_CARGO):
                cargos[msg[len(VOTO_CARGO):].split(b']')[0].decode('latin-1')] += 1
            elif msg.startswith(CANCELA_PREFIXO):
                # não encerra o atendimento: 'Habilitação cancelada durante a captura de digital do mesário' é seguida
                # da captura e do voto do mesmo eleitor (caso real AC 1074/4/253, 2022 T2); o atendimento só recomeça
                # em INICIO_ATEND (cadencia_lib zera aqui e perde a classe desses votos)
                cancelamentos += 1
            elif msg == SUSPENSO:
                # o eleitor suspenso tem o voto parcial computado em seguida ('Atribuido voto nulo por suspensão')
                suspensos += 1
            elif msg.endswith(MESARIO_HAB_FIM):
                if cur is not None:
                    cur['mesario'] = True
            elif msg == PRONTA:
                n_pronta += 1
                em_votacao = True
                if marco['abertura'] is None:
                    marco['abertura'] = t
            elif msg == ENC_CONF:
                marco['encerramento_confirmado'] = t
                em_votacao = False
            elif msg == ENC_SELEC:
                if marco['encerramento_selecionado'] is None:
                    marco['encerramento_selecionado'] = t
            elif msg == ENC_INICIO:
                marco['encerramento_inicio'] = t
            elif msg == ENC_CANCEL:
                enc_cancel += 1
                em_votacao = True
            elif msg == ZERESIMA_GERA or (msg == ZERESIMA_ESPERA and marco['zeresima'] is None):
                marco['zeresima'] = t
            elif msg == BU_RELATORIO:
                if marco['bu_relatorio'] is None:
                    marco['bu_relatorio'] = t
            elif msg.startswith(BU_IMPRIME):
                bu_impresso += 1
            elif msg.startswith(ARQ_RESULTADO):
                if (b'[bu.dat]' in msg or b'[.bu]' in msg) and b'In\xedcio' in msg and marco['bu_arquivo'] is None:
                    marco['bu_arquivo'] = t
                elif (b'[hash.dat]' in msg or b'[.hash]' in msg) and b'T\xe9rmino' in msg:
                    marco['hash_arquivo'] = t
            elif msg == CORRIGIU:
                corrigiu += 1
            elif msg == SUSPENSA:
                suspensa += 1
            elif msg == CHAVE_DESLIGADA:
                chave += 1
            elif msg == REINICIO_PEDIDO:
                rein_pedido += 1
            elif msg == REINICIO_OK:
                rein_ok += 1
            elif msg == BATERIA:
                bateria += 1
            elif nivel != b'INFO' and NAO_REGISTRADO in msg and b'N\xc3O' in msg:
                nao_reg += 1
                erro_inesp += msg.startswith(ERRO_INESPERADO)
            continue
        # linhas dos demais aplicativos (SCUE, GAP, ATUE, LOGD, RED...): cabeçalho técnico e ligamentos, em qualquer dia
        if app == b'LOGD':
            if msg.startswith(LIGADA):
                lig_total += 1
                if no_dia:
                    lig_dia += 1
                    lig_dia_t.append(_hms(a % 86400))
            continue
        if msg.startswith(CARREGADA):
            if marco['carga'] is None:
                marco['carga'] = ts.decode('latin-1')
            continue
        if msg.startswith(CONTING_INSTANTES):
            if marco['contingencia_instante'] is None:
                marco['contingencia_instante'] = ts.decode('latin-1')
            continue
        for pref, campo in CABECALHO:
            if msg.startswith(pref):
                val = msg[len(pref):]
                if campo == 'codigo_carga':
                    val = val.split(b' ')[0]
                elif campo in ('midia_carga_computador', 'midia_votacao_computador'):
                    val = val.split(b': ', 1)[-1]
                val = val.strip().decode('latin-1')
                if campo == 'modo_carga':
                    cab.setdefault(campo, set()).add(val)
                    if modo_cont_instante is None and val.startswith('Urna de conting'):
                        modo_cont_instante = ts.decode('latin-1')
                elif campo not in cab:
                    cab[campo] = val
                break
        if msg.startswith(b'Se'):
            for s in SECTION_LINE.findall(msg):
                secoes.add(int(s))
    r['linhas_rejeitadas'] = rejeitadas
    r['n_info'], r['n_alerta'], r['n_erro'] = niveis[b'INFO'], niveis[b'ALERTA'], niveis[b'ERRO']
    r['n_outros_niveis'] = r['linhas'] - rejeitadas - r['n_info'] - r['n_alerta'] - r['n_erro']
    r['retrocessos'], r['maior_retrocesso_s'], r['saltos_1h'], r['carimbos_iguais_consecutivos'] = retro_n, retro_max, saltos_1h, iguais
    r['retrocessos_dia'], r['maior_retrocesso_dia_s'] = retro_dia_n, retro_dia_max   # só entre linhas do dia do pleito
    r['linhas_outro_dia_apos_abertura'] = outro_dia_apos
    r['contingencia_modo_carga_instante'] = modo_cont_instante
    r['cancelamentos'], r['suspensos'] = cancelamentos, suspensos
    for campo in ('modelo_urna', 'versao_aplicacao', 'versao_uefi', 'id_midia_carga', 'midia_carga_computador', 'data_midia_carga',
                  'codigo_carga', 'serial_impressora', 'serial_mv', 'midia_votacao_computador', 'data_midia_votacao', 'turno_ue',
                  'fase_ue', 'municipio_declarado', 'zona_declarada', 'local_declarado'):
        r[campo] = cab.get(campo)
    r['modo_carga'] = '|'.join(sorted(cab['modo_carga'])) if 'modo_carga' in cab else None
    r['secoes_declaradas'] = json.dumps(sorted(secoes))
    r.update({k: (_hms(v) if isinstance(v, int) else v) for k, v in marco.items()})
    r['n_pronta_para_votos'] = n_pronta
    r['encerramento_cancelado'] = enc_cancel
    r['bu_impresso'] = bu_impresso
    r['ligamentos'], r['ligamentos_dia'], r['desligamentos'] = lig_total, lig_dia, deslig
    r['ligamentos_dia_instantes'] = json.dumps(lig_dia_t)
    r['reinicio_pedido'], r['reinicio_conferido'] = rein_pedido, rein_ok
    r['votacao_suspensa'], r['chave_desligada'], r['bateria_interna'] = suspensa, chave, bateria
    dias_iso = sorted(_iso(k) for k in dias)
    r['dias'] = json.dumps(dias_iso)
    r['n_dias'] = len(dias_iso)
    r['votos_por_dia'] = json.dumps({_iso(k): v for k, v in sorted(votos_dia_cnt.items(), key=lambda kv: _iso(kv[0]))})
    r['votos_dia'] = len(votos)
    r['votos_por_cargo'] = json.dumps(dict(sorted(cargos.items())), ensure_ascii=False)
    r['corrigiu'] = corrigiu
    r['voto_nao_registrado'], r['erro_inesperado_votacao'] = nao_reg, erro_inesp
    r['manual_pedidos'] = len(manual_t)
    r['manual_apos_17h'] = sum(t >= TARDE_17 for t in manual_t)
    v = np.sort(np.array(votos, dtype=np.int64))
    r['primeiro_voto'] = _hms(int(v[0])) if len(v) else None
    r['ultimo_voto'] = _hms(int(v[-1])) if len(v) else None
    r['votos_apos_17h'] = int((v >= TARDE_17).sum()) if len(v) else 0
    r['votos_apos_19h'] = int((v >= TARDE_19).sum()) if len(v) else 0
    g = np.diff(v) if len(v) > 1 else np.array([], dtype=np.int64)
    r['intervalos'] = len(g)
    r['int_min_s'] = int(g.min()) if len(g) else None
    r['int_p5_s'] = float(np.percentile(g, 5)) if len(g) else None
    r['int_mediana_s'] = float(np.median(g)) if len(g) else None
    r['int_cv'] = float(g.std() / g.mean()) if len(g) >= 5 and g.mean() > 0 else None
    r['int_lt30_n'] = int((g < RAPIDO_S).sum()) if len(g) else 0
    r['seq_max_lt30'] = _maior_sequencia(g < RAPIDO_S) if len(g) else 0
    r['pausas_15min_n'] = int((g >= PAUSA_MIN).sum()) if len(g) else 0
    r['pausa_max_min'] = float(g.max() / 60) if len(g) else None
    r['ritmo_llr'], ponto = _mudanca_de_ritmo(v)
    r['ritmo_ponto'] = _hms(ponto)
    for tp in TIPOS:
        r[f'cat_{tp}'] = sum(x['tipo'] == tp for x in atend)
    r['cat_manual'] = r['cat_manual_identificado'] + r['cat_manual_nao_associado'] + r['cat_manual_outro']
    r['cat_sem_biometria_total'] = r['cat_sem_biometria'] + r['cat_biografica']
    r['n_atendimentos'] = sum(x['t_id'] is not None for x in atend)
    r['tentativas_4_n'] = tent_4
    r['t_id_hab_med_s'] = _med([x['t_hab'] - x['t_id'] for x in atend if x['t_id'] is not None and x['t_hab'] is not None])
    r['t_hab_voto_med_s'] = _med([x['t_voto'] - x['t_hab'] for x in atend if x['t_hab'] is not None])
    r['t_id_voto_med_s'] = _med([x['t_voto'] - x['t_id'] for x in atend if x['t_id'] is not None])
    sm = Counter(e['classification'] for e in state_machine(eventos))
    for k, campo in SM_KINDS.items():
        r[campo] = sm[k]
    top_e = Counter()
    top_a = Counter()
    for (nivel, app, msg), n in cnt_vot.items():
        chave_n = f"{app.decode('latin-1')} | {norm(msg.decode('latin-1'))}"
        (top_e if nivel == b'ERRO' else top_a)[chave_n] += n
    r['erros_votacao_n'] = sum(top_e.values())
    r['alertas_votacao_n'] = sum(top_a.values())
    r['erros_votacao_top'] = json.dumps(dict(top_e.most_common(5)), ensure_ascii=False)
    r['alertas_votacao_top'] = json.dumps(dict(top_a.most_common(5)), ensure_ascii=False)
    msgs = Counter()
    for (nivel, app, msg), n in cnt.items():
        msgs[f"{nivel.decode('latin-1')} | {app.decode('latin-1')} | {norm(msg.decode('latin-1'))}"] += n
    return r, msgs


def _iso(d):
    """'DD/MM/AAAA' (bytes) -> 'AAAA-MM-DD'."""
    return (d[6:10] + b'-' + d[3:5] + b'-' + d[0:2]).decode('latin-1')


def _med(x):
    return float(median(x)) if x else None


def _maior_sequencia(flags):
    best = run = 0
    for f_ in flags:
        run = run + 1 if f_ else 0
        best = max(best, run)
    return int(best)


# ---------------------------------------------------------------- pacote (zip/7z) -> linhas por logd.dat
def _votos_no_dia(raw, dia_b):
    n, i = 0, raw.find(VOTE_LINE)
    while i >= 0:
        n += raw.startswith(dia_b, raw.rfind(b'\n', 0, i) + 1)
        i = raw.find(VOTE_LINE, i + len(VOTE_LINE))
    return n


def membros_da_secao(data, dia, section_hint=None):
    """Todos os logd.dat do pacote com (depth, papel, raw). papel: 'secao' (vale para a seção), 'copia' (mesma
    primeira linha que outro, com menos votos no dia ou mais curto), 'outra_secao' (declara só outra seção).
    Mesma regra de auditabr.logs.section_logs, com o dia do pleito fixado."""
    members = read_log_members(data)
    if not members:
        return []
    # "0000" é a seção da urna de contingência antes de assumir uma seção: não informa nada. Quando o log externo só
    # declara 0000 (contingência que recuperou a MV da urna original), vale a seção do nome do arquivo; auditabr.logs
    # tomava 0 como a seção e descartava o log aninhado da urna original (caso SP 71072/418/73, 2026 T1: 265 votos).
    declared = {int(s) for d, raw in members if d == 0 for s in SECTION_LINE.findall(raw)} - {0}
    section = next(iter(declared)) if len(declared) == 1 else section_hint
    dia_b = dia.encode()
    best, score = {}, {}
    papel = []
    for idx, (d, raw) in enumerate(members):
        secs = {int(s) for s in SECTION_LINE.findall(raw)}
        if section is not None and secs and section not in secs and 0 not in secs:
            papel.append('outra_secao')
            continue
        papel.append('copia')
        key = raw[: raw.find(b'\n')] if b'\n' in raw else raw[:200]
        s = (_votos_no_dia(raw, dia_b), len(raw))
        if key not in best or s > score[key]:
            best[key], score[key] = idx, s
    for idx in best.values():
        papel[idx] = 'secao'
    return [(d, papel[i], raw) for i, (d, raw) in enumerate(members)]


def nome_pacote(nome, uf_pasta=None):
    m = NOME.match(nome)
    if not m:
        return None
    uf = (m['uf'] or uf_pasta or '').upper() or None
    return {'uf': uf, 'municipality': int(m['mun']), 'zone': int(m['zona']), 'section': int(m['sec']),
            'stem': re.sub(r'(?:-log)?\.(?:jez|logjez)$', '', nome, flags=re.IGNORECASE)}


def processa_pacote(path, pleito, uf_pasta=None):
    """Linhas (uma por logd.dat) de um pacote; pacotes ilegíveis viram uma linha com status de quarentena."""
    path = Path(path)
    base = {'pleito': pleito, 'arquivo': path.name, 'caminho': str(path), 'uf': uf_pasta, 'municipality': None, 'zone': None,
            'section': None, 'stem': None, 'pacote_sha256': None, 'pacote_bytes': None, 'depth': None, 'papel': None,
            'status_linha': 'OK', 'erro': None}
    ident = nome_pacote(path.name, uf_pasta)
    if ident is None:
        return [{**base, 'status_linha': 'QUARENTENA:NOME_NAO_RECONHECIDO'}], Counter()
    base.update(ident)
    try:
        data = path.read_bytes()
        base['pacote_sha256'], base['pacote_bytes'] = hashlib.sha256(data).hexdigest(), len(data)
        membros = membros_da_secao(data, DIA[pleito], section_hint=ident['section'])
    except Exception as exc:  # noqa: BLE001
        return [{**base, 'status_linha': 'QUARENTENA:PACOTE_ILEGIVEL', 'erro': repr(exc)[:200]}], Counter()
    if not membros:
        return [{**base, 'status_linha': 'QUARENTENA:SEM_LOGD'}], Counter()
    rows, msgs = [], Counter()
    for depth, papel, raw in membros:
        try:
            r, m = extrai_log(raw, DIA[pleito])
        except Exception as exc:  # noqa: BLE001
            rows.append({**base, 'depth': depth, 'papel': papel, 'status_linha': 'QUARENTENA:LOG_ILEGIVEL', 'erro': repr(exc)[:200]})
            continue
        motivos = []
        if r['primeira_linha'] is None or len(r['primeira_linha']) != 19:
            motivos.append('PRIMEIRA_LINHA_SEM_CARIMBO')
        if r['linhas_rejeitadas']:
            motivos.append('LINHAS_REJEITADAS')
        row = {**base, 'depth': depth, 'papel': papel, **r}
        if motivos:
            row['status_linha'] = 'QUARENTENA:' + '+'.join(motivos)
        rows.append(row)
        if papel == 'secao':
            for k, n in m.items():
                msgs[k] += n
    return rows, msgs


def _bloco(args):
    ch, pleito, itens = args
    t0 = time.monotonic()
    rows, msgs, n_logs_msg = [], Counter(), Counter()
    for path, uf in itens:
        rs, m = processa_pacote(path, pleito, uf)
        rows += rs
        for k, n in m.items():
            msgs[k] += n
            n_logs_msg[k] += 1
    return ch, rows, [(k, n, n_logs_msg[k]) for k, n in msgs.items()], time.monotonic() - t0


# ---------------------------------------------------------------- lista de pacotes, cache por bloco, passada
def ufs_do_pleito(pleito):
    if pleito == '2026-t2':
        base = ROOT / 'research' / 'segundo_turno_2026' / 'logs'
    elif pleito.startswith('2024'):
        base = ROOT / 'research' / 'municipais'
    else:
        base = ROOT / 'research' / 'estados'
    ufs = sorted(p.name for p in base.iterdir() if p.is_dir() and len(p.name) == 2) if base.is_dir() else []
    if pleito in ('2022-t1', '2022-t2', '2026-t1') and 'BA' not in ufs:
        ufs.append('BA')
    return sorted(ufs)


def lista_pacotes(pleito, uf):
    """Pacotes de log de uma UF: cache em research/varredura_forense/logs/<pleito>/listas/<UF>.csv; sem cache, 2026-t2
    usa os caminhos de ultimo_voto_por_secao.csv (todas as UFs menos ZZ) e os demais casos leem a pasta da UF uma vez
    (os.scandir, sem recursão)."""
    cache = WORK / pleito / 'listas' / f'{uf}.csv'
    if cache.exists():
        return pd.read_csv(cache, sep=';', encoding='utf-8-sig')
    rows = []
    if pleito == '2026-t2' and uf != 'ZZ' and ULTIMO_VOTO.exists():
        u = pd.read_csv(ULTIMO_VOTO, sep=';', decimal=',', encoding='utf-8-sig', usecols=['uf', 'path'], low_memory=False)
        rows = [{'uf': uf, 'path': p, 'bytes': None} for p in u[u.uf == uf].path.dropna()]
        del u
    if not rows:
        pasta = pasta_logs(pleito, uf)
        if pasta.is_dir():
            with os.scandir(pasta) as it:
                rows = [{'uf': uf, 'path': str(Path(pasta) / e.name), 'bytes': e.stat().st_size} for e in it
                        if e.is_file() and NOME.match(e.name)]
    d = pd.DataFrame(rows, columns=['uf', 'path', 'bytes']).sort_values('path').reset_index(drop=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(cache, sep=';', index=False, encoding='utf-8-sig')
    return d


def chave_bloco(itens):
    return hashlib.sha1('\n'.join(p for p, _ in itens).encode()).hexdigest()[:16]


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _rel(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT)).replace('\\', '/')
    except ValueError:
        return str(path)


def recibo(parquet, inputs, extra=None):
    p = Path(parquet)
    import pyarrow.parquet as pq
    d = {'at': datetime.now().isoformat(timespec='seconds'), 'inputs': inputs, 'sha256': _sha(p),
         'rows': int(pq.ParquetFile(p).metadata.num_rows), 'bytes': p.stat().st_size, 'parser_version': PARSER_VERSION}
    if extra:
        d.update(extra)
    Path(str(p) + '.json').write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    return d


def espera_memoria(min_mb):
    while True:
        fis, virt = memoria_livre_mb()
        if fis >= min_mb and virt >= min_mb:
            return
        print(f'memoria baixa ({fis:.0f} MB de RAM livre, {virt:.0f} MB virtual): pausa de 30 s', flush=True)
        time.sleep(30)


def _janela(ex, fn, itens, n, min_mb):
    """fn sobre itens com no máximo n tarefas em voo (como baixa_pais.em_janela, com limiar de RAM próprio)."""
    pend = set()
    for x in itens:
        espera_memoria(min_mb)
        pend.add(ex.submit(fn, x))
        if len(pend) >= n:
            feitos, pend = wait(pend, return_when=FIRST_COMPLETED)
            for f in feitos:
                yield f.result()
    while pend:
        feitos, pend = wait(pend, return_when=FIRST_COMPLETED)
        for f in feitos:
            yield f.result()


def _blocos_em_cache(pasta):
    """Blocos já lidos: parquet legível e recibo com a mesma versão do parser (bloco de versão antiga ou ilegível,
    por queda no meio da gravação, é lido de novo)."""
    feitos = set()
    for p in pasta.glob('part-*.parquet'):
        try:
            pd.read_parquet(p, columns=['arquivo'])
            rec = json.loads(Path(str(p) + '.json').read_text(encoding='utf-8'))
            if rec.get('parser_version') != PARSER_VERSION:
                raise ValueError('versão antiga do parser')
            feitos.add(p.stem[5:])
        except Exception:  # noqa: BLE001
            p.unlink()
            for orf in (Path(str(p) + '.json'), p.with_name(p.name.replace('part-', 'msgs-'))):
                orf.unlink(missing_ok=True)
    for m in pasta.glob('msgs-*.parquet'):        # msgs órfão de um bloco já removido
        if not (pasta / m.name.replace('msgs-', 'part-')).exists():
            m.unlink()
    return feitos


def grava_bloco(pasta, ch, rows, msgs, segundos, pleito):
    tmp = pasta / f'part-{ch}.tmp'
    df = pd.DataFrame(rows)
    df.to_parquet(tmp, index=False)
    final = pasta / f'part-{ch}.parquet'
    tmp.replace(final)
    mtmp = pasta / f'msgs-{ch}.tmp'
    pd.DataFrame(msgs, columns=['mensagem', 'n_linhas', 'n_logs']).to_parquet(mtmp, index=False)
    mtmp.replace(pasta / f'msgs-{ch}.parquet')
    inputs = {_rel(r['caminho']): r['pacote_sha256'] for r in rows if r.get('pacote_sha256')}
    n_pac = len({r['caminho'] for r in rows})
    recibo(final, inputs, {'pleito': pleito, 'pacotes': n_pac, 'segundos_processo': round(segundos, 2), 'dia': DIA[pleito]})
    return final


def passada(pleito, ufs=None, limite=None, procs=2, min_mb=700):
    pasta = WORK / pleito
    pasta.mkdir(parents=True, exist_ok=True)
    ufs = ufs or ufs_do_pleito(pleito)
    itens, blocos = [], []
    for uf in ufs:                                  # blocos nunca cruzam UF: a mesma lista dá sempre os mesmos blocos
        d = lista_pacotes(pleito, uf)
        it = sorted(zip(d.path, d.uf))              # ordem de pasta: leitura quase sequencial no HD
        if limite:
            it = it[:max(limite - len(itens), 0)]
        itens += it
        blocos += [(chave_bloco(b), pleito, b) for b in (it[i:i + BLOCO] for i in range(0, len(it), BLOCO))]
        print(pleito, uf, 'pacotes:', len(d), flush=True)
    feitos = _blocos_em_cache(pasta)
    pend = [b for b in blocos if b[0] not in feitos]
    print(pleito, 'pacotes', len(itens), '| blocos', len(blocos), '| em cache', len(blocos) - len(pend), flush=True)
    t0 = time.monotonic()
    n_pac = 0
    with ProcessPoolExecutor(procs, initializer=prioridade_baixa) as ex:
        for k, (ch, rows, msgs, seg) in enumerate(_janela(ex, _bloco, pend, procs, min_mb), 1):
            grava_bloco(pasta, ch, rows, msgs, seg, pleito)
            n_pac += len({r['caminho'] for r in rows})
            if k % 10 == 0 or k == len(pend):
                el = time.monotonic() - t0
                print(f'{len(blocos) - len(pend) + k}/{len(blocos)} blocos | {n_pac} pacotes | {el / 60:.1f} min | '
                      f'{1000 * el / max(n_pac, 1):.0f} s por 1.000 pacotes', flush=True)
    el = time.monotonic() - t0
    resumo = {'pleito': pleito, 'ufs': ufs, 'pacotes_listados': len(itens), 'blocos': len(blocos), 'blocos_lidos_agora': len(pend),
              'pacotes_lidos_agora': n_pac, 'segundos_parede': round(el, 1), 'procs': procs,
              's_por_1000_pacotes_parede': round(1000 * el / n_pac, 1) if n_pac else None, 'at': datetime.now().isoformat(timespec='seconds')}
    if n_pac and pleito in TOTAL_MAPA:
        resumo['estimativa_total_pleito_h'] = round(TOTAL_MAPA[pleito] * el / n_pac / 3600, 2)
        resumo['total_pacotes_mapa'] = TOTAL_MAPA[pleito]
    (pasta / f'passada_{"_".join(ufs)[:40]}_{int(time.time())}.json').write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(resumo, ensure_ascii=False), flush=True)
    return resumo


# ---------------------------------------------------------------- consolidação por seção
REFERENCIAS = {
    '2026-t2': (ROOT / 'relatorios' / 'verificacoes' / 'virada_1t_2t_2026' / 'secoes_t1_t2.parquet', 't2_comparecimento', None),
    '2022-t2': (ROOT / 'research' / 'padroes_2t' / 'base_2022.parquet', 't2_comp', 't2_manual'),
    '2022-t1': (ROOT / 'research' / 'padroes_2t' / 'base_2022.parquet', 't1_comp', 't1_manual'),
    '2026-t1': (ROOT / 'research' / 'padroes_2t' / 'hab_2026_t1.parquet', 'comparecimento_bu', 'hab_2'),
}
HAB_BU = {'2026-t2': ROOT / 'research' / 'padroes_2t' / 'hab_2026_t2.parquet', '2026-t1': ROOT / 'research' / 'padroes_2t' / 'hab_2026_t1.parquet'}


def referencia_bu(pleito, ufs=None):
    """(DataFrame chave + bu_comparecimento [+ bu_manual, bu_hab_0/1/2], sha256 das entradas) ou (None, {})."""
    if pleito not in REFERENCIAS:
        return None, {}
    path, comp, manual = REFERENCIAS[pleito]
    if not path.exists():
        return None, {}
    cols = CHAVE + [comp] + ([manual] if manual else [])
    d = pd.read_parquet(path, columns=cols).rename(columns={comp: 'bu_comparecimento', **({manual: 'bu_manual'} if manual else {})})
    for c in ('municipality', 'zone', 'section'):
        d[c] = pd.to_numeric(d[c], errors='coerce').astype('Int64')
    if ufs:
        d = d[d.uf.isin(ufs)]
    d = d.drop_duplicates(CHAVE)
    inputs = {_rel(path): _sha(path)}
    hp = HAB_BU.get(pleito)
    if hp and hp.exists():
        h = pd.read_parquet(hp, columns=CHAVE + ['hab_0', 'hab_1', 'hab_2'])
        if ufs:
            h = h[h.uf.isin(ufs)]
        d = d.merge(h.drop_duplicates(CHAVE).rename(columns={'hab_0': 'bu_hab_0', 'hab_1': 'bu_hab_1', 'hab_2': 'bu_hab_2'}), on=CHAVE, how='left')
        inputs[_rel(hp)] = _sha(hp)
    return d, inputs


def consolida_secoes(logs, ref=None):
    """Agrega a tabela por logd.dat (DataFrame) em uma linha por seção; junta a referência do BU quando houver.
    logs: colunas de processa_pacote. Função pura (testável)."""
    d = logs.copy()
    sec = d[d.papel.eq('secao') & d.status_linha.str.startswith(('OK', 'QUARENTENA:LINHAS_REJEITADAS'))].copy()
    # 'último' = o log que termina por último (a urna que encerrou a seção), não o que começou por último
    sec['fim'] = pd.to_datetime(sec.ultima_linha, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    sec = sec.sort_values(['uf', 'municipality', 'zone', 'section', 'fim'], na_position='first')
    ultimo = sec.groupby(CHAVE, dropna=False).tail(1).set_index(CHAVE)
    soma_cols = (['votos_dia', 'votos_apos_17h', 'votos_apos_19h', 'retrocessos', 'saltos_1h', 'linhas_rejeitadas', 'n_alerta', 'n_erro',
                  'erros_votacao_n', 'alertas_votacao_n', 'voto_nao_registrado', 'reinicio_conferido', 'ligamentos_dia', 'manual_pedidos',
                  'manual_apos_17h', 'corrigiu', 'n_atendimentos', 'int_lt30_n', 'pausas_15min_n', 'encerramento_cancelado', 'cat_manual',
                  'cat_sem_biometria_total', 'retrocessos_dia', 'cancelamentos', 'suspensos']
                 + [f'cat_{t}' for t in TIPOS] + list(SM_KINDS.values()))
    g = sec.groupby(CHAVE, dropna=False)
    s = g.agg(n_logs=('logd_sha256', 'size'), contingencia=('contingencia', 'any'), contingencia_instante=('contingencia_instante', 'min'),
              serials=('serial', lambda x: json.dumps(list(x))), logd_sha256=('logd_sha256', lambda x: json.dumps(list(x))),
              primeiro_voto=('primeiro_voto', 'min'), ultimo_voto=('ultimo_voto', 'max'), abertura=('abertura', 'min'),
              maior_retrocesso_s=('maior_retrocesso_s', 'max'), maior_retrocesso_dia_s=('maior_retrocesso_dia_s', 'max'),
              contingencia_modo_carga_instante=('contingencia_modo_carga_instante', 'min'),
              int_min_s=('int_min_s', 'min'), seq_max_lt30=('seq_max_lt30', 'max'),
              pausa_max_min=('pausa_max_min', 'max'), ritmo_llr=('ritmo_llr', 'max'), modelos=('modelo_urna', lambda x: '|'.join(sorted({str(v) for v in x.dropna()}))))
    for c in soma_cols:
        s[c] = g[c].sum()
    for c in ('stem', 'arquivo', 'pacote_sha256', 'modelo_urna', 'versao_aplicacao', 'versao_uefi', 'codigo_carga', 'data_midia_carga',
              'midia_carga_computador', 'serial_impressora', 'modo_carga', 'carga', 'zeresima', 'encerramento_selecionado',
              'encerramento_confirmado', 'encerramento_inicio', 'bu_relatorio', 'bu_arquivo', 'assinatura_fim', 'ultima_linha',
              'termina_gerando_log', 'int_mediana_s', 'int_cv', 'int_p5_s', 'ritmo_ponto', 't_id_hab_med_s', 't_hab_voto_med_s', 't_id_voto_med_s'):
        s[c] = ultimo[c]
    s['log_completo'] = ultimo.encerramento_confirmado.notna() & ultimo.bu_arquivo.notna() & ultimo.termina_gerando_log.fillna(False).astype(bool)
    s = s.reset_index()
    # pacotes sem log utilizável (ilegíveis, sem logd, nome não reconhecido) entram com n_logs = 0 e o motivo
    ruins = d[~d.index.isin(sec.index)]
    ruins = ruins[~ruins.set_index(CHAVE).index.isin(s.set_index(CHAVE).index)]
    ruins = ruins.dropna(subset=['municipality']).groupby(CHAVE, dropna=False).agg(
        stem=('stem', 'first'), arquivo=('arquivo', 'first'), pacote_sha256=('pacote_sha256', 'first'),
        motivo_sem_log=('status_linha', lambda x: '+'.join(sorted(set(x))))).reset_index()
    if len(ruins):
        ruins['n_logs'] = 0
        s = pd.concat([s, ruins], ignore_index=True)
    s['n_logs'] = s.n_logs.fillna(0).astype(int)
    n_membros = d.dropna(subset=['municipality']).groupby(CHAVE, dropna=False).agg(n_membros=('arquivo', 'size'), n_outra_secao=('papel', lambda x: int((x == 'outra_secao').sum())),
                                                                                   n_copias=('papel', lambda x: int((x == 'copia').sum()))).reset_index()
    s = s.merge(n_membros, on=CHAVE, how='left')
    for c in ('municipality', 'zone', 'section'):
        s[c] = s[c].astype('Int64')
    if ref is None:
        s['bu_comparecimento'] = pd.array([None] * len(s), dtype='Int64')
        s['dif_log_bu'] = pd.array([None] * len(s), dtype='Int64')
        s['status_bu'] = np.where(s.n_logs > 0, 'NOT_COMPARABLE: sem referência de BU carregada para o pleito', 'NOT_COMPARABLE: sem log utilizável')
        return s
    s = s.merge(ref, on=CHAVE, how='outer', indicator=True)
    s['n_logs'] = s.n_logs.fillna(0).astype(int)
    s['dif_log_bu'] = (s.votos_dia - s.bu_comparecimento).astype('Int64')
    s['status_bu'] = np.select(
        [s._merge.eq('right_only').to_numpy(), s.n_logs.eq(0).to_numpy(), s.bu_comparecimento.isna().to_numpy(),
         s.dif_log_bu.eq(0).fillna(False).to_numpy(dtype=bool)],
        ['NOT_COMPARABLE: sem pacote de log no HD', 'NOT_COMPARABLE: sem log utilizável (ver motivo_sem_log)',
         'NOT_COMPARABLE: seção sem linha na referência do BU', 'IGUAL'], 'DIFERENTE')
    if 'bu_hab_2' in s:
        s['dif_manual_bu'] = (s.cat_manual - s.bu_hab_2).astype('Int64')
        s['dif_bio_bu'] = (s.cat_biometrica - s.bu_hab_1).astype('Int64')
        s['dif_sem_bio_bu'] = (s.cat_sem_biometria_total - s.bu_hab_0).astype('Int64')
    elif 'bu_manual' in s:
        s['dif_manual_bu'] = (s.cat_manual - s.bu_manual).astype('Int64')
    return s.drop(columns='_merge')


def _posix(path):
    return str(path).replace('\\', '/')


def _duckdb():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='400MB'")
    con.execute('SET threads=2')
    return con


def une_blocos(pasta, destino, con=None):
    """Une os part-*.parquet de <pasta> em <destino> (DuckDB, sem carregar tudo na memória). O mesmo pacote pode estar em
    mais de um bloco (lista de uma UF que mudou, --limite): fica a linha do bloco de recibo mais novo; a coluna 'bloco'
    diz de que part-*.parquet cada linha veio. Devolve (recibos dos blocos, blocos superados por inteiro, blocos
    parcialmente superados, msgs-*.parquet dos blocos vivos)."""
    con = con or _duckdb()
    partes = sorted(Path(pasta).glob('part-*.parquet'))
    if not partes:
        raise SystemExit(f'sem blocos em {pasta}')
    recs = []
    for p in partes:
        rj = Path(str(p) + '.json')
        rec = json.loads(rj.read_text(encoding='utf-8')) if rj.exists() else {}
        recs.append({'bloco': p.name, 'at': rec.get('at', ''), 'pacotes': rec.get('pacotes', 0)})
    recs = pd.DataFrame(recs)
    con.register('recibos', recs)
    glob = _posix(Path(pasta) / 'part-*.parquet')
    con.execute(f"""COPY (SELECT * EXCLUDE (filename, _at, _rn) FROM (
        SELECT l.*, regexp_extract(l.filename, '[^/\\\\]+$') AS bloco, r.at AS _at,
               row_number() OVER (PARTITION BY l.caminho, l.depth, coalesce(l.logd_sha256, l.status_linha) ORDER BY r.at DESC, bloco DESC) AS _rn
        FROM read_parquet('{glob}', union_by_name=true, filename=true) l
        LEFT JOIN recibos r ON regexp_extract(l.filename, '[^/\\\\]+$') = r.bloco) WHERE _rn = 1)
        TO '{_posix(destino)}' (FORMAT PARQUET)""")
    con.unregister('recibos')
    vivos = dict(con.execute(f"SELECT bloco, count(DISTINCT caminho) FROM read_parquet('{_posix(destino)}') GROUP BY 1").fetchall())
    superados = sorted(b for b in recs.bloco if vivos.get(b, 0) == 0)              # todos os pacotes relidos em bloco mais novo
    parciais = sorted(b for b, n in zip(recs.bloco, recs.pacotes) if 0 < vivos.get(b, 0) < n)
    msgs_vivos = [Path(pasta) / b.replace('part-', 'msgs-') for b in recs.bloco if b not in superados and (Path(pasta) / b.replace('part-', 'msgs-')).exists()]
    return recs, superados, parciais, msgs_vivos


def consolida(pleito, ufs=None):
    pasta = WORK / pleito
    con = _duckdb()
    logs_pq = WORK / f'logs_{pleito}.parquet'
    recs, superados, parciais, msgs_vivos = une_blocos(pasta, logs_pq, con)
    partes = sorted(pasta.glob('part-*.parquet'))
    inputs = {_rel(p): _sha(p) for p in partes}
    rec_logs = recibo(logs_pq, inputs, {'pleito': pleito})
    print('logs por logd.dat:', rec_logs['rows'], flush=True)
    lp = _posix(logs_pq)
    ref, inputs_ref = referencia_bu(pleito, ufs)
    uf_filter = ''
    if ufs:
        uf_filter = ' WHERE uf IN (' + ','.join(f"'{u}'" for u in ufs) + ')'
    # por UF, para manter cada DataFrame pequeno (uma UF grande tem ~70 mil logs)
    ufs_lidas = [r[0] for r in con.execute(f"SELECT DISTINCT uf FROM read_parquet('{lp}'){uf_filter} ORDER BY uf").fetchall()]
    partes_s = []
    quar = []
    for uf in ufs_lidas:
        q = f"SELECT * FROM read_parquet('{lp}') WHERE uf = '{uf}'" if uf is not None else f"SELECT * FROM read_parquet('{lp}') WHERE uf IS NULL"
        d = con.execute(q).df()
        quar.append(d[~d.status_linha.eq('OK')][['pleito', 'arquivo', 'caminho', 'uf', 'municipality', 'zone', 'section', 'depth', 'papel',
                                                   'status_linha', 'erro', 'primeira_linha', 'linhas', 'linhas_rejeitadas', 'votos_dia']])
        r_uf = ref[ref.uf == uf] if ref is not None else None
        partes_s.append(consolida_secoes(d, r_uf))
        del d
    s = pd.concat(partes_s, ignore_index=True)
    sec_pq = WORK / f'secoes_{pleito}.parquet'
    s.to_parquet(sec_pq, index=False)
    recibo(sec_pq, {**{_rel(logs_pq): rec_logs['sha256']}, **inputs_ref}, {'pleito': pleito, 'ufs': ufs_lidas})
    # quarentena: valores originais como string, com o motivo
    q = pd.concat(quar, ignore_index=True) if quar else pd.DataFrame()
    QUAR.mkdir(parents=True, exist_ok=True)
    rows_q = [{k: (None if pd.isna(v) else str(v)) for k, v in r.items()} | {'reason': r['status_linha']} for r in q.to_dict('records')]
    (QUAR / f'rows-logs-C3-04_{pleito}.json').write_text(json.dumps(rows_q, ensure_ascii=False, indent=1), encoding='utf-8')
    q.to_csv(QUAR / f'quarentena_C3-04_{pleito}.csv', **CSV)
    # catálogo de mensagens do dia: frequência real (blocos vivos; um bloco só parcialmente superado ainda conta inteiro) + classe + exemplos
    lista = '[' + ','.join(f"'{_posix(x)}'" for x in msgs_vivos) + ']'
    m = con.execute(f"SELECT mensagem, sum(n_linhas) AS n_linhas, sum(n_logs) AS n_logs FROM read_parquet({lista}) GROUP BY 1 ORDER BY 2 DESC").df()
    n_logs_total = int((s.n_logs > 0).sum()) or 1
    m['pct_secoes'] = (100 * m.n_logs / n_logs_total).round(2)
    m['classe'] = m.mensagem.map(lambda x: classe_mensagem(x.split(' | ', 2)[2]))
    ex = catalogo_exemplos(pleito, grava=False)
    if ex is not None:
        m = m.merge(ex[['mensagem', 'n_linhas_exemplos', 'n_logs_exemplos']], on='mensagem', how='outer')
        m['classe'] = m.mensagem.map(lambda x: classe_mensagem(x.split(' | ', 2)[2]))
    m.sort_values('n_linhas', ascending=False).to_csv(WORK / f'catalogo_mensagens_{pleito}.csv', **CSV)
    resumo = {'pleito': pleito, 'ufs': ufs_lidas, 'logs': int(rec_logs['rows']), 'secoes': int(len(s)), 'secoes_com_log': int((s.n_logs > 0).sum()),
              'status_bu': {str(k): int(v) for k, v in s.status_bu.value_counts().items()},
              'quarentena': {str(k): int(v) for k, v in q.status_linha.value_counts().items()} if len(q) else {},
              'contingencia': int(s.contingencia.fillna(False).sum()), 'n_logs_dist': {str(k): int(v) for k, v in s.n_logs.value_counts().sort_index().items()},
              'papel': {str(k): int(v) for k, v in con.execute(f"SELECT papel, count(*) FROM read_parquet('{lp}'){uf_filter} GROUP BY 1").fetchall()},
              'blocos': int(len(partes)), 'blocos_superados': superados, 'blocos_parcialmente_superados': parciais,
              'at': datetime.now().isoformat(timespec='seconds')}
    tempos = [json.loads(p.read_text(encoding='utf-8')) for p in pasta.glob('part-*.parquet.json')]
    seg = sum(t.get('segundos_processo', 0) for t in tempos)
    pac = sum(t.get('pacotes', 0) for t in tempos)
    resumo['s_por_1000_pacotes_processo'] = round(1000 * seg / pac, 1) if pac else None
    if 'dif_log_bu' in s:
        comp = s[s.status_bu.isin(['IGUAL', 'DIFERENTE'])]
        resumo['log_x_bu'] = {'comparaveis': int(len(comp)), 'iguais': int((comp.dif_log_bu == 0).sum()),
                              'abs_dif_le_5': int((comp.dif_log_bu.abs() <= 5).sum()), 'soma_log': int(comp.votos_dia.sum()), 'soma_bu': int(comp.bu_comparecimento.sum())}
    (WORK / f'resumo_{pleito}.json').write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(resumo, ensure_ascii=False, indent=1), flush=True)
    return resumo


def catalogo_exemplos(pleito, grava=True):
    """Catálogo das mensagens do dia do pleito nos logs de exemplo (relatorios/logs_exemplo/*_<pleito>_*.txt), normalizadas,
    com a classe atribuída; base para conferir a taxonomia antes da passada."""
    arqs = sorted(EXEMPLOS.glob(f'*_{pleito}_*.txt')) if EXEMPLOS.is_dir() else []
    if not arqs:
        return None
    cnt, n_logs = Counter(), Counter()
    dia = DIA[pleito]
    for a in arqs:
        local = Counter()
        for line in a.read_text(encoding='utf-8').splitlines():
            if not line.startswith(dia):
                continue
            f = line.split('\t', 5)
            if len(f) < 5:
                continue
            local[f'{f[1]} | {f[3]} | {norm(f[4])}'] += 1
        for k, n in local.items():
            cnt[k] += n
            n_logs[k] += 1
    m = pd.DataFrame([{'mensagem': k, 'n_linhas_exemplos': n, 'n_logs_exemplos': n_logs[k]} for k, n in cnt.most_common()])
    m['classe'] = m.mensagem.map(lambda x: classe_mensagem(x.split(' | ', 2)[2]))
    m['fonte'] = ';'.join(a.name for a in arqs)
    if grava:   # só os exemplos; consolida grava catalogo_mensagens_<pleito>.csv com a frequência real de todas as seções lidas
        WORK.mkdir(parents=True, exist_ok=True)
        m.to_csv(WORK / f'catalogo_mensagens_{pleito}_exemplos.csv', **CSV)
        print(m.groupby('classe').n_linhas_exemplos.sum().sort_values(ascending=False).to_string(), flush=True)
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('fase', choices=['passada', 'consolida', 'catalogo'])
    ap.add_argument('pleito', choices=PLEITOS)
    ap.add_argument('--ufs', default=None, help='lista separada por vírgula, ex. AC,AL')
    ap.add_argument('--limite', type=int, default=None, help='só os N primeiros pacotes (teste)')
    ap.add_argument('--procs', type=int, default=2)
    ap.add_argument('--min-livre-mb', type=int, default=700, help='pausa entre blocos enquanto a RAM livre estiver abaixo disto')
    a = ap.parse_args()
    prioridade_baixa()
    ufs = [u.strip().upper() for u in a.ufs.split(',')] if a.ufs else None
    if a.fase == 'passada':
        passada(a.pleito, ufs, a.limite, a.procs, a.min_livre_mb)
    elif a.fase == 'consolida':
        consolida(a.pleito, ufs)
    else:
        catalogo_exemplos(a.pleito)


if __name__ == '__main__':
    main()
