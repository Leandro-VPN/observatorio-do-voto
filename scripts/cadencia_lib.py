"""Atendimentos por eleitor a partir do log da urna (aplicativo VOTA, dia da eleicao).

Um atendimento vai de "Identificador do eleitor digitado pelo mesario" ate "O voto do eleitor foi
computado". Para cada um guarda os instantes (s desde 0h) de identificacao, habilitacao e voto, quantas
tentativas de digital houve e como o eleitor foi habilitado:
  biometrica            - digital do eleitor reconhecida
  manual_identificado   - liberacao manual; o log registra "Mesario <titulo> habilitou o eleitor"
  manual_nao_associado  - liberacao manual por digital que a urna nao associa a um mesario cadastrado
                          ("...Nao e possivel associar a habilitacao a um mesario" ou "...vai salvar a
                          digital em novo arquivo"), o achado A-002
  manual_outro          - pedido de habilitacao manual sem nenhuma das mensagens acima
  sem_biometria         - eleitor sem biometria cadastrada
  outro                 - nenhum dos casos acima
Nao guarda titulo de eleitor nem nenhum identificador de pessoa.
"""
from statistics import median, pstdev

ID = 'Identificador do eleitor digitado pelo mesário'
HAB = 'Eleitor foi habilitado'
VOTO = 'O voto do eleitor foi computado'
BIO = 'Tipo de habilitação do eleitor [biométrica]'
SEM_BIO = 'O eleitor não possui biometria'
MANUAL = 'Solicitação de dado pessoal do eleitor para habilitação manual'
NAO_ASSOC = ('Digital coletada bate com uma digital gravada após o registro inicial de mesário. '
             'Não é possível associar a habilitação a um mesário.')
NOVO_ARQ = 'Não encontrou digital coletada em nenhum dos arquivos, vai salvar a digital em novo arquivo.'
RESET = ('Aguardando digitação do identificador do eleitor', 'Aguardando digitação do título')
TARDE = 16 * 3600


def _seg(hms):
    h, m, s = hms.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def atendimentos(text, dia):
    """Lista de atendimentos concluidos (com voto computado), na ordem do log. dia = 'DD/MM/AAAA'."""
    out, cur, last_t, reversoes = [], None, {}, 0
    for line in text.splitlines():
        f = line.split('\t', 5)
        if len(f) < 5 or f[3] != 'VOTA' or not f[0].startswith(dia):
            continue
        try:
            t = _seg(f[0][11:19])
        except ValueError:
            continue
        dev, msg = f[2], f[4]
        if dev in last_t and t < last_t[dev]:
            reversoes += 1
            cur = None
        last_t[dev] = t
        if msg in RESET:
            continue
        if msg == ID:
            cur = {'dev': dev, 't_id': t, 't_hab': None, 'tent': 0, 'bio': False, 'sem_bio': False,
                   'manual': False, 'ident': False, 'nao_assoc': False}
            continue
        if cur is None:
            if msg == VOTO:  # voto sem inicio visivel (reinicio da urna no meio do atendimento)
                out.append({'dev': dev, 't_id': None, 't_hab': None, 't_voto': t, 'tipo': 'outro', 'tent': 0})
            continue
        if msg.startswith('Solicita digital. Tentativa ['):
            try:
                cur['tent'] = max(cur['tent'], int(msg.split('[')[1].split(']')[0]))
            except (IndexError, ValueError):
                pass
        elif msg == BIO:
            cur['bio'] = True
        elif msg == SEM_BIO:
            cur['sem_bio'] = True
        elif msg == MANUAL:
            cur['manual'] = True
        elif msg.startswith('Mesário ') and msg.endswith(' habilitou o eleitor'):
            cur['ident'] = True
        elif msg in (NAO_ASSOC, NOVO_ARQ):
            cur['nao_assoc'] = True
        elif msg == HAB:
            cur['t_hab'] = t
        elif msg.startswith('Habilitação cancelada') or msg == 'Eleitor foi suspenso pelo mesário':
            cur = None
        elif msg == VOTO:
            if cur['manual'] and cur['nao_assoc']:
                tipo = 'manual_nao_associado'
            elif cur['manual'] and cur['ident']:
                tipo = 'manual_identificado'
            elif cur['manual']:
                tipo = 'manual_outro'
            elif cur['bio']:
                tipo = 'biometrica'
            elif cur['sem_bio']:
                tipo = 'sem_biometria'
            else:
                tipo = 'outro'
            out.append({'dev': cur['dev'], 't_id': cur['t_id'], 't_hab': cur['t_hab'], 't_voto': t, 'tipo': tipo,
                        'tent': cur['tent']})
            cur = None
    return out, reversoes


def _med(x):
    return median(x) if x else None


def _cv(x):
    if len(x) < 5:
        return None
    m = sum(x) / len(x)
    return pstdev(x) / m if m > 0 else None


def metricas(ats, rapido=None):
    """Metricas por periodo ('dia' = antes das 16h, 'tarde' = 16h em diante) e totais de habilitacao.
    rapido: limiar (s) de atendimento muito curto; conta a fracao abaixo dele e a maior sequencia seguida."""
    r = {}
    for per, sel in (('dia', lambda a: a['t_voto'] < TARDE), ('tarde', lambda a: a['t_voto'] >= TARDE)):
        a = [x for x in ats if sel(x)]
        atend = [x['t_voto'] - x['t_id'] for x in a if x['t_id'] is not None]
        cab = [x['t_voto'] - x['t_hab'] for x in a if x['t_hab'] is not None]
        hab = [x['t_hab'] - x['t_id'] for x in a if x['t_hab'] is not None and x['t_id'] is not None]
        interv, ocioso = [], []
        for p, q in zip(a, a[1:]):
            if p['dev'] == q['dev']:
                interv.append(q['t_voto'] - p['t_voto'])
                if q['t_id'] is not None:
                    ocioso.append(q['t_id'] - p['t_voto'])
        r[f'{per}_votos'] = len(a)
        r[f'{per}_atend_med'] = _med(atend)
        r[f'{per}_atend_p10'] = sorted(atend)[len(atend) // 10] if len(atend) >= 10 else None
        r[f'{per}_cabine_med'] = _med(cab)
        r[f'{per}_habil_med'] = _med(hab)
        r[f'{per}_interv_med'] = _med(interv)
        r[f'{per}_interv_cv'] = _cv(interv)
        r[f'{per}_ocioso_med'] = _med(ocioso)
        if rapido is not None and atend:
            flags = [x['t_id'] is not None and x['t_voto'] - x['t_id'] <= rapido for x in a]
            r[f'{per}_frac_rapido'] = sum(flags) / len(flags)
            run = best = 0
            for f_ in flags:
                run = run + 1 if f_ else 0
                best = max(best, run)
            r[f'{per}_maior_sequencia_rapida'] = best
    for tp in ('biometrica', 'manual_identificado', 'manual_nao_associado', 'manual_outro', 'sem_biometria', 'outro'):
        sub = [x for x in ats if x['tipo'] == tp]
        r[f'n_{tp}'] = len(sub)
        r[f'n_{tp}_tarde'] = sum(x['t_voto'] >= TARDE for x in sub)
        r[f'atend_med_{tp}'] = _med([x['t_voto'] - x['t_id'] for x in sub if x['t_id'] is not None])
    r['votos_log'] = len(ats)
    return r
