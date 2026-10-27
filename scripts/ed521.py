"""Verificador EdDSA Ed521 (curva E-521, ICP-Brasil DOC-ICP-01.01), independente.

Parametros: p = 2^521-1, x^2 + y^2 = 1 + d x^2 y^2 com d = -376014, ordem L, base (Gx, 12),
hash SHAKE256 com 132 bytes, dom = b'SigEd521' + phflag(0) + len(ctx)(0), codificacao little-endian
de 66 bytes com o bit de sinal de x no bit mais alto do ultimo byte (mesmo esquema do Ed448/RFC 8032).
Verificacao: [S]B == R + [k]A, k = SHAKE256(dom || R || A || M) mod L.
"""
import hashlib

try:
    import gmpy2
    mpz = gmpy2.mpz
except ImportError:  # funciona sem gmpy2, apenas mais devagar
    mpz = int

P = mpz(2) ** 521 - 1
D = mpz(-376014) % P
L = mpz(1716199415032652428745475199770348304317358825035826352348615864796385795849413675475876651663657849636693659065234142604319282948702542317993421293670108523)
GX = mpz(1571054894184995387535939749894317568645297350402905821437625181152304994381188529632591196067604100772673927915114267193389905003276673749012051148356041324)
GY = mpz(12)
DOM = b'SigEd521\x00\x00'
SIZE = 66


def _inv(a):
    return pow(a, P - 2, P)


def _recover_x(y, sign):
    yy = y * y % P
    xx = (1 - yy) * _inv((1 - D * yy) % P) % P
    x = pow(xx, (P + 1) // 4, P)
    if x * x % P != xx:
        return None
    if int(x & 1) != sign:
        x = (P - x) % P
    return x


def decode_point(b):
    if len(b) != SIZE:
        return None
    v = bytearray(b)
    sign = v[-1] >> 7
    v[-1] &= 0x7F
    y = mpz(int.from_bytes(v, 'little'))
    if y >= P:
        return None
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, mpz(1), x * y % P)


# coordenadas estendidas (X, Y, Z, T), a = 1
def _add(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = x1 * x2 % P
    b = y1 * y2 % P
    c = D * t1 % P * t2 % P
    d = z1 * z2 % P
    e = ((x1 + y1) * (x2 + y2) - a - b) % P
    f = (d - c) % P
    g = (d + c) % P
    h = (b - a) % P
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _dbl(p):
    x1, y1, z1, _ = p
    a = x1 * x1 % P
    b = y1 * y1 % P
    c = 2 * z1 * z1 % P
    e = ((x1 + y1) * (x1 + y1) - a - b) % P
    g = (a + b) % P
    f = (g - c) % P
    h = (a - b) % P
    return (e * f % P, g * h % P, f * g % P, e * h % P)


ZERO = (mpz(0), mpz(1), mpz(1), mpz(0))
B = (GX, GY, mpz(1), GX * GY % P)


def _mul2(s1, p1, s2, p2):
    """s1*p1 + s2*p2 (truque de Shamir)."""
    p12 = _add(p1, p2)
    r = ZERO
    for i in range(max(int(s1).bit_length(), int(s2).bit_length()) - 1, -1, -1):
        r = _dbl(r)
        b1 = (s1 >> i) & 1
        b2 = (s2 >> i) & 1
        if b1 and b2:
            r = _add(r, p12)
        elif b1:
            r = _add(r, p1)
        elif b2:
            r = _add(r, p2)
    return r


def _neg(p):
    x, y, z, t = p
    return ((P - x) % P, y, z, (P - t) % P)


def _is_zero(p):
    x, y, z, _ = p
    return x % P == 0 and (y - z) % P == 0


def verify(pub, msg, sig):
    """True se sig (132 bytes) e uma assinatura Ed521 valida de msg sob a chave pub (66 bytes)."""
    if len(sig) != 2 * SIZE or len(pub) != SIZE:
        return False
    A = decode_point(pub)
    R = decode_point(sig[:SIZE])
    if A is None or R is None:
        return False
    s = mpz(int.from_bytes(sig[SIZE:], 'little'))
    if s >= L:
        return False
    k = mpz(int.from_bytes(hashlib.shake_256(DOM + sig[:SIZE] + pub + msg).digest(2 * SIZE), 'little')) % L
    # [S]B - [k]A - R == 0
    q = _add(_mul2(s, B, k, _neg(A)), _neg(R))
    return _is_zero(q)


def _selftest():
    assert (GX * GX + GY * GY - 1 - D * GX * GX % P * GY * GY) % P == 0, 'base fora da curva'


_selftest()
