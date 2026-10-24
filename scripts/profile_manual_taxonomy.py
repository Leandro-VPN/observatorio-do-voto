"""Small deterministic technical sample; never estimates state prevalence."""
from collections import Counter
from pathlib import Path

from auditabr.logs import read_log
from auditabr.utils import sha256, utcnow, write_json

ROOT = Path('research/piloto-ba-2022-t2')
events = Counter()
sources = []
for path in sorted((ROOT / 'logs').glob('*.logjez'))[:16]:
    data = read_log(path)
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('latin1')
    sources.append({'file': path.name, 'sha256': sha256(path)})
    for line in text.splitlines():
        fields = line.split('\t')
        if len(fields) < 5 or not fields[0].startswith('30/10/2022 ') or fields[3] != 'VOTA':
            continue
        # Only exact known technical categories, never arbitrary raw messages/identifiers.
        message = fields[4]
        if message in (
            'Solicitação de dado pessoal do eleitor para habilitação manual',
            'Solicita digital do mesário', 'Capturada a digital do mesário',
            'Eleitor foi habilitado', 'O voto do eleitor foi computado',
            'Tipo de habilitação do eleitor [biométrica]', 'O eleitor não possui biometria',
            'Habilitação cancelada durante confirmação de dado do eleitor',
            'Habilitação cancelada durante a captura de digital do mesário',
            'Habilitação manual confirmada',
        ):
            events[message] += 1
write_json(ROOT / 'manual-taxonomy-evidence.json', {
    'at': utcnow(), 'selection': 'First 16 lexicographically sorted log filenames; technical, not representative',
    'sources': sources, 'script_sha256': sha256(Path(__file__)), 'event_counts': dict(events),
    'official_reference': 'https://www.tse.jus.br/eleicoes/eleicoes-2022/arquivos/formato-dos-arquivos-de-log-17-9-22/@@download/file/formato-arquivos-log.pdf',
    'finding': 'Official example and sample contain request, worker fingerprint capture and elector habilitated events. The old hypothetical manual-confirmed phrase is not a validated completion rule.',
    'next_validation': 'Validate ordered per-session state machine including resets/cancellations, then require vote completion. Captured fingerprint alone is not a completed vote.',
    'limits': 'Counts are events, not distinct voters; no late/manual coincidence or party association inferred.',
})
print(dict(events))
