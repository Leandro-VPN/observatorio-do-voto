"""Gatilho por janela de horário e por volume no 2º turno, em todas as urnas.

Pergunta: se um programa trocasse votos só entre uma hora e outra (14h–15h, por exemplo), ou só a partir do
N-ésimo voto, dava para ver? O RDV não tem ordem nem hora, mas a fração de votos de cada seção dentro da
janela varia de seção para seção, e a seção se afastaria das vizinhas do mesmo prédio na proporção dessa fração.

Varredura: o resíduo do modelo do local (anomalias_2t, M1: res_pp = % do PT observada - prevista pelas vizinhas
e pelo próprio 1º turno) é regredido, dentro de cada prédio e com controles (tamanho, habilitação manual,
comparecimento e sua mudança), na fração de votos da seção dentro de cada janela de uma grade de 15 min
(5h–21h, hora local da urna). Todas as janelas início-fim são testadas (cerca de 2.000), com erro-padrão
agrupado por prédio e limite de Bonferroni. Dois tipos de regra: deslocamento ("2 para 1": a seção anda para
um lado na proporção da exposição) e inversão (a seção anda contra o próprio lado: exposição × sinal de quem
liderava no 1º turno). 2022 é medido do mesmo jeito. Cópias de 2026 com regras plantadas (no país inteiro, em 20%
das seções ou numa UF) dizem o que a varredura enxerga. Regras por volume (a partir do N-ésimo voto; a partir de
p% dos aptos; só os últimos k votos) usam só o BU; como essas exposições são funções do comparecimento, o teste
controla a relação suave comparecimento × resíduo e procura só a quebra que a regra criaria.

Leitura dos logs: todos os logd.dat do pacote da seção (a urna de contingência e, aninhadas, as urnas
anteriores), deduplicados por número de série e filtrados pela seção declarada na carga (um pacote pode trazer
a urna de outra seção). Cache por bloco de 500 logs em research/janelas_horario/<ano>/cache: retomável.

Além da reta no país inteiro (uma regra proporcional, em toda parte), a mesma regra pode aparecer como curvatura
(resposta por decil de exposição que não é reta), como dispersão (um subconjunto de seções com a regra: a média
quase não anda, mas as seções expostas se espalham mais que o ruído binomial/Poisson esperado) ou como agrupamento
(a regra num território: a reta refeita dentro de cada UF, zona e município). `clusters` faz isso em cada janela
válida; `clusters_plantadas` planta regras com essas formas em cópias de 2026 para calibrar.

Uso: python scripts/janelas_horario.py coleta 2026 | coleta 2022 | volume | janelas 2026 | janelas 2022 | plantadas
                                       | clusters 2026 | clusters 2022 | clusters_plantadas
"""
import hashlib
import io
import os
import re
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.special import erfinv, expit
from scipy.stats import chi2, norm

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from baixa_pais import em_janela, prioridade_baixa  # noqa: E402
from padroes_lib import EPS, _lg  # noqa: E402

WORK = ROOT / 'research' / 'janelas_horario'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'janelas_horario'
ANOM = ROOT / 'research' / 'anomalias_2t'
BASE = ROOT / 'research' / 'padroes_2t'
CHAVE = ['uf', 'municipality', 'zone', 'section']
LOC = ['uf', 'municipality', 'zone', 'voting_place']
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')
CSV_LE = dict(sep=';', decimal=',', encoding='utf-8-sig')
GRADE = np.arange(5 * 60, 21 * 60 + 1, 15)   # 5h00 a 21h00 de 15 em 15 min (hora local da urna; em 2022 há urnas do AC marcando 6h)
NB = len(GRADE) - 1
DIA = {2026: b'25/10/2026 ', 2022: b'30/10/2022 '}
MSG = b'\tVOTA\tO voto do eleitor foi computado\t'
SECAO = re.compile(rb'Se(?:\xe7\xe3|\xc3\xa7\xc3\xa3)o Eleitoral: (\d{4})')
NOME = {2026: re.compile(r'^o0*\d+(?P<uf>[a-z]{2})(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})-log\.jez$'),
        2022: re.compile(r'^o00407-(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})\.logjez$')}
MAX_MEMBRO = 64 * 2 ** 20
COLS = ['nome', 'n_logs', 'contingencia', 'erro'] + [f'b{m // 60:02d}h{m % 60:02d}' for m in GRADE[:-1]]
BINS = COLS[4:]
CONTROLES = ['ctl_logn', 'ctl_manual', 'ctl_dcomp']
SUAVES = CONTROLES + ['ctl_tx', 'ctl_tx2', 'ctl_tx3', 'ctl_logaptos']   # relação suave comparecimento × resíduo (regras por volume)
FLEX = CONTROLES + ['ctl_logaptos'] + [f'ctl_txb{i}' for i in range(1, 12)]   # faixas de comparecimento (12 quantis): relação de forma livre
SINAL = ['sinal_t1', 'sinal_tx', 'sinal_tx2']   # no teste de inversão: quem liderava no 1º turno entra como controle (o resíduo M1 depende disso)
PASSO = 32


# ---------------------------------------------------------------- leitura dos logs
def _membros(data, prof=0):
    """Todos os logd.dat de um pacote (zip ou 7z), descendo nos pacotes aninhados das urnas anteriores da seção."""
    if prof > 3 or len(data) > MAX_MEMBRO:
        return []
    out = []
    if data[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for i in z.infolist():
                if i.file_size > MAX_MEMBRO:
                    continue
                n = Path(i.filename).name.lower()
                if n == 'logd.dat':
                    out.append(z.read(i))
                elif n.endswith(('.jez', '.logjez')):
                    out += _membros(z.read(i), prof + 1)
    elif data[:6] == b'7z\xbc\xaf\x27\x1c':
        import py7zr
        from py7zr.io import BytesIOFactory
        with py7zr.SevenZipFile(io.BytesIO(data)) as z:
            nomes = [n for n in z.getnames() if Path(n).name.lower() == 'logd.dat' or Path(n).name.lower().endswith(('.jez', '.logjez'))]
            fab = BytesIOFactory(MAX_MEMBRO)
            z.extract(targets=nomes, factory=fab)
            for nome in nomes:
                b = fab.get(nome).read()
                if Path(nome).name.lower() == 'logd.dat':
                    out.append(b)
                else:
                    out += _membros(b, prof + 1)
    return out


def _serie(raw):
    f = raw[:200].split(b'\t')
    return f[2] if len(f) > 2 else b'?'


def _votos_no_dia(raw, dia):
    """Quantas linhas 'voto computado' do log caem no dia da eleição."""
    n, i = 0, raw.find(MSG)
    while i >= 0:
        n += raw.startswith(dia, raw.rfind(b'\n', 0, i) + 1)
        i = raw.find(MSG, i + len(MSG))
    return n


def le_bins(path, dia, secao):
    """Votos computados por faixa de 15 min no dia (hora local da urna), somando as urnas que atenderam a seção.
    Devolve (histograma, nº de logs usados, teve urna de contingência, erro)."""
    logs = _membros(Path(path).read_bytes())
    if not logs:
        return None, 0, False, 'sem logd.dat'
    por_serie, votos_dia = {}, {}
    for raw in logs:
        secs = {int(x) for x in SECAO.findall(raw)}
        if secs and secao not in secs and 0 not in secs:
            continue                                   # urna de outra seção embalada no mesmo pacote
        # identidade do log = sua primeira linha (instante em que o logd começou + hash da linha): duas exportações do
        # mesmo log têm a mesma; urnas diferentes (troca durante o dia) têm outra e somam. Em 2022 o 3º campo da linha
        # não é o número de série da urna (é igual para todas), por isso não serve de chave.
        s = raw[:raw.find(b'\n')] if b'\n' in raw else raw[:200]
        v = _votos_no_dia(raw, dia)
        # mesmo log mais de uma vez (exportação parcial e final): fica a versão com mais votos no dia; em empate, a mais longa
        if s not in por_serie or (v, len(raw)) > (votos_dia[s], len(por_serie[s])):
            por_serie[s], votos_dia[s] = raw, v
    if not por_serie:
        return None, len(logs), False, 'nenhum log da seção'
    h = np.zeros(NB, dtype=np.int64)
    cont = False
    for raw in por_serie.values():
        cont |= b'Urna de conting' in raw
        i = raw.find(MSG)
        while i >= 0:
            ini = raw.rfind(b'\n', 0, i) + 1
            if raw.startswith(dia, ini):
                try:
                    k = (int(raw[ini + 11:ini + 13]) * 60 + int(raw[ini + 14:ini + 16]) - GRADE[0]) // 15
                except ValueError:
                    k = -1
                if 0 <= k < NB:
                    h[k] += 1
            i = raw.find(MSG, i + len(MSG))
    return h, len(por_serie), cont, None


def _bloco(args):
    ch, ano, itens = args
    out = []
    for path, secao in itens:
        try:
            h, n, cont, err = le_bins(path, DIA[ano], secao)
        except Exception as exc:  # noqa: BLE001
            h, n, cont, err = None, 0, False, repr(exc)[:100]
        out.append((Path(path).name, n, cont, err) + (tuple(int(x) for x in h) if h is not None else (None,) * NB))
    return ch, out


def arquivos(ano):
    rows = []
    if ano == 2026:
        for d in sorted((ROOT / 'research' / 'segundo_turno_2026' / 'logs').iterdir()):
            for p in d.glob('*-log.jez'):
                m = NOME[2026].match(p.name)
                if m:
                    rows.append((m['uf'].upper(), int(m['mun']), int(m['zona']), int(m['sec']), str(p)))
    else:
        pastas = [(uf, ROOT / 'research' / 'estados' / uf / '2022-t2' / 'logs') for uf in sorted(os.listdir(ROOT / 'research' / 'estados'))]
        pastas.append(('BA', ROOT / 'research' / 'piloto-ba-2022-t2' / 'logs'))
        for uf, d in pastas:
            if not d.is_dir():
                continue
            for p in d.glob('*.logjez'):
                m = NOME[2022].match(p.name)
                if m:
                    rows.append((uf, int(m['mun']), int(m['zona']), int(m['sec']), str(p)))
    return pd.DataFrame(rows, columns=CHAVE + ['path']).drop_duplicates(CHAVE)


def coleta_corrige(ano):
    """Relê só as seções cujo total de votos no log difere do comparecimento do BU e corrige bins_<ano>.parquet
    (depois da correção do leitor em 03/11/2026: log do 1º turno aninhado vencia o do 2º; em 2022 o 3º campo não é série)."""
    h = pd.read_parquet(WORK / f'bins_{ano}.parquet')
    b = pd.read_parquet(BASE / f'base_{ano}.parquet', columns=CHAVE + ['t2_comp'])
    m = h.merge(b, on=CHAVE, how='left')
    ruim = m[(m[BINS].sum(axis=1) != m.t2_comp) & m.t2_comp.notna()][CHAVE].merge(arquivos(ano), on=CHAVE, how='inner')
    lista = list(zip(ruim.path, ruim.section.astype(int)))
    print(ano, 'seções com log ≠ BU a reler:', len(lista), flush=True)
    novo = pd.DataFrame(_bloco((0, ano, lista))[1], columns=COLS)
    novo = ruim[CHAVE].assign(nome=ruim.path.map(lambda p: Path(p).name)).merge(novo, on='nome').drop(columns='nome')
    h = h.set_index(CHAVE)
    h.loc[novo.set_index(CHAVE).index, COLS[1:]] = novo.set_index(CHAVE)[COLS[1:]]
    h = h.reset_index()
    h.to_parquet(WORK / f'bins_{ano}.parquet', index=False)
    m = h.merge(b, on=CHAVE, how='left')
    dif = m[BINS].sum(axis=1) - m.t2_comp
    print('depois: log = BU em', int((dif == 0).sum()), 'de', len(m), '| log = 0:', int((m[BINS].sum(axis=1) == 0).sum()), '| |dif| > 5:', int((dif.abs() > 5).sum()), flush=True)


def coleta(ano, procs=2):
    cache = WORK / str(ano) / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    a = arquivos(ano).sort_values('path')              # ordem de pasta: leitura quase sequencial no HD
    print(ano, 'logs no HD:', len(a), flush=True)
    itens = list(zip(a.path, a.section.astype(int)))
    blocos = [(hashlib.sha1('\n'.join(p for p, _ in b).encode()).hexdigest()[:16], ano, b)
              for b in (itens[i:i + 500] for i in range(0, len(itens), 500))]
    feitos = set()
    for p in cache.glob('*.parquet'):                  # bloco ilegível (queda no meio da gravação) é lido de novo
        try:
            pd.read_parquet(p, columns=['nome'])
            feitos.add(p.stem)
        except Exception:  # noqa: BLE001
            p.unlink()
    pend = [b for b in blocos if b[0] not in feitos]
    print('blocos', len(blocos), '| em cache', len(blocos) - len(pend), flush=True)
    with ProcessPoolExecutor(procs, initializer=prioridade_baixa) as ex:
        for k, (ch, out) in enumerate(em_janela(ex, _bloco, pend, 2 * procs), 1):
            tmp = cache / f'{ch}.tmp'
            pd.DataFrame(out, columns=COLS).to_parquet(tmp, index=False)
            tmp.replace(cache / f'{ch}.parquet')       # bloco só conta como lido depois de gravado inteiro
            if k % 20 == 0:
                print(f'{len(blocos) - len(pend) + k}/{len(blocos)} blocos', flush=True)
    res = pd.concat([pd.read_parquet(cache / f'{ch}.parquet') for ch, _, _ in blocos], ignore_index=True)
    a['nome'] = a.path.map(lambda p: Path(p).name)
    b = a[CHAVE + ['nome']].merge(res, on='nome', how='left').drop(columns='nome')
    b.to_parquet(WORK / f'bins_{ano}.parquet', index=False)
    print('seções com bins:', int(b.erro.isna().sum()), '| erros:', b.erro.value_counts().head(5).to_dict(), flush=True)


# ---------------------------------------------------------------- base e regressão dentro do prédio
def prepara(ano, com_bins=True):
    e = pd.read_parquet(ANOM / f'secoes_{ano}.parquet')
    if os.environ.get('JANELAS_UF'):                     # teste rápido numa UF só
        e = e[e.uf.isin(os.environ['JANELAS_UF'].split(','))]
    b = pd.read_parquet(BASE / f'base_{ano}.parquet', columns=CHAVE + ['t2_comp', 't2_aptos', 't2_manual', 't1_comp', 't1_aptos'])
    e = e.merge(b, on=CHAVE, how='left')
    if com_bins:
        h = pd.read_parquet(WORK / f'bins_{ano}.parquet')
        e = e.merge(h[CHAVE + BINS + ['n_logs', 'contingencia']], on=CHAVE, how='inner')
        votos_log = e[BINS].sum(axis=1)
        # seção entra se o log do dia conta os mesmos eleitores do BU (±5): sem isso, uma seção cujo pacote perdeu o log
        # de uma das urnas teria o perfil de horário de meio dia só (PROTOCOLO.md v1.1)
        e = e[(votos_log >= 20) & ((votos_log - e.t2_comp).abs() <= 5)].copy()
    e = e.sort_values(LOC + ['section']).reset_index(drop=True)    # prédios contíguos e aninhados em zona/município/UF
    e['place'] = e.groupby(LOC, sort=False).ngroup()
    e['k'] = e.groupby('place').section.transform('size')
    e = e[e.k >= 3].sort_values('place', kind='stable').reset_index(drop=True)
    e['ctl_logn'] = np.log(e.n2)
    e['ctl_manual'] = (e.t2_manual / e.t2_comp).fillna(0)
    e['ctl_dcomp'] = (e.t2_comp / e.t2_aptos - e.t1_comp / e.t1_aptos).fillna(0)
    e['ctl_tx'] = (e.t2_comp / e.t2_aptos).fillna(0)
    e['ctl_tx2'] = e.ctl_tx ** 2
    e['ctl_tx3'] = e.ctl_tx ** 3
    e['ctl_logaptos'] = np.log(e.t2_aptos.clip(lower=1))
    e['sinal_t1'] = np.sign(2 * e.t1_X / e.n1 - 1).replace(0, 1)   # quem liderava na seção no 1º turno: +1 PT, -1 adversário
    e['sinal_tx'] = e.sinal_t1 * e.ctl_tx
    e['sinal_tx2'] = e.sinal_t1 * e.ctl_tx2
    faixa = pd.qcut(e.ctl_tx.rank(method='first'), 12, labels=False)
    for i in range(1, 12):
        e[f'ctl_txb{i}'] = (faixa == i).astype(float)
    return e


def res_m1(e, t2_X, t2_Y, com_z=False):
    """Resíduo do modelo do local (padroes_lib.modelo_local) em pontos, recalculado para contagens t2_X/t2_Y.
    com_z: devolve também o resíduo de Pearson z = (observado - previsto) / desvio binomial, que vale ~1 de
    variância se a seção fosse só ruído de amostragem em torno do previsto (escala Poisson/binomial do ruído)."""
    n2 = t2_X + t2_Y
    g = pd.DataFrame({'place': e.place, 'x1': e.t1_X, 'n1': e.n1, 'x2': t2_X, 'n2': n2}).groupby('place')
    S1X, S1N, S2X, S2N = (g[c].transform('sum').to_numpy() for c in ('x1', 'n1', 'x2', 'n2'))
    p = np.clip(expit(_lg(e.t1_X, e.n1) + _lg(S2X - t2_X, S2N - n2) - _lg(S1X - e.t1_X, S1N - e.n1)), EPS, 1 - EPS)
    res = 100 * (t2_X / n2 - p)
    if not com_z:
        return res
    z = (t2_X / n2 - p) / np.sqrt(p * (1 - p) / np.maximum(n2, 1))
    return np.asarray(res, float), np.asarray(z, float)


def limite_bonferroni(m, alfa=0.05):
    return float(abs(np.sqrt(2) * erfinv(1 - alfa / m)))


class Teste:
    """Coeficiente de y (resíduo) em cada coluna de X (exposição à regra), tudo centrado no prédio, com controles
    (Frisch-Waugh) e erro-padrão robusto agrupado por prédio. X chega em blocos de colunas (gerador), para não
    segurar na memória as ~2.000 janelas × 450 mil seções."""

    def __init__(self, e, controles=CONTROLES):
        self.place = e.place.to_numpy()
        self.starts = np.r_[0, np.flatnonzero(np.diff(self.place)) + 1]
        C = e[controles].to_numpy(float) if controles else np.zeros((len(e), 0))
        self.C0 = self._centra(C)
        self.C1 = self._centra(np.c_[C, e[SINAL].to_numpy(float)])   # teste de inversão: + sinal de quem liderava
        self.C = self.C0
        self.n = len(e)

    def _centra(self, M):
        M = np.asarray(M, float)
        if M.ndim == 1:
            M = M[:, None]
        soma = np.add.reduceat(M, self.starts, axis=0)
        cnt = np.diff(np.r_[self.starts, len(M)])[:, None]
        return M - np.repeat(soma / cnt, cnt[:, 0], axis=0)

    def _res_ctl(self, M):
        if self.C.shape[1] == 0:
            return M
        return M - self.C @ np.linalg.lstsq(self.C, M, rcond=None)[0]

    def yres(self, y, sinal=None):
        """Resíduo (centrado no prédio, controles descontados) de y; com sinal, usa os controles do teste de inversão."""
        self.C = self.C0 if sinal is None else self.C1
        return self._res_ctl(self._centra(y))[:, 0]

    def residualiza(self, X, sinal=None):
        """Exposição (× sinal, na inversão) centrada no prédio e com os controles descontados."""
        self.C = self.C0 if sinal is None else self.C1
        Xs = X if sinal is None else X * sinal[:, None]
        return self._res_ctl(self._centra(Xs))

    def roda(self, y, blocos, sinal=None):
        """y (n,); blocos: iterável de matrizes (n, m_k) de exposição; sinal (n,) multiplica a exposição (inversão).
        -> DataFrame com beta (pontos por 100% de exposição), ep, t, exposição média, seções expostas."""
        yr = self.yres(y, sinal)
        out = []
        for X in blocos:
            Xr = self.residualiza(X, sinal)
            sxx = (Xr ** 2).sum(0)
            sxx = np.where(sxx > 0, sxx, np.nan)
            beta = (Xr * yr[:, None]).sum(0) / sxx
            u = np.add.reduceat(Xr * (yr[:, None] - Xr * beta), self.starts, axis=0)
            ep = np.sqrt((u ** 2).sum(0)) / sxx
            out.append(pd.DataFrame({'beta_pp': beta, 'ep_pp': ep, 't': beta / ep, 'exposicao_media': X.mean(0),
                                     'secoes_expostas': (X > 0).sum(0)}))
        return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- janelas de horário
def janelas_grade():
    return [(s, t) for s in range(NB) for t in range(s + 1, NB + 1)]


def _hhmm(i):
    m = int(GRADE[i])
    return f'{m // 60:02d}:{m % 60:02d}'


class Exposicoes:
    """Fração dos votos da seção dentro de cada janela [s, t) da grade, calculada por blocos de janelas."""

    def __init__(self, e, jan, H=None):
        H = e[BINS].to_numpy(float) if H is None else H
        self.tot = H.sum(1)
        self.Cum = np.c_[np.zeros(len(H)), np.cumsum(H, 1)]
        self.jan = jan

    def coluna(self, k):
        s, t = self.jan[k]
        return (self.Cum[:, t] - self.Cum[:, s]) / self.tot

    def nao_expostas(self):
        """Por janela, quantas seções têm voto fora dela (exposição < 1)."""
        return np.array([int((self.coluna(k) < 1).sum()) for k in range(len(self.jan))])

    def blocos(self, passo=PASSO):
        for i in range(0, len(self.jan), passo):
            yield np.column_stack([self.coluna(k) for k in range(i, min(i + passo, len(self.jan)))])


def _planta(e, x, regra, onde=None, com_z=False):
    """Aplica a regra à fração x dos votos de cada seção (vizinhas incluídas) e devolve o resíduo M1 recalculado.
    onde: máscara das seções em que a regra está ativa (None = todas)."""
    ativo = np.ones(len(e), bool) if onde is None else onde
    xa = np.where(ativo, x, 0.0)
    A, B = e.t2_X.to_numpy(float), e.t2_Y.to_numpy(float)
    Aw, Bw = xa * A, xa * B
    if regra == '2_para_1':                              # metade dos votos do adversário na janela vira voto do PT
        A2, B2 = A + 0.5 * Bw, B - 0.5 * Bw
    elif regra == 'inversao':                            # na janela, os votos trocam de lado
        A2, B2 = A - Aw + Bw, B - Bw + Aw
    else:
        raise ValueError(regra)
    r = res_m1(e, np.round(A2), np.round(B2), com_z)
    return r if com_z else np.asarray(r, float)


FRACAO_MINIMA = 0.01   # janela válida: pelo menos 1% das seções com voto dentro dela e 1% com voto fora dela


def _acertou(X, k_achado, k_plantado):
    """A janela achada é a plantada, ou uma vizinha cuja exposição é quase a mesma (corr >= 0,98: fora do horário
    de votação as janelas se confundem, p.ex. 16:00–17:00 e 16:00–17:45)."""
    if k_achado == k_plantado:
        return True
    return bool(np.corrcoef(X.coluna(k_achado), X.coluna(k_plantado))[0, 1] >= .98)


def _varre(T, y, X, jan, sinal=None):
    r = T.roda(y, X.blocos(), sinal)
    r.insert(0, 'fim', [_hhmm(t) for _, t in jan])
    r.insert(0, 'inicio', [_hhmm(s) for s, _ in jan])
    r['duracao_min'] = [15 * (t - s) for s, t in jan]
    # janelas em que quase ninguém (ou quase todo mundo) tem voto não medem nada: uma seção isolada vira o "efeito"
    r['secoes_nao_expostas'] = X.nao_expostas()
    r['valida'] = (r.secoes_expostas >= FRACAO_MINIMA * T.n) & (r.secoes_nao_expostas >= FRACAO_MINIMA * T.n)
    r.loc[~r.valida, 't'] = np.nan
    return r


def janelas(ano):
    OUT.mkdir(parents=True, exist_ok=True)
    e = prepara(ano)
    jan = janelas_grade()
    X = Exposicoes(e, jan)
    print(ano, 'seções', len(e), '| prédios', e.place.nunique(), '| janelas', len(jan), '| contingência',
          int(e.contingencia.sum()), flush=True)
    T = Teste(e)
    y = e.res_pp.to_numpy(float)
    saida = []
    for tipo, sinal in (('deslocamento', None), ('inversao', e.sinal_t1.to_numpy(float))):
        r = _varre(T, y, X, jan, sinal)
        r['tipo'] = tipo
        r['ano'] = ano
        r['limite_bonferroni'] = limite_bonferroni(2 * int(r.valida.sum()))
        saida.append(r)
        top = r.reindex(r.t.abs().sort_values(ascending=False).index).head(8)
        print(f'--- {tipo}: {int(r.valida.sum())} janelas válidas | máx |t| = {r.t.abs().max():.2f} (limite {r.limite_bonferroni[0]:.2f})', flush=True)
        print(top[['inicio', 'fim', 'beta_pp', 'ep_pp', 't', 'exposicao_media', 'secoes_expostas']].round(3).to_string(index=False), flush=True)
    s = pd.concat(saida, ignore_index=True)
    s.to_csv(OUT / f'janelas_{ano}.csv', **CSV)
    return s


def plantadas(ano=2026, seed=0):
    """Regras plantadas em cópias de 2026: a varredura acha a janela certa? com que t?"""
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    e = prepara(ano)
    jan = janelas_grade()
    X = Exposicoes(e, jan)
    T = Teste(e)
    sinal = e.sinal_t1.to_numpy(float)
    idx = {(_hhmm(s), _hhmm(t)): k for k, (s, t) in enumerate(jan)}
    cenarios = []
    for ini, fim in (('14:00', '15:00'), ('10:00', '12:00'), ('16:00', '17:00'), ('08:00', '08:30'), ('12:00', '12:15')):
        k = idx[(ini, fim)]
        x = X.coluna(k)
        for regra in ('2_para_1', 'inversao'):
            for onde_nome, onde in (('país', None), ('20% das seções', rng.random(len(e)) < .2), ('só MG', (e.uf == 'MG').to_numpy())):
                y = _planta(e, x, regra, onde)
                r = _varre(T, y, X, jan, sinal if regra == 'inversao' else None)
                j = int(r.t.abs().idxmax())
                cenarios.append(dict(regra=regra, onde=onde_nome, janela_plantada=f'{ini}–{fim}', exposicao_media_pct=round(100 * x.mean(), 2),
                                     t_na_janela_plantada=round(float(r.t[k]), 1), beta_na_janela_pp=round(float(r.beta_pp[k]), 2),
                                     janela_encontrada=f'{r.inicio[j]}–{r.fim[j]}', t_maximo=round(float(r.t.abs().max()), 1),
                                     acertou_janela=_acertou(X, j, k)))
                print(cenarios[-1], flush=True)
    c = pd.DataFrame(cenarios)
    c.to_csv(OUT / 'janelas_plantadas.csv', **CSV)
    return c


# ---------------------------------------------------------------- regras por volume (só BU)
def _expo_volume(e):
    comp = e.t2_comp.to_numpy(float)
    aptos = e.t2_aptos.to_numpy(float)
    cols, X = [], []
    for N in range(50, 401, 25):
        cols.append(('a partir do voto N', N))
        X.append(np.clip(comp - N, 0, None) / comp)
    for p in np.arange(.30, .951, .05):
        cols.append(('a partir de p% dos aptos', int(round(100 * p))))
        X.append(np.clip(comp - p * aptos, 0, None) / comp)
    for k in range(10, 101, 10):
        cols.append(('só os últimos k votos', k))
        X.append(np.minimum(k, comp) / comp)
    return cols, np.column_stack(X)


def _curva_comparecimento(e, ano):
    """Resíduo médio (centrado no prédio) por faixa de comparecimento relativo ao prédio: a relação suave que
    as exposições por volume carregam."""
    g = e.groupby('place')
    d = pd.DataFrame({'res': e.res_pp - g.res_pp.transform('mean'), 'tx': e.ctl_tx - g.ctl_tx.transform('mean')})
    d['faixa'] = pd.cut(d.tx, [-1, -.1, -.05, -.02, -.01, 0, .01, .02, .05, .1, 1])
    c = d.groupby('faixa', observed=True).res.agg(['mean', 'sem', 'size']).reset_index()
    c.columns = ['comparecimento_menos_predio', 'residuo_medio_pp', 'ep_pp', 'secoes']
    c['ano'] = ano
    return c


def volume(seed=0):
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    saida, plant, curvas = [], [], []
    for ano in (2022, 2026):
        e = prepara(ano, com_bins=False)
        curvas.append(_curva_comparecimento(e, ano))
        cols, X = _expo_volume(e)
        sinal = e.sinal_t1.to_numpy(float)
        y = e.res_pp.to_numpy(float)
        for ctl_nome, ctl in (('controles básicos', CONTROLES), ('+ comparecimento suave', SUAVES), ('+ comparecimento flexível', FLEX)):
            T = Teste(e, ctl)
            for tipo, sg in (('deslocamento', None), ('inversao', sinal)):
                r = T.roda(y, [X], sg)
                r.insert(0, 'parametro', [c[1] for c in cols])
                r.insert(0, 'regra', [c[0] for c in cols])
                r['tipo'] = tipo
                r['controles'] = ctl_nome
                r['ano'] = ano
                saida.append(r)
                for regra, g in r.groupby('regra', sort=False):
                    j = int(g.t.abs().idxmax())
                    print(ano, ctl_nome, tipo, '|', regra, '| máx |t|:', round(float(g.t.abs().max()), 2), 'em', g.parametro[j],
                          '| beta', round(float(g.beta_pp[j]), 2), flush=True)
        if ano == 2026:                                   # cópias plantadas: a varredura acha a regra e o parâmetro? (controles suaves, os do relatório)
            T = Teste(e, SUAVES)
            for (regra, par) in (('a partir do voto N', 200), ('a partir do voto N', 300), ('a partir de p% dos aptos', 60), ('só os últimos k votos', 30)):
                k = cols.index((regra, par))
                for tipo in ('2_para_1', 'inversao'):
                    for onde_nome, onde in (('país', None), ('20% das seções', rng.random(len(e)) < .2)):
                        yy = _planta(e, X[:, k], tipo, onde)
                        rr = T.roda(yy, [X], sinal if tipo == 'inversao' else None)
                        j = int(rr.t.abs().idxmax())
                        plant.append(dict(tipo=tipo, onde=onde_nome, regra_plantada=regra, parametro=par, exposicao_media_pct=round(100 * X[:, k].mean(), 2),
                                          t_na_regra_plantada=round(float(rr.t[k]), 1), beta_pp=round(float(rr.beta_pp[k]), 2),
                                          regra_encontrada=f'{cols[j][0]} = {cols[j][1]}', t_maximo=round(float(rr.t.abs().max()), 1)))
                        print(plant[-1], flush=True)
    s = pd.concat(saida, ignore_index=True)
    s['limite_bonferroni'] = limite_bonferroni(2 * len(cols))
    s.to_csv(OUT / 'volume_real.csv', **CSV)
    pd.DataFrame(plant).to_csv(OUT / 'volume_plantado.csv', **CSV)
    pd.concat(curvas, ignore_index=True).to_csv(OUT / 'curva_comparecimento.csv', **CSV)
    return s


# ---------------------------------------------------------------- padrões não lineares, mistura e agrupamentos
# A reta "resíduo × exposição" no país inteiro só enxerga uma regra que valha em (quase) toda parte e na proporção
# da exposição. Três outras formas de a mesma regra aparecer:
#   curvatura  - a resposta por decil de exposição não é uma reta (regra com limiar, ou só acima de certa exposição);
#   dispersão  - a regra vale num subconjunto de seções sem marca territorial: a média quase não anda, mas as seções
#                expostas ficam mais espalhadas que o ruído binomial/Poisson esperado (mistura de duas populações);
#   agrupamento - a regra vale num território (UF, zona, município): a varredura refaz a reta dentro de cada grupo.
NIVEIS = {'UF': ['uf'], 'zona': ['uf', 'zone'], 'município': ['uf', 'municipality']}
MIN_PREDIOS = 30          # grupo entra na varredura por agrupamento com pelo menos 30 prédios (erro-padrão agrupado)


def _t_equivalente(p):
    """|t| de um teste normal bilateral com o mesmo p (põe qui-quadrado e t na mesma régua)."""
    return float(norm.isf(max(float(p), 1e-300) / 2))


def _ols1(xr, yr, starts):
    """Coeficiente de yr em xr (já centrados no prédio e com controles descontados), erro-padrão agrupado por prédio."""
    sxx = float((xr ** 2).sum())
    if sxx <= 0:
        return np.nan, np.nan, np.nan
    beta = float((xr * yr).sum() / sxx)
    u = np.add.reduceat(xr * (yr - xr * beta), starts)
    ep = float(np.sqrt((u ** 2).sum()) / sxx)
    return beta, ep, beta / ep


class Agrupamentos:
    """Coeficiente da exposição dentro de cada grupo (UF, zona, município) com erro-padrão agrupado por prédio.
    Os grupos não precisam ser contíguos: somas por np.bincount sobre o id do grupo."""

    def __init__(self, e, T):
        self.T = T
        self.niveis = {}
        for nome, cols in NIVEIS.items():
            gid = e.groupby(cols, sort=False).ngroup().to_numpy()
            gid_predio = gid[T.starts]
            primeiro = np.unique(gid, return_index=True)[1]
            rot = e[cols].astype(str).agg(' '.join, axis=1).to_numpy()[primeiro]
            self.niveis[nome] = dict(gid=gid, gid_predio=gid_predio, predios=np.bincount(gid_predio),
                                     secoes=np.bincount(gid), rotulo=rot)

    def t_por_grupo(self, x, xr, yr, nome):
        """x: exposição bruta (valida o grupo: dentro dele, pelo menos 10% das seções e 30 delas com voto dentro da janela
        e outras tantas com voto fora; senão a variação da exposição no grupo se concentra em meia dúzia de seções e o t
        explode sem medir nada). xr, yr: já centrados no prédio e com controles descontados."""
        g = self.niveis[nome]
        den = np.bincount(g['gid'], xr * xr)
        den = np.where(den > 0, den, np.nan)
        beta = np.bincount(g['gid'], xr * yr) / den
        u = np.add.reduceat(xr * (yr - xr * beta[g['gid']]), self.T.starts)
        ep = np.sqrt(np.bincount(g['gid_predio'], u * u)) / den
        with np.errstate(divide='ignore', invalid='ignore'):
            t = np.where(ep > 0, beta / ep, np.nan)
        minimo = np.maximum(MIN_PREDIOS, .1 * g['secoes'])
        ok = (g['predios'] >= MIN_PREDIOS) & (np.bincount(g['gid'], x > 0) >= minimo) & (np.bincount(g['gid'], x < 1) >= minimo)
        t[~ok] = np.nan
        return beta, ep, t

    def n_grupos(self, nome):
        return int((self.niveis[nome]['predios'] >= MIN_PREDIOS).sum())

    def melhor(self, x, xr, yr, nome, top=1):
        """Grupo(s) de maior |t| no nível: lista de dicts (o primeiro é o máximo)."""
        beta, ep, t = self.t_por_grupo(x, xr, yr, nome)
        if np.all(np.isnan(t)):
            return []
        g = self.niveis[nome]
        ordem = np.argsort(-np.nan_to_num(np.abs(t), nan=-1))[:top]
        return [dict(nivel=nome, grupo=str(g['rotulo'][j]), beta_pp=float(beta[j]), ep_pp=float(ep[j]), t=float(t[j]),
                     secoes=int(g['secoes'][j]), predios=int(g['predios'][j])) for j in ordem if np.isfinite(t[j])]


def _curvatura(T, x, yr, sinal=None):
    """Resposta por decil de exposição (× sinal, na inversão), dentro do prédio e com controles, ALÉM da reta:
    Wald agrupado por prédio dos contrastes de decil dado o termo linear (qui-quadrado; decis empatados, p.ex. muitas
    seções com exposição zero, são fundidos, e os graus de liberdade caem junto).
    Devolve (estatísticas, perfil por decil: exposição residual média, resíduo médio, seções)."""
    xs = x if sinal is None else x * sinal
    dec = pd.qcut(xs, 10, labels=False, duplicates='drop')
    K = int(dec.max()) + 1
    D = (dec[:, None] == np.arange(1, K)[None, :]).astype(float)
    T.C = T.C0 if sinal is None else T.C1
    Mr = T._res_ctl(T._centra(np.c_[xs, D]))
    b = np.linalg.lstsq(Mr, yr, rcond=None)[0]
    r = yr - Mr @ b
    S = np.add.reduceat(Mr * r[:, None], T.starts, axis=0)
    XtX_inv = np.linalg.pinv(Mr.T @ Mr)
    V = XtX_inv @ (S.T @ S) @ XtX_inv
    bq, Vq = b[1:], V[1:, 1:]
    gl = int(np.linalg.matrix_rank(Vq)) if len(bq) else 0
    W = float(bq @ np.linalg.pinv(Vq) @ bq) if gl else 0.0
    p = float(chi2.sf(W, gl)) if gl else 1.0
    cnt = np.bincount(dec, minlength=K)
    perfil = pd.DataFrame({'decil': np.arange(1, K + 1), 'exposicao_residual_media': np.bincount(dec, Mr[:, 0], K) / cnt,
                           'residuo_medio_pp': np.bincount(dec, yr, K) / cnt, 'secoes': cnt, 'beta_linear_pp': float(b[0])})
    return dict(wald_curvatura=W, gl_curvatura=gl, p_curvatura=p, t_curvatura=_t_equivalente(p)), perfil


def _chegada(e, T, ano):
    """Processo de chegada: índice de dispersão das contagens de 15 min de cada seção em torno da curva do prédio
    (sem a própria seção). Poisson puro daria 1; filas e horários próprios dão mais. Serve para ver se o ritmo de
    votação de 2026 tem seções fora do padrão e se isso anda com o resíduo. (Uma troca de candidato no voto não
    muda a chegada; isso mede só inserção/remoção de votos e ritmo.)"""
    H = e[BINS].to_numpy(float)
    tot = H.sum(1)
    cnt = np.diff(np.r_[T.starts, len(e)])
    idx = np.repeat(np.arange(len(T.starts)), cnt)
    E = np.add.reduceat(H, T.starts, axis=0)[idx] - H                    # curva do prédio sem a seção
    E *= (tot / np.maximum(E.sum(1), 1))[:, None]                         # esperado da seção, bin a bin
    m = E >= 1
    q = np.where(m, (H - E) ** 2 / np.where(m, E, 1), 0).sum(1)
    del E, H
    gl = m.sum(1) - 1
    D = np.where(gl >= 10, q / np.maximum(gl, 1), np.nan)
    ok = np.isfinite(D)
    xl = np.log(np.clip(np.where(ok, D, np.nanmedian(D)), .05, None))
    r = T.roda(e.res_pp.to_numpy(float), [xl[:, None]])
    qs = np.nanquantile(D, [.1, .5, .9, .99])
    resumo = dict(ano=ano, secoes=int(ok.sum()), D_q10=qs[0], D_mediana=qs[1], D_q90=qs[2], D_q99=qs[3],
                  fracao_D_maior_2=float(np.nanmean(D > 2)), fracao_D_maior_3=float(np.nanmean(D > 3)),
                  beta_res_por_logD_pp=float(r.beta_pp[0]), t=float(r.t[0]))
    hist = pd.DataFrame({'ano': ano, 'D_de': np.arange(0, 8, .25), 'D_ate': np.arange(.25, 8.25, .25)})
    hist['secoes'] = [int(((D >= a) & (D < b)).sum()) for a, b in zip(hist.D_de, hist.D_ate)]
    return resumo, hist


def _validas(X, n):
    return [k for k in range(len(X.jan)) if (X.coluna(k) > 0).sum() >= FRACAO_MINIMA * n and (X.coluna(k) < 1).sum() >= FRACAO_MINIMA * n]


def clusters(ano):
    """Para cada janela válida e cada tipo: reta, dispersão (z² × exposição), curvatura por decil e melhor grupo por nível."""
    OUT.mkdir(parents=True, exist_ok=True)
    e = prepara(ano)
    jan = janelas_grade()
    X = Exposicoes(e, jan)
    T = Teste(e)
    A = Agrupamentos(e, T)
    validas = _validas(X, T.n)
    y = e.res_pp.to_numpy(float)
    _, z = res_m1(e, e.t2_X.to_numpy(float), e.t2_Y.to_numpy(float), com_z=True)
    z2 = z ** 2
    print(ano, 'seções', T.n, '| janelas válidas', len(validas), '| var(z) =', round(float(z.var()), 2),
          '| grupos:', {k: A.n_grupos(k) for k in NIVEIS}, flush=True)
    linhas, perfis = [], []
    for tipo, sinal in (('deslocamento', None), ('inversao', e.sinal_t1.to_numpy(float))):
        yr, z2r = T.yres(y, sinal), T.yres(z2, sinal)
        for k in validas:
            x = X.coluna(k)
            xr = T.residualiza(x[:, None], sinal)[:, 0]
            bl, el, tl = _ols1(xr, yr, T.starts)
            bd, ed, td = _ols1(xr, z2r, T.starts)
            c, perfil = _curvatura(T, x, yr, sinal)
            linha = dict(tipo=tipo, ano=ano, inicio=_hhmm(jan[k][0]), fim=_hhmm(jan[k][1]), duracao_min=15 * (jan[k][1] - jan[k][0]),
                         secoes_expostas=int((x > 0).sum()), exposicao_media=float(x.mean()), beta_pp=bl, t_linear=tl,
                         beta_dispersao=bd, t_dispersao=td, **c)
            for nome in NIVEIS:
                m = A.melhor(x, xr, yr, nome)
                m = m[0] if m else dict(grupo='', beta_pp=np.nan, t=np.nan, secoes=0, predios=0)
                linha.update({f'grupo_{nome}': m['grupo'], f'beta_{nome}': m['beta_pp'], f't_{nome}': m['t'], f'secoes_{nome}': m['secoes']})
            linhas.append(linha)
            perfil['tipo'], perfil['ano'], perfil['inicio'], perfil['fim'] = tipo, ano, linha['inicio'], linha['fim']
            perfis.append(perfil)
    L = pd.DataFrame(linhas)
    L['limite_janelas'] = limite_bonferroni(2 * len(validas))
    for nome in NIVEIS:
        L[f'limite_{nome}'] = limite_bonferroni(2 * len(validas) * A.n_grupos(nome))
    L.to_csv(OUT / f'clusters_{ano}.csv', **CSV)
    P = pd.concat(perfis, ignore_index=True)
    P.to_csv(OUT / f'perfis_{ano}.csv', **CSV)
    resumo, hist = _chegada(e, T, ano)
    pd.DataFrame([resumo]).to_csv(OUT / f'chegada_{ano}.csv', **CSV)
    hist.to_csv(OUT / f'chegada_hist_{ano}.csv', **CSV)
    for tipo, g in L.groupby('tipo'):
        print(f'--- {tipo}: máx |t| reta {g.t_linear.abs().max():.1f} | dispersão {g.t_dispersao.abs().max():.1f} | curvatura {g.t_curvatura.max():.1f}'
              f' (limite {g.limite_janelas.iloc[0]:.2f})', flush=True)
        for nome in NIVEIS:
            j = g[f't_{nome}'].abs().idxmax()
            print(f'    {nome}: máx |t| {abs(g.loc[j, f"t_{nome}"]):.1f} em {g.loc[j, f"grupo_{nome}"]} ({g.loc[j, "inicio"]}–{g.loc[j, "fim"]}),'
                  f' limite {g.loc[j, f"limite_{nome}"]:.2f}', flush=True)
    print('chegada:', {k: (round(v, 3) if isinstance(v, float) else v) for k, v in resumo.items()}, flush=True)
    return L


def clusters_plantadas(ano=2026, seed=0):
    """Regras plantadas em cópias de 2026 com forma de cluster: subconjunto aleatório de seções (20%, 5%), 30 zonas,
    só acima de um limiar de exposição; o que cada teste (reta, dispersão, curvatura, agrupamento) enxerga."""
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    e = prepara(ano)
    jan = janelas_grade()
    X = Exposicoes(e, jan)
    T = Teste(e)
    A = Agrupamentos(e, T)
    validas = _validas(X, T.n)
    sinal_t1 = e.sinal_t1.to_numpy(float)
    idx = {(_hhmm(s), _hhmm(t)): k for k, (s, t) in enumerate(jan)}
    zona_id = A.niveis['zona']['gid']
    zonas_plantadas = rng.choice(np.flatnonzero(A.niveis['zona']['predios'] >= MIN_PREDIOS), 30, replace=False)
    rot_zonas = set(A.niveis['zona']['rotulo'][zonas_plantadas])
    sorteio20, sorteio5 = rng.random(T.n) < .2, rng.random(T.n) < .05
    saida = []
    for ini, fim in (('14:00', '15:00'), ('16:00', '17:00')):
        k = idx[(ini, fim)]
        x = X.coluna(k)
        limiar = x > np.quantile(x, .7)
        for regra in ('2_para_1', 'inversao'):
            sinal = sinal_t1 if regra == 'inversao' else None
            for onde_nome, onde in (('país', None), ('20% das seções', sorteio20), ('5% das seções', sorteio5),
                                    ('30 zonas', np.isin(zona_id, zonas_plantadas)), ('só exposição > p70', limiar)):
                y2, z2 = _planta(e, x, regra, onde, com_z=True)
                yr, z2r = T.yres(y2, sinal), T.yres(z2 ** 2, sinal)
                xr = T.residualiza(x[:, None], sinal)[:, 0]
                _, _, tl = _ols1(xr, yr, T.starts)
                _, _, td = _ols1(xr, z2r, T.starts)
                c, _ = _curvatura(T, x, yr, sinal)
                linha = dict(regra=regra, onde=onde_nome, janela_plantada=f'{ini}–{fim}', secoes_com_regra=int(T.n if onde is None else onde.sum()),
                             t_linear=tl, t_dispersao=td, t_curvatura=c['t_curvatura'])
                for nome in NIVEIS:
                    top = A.melhor(x, xr, yr, nome, top=10)
                    linha[f't_{nome}'] = top[0]['t'] if top else np.nan
                    linha[f'grupo_{nome}'] = top[0]['grupo'] if top else ''
                    if nome == 'zona':
                        linha['zonas_plantadas_no_top10'] = sum(m['grupo'] in rot_zonas for m in top)
                # varredura completa (reta e zona) nas janelas válidas: a janela achada é a plantada?
                melhor_reta, melhor_zona = (0, None), (0, None, '')
                for kk in validas:
                    x_kk = X.coluna(kk)
                    xk = T.residualiza(x_kk[:, None], sinal)[:, 0]
                    _, _, t = _ols1(xk, yr, T.starts)
                    if abs(t) > melhor_reta[0]:
                        melhor_reta = (abs(t), kk)
                    m = A.melhor(x_kk, xk, yr, 'zona')
                    if m and abs(m[0]['t']) > melhor_zona[0]:
                        melhor_zona = (abs(m[0]['t']), kk, m[0]['grupo'])
                linha.update(t_max_reta_grade=melhor_reta[0], janela_reta=f'{_hhmm(jan[melhor_reta[1]][0])}–{_hhmm(jan[melhor_reta[1]][1])}',
                             acertou_reta=_acertou(X, melhor_reta[1], k), t_max_zona_grade=melhor_zona[0],
                             janela_zona=f'{_hhmm(jan[melhor_zona[1]][0])}–{_hhmm(jan[melhor_zona[1]][1])}', zona_achada=melhor_zona[2],
                             acertou_zona=_acertou(X, melhor_zona[1], k) and (melhor_zona[2] in rot_zonas))
                saida.append(linha)
                print({a: (round(b, 1) if isinstance(b, float) else b) for a, b in linha.items()}, flush=True)
    S = pd.DataFrame(saida)
    S['limite_janelas'] = limite_bonferroni(2 * len(validas))
    S['limite_zona'] = limite_bonferroni(2 * len(validas) * A.n_grupos('zona'))
    S.to_csv(OUT / 'clusters_plantados.csv', **CSV)
    return S


# ---------------------------------------------------------------- nulo por permutação dentro do prédio (PROTOCOLO.md, seção 5)
NPERM = 60


class GruposBloco:
    """Agrupamento vetorizado: t por grupo para um bloco de janelas de uma vez (matrizes esparsas grupo × seção e
    grupo × prédio). Mesmas regras de validade de Agrupamentos.t_por_grupo."""

    def __init__(self, e, T):
        self.T = T
        n, npred = len(e), len(T.starts)
        self.niveis = {}
        for nome, cols in NIVEIS.items():
            gid = e.groupby(cols, sort=False).ngroup().to_numpy()
            ng = int(gid.max()) + 1
            gid_predio = gid[T.starts]
            rot = e[cols].astype(str).agg(' '.join, axis=1).to_numpy()[np.unique(gid, return_index=True)[1]]
            g = dict(gid=gid, rotulo=rot, ok_predios=np.bincount(gid_predio, minlength=ng) >= MIN_PREDIOS,
                     minimo=np.maximum(MIN_PREDIOS, .1 * np.bincount(gid, minlength=ng)))
            if np.all(np.diff(gid) >= 0):                    # grupos contíguos (UF, município): somas por reduceat
                g['starts'] = np.r_[0, np.flatnonzero(np.diff(gid)) + 1]
                g['starts_predio'] = np.r_[0, np.flatnonzero(np.diff(gid_predio)) + 1]
            else:                                             # zona cruza municípios: matrizes esparsas
                g['G'] = csr_matrix((np.ones(n), (gid, np.arange(n))), shape=(ng, n))
                g['Gp'] = csr_matrix((np.ones(npred), (gid_predio, np.arange(npred))), shape=(ng, npred))
            self.niveis[nome] = g

    @staticmethod
    def _soma(g, M, predio=False):
        if 'G' in g:
            return np.asarray((g['Gp'] if predio else g['G']) @ M)
        return np.add.reduceat(M, g['starts_predio'] if predio else g['starts'], axis=0)

    def t(self, X, Xr, yr, nome):
        """X, Xr: (n, m) exposição bruta e residualizada; yr: (n,). -> |t| (grupos, m), NaN onde o grupo não vale."""
        g = self.niveis[nome]
        gid = g['gid']
        den = self._soma(g, Xr * Xr)
        den = np.where(den > 0, den, np.nan)
        beta = self._soma(g, Xr * yr[:, None]) / den
        u = np.add.reduceat(Xr * (yr[:, None] - Xr * beta[gid]), self.T.starts, axis=0)
        ep = np.sqrt(self._soma(g, u * u, predio=True)) / den
        with np.errstate(divide='ignore', invalid='ignore'):
            t = np.where(ep > 0, beta / ep, np.nan)
        ok = (g['ok_predios'][:, None] & (self._soma(g, (X > 0).astype(float)) >= g['minimo'][:, None])
              & (self._soma(g, (X < 1).astype(float)) >= g['minimo'][:, None]))
        t[~ok] = np.nan
        return t


def _maximos(T, GB, X, validas, yr, z2r, sinal_t1):
    """Máximo de |t| sobre as janelas válidas, por tipo: reta, dispersão e cada nível de agrupamento.
    yr, z2r: dicionários tipo -> vetor já residualizado. Devolve dict tipo -> (máximos, onde)."""
    out = {}
    for tipo, sinal in (('deslocamento', None), ('inversao', sinal_t1)):
        y1, y2 = yr[tipo], z2r[tipo]
        mx = {k: 0.0 for k in ['reta', 'dispersao'] + list(NIVEIS)}
        onde = {k: '' for k in mx}
        for i in range(0, len(validas), PASSO):
            ks = validas[i:i + PASSO]
            Xb = np.column_stack([X.coluna(k) for k in ks])
            Xr = T.residualiza(Xb, sinal)
            sxx = (Xr ** 2).sum(0)
            for nome, yy in (('reta', y1), ('dispersao', y2)):
                beta = (Xr * yy[:, None]).sum(0) / sxx
                u = np.add.reduceat(Xr * (yy[:, None] - Xr * beta), T.starts, axis=0)
                t = np.abs(beta / (np.sqrt((u ** 2).sum(0)) / sxx))
                j = int(np.nanargmax(t))
                if t[j] > mx[nome]:
                    mx[nome], onde[nome] = float(t[j]), f'{_hhmm(X.jan[ks[j]][0])}–{_hhmm(X.jan[ks[j]][1])}'
            for nv in NIVEIS:
                t = np.abs(GB.t(Xb, Xr, y1, nv))
                if np.all(np.isnan(t)):
                    continue
                jg, jc = np.unravel_index(int(np.nanargmax(t)), t.shape)
                if t[jg, jc] > mx[nv]:
                    mx[nv] = float(t[jg, jc])
                    onde[nv] = f'{GB.niveis[nv]["rotulo"][jg]} ({_hhmm(X.jan[ks[jc]][0])}–{_hhmm(X.jan[ks[jc]][1])})'
        out[tipo] = (mx, onde)
    return out


def permutacao(ano, nperm=NPERM, seed=0):
    """Embaralha o vetor de horários entre as seções do mesmo prédio e refaz a varredura inteira; guarda o máximo
    de |t| de cada família em cada permutação (permutação 0 = dado real). Retomável: continua o CSV existente."""
    OUT.mkdir(parents=True, exist_ok=True)
    e = prepara(ano)
    jan = janelas_grade()
    T = Teste(e)
    GB = GruposBloco(e, T)
    H = e[BINS].to_numpy(float)
    X0 = Exposicoes(e, jan, H)
    validas = _validas(X0, T.n)
    y = e.res_pp.to_numpy(float)
    _, z = res_m1(e, e.t2_X.to_numpy(float), e.t2_Y.to_numpy(float), com_z=True)
    sinal_t1 = e.sinal_t1.to_numpy(float)
    yr = {'deslocamento': T.yres(y), 'inversao': T.yres(y, sinal_t1)}
    z2r = {'deslocamento': T.yres(z ** 2), 'inversao': T.yres(z ** 2, sinal_t1)}
    place = e.place.to_numpy()
    rng = np.random.default_rng(seed)
    arq = OUT / f'permutacao_{ano}.csv'
    feitas = pd.read_csv(arq, **CSV_LE) if arq.exists() else pd.DataFrame()
    prontas = set(feitas.permutacao) if len(feitas) else set()
    print(ano, 'seções', T.n, '| janelas válidas', len(validas), '| permutações prontas', len(prontas), flush=True)
    linhas = [feitas] if len(feitas) else []
    for p in range(nperm + 1):
        chaves = place + rng.random(T.n) if p else None            # a sequência do gerador anda mesmo nas prontas
        if p in prontas:
            continue
        X = X0 if p == 0 else Exposicoes(e, jan, H[np.argsort(chaves, kind='stable')])
        res = _maximos(T, GB, X, validas, yr, z2r, sinal_t1)
        novas = pd.DataFrame([dict(ano=ano, permutacao=p, tipo=tipo, familia=fam, max_abs_t=mx[fam], onde=onde[fam])
                              for tipo, (mx, onde) in res.items() for fam in mx])
        linhas.append(novas)
        pd.concat(linhas, ignore_index=True).to_csv(arq, **CSV)
        print(f'permutação {p}:', ' | '.join(f'{t[:4]} {f} {v:.1f}' for t, (mx, _) in res.items() for f, v in mx.items()), flush=True)
    S = pd.concat(linhas, ignore_index=True)
    real, nulo = S[S.permutacao == 0], S[S.permutacao > 0]
    if len(nulo):
        lim = nulo.groupby(['tipo', 'familia']).max_abs_t.quantile(.95).rename('limite_p95')
        print(real.merge(lim, on=['tipo', 'familia'])[['tipo', 'familia', 'max_abs_t', 'onde', 'limite_p95']].round(2).to_string(index=False), flush=True)
    return S


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    prioridade_baixa()
    if cmd == 'coleta':
        coleta(int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 2)
    elif cmd == 'coleta_corrige':
        coleta_corrige(int(sys.argv[2]))
    elif cmd == 'janelas':
        janelas(int(sys.argv[2]))
    elif cmd == 'plantadas':
        plantadas()
    elif cmd == 'volume':
        volume()
    elif cmd == 'clusters':
        clusters(int(sys.argv[2]))
    elif cmd == 'clusters_plantadas':
        clusters_plantadas()
    elif cmd == 'permutacao':
        permutacao(int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else NPERM)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
