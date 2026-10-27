"""2026 2nd round (pleito 3221, 25/10/2026) from the TSE results system (resultados.tse.jus.br), before the open-data packages exist.

Subcommands:
  mun  UF...   municipal results (presidente T1 e6257 / T2 e6258): electorate, turnout, abstention, votes  -> research/segundo_turno_2026/mun/<UF>.parquet
  bu   UF...   every section's BU (bu.dat, ASN.1/BER) decoded: aptos, comparecimento, abertura/encerramento, habilitação, votes per candidate
               -> research/segundo_turno_2026/bu/<UF>.parquet (raw bu.dat kept as bytes column)
  logs UF...   urn logs for sections that closed at or after 17:10 (BU), all sections of Salvador/Feira de Santana/Lauro de Freitas (BA),
               and a 3% random control sample; parsed with the same engine -> research/segundo_turno_2026/logs/<UF>/ + ops_<UF>.parquet
"""
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

BASE = 'https://resultados.tse.jus.br/oficial/ele2026'
PLEITO = '3221'
OUT = Path('research/segundo_turno_2026')
ALL_UFS = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']
BA_CITIES = {'38490', '35157', '36854'}  # Salvador, Feira de Santana, Lauro de Freitas (cities named in the petition)
_local = threading.local()


def client():
    if not hasattr(_local, 'c'):
        _local.c = httpx.Client(timeout=60, limits=httpx.Limits(max_connections=8, max_keepalive_connections=8))
    return _local.c


class Limiter:
    """Global adaptive rate limiter: on HTTP 429 every thread pauses and the rate drops 25%; it creeps back up 5% per quiet minute."""
    def __init__(self, rate=30.0):
        self.rate, self.lock, self.next_t, self.pause_until, self.last_429, self.hits429 = rate, threading.Lock(), time.time(), 0.0, time.time(), 0

    def wait(self):
        with self.lock:
            now = time.time()
            if now < self.pause_until:
                self.next_t = max(self.next_t, self.pause_until)
            if now - self.last_429 > 60 and self.rate < 60:
                self.rate *= 1.05
                self.last_429 = now
            t = max(now, self.next_t)
            self.next_t = t + 1.0 / self.rate
        time.sleep(max(0.0, t - time.time()))

    def throttled(self):
        with self.lock:
            now = time.time()
            if now > self.pause_until:
                self.rate = max(4.0, self.rate * .75)
                self.pause_until = now + 150
                self.hits429 += 1
                print(f'429: pausing 150 s, rate -> {self.rate:.1f} req/s', flush=True)
            self.last_429 = now


LIMIT = Limiter()


def get(url, kind='json', tries=6):
    for a in range(tries):
        LIMIT.wait()
        try:
            r = client().get(url)
            if r.status_code == 200 and r.content.strip():
                return r.json() if kind == 'json' else r.content
            if r.status_code == 429:
                LIMIT.throttled()
                continue
            if r.status_code == 404 and a >= 1:
                return None
        except Exception:
            pass
        time.sleep(1.0 * (a + 1))
    return None


def sections(uf):
    cfg = get(f'{BASE}/arquivo-urna/{PLEITO}/config/{uf.lower()}/{uf.lower()}-p00{PLEITO}-cs.json')
    (OUT / 'config').mkdir(parents=True, exist_ok=True)
    (OUT / 'config' / f'{uf}-cs.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
    return [(mu['cd'], mu['nm'], z['cd'], s['ns'], s.get('da'), s.get('ha')) for ab in cfg['abr'] for mu in ab['mu'] for z in mu['zon'] for s in z['sec']]


# ------------------------------------------------------------------ BER decoding of the BU
def _tlv(b, i):
    t = b[i]
    i += 1
    cls, cons, num = t >> 6, bool(t & 0x20), t & 0x1f
    if num == 0x1f:
        num = 0
        while True:
            x = b[i]
            i += 1
            num = (num << 7) | (x & 0x7f)
            if not x & 0x80:
                break
    ln = b[i]
    i += 1
    if ln & 0x80:
        k = ln & 0x7f
        ln = int.from_bytes(b[i:i + k], 'big')
        i += k
    return cls, cons, num, i, ln


def _is_der(v):
    """True when an OCTET STRING holds exactly one well-formed nested SEQUENCE (signatures/hashes may start with 0x30 by chance)."""
    try:
        _, _, _, s, ln = _tlv(v, 0)
        if s + ln != len(v):
            return False
        tree(v)
        return True
    except Exception:
        return False


def tree(b, i=0, end=None):
    end = len(b) if end is None else end
    out = []
    while i < end:
        cls, cons, num, s, ln = _tlv(b, i)
        if s + ln > end:
            raise ValueError('TLV overruns parent')
        v = b[s:s + ln]
        if cons:
            out.append((cls, num, tree(b, s, s + ln)))
        elif cls == 0 and num == 4 and ln > 2 and v[0] == 0x30 and _is_der(v):
            out.append((cls, num, tree(v)))
        else:
            out.append((cls, num, v))
        i = s + ln
    return out


def ival(v):
    return int.from_bytes(v, 'big', signed=True)


def sval(v):
    return v.decode('latin1')


def decode_bu(raw):
    env = tree(raw)[0][2]
    bu = next(x for x in env if x[0] == 0 and x[1] == 4)[2][0][2]
    rec = {}
    idx = [x for x in bu if x[0] == 0 and x[1] == 16]
    # identificacaoSecao: SEQ(SEQ(mun, zona), local, secao)
    for x in bu:
        if x[0] == 0 and x[1] == 16 and len(x[2]) == 3 and x[2][0][1] == 16 and x[2][1][1] == 2:
            rec['municipality'], rec['zone'] = ival(x[2][0][2][0][2]), ival(x[2][0][2][1][2])
            rec['voting_place'], rec['section'] = ival(x[2][1][2]), ival(x[2][2][2])
            break
    for x in bu:
        if x[0] == 2 and x[1] == 0 and len(x[2]) == 2 and x[2][0][1] == 27:
            rec['opening'], rec['closing'] = sval(x[2][0][2]), sval(x[2][1][2])
        if x[0] == 2 and x[1] == 1 and all(y[1] == 2 for y in x[2]):
            vals = [ival(y[2]) for y in x[2]]
            for k, v in enumerate(vals):
                rec[f'hab_{k}'] = v
    ints = [ival(x[2]) for x in bu if x[0] == 0 and x[1] == 2]
    rec['comparecimento_bu'] = ints[0] if ints else None
    # resultadosVotacaoPorEleicao
    for x in bu:
        if x[0] == 0 and x[1] == 16 and x[2] and x[2][0][1] == 16 and x[2][0][2] and x[2][0][2][0][1] == 2 and len(x[2][0][2]) >= 4:
            for el in x[2]:
                f = el[2]
                eid = ival(f[0][2])
                rec[f'e{eid}_aptos'] = ival(f[1][2])
                for res in [y for y in f if y[1] == 16]:
                    for rv in res[2]:
                        g = rv[2]
                        comp = [ival(y[2]) for y in g if y[0] == 0 and y[1] == 2]
                        if comp:
                            rec[f'e{eid}_comparecimento'] = comp[0]
                        for tot in [y for y in g if y[1] == 16]:
                            for cargo in tot[2]:
                                h = cargo[2]
                                cod = ival(h[0][2])
                                for vv in [y for y in h if y[1] == 16]:
                                    for vot in vv[2]:
                                        q = {(y[0], y[1]): y[2] for y in vot[2]}
                                        tipo = ival(q[(2, 1)])
                                        n = ival(q[(2, 2)])
                                        if tipo == 1 and (2, 3) in q:
                                            num = ival(q[(2, 3)][1][2]) if isinstance(q[(2, 3)], list) else None
                                            key = f'e{eid}_c{cod}_v{num}'
                                        else:
                                            key = f'e{eid}_c{cod}_' + {2: 'branco', 3: 'nulo', 4: 'legenda'}.get(tipo, f't{tipo}')
                                        rec[key] = rec.get(key, 0) + n
            break
    return rec


# ------------------------------------------------------------------ commands
def cmd_bu(uf):
    random.seed(hash(uf) % 100000)
    dest = OUT / 'bu' / f'{uf}.parquet'
    if dest.exists():
        print(uf, 'SKIP', flush=True)
        return
    secs = sections(uf)
    def job(t):
        mu, nm, z, s, da, ha = t
        B = f'{BASE}/arquivo-urna/{PLEITO}/dados/{uf.lower()}/{mu}/{z}/{s}'
        aux = get(f'{B}/p00{PLEITO}-{uf.lower()}-m{mu}-z{z}-s{s}-aux.json')
        rec = dict(uf=uf, mun_cd=mu, municipality_name=nm, zone_cd=z, section_cd=s, receipt_date=da, receipt_time=ha)
        if not aux:
            rec['status'] = 'NO_AUX'
            return rec
        h = aux['hashes'][-1]
        rec.update(n_hashes=len(aux['hashes']), aux_status=aux.get('st'), hash=h['hash'], hash_status=h.get('st'), hash_time=h.get('hr'),
                   log_name=next((a['nm'] for a in h['arq'] if a['tp'] == 'log'), None))
        bun = next((a['nm'] for a in h['arq'] if a['tp'] == 'bu'), None)
        raw = get(f'{B}/{h["hash"]}/{bun}', kind='bytes') if bun else None
        if not raw:
            rec['status'] = 'NO_BU'
            return rec
        rec['bu_raw'] = raw
        try:
            rec.update(decode_bu(raw))
            rec['status'] = 'OK'
        except Exception as exc:
            rec['status'] = 'DECODE_ERROR ' + repr(exc)[:80]
            return rec
        # fetch the urn log for late-closing sections, the three BA cities of the petition, and a 3% random control sample
        try:
            hh, mm, ss = int(rec['closing'][9:11]), int(rec['closing'][11:13]), int(rec['closing'][13:15])
            close_min = hh * 60 + mm + ss / 60 - 1020
        except Exception:
            close_min = None
        why = 'late' if close_min is not None and close_min >= 10 else ('ba_city' if (uf == 'BA' and mu in BA_CITIES) else ('control' if random.random() < .03 else None))
        rec['log_why'] = why
        if why and rec.get('log_name'):
            folder = OUT / 'logs' / uf
            folder.mkdir(parents=True, exist_ok=True)
            lp = folder / rec['log_name']
            if not lp.exists():
                lraw = get(f'{B}/{h["hash"]}/{rec["log_name"]}', kind='bytes')
                if lraw:
                    lp.write_bytes(lraw)
            rec['log_saved'] = lp.exists()
        return rec
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(24) as ex:
        for i, r in enumerate(ex.map(job, secs), 1):
            rows.append(r)
            if i % 2000 == 0:
                print(uf, i, len(secs), round(i / (time.time() - t0), 1), 'sec/s', flush=True)
    d = pd.DataFrame(rows)
    dest.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(dest, index=False)
    print(uf, 'BU DONE', len(d), d.status.value_counts().to_dict(), flush=True)


def cmd_mun(uf):
    dest = OUT / 'mun' / f'{uf}.parquet'
    if dest.exists():
        print(uf, 'SKIP', flush=True)
        return
    cfg_path = OUT / 'config' / f'{uf}-cs.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8')) if cfg_path.exists() else get(f'{BASE}/arquivo-urna/{PLEITO}/config/{uf.lower()}/{uf.lower()}-p00{PLEITO}-cs.json')
    muns = [(mu['cd'], mu['nm']) for ab in cfg['abr'] for mu in ab['mu']]
    def job(m):
        cd, nm = m
        rec = dict(uf=uf, mun_cd=cd, municipality_name=nm)
        for t, e in (('t1', '6257'), ('t2', '6258')):
            j = get(f'{BASE}/{e}/dados/{uf.lower()}/{uf.lower()}{cd}-c0001-e00{e}-u.json')
            if not j:
                continue
            ee = j.get('e', {})
            rec.update({f'{t}_eleitorado': int(ee.get('te', 0) or 0), f'{t}_comparecimento': int(ee.get('c', 0) or 0), f'{t}_abstencao': int(ee.get('a', 0) or 0),
                        f'{t}_secoes': int(j.get('s', {}).get('ts', 0) or 0)})
            v = j.get('v', {})
            rec[f'{t}_validos'] = int(v.get('vvc', 0) or 0)
            for cg in j.get('carg', []):
                for ag in cg.get('agr', []):
                    for p in ag.get('par', []):
                        for cand in p.get('cand', []):
                            rec[f'{t}_v{cand["n"]}'] = int(cand.get('vap', 0) or 0)
        return rec
    with ThreadPoolExecutor(16) as ex:
        rows = list(ex.map(job, muns))
    d = pd.DataFrame(rows)
    dest.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(dest, index=False)
    print(uf, 'MUN DONE', len(d), flush=True)


def cmd_logs(uf):
    import sys as _s
    _s.path.insert(0, 'scripts')
    bu = pd.read_parquet(OUT / 'bu' / f'{uf}.parquet', columns=['mun_cd', 'zone_cd', 'section_cd', 'hash', 'log_name', 'closing', 'status'])
    bu = bu[bu.status == 'OK'].copy()
    t = pd.to_datetime(bu.closing, format='%Y%m%dT%H%M%S', errors='coerce')
    bu['close_min'] = t.dt.hour * 60 + t.dt.minute + t.dt.second / 60 - 1020
    random.seed(20261025)
    late = bu.close_min >= 10
    city = (uf == 'BA') & bu.mun_cd.isin(BA_CITIES)
    ctrl = bu.index.isin(random.sample(list(bu.index[~late & ~city]), k=max(1, int(.03 * (~late & ~city).sum()))))
    sel = bu[late | city | ctrl].copy()
    sel['why'] = ['late' if l else ('ba_city' if c else 'control') for l, c in zip(late[late | city | ctrl], city[late | city | ctrl])]
    folder = OUT / 'logs' / uf
    folder.mkdir(parents=True, exist_ok=True)
    def job(r):
        p = folder / r.log_name
        if not p.exists():
            raw = get(f'{BASE}/arquivo-urna/{PLEITO}/dados/{uf.lower()}/{r.mun_cd}/{r.zone_cd}/{r.section_cd}/{r.hash}/{r.log_name}', kind='bytes')
            if not raw:
                return 'NO_LOG'
            p.write_bytes(raw)
        return 'OK'
    with ThreadPoolExecutor(24) as ex:
        st = list(ex.map(job, sel.itertuples()))
    sel['log_status'] = st
    sel.drop(columns=['status']).to_parquet(OUT / f'logsel_{uf}.parquet', index=False)
    print(uf, 'LOGS DONE', len(sel), pd.Series(st).value_counts().to_dict(), sel.why.value_counts().to_dict(), flush=True)


def cmd_fixlogs(uf):
    """Download logs for late / BA-city sections whose BU failed the first decoder (no log fetched then)."""
    b = pd.read_parquet(OUT / 'bu' / f'{uf}.parquet', columns=['mun_cd', 'zone_cd', 'section_cd', 'hash', 'log_name', 'status', 'bu_raw'])
    b = b[b.status.astype(str).str.startswith('DECODE') & b.log_name.notna()]
    folder = OUT / 'logs' / uf
    folder.mkdir(parents=True, exist_ok=True)
    todo = []
    for r in b.itertuples():
        rec = decode_bu(r.bu_raw)
        c = rec.get('closing', '')
        late = len(c) >= 15 and (int(c[9:11]) * 60 + int(c[11:13])) >= 1030
        if (late or (uf == 'BA' and r.mun_cd in BA_CITIES)) and not (folder / r.log_name).exists():
            todo.append(r)
    def job(r):
        raw = get(f'{BASE}/arquivo-urna/{PLEITO}/dados/{uf.lower()}/{r.mun_cd}/{r.zone_cd}/{r.section_cd}/{r.hash}/{r.log_name}', kind='bytes')
        if raw:
            (folder / r.log_name).write_bytes(raw)
        return bool(raw)
    with ThreadPoolExecutor(8) as ex:
        ok = sum(ex.map(job, todo))
    print(uf, 'FIXLOGS', len(todo), 'ok', ok, flush=True)


if __name__ == '__main__':
    cmd, ufs = sys.argv[1], [u.upper() for u in sys.argv[2:]] or ALL_UFS
    for uf in ufs:
        try:
            {'bu': cmd_bu, 'mun': cmd_mun, 'logs': cmd_logs, 'fixlogs': cmd_fixlogs}[cmd](uf)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print(uf, cmd, 'FAILED', repr(exc)[:150], flush=True)
    print(cmd.upper(), 'ALL DONE', flush=True)
