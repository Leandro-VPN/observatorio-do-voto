"""Safeguards against counting requests/cancelled attempts as manual votes."""
from scripts.analyze_pilot_operations import parse


def log(messages):
    return '\n'.join(f'30/10/2022 {stamp}\tINFO\t123\tVOTA\t{message}\tHASH'
                     for stamp, message in messages).encode('utf-8')


def test_manual_requires_ordered_completion_and_strict_cutoff():
    result = parse(log([
        ('16:59:10', 'Solicitação de dado pessoal do eleitor para habilitação manual'),
        ('16:59:20', 'Capturada a digital do mesário'),
        ('16:59:30', 'Eleitor foi habilitado'),
        ('17:00:00', 'O voto do eleitor foi computado'),
        ('17:00:10', 'Solicitação de dado pessoal do eleitor para habilitação manual'),
        ('17:00:20', 'Capturada a digital do mesário'),
        ('17:00:30', 'Eleitor foi habilitado'),
        ('17:01:00', 'O voto do eleitor foi computado'),
    ]))
    assert result['vote_events'] == 2
    assert result['manual_sequence_votes'] == 2
    assert result['after_17_manual_sequence'] == 1


def test_cancel_and_new_session_prevent_state_leakage():
    result = parse(log([
        ('17:00:10', 'Solicitação de dado pessoal do eleitor para habilitação manual'),
        ('17:00:20', 'Capturada a digital do mesário'),
        ('17:00:30', 'Habilitação cancelada durante a captura de digital do mesário'),
        ('17:00:40', 'Eleitor foi habilitado'),
        ('17:01:00', 'O voto do eleitor foi computado'),
        ('17:01:10', 'Solicitação de dado pessoal do eleitor para habilitação manual'),
        ('17:01:20', 'Aguardando digitação do título'),
        ('17:01:30', 'Capturada a digital do mesário'),
        ('17:01:40', 'Eleitor foi habilitado'),
        ('17:02:00', 'O voto do eleitor foi computado'),
    ]))
    assert result['manual_sequence_votes'] == 0
    assert result['unclassified_votes'] == 2


def test_capture_alone_and_unordered_sequence_are_not_manual_votes():
    result = parse(log([
        ('17:00:10', 'Capturada a digital do mesário'),
        ('17:00:20', 'Solicitação de dado pessoal do eleitor para habilitação manual'),
        ('17:00:30', 'Eleitor foi habilitado'),
        ('17:01:00', 'O voto do eleitor foi computado'),
    ]))
    assert result['manual_sequence_votes'] == 0


def test_clock_reversal_clears_session_and_is_reported():
    result = parse(log([
        ('17:02:10', 'Solicitação de dado pessoal do eleitor para habilitação manual'),
        ('17:02:20', 'Capturada a digital do mesário'),
        ('17:01:30', 'Eleitor foi habilitado'),
        ('17:02:00', 'O voto do eleitor foi computado'),
    ]))
    assert result['clock_reversals'] == 1
    assert result['manual_sequence_votes'] == 0


def test_biometric_manual_conflict_does_not_double_count():
    result = parse(log([
        ('17:00:10', 'Solicitação de dado pessoal do eleitor para habilitação manual'),
        ('17:00:20', 'Capturada a digital do mesário'),
        ('17:00:30', 'Eleitor foi habilitado'),
        ('17:00:40', 'Tipo de habilitação do eleitor [biométrica]'),
        ('17:01:00', 'O voto do eleitor foi computado'),
    ]))
    assert result['conflicting_votes'] == 1
    assert result['manual_sequence_votes'] == result['biometric_votes'] == 0
