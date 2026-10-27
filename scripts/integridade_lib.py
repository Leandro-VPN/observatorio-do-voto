"""Conferencia independente dos arquivos de assinatura da urna (.vscmr / -vota.vsc).

O que se confere, por urna:
  1. SHA-512 de cada arquivo (log, BU, RDV, imagem do BU) == hash listado no manifesto;
  2. assinatura de HARDWARE (chave da urna, guardada no modulo de seguranca) sobre cada hash:
     - urnas UE2009..UE2015 (AC URNA): ECDSA P-521 com SHA-512 aplicado ao hash;
     - urnas UE2020/UE2022 (AC UE2020 / AC UE2022): Ed521 (ICP-Brasil) sobre SHA-512(hash);
  3. certificado da urna emitido pela AC indicada (assinatura da AC sobre o TBSCertificate),
     com os certificados das ACs do pacote oficial do TSE (formato-arquivos-bu-rdv-ass-digital).
O autenticador SipHash de cada linha do log usa chave secreta do TSE e nao e verificavel por terceiros.
"""
import base64
import hashlib
import re
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

import ed521
from t2_2026_collect import tree

OID_ED521 = '1.3.6.1.4.1.44588.2.1'
_OID_ED521_DER = bytes.fromhex('060a2b0601040182dc2c0201')
AC_DIR = Path(__file__).resolve().parents[1] / 'research' / 'integridade' / 'ac'


# ---------------------------------------------------------------- DER minimo
def _tlv(b, i):
    tag = b[i]; i += 1
    if tag & 0x1F == 0x1F:
        while b[i] & 0x80:
            i += 1
        i += 1
    ln = b[i]; i += 1
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(b[i:i + n], 'big'); i += n
    return tag, i, i + ln  # tag, inicio do conteudo, fim


def _children(b, start, end):
    out = []
    i = start
    while i < end:
        tag, s, e = _tlv(b, i)
        out.append((tag, i, s, e))
        i = e
    return out


def split_cert(der):
    """(tbs_bytes, sig_alg_oid_bytes, signature_bytes) de um certificado DER."""
    _, s, e = _tlv(der, 0)
    tbs, alg, sig = _children(der, s, e)[:3]
    tbs_bytes = der[tbs[1]:tbs[3]]
    sig_bits = der[sig[2]:sig[3]][1:]  # BIT STRING sem o byte de bits nao usados
    alg_oid = der[alg[2]:alg[3]]
    return tbs_bytes, alg_oid, sig_bits


def ed521_pubkey_from_der(der):
    for m in re.finditer(re.escape(_OID_ED521_DER), der):
        j = m.end()
        if der[j:j + 3] == b'\x03\x43\x00':
            return der[j + 3:j + 69]
        if der[j:j + 5] == b'\x05\x00\x03\x43\x00':
            return der[j + 5:j + 71]
    return None


def _cn(name_obj):
    try:
        return name_obj.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
    except Exception:
        return None


class CertInfo:
    __slots__ = ('der', 'subject_cn', 'issuer_cn', 'not_before', 'not_after', 'alg', 'pub', 'sha256')


def load_cert(der):
    c = CertInfo()
    c.der = der
    c.sha256 = hashlib.sha256(der).hexdigest()
    cert = x509.load_der_x509_certificate(der)
    c.subject_cn = _cn(cert.subject)
    c.issuer_cn = _cn(cert.issuer)
    c.not_before = cert.not_valid_before_utc
    c.not_after = cert.not_valid_after_utc
    pk = ed521_pubkey_from_der(der)
    if pk is not None:  # SubjectPublicKeyInfo Ed521 (OID seguido da BIT STRING de 67 bytes)
        c.alg = 'Ed521'; c.pub = pk
    else:
        c.alg = 'ECDSA-P521'; c.pub = cert.public_key()
    return c


@lru_cache(maxsize=None)
def ac_certs():
    out = {}
    for p in sorted(AC_DIR.glob('*.pem')):
        pem = p.read_bytes()
        der = base64.b64decode(b''.join(pem.split(b'-----')[2].split()))
        info = load_cert(der)
        out[info.subject_cn] = info
    return out


def verify_sig(cert, msg_hash, sig):
    """Assinatura de hardware de um arquivo: msg_hash = SHA-512 do arquivo (64 bytes)."""
    if cert.alg == 'Ed521':
        if not isinstance(sig, (bytes, bytearray)) or len(sig) != 132:
            return False
        return ed521.verify(cert.pub, hashlib.sha512(msg_hash).digest(), bytes(sig))
    if isinstance(sig, tuple):
        der = utils.encode_dss_signature(*sig)
    elif len(sig) == 132:
        der = utils.encode_dss_signature(int.from_bytes(sig[:66], 'big'), int.from_bytes(sig[66:], 'big'))
    else:
        der = bytes(sig)
    try:
        cert.pub.verify(der, msg_hash, ec.ECDSA(hashes.SHA512()))
        return True
    except (InvalidSignature, ValueError):
        return False


_chain_cache = {}


def verify_chain(cert):
    """(ac_nome, ok) - assinatura da AC sobre o certificado da urna."""
    key = cert.sha256
    if key in _chain_cache:
        return _chain_cache[key]
    acs = ac_certs()
    ac = acs.get(cert.issuer_cn)
    if ac is None:
        res = (cert.issuer_cn, None)
    else:
        tbs, _, sig = split_cert(cert.der)
        if ac.alg == 'Ed521':
            ok = ed521.verify(ac.pub, tbs, sig)
        else:
            try:
                ac.pub.verify(sig, tbs, ec.ECDSA(hashes.SHA512())); ok = True
            except InvalidSignature:
                ok = False
        res = (ac.subject_cn, ok)
    _chain_cache[key] = res
    return res


# ---------------------------------------------------------------- manifesto
def _find_cert_der(raw):
    m = re.search(rb'-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----', raw, re.S)
    if m:
        return base64.b64decode(b''.join(m.group(1).split()))
    for mm in re.finditer(rb'\x30\x82(..)\x30\x82..\xa0\x03\x02\x01\x02', raw, re.S):
        ln = int.from_bytes(mm.group(1), 'big')
        der = raw[mm.start():mm.start() + 4 + ln]
        try:
            x509.load_der_x509_certificate(der)
            return der
        except Exception:
            continue
    return None


def _str(v):
    return v.decode('latin-1') if isinstance(v, (bytes, bytearray)) else None


def parse_manifest(raw):
    """dict: blocks=[{user, when, entries:{nome:(hash, sig)}}], cert_der."""
    top = tree(raw)[0][2]
    blocks = []
    for c, n, v in top:
        if not isinstance(v, list):
            continue
        user = None; when = None; entries = {}
        for c2, n2, v2 in v:
            if n2 == 27 and isinstance(v2, (bytes, bytearray)) and when is None and len(v2) == 15:
                when = _str(v2)
            if isinstance(v2, list) and len(v2) == 4 and isinstance(v2[0][2], list) and user is None:
                try:
                    user = _str(v2[0][2][0][2])
                except Exception:
                    pass
            if c2 == 0 and n2 == 4 and isinstance(v2, list):
                try:
                    lst = v2[0][2][0][2]
                    for e in lst:
                        name = _str(e[2][0][2]); trip = e[2][1][2]
                        h = trip[1][2]; s = trip[2][2]
                        if isinstance(s, list):  # ECDSA DER decodificado pelo tree: SEQ{r,s}
                            seq = s[0][2]
                            s = (int.from_bytes(seq[0][2], 'big'), int.from_bytes(seq[1][2], 'big'))
                        entries[name] = (bytes(h), s)
                except Exception:
                    pass
        if user is not None:
            blocks.append({'user': user, 'when': when, 'entries': entries})
    return {'blocks': blocks, 'cert_der': _find_cert_der(raw)}


def hw_block(man):
    for b in man['blocks']:
        if b['user'] and b['user'].upper().startswith('UEAO'):
            return b
    return None


def suffix_of(name):
    """Tipo do arquivo pelo nome (2022: .logjez/.bu; 2024+: -log.jez/-bu.dat)."""
    n = name.lower()
    for k, tags in (('log', ('.logjez', '-log.jez')), ('bu', ('.bu', '-bu.dat')), ('rdv', ('.rdv', '-rdv.dat')),
                    ('imgbu', ('.imgbu', '-imgbu.dat'))):
        if n.endswith(tags):
            return k
    return None


def check_urn(manifest_raw, files):
    """files: {tipo: bytes} (log, bu, rdv, imgbu, presentes). Retorna dict de resultados."""
    r = {'manifest_ok': False}
    try:
        man = parse_manifest(manifest_raw)
    except Exception as exc:
        r['erro'] = 'manifesto: %s' % exc
        return r
    hw = hw_block(man)
    sw = [b for b in man['blocks'] if b is not hw]
    if hw is None or man['cert_der'] is None:
        r['erro'] = 'sem bloco de hardware ou certificado'
        return r
    r['manifest_ok'] = True
    r['assinado_em'] = hw['when']
    try:
        cert = load_cert(man['cert_der'])
    except Exception as exc:
        r['erro'] = 'certificado: %s' % exc
        return r
    r['cert_cn'] = cert.subject_cn
    r['cert_emissor'] = cert.issuer_cn
    r['cert_alg'] = cert.alg
    r['cert_sha256'] = cert.sha256
    r['cert_validade_fim'] = cert.not_after.isoformat()
    ac, ok = verify_chain(cert)
    r['cadeia_ac'] = ac
    r['cadeia_ok'] = ok
    hw_by_type = {suffix_of(k): (k, v) for k, v in hw['entries'].items() if suffix_of(k)}
    sw_by_type = {}
    for b in sw:
        for k, v in b['entries'].items():
            if suffix_of(k):
                sw_by_type[suffix_of(k)] = v[0]
    r['n_arquivos_manifesto'] = len(hw['entries'])
    for t, data in files.items():
        if data is None:
            continue
        h = hashlib.sha512(data).digest()
        ent = hw_by_type.get(t)
        if ent is None:
            r[t + '_no_manifesto'] = False
            continue
        r[t + '_no_manifesto'] = True
        r[t + '_hash_ok'] = (h == ent[1][0])
        r[t + '_hash_sw_ok'] = (h == sw_by_type.get(t)) if len(sw_by_type.get(t) or b'') == 64 else None
        r[t + '_assinatura_ok'] = verify_sig(cert, ent[1][0], ent[1][1])
    return r
