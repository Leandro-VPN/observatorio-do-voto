"""Decodifica RDV e BU (ASN.1/BER) de 2022 e 2026 e reduz os dois ao mesmo formato
{cod_cargo: Counter(rotulo -> quantidade)}, para conferir, voto a voto, se o total do BU e
igual a soma dos votos individuais do RDV da mesma urna. Reaproveita o parser de t2_2026_collect.

RDV: lista embaralhada de votos individuais. Cada voto SEQ(tipo, valor-ascii):
     tipo 2 = nominal (valor = numero), 3 = branco, 4 = nulo.
BU : totais por votavel. Cada votavel SEQ(C1=tipo, C2=quantidade[, C3=numero]):
     tipo 1 = nominal, 2 = branco, 3 = nulo, 4 = legenda.
Em ambos o cargo e o C1 (contexto-1) irmao da lista; cargo 1 = Presidente.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t2_2026_collect import tree, ival, sval  # noqa: E402


def _cod(v):
    """codigo do cargo = primeiro contexto-1 primitivo entre os irmaos; senao ultimo U2."""
    for c in v:
        if c[0] == 2 and c[1] == 1 and not isinstance(c[2], list):
            return ival(c[2])
    u2 = [c for c in v if c[0] == 0 and c[1] == 2 and not isinstance(c[2], list)]
    return ival(u2[-1][2]) if u2 else None


def _rdv_votelist(v):
    return isinstance(v, list) and len(v) > 0 and all(
        isinstance(c[2], list) and len(c[2]) >= 1 and c[2][0][0] == 0 and c[2][0][1] == 10 for c in v)


def _votavel(c):
    """Folha de total do BU: SEQ com C1(tipo) e C2(quantidade); demais filhos primitivos,
    exceto um C3 (numero) que e uma SEQ curta de primitivos. Sem sub-SEQ grande."""
    k = c[2]
    if not isinstance(k, list):
        return False
    if not (any(x[0] == 2 and x[1] == 1 and not isinstance(x[2], list) for x in k)
            and any(x[0] == 2 and x[1] == 2 and not isinstance(x[2], list) for x in k)):
        return False
    for x in k:
        if isinstance(x[2], list):
            if not (x[0] == 2 and x[1] == 3 and all(not isinstance(y[2], list) for y in x[2])):
                return False
    return True


def _bu_totais(v):
    return isinstance(v, list) and len(v) > 0 and all(_votavel(c) for c in v)


def votos_rdv(raw):
    res = {}

    def walk(node):
        v = node[2]
        if not isinstance(v, list):
            return
        vls = [c for c in v if _rdv_votelist(c[2])]
        if vls:
            cod = _cod(v)
            cnt = res.setdefault(cod, Counter())
            for vl in vls:
                for voto in vl[2]:
                    kids = voto[2]
                    tipo = ival(kids[0][2])
                    if tipo in (1, 2) and len(kids) > 1:
                        cnt['v' + sval(kids[1][2])] += 1
                    elif tipo == 3:
                        cnt['branco'] += 1
                    else:
                        # 4 = nulo; 6 = subtipo de nulo que o BU agrega em "nulo".
                        # Para Presidente (sem legenda) todo nao-nominal/nao-branco e nulo.
                        cnt['nulo'] += 1
            return
        for c in v:
            walk(c)

    walk(tree(raw)[0])
    return res


def votos_bu(raw):
    res = {}

    def walk(node):
        v = node[2]
        if not isinstance(v, list):
            return
        tot = [c for c in v if _bu_totais(c[2])]
        if tot:
            cod = _cod(v)
            cnt = res.setdefault(cod, Counter())
            for lst in tot:
                for votavel in lst[2]:
                    k = votavel[2]
                    tipo = next(ival(x[2]) for x in k if x[0] == 2 and x[1] == 1)
                    qtd = next(ival(x[2]) for x in k if x[0] == 2 and x[1] == 2)
                    num = None
                    for x in k:
                        if x[0] == 2 and x[1] == 3 and isinstance(x[2], list):
                            ints = [ival(y[2]) for y in x[2] if not isinstance(y[2], list)]
                            num = ints[0] if ints else None
                    if tipo == 1:
                        cnt['v' + str(num)] += qtd
                    elif tipo == 2:
                        cnt['branco'] += qtd
                    elif tipo == 3:
                        cnt['nulo'] += qtd
                    elif tipo == 4:
                        cnt['legenda_v' + str(num)] += qtd
                    else:
                        cnt[f't{tipo}'] += qtd
            return
        for c in v:
            walk(c)

    walk(tree(raw)[0])
    return res


def compara(bu_raw, rdv_raw, cargos=(1,)):
    """Confere os cargos pedidos (padrao: so Presidente, cod 1). Retorna (ok, difs, total_bu, total_rdv)."""
    b, r = votos_bu(bu_raw), votos_rdv(rdv_raw)
    difs = []
    tb = tr = 0
    for cod in cargos:
        cb, cr = b.get(cod, Counter()), r.get(cod, Counter())
        tb += sum(cb.values())
        tr += sum(cr.values())
        for rot in sorted(set(cb) | set(cr)):
            if cb.get(rot, 0) != cr.get(rot, 0):
                difs.append((cod, rot, cb.get(rot, 0), cr.get(rot, 0)))
    return (not difs), difs, tb, tr


if __name__ == '__main__':
    sc = Path('C:/Users/LeandroM/AppData/Local/Temp/claude/F--votos/e9fca4d2-1d59-469c-9ad1-6692ecd8c184/scratchpad')
    bu = (sc / 'pa_bu.dat').read_bytes()
    rdv = (sc / 'pa_rdv.dat').read_bytes()
    print('BU todos cargos :', {k: dict(v) for k, v in votos_bu(bu).items()})
    print('RDV todos cargos:', {k: dict(v) for k, v in votos_rdv(rdv).items()})
    print('confere (presidente):', compara(bu, rdv))
    d = Path('F:/votos/research/segundo_turno_2026/teste')  # confirma que 2026 ainda funciona
    print('2026 confere:', compara((d / 'o03221ba3005801880295-bu.dat').read_bytes(),
                                   (d / 'o03221ba3005801880295-rdv.dat').read_bytes()))
