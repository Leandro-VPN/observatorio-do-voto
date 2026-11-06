"""Testes da passada única de logs (scripts/varredura_forense_logs.py) com logs sintéticos: cada extrator, o pacote
zip aninhado (contingência), 7z quando py7zr existe, quarentena, cache por bloco com recibo e consolidação por seção.
Rodam no ambiente .venv-report, sem research/ nem relatorios/."""
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
V = pytest.importorskip('varredura_forense_logs')

DIA = '25/10/2026'


def linha(ts, msg, app='VOTA', nivel='INFO', serial='02000001'):
    return f'{ts}\t{nivel}\t{serial}\t{app}\t{msg}\tHASH\n'.encode('latin-1')


def cabecalho(serial='02000001', secao='0085', modo='Votação'):
    t = '22/09/2026 10:00:0'
    return b''.join([
        linha(t + '0', 'Início das operações do logd', 'LOGD', serial=serial),
        linha(t + '0', 'Urna ligada em 22/09/2026 às 09:59:30', 'LOGD', serial=serial),
        linha(t + '1', 'Versão da aplicação: 10.23.0.0 - Praia da Barra do Cahy', 'SCUE', serial=serial),
        linha(t + '2', 'Identificação do Modelo de Urna: UE2022', 'SCUE', serial=serial),
        linha(t + '2', 'Detectada impressora com serial 30515351', 'SCUE', serial=serial),
        linha(t + '3', 'Versão do UEFI: IYEA26_P', 'SCUE', serial=serial),
        linha(t + '4', 'Identificador da mídia de carga: 6CFF5C9C', 'SCUE', serial=serial),
        linha(t + '4', 'Mídia de carga gerada pelo computador (nome - tpm - instalação): RCEWGEDAI31 - 7075 - 4E6E', 'SCUE', serial=serial),
        linha(t + '4', 'Data e hora da geração da mídia de carga: 18/09/2026 14:52:12', 'SCUE', serial=serial),
        linha(t + '4', 'Mídia de carga gerada pelo usuário: 033960770710', 'SCUE', serial=serial),
        linha(t + '4', 'Município: 57932', 'SCUE', serial=serial),
        linha(t + '4', 'Zona Eleitoral: 0009', 'SCUE', serial=serial),
        linha(t + '4', 'Local de Votação: 1023', 'SCUE', serial=serial),
        linha(t + '4', f'Seção Eleitoral: {secao}', 'SCUE', serial=serial),
        linha(t + '5', 'Código de carga 177.377.469.497.220.646.279.677 gravado na tabela de correspondência', 'SCUE', serial=serial),
        linha(t + '6', 'Urna carregada com sucesso', 'SCUE', serial=serial),
        linha(t + '7', 'Desligando a urna', 'SCUE', serial=serial),
        linha('23/09/2026 08:00:00', 'Urna ligada em 23/09/2026 às 07:59:00', 'LOGD', serial=serial),
        linha('23/09/2026 08:00:01', f'Modo de carga da UE - {modo}', 'GAP', serial=serial),
        linha('23/09/2026 08:00:01', 'Turno da UE: 2º turno', 'GAP', serial=serial),
        linha('23/09/2026 08:00:01', f'Seção Eleitoral: {secao}', 'GAP', serial=serial),
    ])


def eleitor(h, m, tipo, serial='02000001', cargo='Presidente'):
    """Atendimento sintético que termina em voto computado no instante h:m:30."""
    ts = lambda s: f'{DIA} {h:02d}:{m:02d}:{s:02d}'  # noqa: E731
    out = [linha(ts(0), 'Aguardando digitação do identificador do eleitor', serial=serial),
           linha(ts(5), 'Identificador do eleitor digitado pelo mesário', serial=serial)]
    if tipo == 'biometrica':
        out += [linha(ts(6), 'Solicita digital. Tentativa [1] de [4]', serial=serial),
                linha(ts(10), 'Tipo de habilitação do eleitor [biométrica]', serial=serial)]
    elif tipo == 'biografica':
        out += [linha(ts(10), 'Ano de nascimento digitado é igual ao do cadastro', serial=serial)]
    elif tipo == 'sem_biometria':
        out += [linha(ts(10), 'O eleitor não possui biometria', nivel='ALERTA', serial=serial)]
    elif tipo.startswith('manual'):
        out += [linha(ts(6), 'Solicita digital. Tentativa [1] de [4]', serial=serial),
                linha(ts(7), 'Solicita digital. Tentativa [4] de [4]', serial=serial),
                linha(ts(8), 'Solicitação de dado pessoal do eleitor para habilitação manual', serial=serial),
                linha(ts(9), 'Dado digitado confere', serial=serial)]
        if tipo == 'manual_identificado':
            out += [linha(ts(10), 'Mesário 039024590787 habilitou o eleitor', serial=serial)]
        elif tipo == 'manual_nao_associado':
            out += [linha(ts(10), 'Não encontrou digital coletada em nenhum dos arquivos, vai salvar a digital em novo arquivo.', serial=serial)]
    out += [linha(ts(12), 'Eleitor foi habilitado', serial=serial),
            linha(ts(29), f'Voto confirmado para [{cargo}]', serial=serial),
            linha(ts(30), 'O voto do eleitor foi computado', serial=serial)]
    return b''.join(out)


def dia_completo(serial='02000001', votos=(('biometrica', 8, 5), ('manual_identificado', 8, 7), ('biografica', 8, 9),
                                             ('manual_nao_associado', 8, 10), ('biometrica', 8, 30), ('biometrica', 9, 0)),
                 com_fim=True, extra=b''):
    ts = lambda h, m, s: f'{DIA} {h:02d}:{m:02d}:{s:02d}'  # noqa: E731
    out = [linha(ts(7, 0, 0), 'Urna ligada em 25/10/2026 às 06:59:00', 'LOGD', serial=serial),
           linha(ts(7, 0, 1), 'Modo de carga da UE - Votação', 'GAP', serial=serial),
           linha(ts(7, 0, 2), 'Problema ao desmontar a MR', 'GAP', nivel='ERRO', serial=serial),
           linha(ts(7, 30, 0), 'Aguardando confirmação para emissão da zerésima', serial=serial),
           linha(ts(7, 30, 5), 'Gerando relatório [ZERÉSIMA] [INÍCIO]', serial=serial),
           linha(ts(8, 0, 1), 'Urna pronta para receber votos', serial=serial)]
    for tipo, h, m in votos:
        out.append(eleitor(h, m, tipo, serial=serial))
    out += [linha(ts(9, 20, 0), 'Aguardando digitação do identificador do eleitor', serial=serial),
            linha(ts(9, 20, 5), 'Identificador do eleitor digitado pelo mesário', serial=serial),
            linha(ts(9, 20, 6), 'Identificador do eleitor digitado inválido', nivel='ALERTA', serial=serial),
            linha(ts(9, 20, 9), 'Habilitação cancelada durante confirmação de dado do eleitor', serial=serial),
            linha(ts(9, 25, 0), 'Erro inesperado durante a votação | O voto do eleitor NÃO foi registrado (8044) | Ocorreu um erro', nivel='ERRO', serial=serial),
            linha(ts(9, 26, 0), 'Mudança do estado da chave: URNA DESLIGADA', serial=serial),
            linha(ts(9, 26, 0), 'Votação suspensa', serial=serial),
            linha(ts(9, 26, 1), 'Desligando a urna', 'VOTA', serial=serial),
            linha(ts(9, 28, 0), 'Urna ligada em 25/10/2026 às 09:27:30', 'LOGD', serial=serial),
            linha(ts(9, 28, 1), 'Modo de carga da UE - Votação', 'GAP', serial=serial),
            linha(ts(9, 29, 0), 'Solicitado código de reinício', serial=serial),
            linha(ts(9, 29, 5), 'Código de reinício conferido', serial=serial),
            linha(ts(9, 29, 5), 'Urna pronta para receber votos', serial=serial)]
    out.append(extra)
    if com_fim:
        out += [linha(ts(17, 0, 6), 'Operador selecionou: Encerrar votação', serial=serial),
                linha(ts(17, 0, 25), 'Procedimento de encerramento confirmado', serial=serial),
                linha(ts(17, 1, 28), 'Inicio do Encerramento', serial=serial),
                linha(ts(17, 1, 29), 'Gerando relatório [BU] [INÍCIO]', serial=serial),
                linha(ts(17, 1, 40), 'Imprimindo relatório [BU] via nº [1]', serial=serial),
                linha(ts(17, 1, 50), 'Gerando arquivo de resultado [bu.dat] + [Início]', serial=serial),
                linha(ts(17, 1, 51), 'Gerando arquivo de resultado [bu.dat] + [Término]', serial=serial),
                linha(ts(17, 1, 55), 'Gerando arquivo de resultado [hash.dat] + [Término]', serial=serial),
                linha(ts(17, 1, 56), 'Gerando arquivo de resultado [logjez] + [Início]', serial=serial)]
    return b''.join(out)


def test_kind_bate_com_classify_message_do_auditabr():
    from auditabr.logs import classify_message
    for msg, kind in V.KIND.items():
        assert classify_message(msg.decode('latin-1')) == kind


def test_extrai_log_cabecalho_marcos_habilitacao_e_intervalos():
    raw = cabecalho() + dia_completo()
    r, msgs = V.extrai_log(raw, DIA)
    assert r['serial'] == '02000001' and r['primeira_linha'] == '22/09/2026 10:00:00' and r['ultima_linha'] == f'{DIA} 17:01:56'
    assert r['modelo_urna'] == 'UE2022' and r['versao_aplicacao'] == '10.23.0.0 - Praia da Barra do Cahy' and r['versao_uefi'] == 'IYEA26_P'
    assert r['id_midia_carga'] == '6CFF5C9C' and r['midia_carga_computador'] == 'RCEWGEDAI31 - 7075 - 4E6E'
    assert r['data_midia_carga'] == '18/09/2026 14:52:12' and r['codigo_carga'] == '177.377.469.497.220.646.279.677'
    assert r['serial_impressora'] == '30515351' and r['modo_carga'] == 'Votação' and r['turno_ue'] == '2º turno'
    assert json.loads(r['secoes_declaradas']) == [85] and r['municipio_declarado'] == '57932' and r['local_declarado'] == '1023'
    assert r['carga'] == '22/09/2026 10:00:06'
    assert r['zeresima'] == '07:30:05' and r['abertura'] == '08:00:01' and r['n_pronta_para_votos'] == 2
    assert r['encerramento_selecionado'] == '17:00:06' and r['encerramento_confirmado'] == '17:00:25' and r['encerramento_inicio'] == '17:01:28'
    assert r['bu_relatorio'] == '17:01:29' and r['bu_impresso'] == 1 and r['bu_arquivo'] == '17:01:50' and r['hash_arquivo'] == '17:01:55'
    assert r['termina_gerando_log'] is True and r['contingencia'] is False
    assert r['ligamentos'] == 4 and r['ligamentos_dia'] == 2 and json.loads(r['ligamentos_dia_instantes']) == ['07:00:00', '09:28:00']
    assert r['desligamentos'] == 2 and r['reinicio_pedido'] == 1 and r['reinicio_conferido'] == 1
    assert r['votacao_suspensa'] == 1 and r['chave_desligada'] == 1
    assert r['votos_dia'] == 6 and json.loads(r['votos_por_dia']) == {'2026-10-25': 6} and r['n_dias'] == 3
    assert json.loads(r['votos_por_cargo']) == {'Presidente': 6}
    assert r['primeiro_voto'] == '08:05:30' and r['ultimo_voto'] == '09:00:30' and r['votos_apos_17h'] == 0
    # taxonomia própria: 3 biométricas, 1 manual com mesário, 1 manual não associada, 1 biográfica (sem biometria)
    assert (r['cat_biometrica'], r['cat_manual_identificado'], r['cat_manual_nao_associado'], r['cat_biografica']) == (3, 1, 1, 1)
    assert r['cat_manual'] == 2 and r['cat_sem_biometria_total'] == 1 and r['cat_nao_classificada'] == 0 and r['n_atendimentos'] == 6
    assert r['tentativas_4_n'] == 2
    # máquina de estados de auditabr: só a biométrica é reconhecida; manual e biográfica ficam 'não classificadas'
    assert r['sm_biometrica'] == 3 and r['sm_manual'] == 0 and r['sm_nao_classificada'] == 3
    assert r['t_id_hab_med_s'] == 7.0 and r['t_hab_voto_med_s'] == 18.0 and r['t_id_voto_med_s'] == 25.0
    # intervalos: 2, 2, 1, 20, 30 min -> min 60 s, 0 < 30 s, 1 pausa >= 15 min (20 e 30 min = 2)
    assert r['intervalos'] == 5 and r['int_min_s'] == 60 and r['int_lt30_n'] == 0 and r['pausas_15min_n'] == 2
    assert r['pausa_max_min'] == 30.0 and r['int_mediana_s'] == 120.0 and r['ritmo_llr'] is None
    # erros e alertas durante a votação (entre abertura e encerramento): o ERRO da MR às 7h fica fora
    assert r['voto_nao_registrado'] == 1 and r['erro_inesperado_votacao'] == 1
    assert r['erros_votacao_n'] == 1 and r['alertas_votacao_n'] == 1 and r['n_erro'] == 2 and r['n_alerta'] == 1
    assert list(json.loads(r['alertas_votacao_top'])) == ['VOTA | Identificador do eleitor digitado inválido']
    assert r['retrocessos'] == 0 and r['retrocessos_dia'] == 0 and r['linhas_rejeitadas'] == 0 and r['saltos_1h'] >= 2
    assert r['cancelamentos'] == 1 and r['suspensos'] == 0 and r['contingencia_modo_carga_instante'] is None
    assert msgs['INFO | VOTA | O voto do eleitor foi computado'] == 6 and msgs['ERRO | GAP | Problema ao desmontar a MR'] == 1
    assert msgs['INFO | VOTA | Mesário # habilitou o eleitor'] == 1


def test_extrai_log_2022_sem_biometria_titulo_e_assinatura_do_turno_anterior():
    dia = '30/10/2022'
    raw = b''.join([
        linha('02/10/2022 17:40:12', 'Início do procedimento de assinatura dos arquivos de resultados'),
        linha('02/10/2022 17:41:04', 'Término do procedimento de assinatura dos arquivos de resultados'),
        linha(f'{dia} 08:01:01', 'Urna pronta para receber votos'),
        linha(f'{dia} 08:02:00', 'Aguardando digitação do título'),
        linha(f'{dia} 08:02:05', 'Título digitado pelo mesário'),
        linha(f'{dia} 08:02:10', 'O eleitor não possui biometria', nivel='ALERTA'),
        linha(f'{dia} 08:02:12', 'Eleitor foi habilitado'),
        linha(f'{dia} 08:02:30', 'O voto do eleitor foi computado'),
        linha(f'{dia} 08:05:05', 'Título digitado pelo mesário'),
        linha(f'{dia} 08:05:10', 'Tipo de habilitação do eleitor [biométrica]'),
        linha(f'{dia} 08:05:12', 'Eleitor foi habilitado'),
        linha(f'{dia} 08:05:30', 'O voto do eleitor foi computado'),
        linha(f'{dia} 17:05:17', 'Gerando arquivo de resultado [.logjez] + [Início]'),
    ])
    r, _ = V.extrai_log(raw, dia)
    assert r['cat_sem_biometria'] == 1 and r['cat_biometrica'] == 1 and r['sm_sem_biometria'] == 1 and r['sm_biometrica'] == 1
    assert r['assinatura_inicio'] == '02/10/2022 17:40:12' and r['assinatura_fim'] == '02/10/2022 17:41:04'
    assert r['termina_gerando_log'] is True and json.loads(r['votos_por_dia']) == {'2022-10-30': 2}


def test_monotonicidade_sobre_todas_as_linhas_e_linhas_rejeitadas():
    raw = b''.join([
        linha(f'{DIA} 08:00:00', 'Urna pronta para receber votos'),
        linha(f'{DIA} 08:00:00', 'Aguardando digitação do identificador do eleitor'),
        linha(f'{DIA} 09:30:00', 'Tecla indevida pressionada'),                       # salto > 1 h
        linha(f'{DIA} 09:29:10', 'Tecla indevida pressionada', 'GAP'),                # retrocesso de 50 s (outro app)
        b'linha sem campos\n',
        linha('99/99/2026 10:00:00', 'Tecla indevida pressionada'),                   # carimbo inválido
        linha('26/10/2026 00:10:00', 'Tecla indevida pressionada'),                   # outro dia depois da abertura
        linha(f'{DIA} 17:00:25', 'Procedimento de encerramento confirmado'),          # retrocesso de ~7 h
    ])
    r, _ = V.extrai_log(raw, DIA)
    assert r['retrocessos'] == 2 and r['maior_retrocesso_s'] == 7 * 3600 + 10 * 60 - 25 and r['saltos_1h'] == 2
    assert r['retrocessos_dia'] == 1 and r['maior_retrocesso_dia_s'] == 50     # o retrocesso vindo de outro dia não conta no dia
    assert r['carimbos_iguais_consecutivos'] == 1 and r['linhas_rejeitadas'] == 2 and r['linhas_outro_dia_apos_abertura'] == 1
    assert r['linhas'] == 8 and r['n_info'] == 6 and r['n_outros_niveis'] == 0


def test_cancelamento_e_suspensao_nao_encerram_o_atendimento():
    # caso real 2022: 'Habilitação cancelada durante a captura de digital do mesário' e depois o mesário habilita o
    # mesmo eleitor; caso real 2026: eleitor suspenso tem o voto parcial computado
    ts = lambda s: f'{DIA} 10:{s}'  # noqa: E731
    raw = b''.join([
        linha(ts('00:00'), 'Urna pronta para receber votos'),
        linha(ts('20:00'), 'Identificador do eleitor digitado pelo mesário'),
        linha(ts('20:05'), 'Solicitação de dado pessoal do eleitor para habilitação manual'),
        linha(ts('20:07'), 'Habilitação cancelada durante a captura de digital do mesário'),
        linha(ts('20:19'), 'Não encontrou digital coletada em nenhum dos arquivos, vai salvar a digital em novo arquivo.'),
        linha(ts('20:23'), 'Eleitor foi habilitado'),
        linha(ts('20:44'), 'O voto do eleitor foi computado'),
        linha(ts('30:00'), 'Identificador do eleitor digitado pelo mesário'),
        linha(ts('30:10'), 'Tipo de habilitação do eleitor [biométrica]'),
        linha(ts('30:12'), 'Eleitor foi habilitado'),
        linha(ts('36:00'), 'Mesário indagado se eleitor está votando', nivel='ALERTA'),
        linha(ts('36:30'), 'Eleitor foi suspenso pelo mesário'),
        linha(ts('36:30'), 'Atribuido voto nulo por suspensão [Presidente]'),
        linha(ts('36:30'), 'O voto do eleitor foi computado'),
    ])
    r, _ = V.extrai_log(raw, DIA)
    assert r['votos_dia'] == 2 and r['cat_manual_nao_associado'] == 1 and r['cat_biometrica'] == 1 and r['cat_sem_inicio'] == 0
    assert r['cancelamentos'] == 1 and r['suspensos'] == 1 and r['n_atendimentos'] == 2


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def pacote_contingencia():
    """Pacote da seção 85: log externo da urna de contingência (declara só 0000, sem votos), aninhados o log da urna
    original (3 votos), uma cópia parcial dele (mesma primeira linha, 1 voto) e o log de uma urna da seção 112."""
    original = cabecalho('02001951', '0085') + dia_completo('02001951', votos=(('biometrica', 8, 5), ('biometrica', 8, 7), ('biografica', 8, 9)), com_fim=False)
    copia = cabecalho('02001951', '0085') + dia_completo('02001951', votos=(('biometrica', 8, 5),), com_fim=False)
    outra = cabecalho('02001952', '0112') + dia_completo('02001952', votos=(('biometrica', 8, 5),) * 4)
    conting = (cabecalho('02276282', '0000', modo='Urna de contingência')
               + linha(f'{DIA} 19:55:16', 'Identificada uma urna de contingência', 'RED', serial='02276282')
               + linha(f'{DIA} 19:55:18', 'Detectada MV em Urna de contingência', 'RED', serial='02276282')
               + linha(f'{DIA} 19:57:29', 'Gerando arquivo de resultado [logjez] + [Início]', serial='02276282'))
    return _zip([('022762820410202619543001ME.jez', _zip([('logd.dat', original)])), ('copia.jez', _zip([('logd.dat', copia)])),
                 ('outra.jez', _zip([('logd.dat', outra)])), ('logd.dat', conting)])


def test_membros_da_secao_zip_aninhado_contingencia_copia_e_outra_secao():
    m = V.membros_da_secao(pacote_contingencia(), DIA, section_hint=85)
    papeis = [(d, p, raw.split(b'\t')[2].decode()) for d, p, raw in m]
    assert sorted(papeis) == [(0, 'secao', '02276282'), (1, 'copia', '02001951'), (1, 'outra_secao', '02001952'), (1, 'secao', '02001951')]
    # sem a dica da seção o log externo (só 0000) não decide: fica a regra do nome do arquivo em processa_pacote
    assert [p for _, p, _ in V.membros_da_secao(pacote_contingencia(), DIA)].count('secao') == 3


def test_processa_pacote_zip_e_quarentena(tmp_path):
    p = tmp_path / 'o03221es5793200090085-log.jez'
    p.write_bytes(pacote_contingencia())
    rows, msgs = V.processa_pacote(p, '2026-t2', 'ES')
    assert len(rows) == 4 and {r['status_linha'] for r in rows} == {'OK'}
    assert all(r['uf'] == 'ES' and r['municipality'] == 57932 and r['zone'] == 9 and r['section'] == 85 for r in rows)
    assert rows[0]['stem'] == 'o03221es5793200090085' and len(rows[0]['pacote_sha256']) == 64 and rows[0]['pacote_bytes'] == p.stat().st_size
    sec = [r for r in rows if r['papel'] == 'secao']
    assert sum(r['votos_dia'] for r in sec) == 3 and {r['serial'] for r in sec} == {'02001951', '02276282'}
    assert [r for r in sec if r['serial'] == '02276282'][0]['contingencia_instante'] == f'{DIA} 19:55:16'
    assert [r for r in sec if r['serial'] == '02276282'][0]['modo_carga'] == 'Urna de contingência'
    assert [r for r in sec if r['serial'] == '02276282'][0]['contingencia_modo_carga_instante'] == '23/09/2026 08:00:01'
    assert msgs['INFO | VOTA | O voto do eleitor foi computado'] == 3          # só os logs da seção contam no catálogo
    # nome não reconhecido, pacote ilegível e log com linha malformada
    (tmp_path / 'qualquer.jez').write_bytes(b'PK\x03\x04lixo')
    assert V.processa_pacote(tmp_path / 'qualquer.jez', '2026-t2', 'ES')[0][0]['status_linha'] == 'QUARENTENA:NOME_NAO_RECONHECIDO'
    q = tmp_path / 'o03221es5793200090086-log.jez'
    q.write_bytes(b'isto nao e zip nem 7z')
    assert V.processa_pacote(q, '2026-t2', 'ES')[0][0]['status_linha'] == 'QUARENTENA:SEM_LOGD'
    q.write_bytes(b'PK\x03\x04' + b'\x00' * 40)
    assert V.processa_pacote(q, '2026-t2', 'ES')[0][0]['status_linha'] == 'QUARENTENA:PACOTE_ILEGIVEL'
    q.write_bytes(_zip([('logd.dat', cabecalho() + b'linha quebrada\n' + dia_completo())]))
    r = V.processa_pacote(q, '2026-t2', 'ES')[0][0]
    assert r['status_linha'] == 'QUARENTENA:LINHAS_REJEITADAS' and r['linhas_rejeitadas'] == 1 and r['votos_dia'] == 6


def test_processa_pacote_7z_2022(tmp_path):
    py7zr = pytest.importorskip('py7zr')
    dia = '30/10/2022'
    raw = (linha('19/09/2022 10:20:55', 'Identificação do Modelo de Urna: UE2013', 'SCUE', serial='67305985')
           + linha('19/09/2022 10:20:55', 'Mídia de carga gerada pelo computador: ZRJ043WKS04', 'SCUE', serial='67305985')
           + linha('19/09/2022 10:20:56', 'Seção Eleitoral: 0053', 'SCUE', serial='67305985')
           + linha(f'{dia} 08:01:01', 'Urna pronta para receber votos', serial='67305985')
           + linha(f'{dia} 08:03:52', 'O voto do eleitor foi computado', serial='67305985')
           + linha(f'{dia} 17:05:17', 'Gerando arquivo de resultado [.logjez] + [Início]', serial='67305985'))
    p = tmp_path / 'o00407-5808400430053.logjez'
    with py7zr.SevenZipFile(p, 'w') as z:
        z.writestr(raw, 'logd.dat')
    rows, _ = V.processa_pacote(p, '2022-t2', 'RJ')
    assert len(rows) == 1 and rows[0]['uf'] == 'RJ' and rows[0]['municipality'] == 58084 and rows[0]['section'] == 53
    assert rows[0]['modelo_urna'] == 'UE2013' and rows[0]['midia_carga_computador'] == 'ZRJ043WKS04' and rows[0]['votos_dia'] == 1
    assert rows[0]['cat_sem_inicio'] == 1 and rows[0]['termina_gerando_log'] is True and rows[0]['stem'] == 'o00407-5808400430053'


def test_grava_bloco_recibo_e_cache(tmp_path):
    p = tmp_path / 'o03221es5793200090085-log.jez'
    p.write_bytes(pacote_contingencia())
    ch, rows, msgs, seg = V._bloco(('abc123', '2026-t2', [(str(p), 'ES')]))
    final = V.grava_bloco(tmp_path, ch, rows, msgs, seg, '2026-t2')
    rec = json.loads((tmp_path / 'part-abc123.parquet.json').read_text(encoding='utf-8'))
    assert final.name == 'part-abc123.parquet' and rec['rows'] == 4 and rec['parser_version'] == V.PARSER_VERSION
    assert rec['pacotes'] == 1 and set(rec) >= {'at', 'inputs', 'sha256', 'rows', 'bytes'} and list(rec['inputs'].values()) == [rows[0]['pacote_sha256']]
    assert rec['sha256'] == V._sha(final) and (tmp_path / 'msgs-abc123.parquet').exists()
    (tmp_path / 'part-quebrado.parquet').write_bytes(b'nao e parquet')
    assert V._blocos_em_cache(tmp_path) == {'abc123'} and not (tmp_path / 'part-quebrado.parquet').exists()
    rec['parser_version'] = 'outra'                       # bloco de versão antiga do parser é lido de novo
    (tmp_path / 'part-abc123.parquet.json').write_text(json.dumps(rec), encoding='utf-8')
    assert V._blocos_em_cache(tmp_path) == set() and not final.exists()
    assert not (tmp_path / 'msgs-abc123.parquet').exists() and not (tmp_path / 'part-abc123.parquet.json').exists()
    assert V.chave_bloco([(str(p), 'ES')]) == V.chave_bloco([(str(p), 'ES')]) and len(V.chave_bloco([])) == 16


def test_une_blocos_dedup_por_bloco_mais_novo(tmp_path):
    pytest.importorskip('duckdb')
    p1 = tmp_path / 'o03221es5793200090085-log.jez'
    p1.write_bytes(_zip([('logd.dat', cabecalho('02000001', '0085') + dia_completo('02000001'))]))
    p2 = tmp_path / 'o03221es5793200090086-log.jez'
    p2.write_bytes(_zip([('logd.dat', cabecalho('02000002', '0086') + dia_completo('02000002'))]))
    pasta = tmp_path / 'blocos'
    pasta.mkdir()
    ch, rows, msgs, seg = V._bloco(('velho', '2026-t2', [(str(p1), 'ES')]))                 # bloco antigo: só o pacote 85
    V.grava_bloco(pasta, ch, rows, msgs, seg, '2026-t2')
    rec = json.loads((pasta / 'part-velho.parquet.json').read_text(encoding='utf-8'))
    rec['at'] = '2026-01-01T00:00:00'
    (pasta / 'part-velho.parquet.json').write_text(json.dumps(rec), encoding='utf-8')
    ch, rows, msgs, seg = V._bloco(('novo', '2026-t2', [(str(p1), 'ES'), (str(p2), 'ES')]))  # bloco novo: 85 e 86
    V.grava_bloco(pasta, ch, rows, msgs, seg, '2026-t2')
    destino = tmp_path / 'logs.parquet'
    recs, superados, parciais, msgs_vivos = V.une_blocos(pasta, destino)
    d = pd.read_parquet(destino)
    assert len(d) == 2 and set(d.bloco) == {'part-novo.parquet'} and sorted(d.section) == [85, 86]
    assert superados == ['part-velho.parquet'] and parciais == [] and [m.name for m in msgs_vivos] == ['msgs-novo.parquet']
    assert sorted(recs.bloco) == ['part-novo.parquet', 'part-velho.parquet']


def test_consolida_secoes_com_referencia_do_bu(tmp_path):
    p1 = tmp_path / 'o03221es5793200090085-log.jez'
    p1.write_bytes(pacote_contingencia())
    p2 = tmp_path / 'o03221es5793200090086-log.jez'
    p2.write_bytes(_zip([('logd.dat', cabecalho('02000002', '0086') + dia_completo('02000002'))]))
    p3 = tmp_path / 'o03221es5793200090087-log.jez'
    p3.write_bytes(b'PK\x03\x04' + b'\x00' * 40)
    rows = []
    for p in (p1, p2, p3):
        rows += V.processa_pacote(p, '2026-t2', 'ES')[0]
    logs = pd.DataFrame(rows)
    ref = pd.DataFrame({'uf': ['ES'] * 4, 'municipality': [57932] * 4, 'zone': [9] * 4, 'section': [85, 86, 87, 88],
                        'bu_comparecimento': [3, 7, 10, 20], 'bu_hab_0': [1, 1, 0, 0], 'bu_hab_1': [2, 3, 0, 0], 'bu_hab_2': [0, 2, 0, 0]})
    s = V.consolida_secoes(logs, ref).set_index('section')
    assert s.loc[85, 'n_logs'] == 2 and s.loc[85, 'n_membros'] == 4 and s.loc[85, 'n_outra_secao'] == 1 and s.loc[85, 'n_copias'] == 1
    assert s.loc[85, 'votos_dia'] == 3 and s.loc[85, 'status_bu'] == 'IGUAL' and bool(s.loc[85, 'contingencia']) is True
    assert json.loads(s.loc[85, 'serials']) == ['02001951', '02276282'] and s.loc[85, 'modelos'] == 'UE2022'
    assert bool(s.loc[85, 'log_completo']) is False and s.loc[85, 'dif_bio_bu'] == 0 and s.loc[85, 'dif_sem_bio_bu'] == 0
    assert s.loc[86, 'votos_dia'] == 6 and s.loc[86, 'status_bu'] == 'DIFERENTE' and s.loc[86, 'dif_log_bu'] == -1
    assert s.loc[86, 'dif_manual_bu'] == 0 and s.loc[86, 'dif_bio_bu'] == 0 and bool(s.loc[86, 'log_completo']) is True
    assert s.loc[86, 'encerramento_confirmado'] == '17:00:25' and s.loc[86, 'ultimo_voto'] == '09:00:30' and s.loc[86, 'reinicio_conferido'] == 1
    assert s.loc[87, 'n_logs'] == 0 and s.loc[87, 'status_bu'].startswith('NOT_COMPARABLE: sem log utilizável') and s.loc[87, 'motivo_sem_log'] == 'QUARENTENA:PACOTE_ILEGIVEL'
    assert s.loc[88, 'n_logs'] == 0 and s.loc[88, 'status_bu'] == 'NOT_COMPARABLE: sem pacote de log no HD'
    sem = V.consolida_secoes(logs, None).set_index('section')
    assert sem.loc[85, 'status_bu'].startswith('NOT_COMPARABLE: sem referência') and 87 in sem.index and 88 not in sem.index


def test_classe_mensagem_norm_e_nome_pacote():
    assert V.norm('Mesário 039024590787 habilitou o eleitor') == 'Mesário # habilitou o eleitor'
    assert V.norm('Solicita digital. Tentativa [1] de [4]') == 'Solicita digital. Tentativa [] de []'
    assert V.classe_mensagem('Tipo de habilitação do eleitor []').startswith('HAB_BIOMETRICA')
    assert V.classe_mensagem('Ano de nascimento digitado é igual ao do cadastro').startswith('HAB_BIOGRAFICA')
    assert V.classe_mensagem('Habilitação cancelada durante reconhecimento biométrico') == 'CANCELAMENTO'
    assert V.classe_mensagem('mensagem inédita') == 'OUTRA'
    assert V.nome_pacote('o03221ac0100700090001-log.jez') == {'uf': 'AC', 'municipality': 1007, 'zone': 9, 'section': 1, 'stem': 'o03221ac0100700090001'}
    assert V.nome_pacote('o00407-0100700090002.logjez', 'ac') == {'uf': 'AC', 'municipality': 1007, 'zone': 9, 'section': 2, 'stem': 'o00407-0100700090002'}
    assert V.nome_pacote('o00452pe2449001430041-log.jez')['uf'] == 'PE' and V.nome_pacote('logd.dat') is None
