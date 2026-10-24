"""Exploratory leave-one-out scoring. Scores are not calibrated probabilities."""
from __future__ import annotations

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

VERSION = "loo-moments-1.0.0"
ALTERNATIVES = ["Composição e mudanças do eleitorado", "Acesso ao local de votação", "Agregação de seções",
                "Diferenças de cobertura ou retificações da fonte"]


def rate(numerator: int | None, denominator: int | None):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def weighted_rate(records):
    valid = [r for r in records if r.get("eligible", 0) > 0 and r.get("absent") is not None]
    return rate(sum(r["absent"] for r in valid), sum(r["eligible"] for r in valid))


@dataclass(frozen=True)
class Thresholds:
    min_eligible: int = 50
    min_peers: int = 5
    z_threshold: float = 3.0
    min_effect_pp: float = 5.0


def score_sections(records: list[dict], thresholds: Thresholds | None = None):
    t = thresholds or Thresholds()
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in records:
        if row["eligible"] <= 0:
            continue
        groups[(row["year"], row["round"], row["uf"], row["municipality"])].append(row)
        groups[(row["year"], row["round"], row["uf"])].append(row)
    aggregates: dict[tuple, dict[str, Any]] = {}
    for key, peers in groups.items():
        rates = sorted(r["absent"] / r["eligible"] for r in peers)
        aggregates[key] = {"count": len(peers), "n": sum(r["eligible"] for r in peers),
                           "a": sum(r["absent"] for r in peers), "sum_p": sum(rates),
                           "sum_p2": sum(p*p for p in rates), "rates": rates,
                           "sum_noise": sum((r["absent"]/r["eligible"])*(1-r["absent"]/r["eligible"])/r["eligible"] for r in peers)}
    output = []
    for row in records:
        result = {**row, "abstention_rate": rate(row["absent"], row["eligible"]),
                  "method_version": VERSION, "z_score": None, "p_value": None, "q_value": None,
                  "status": "INSUFFICIENT_PEERS", "baseline": None, "effect_pp": None,
                  "lower_band": None, "upper_band": None, "signal": None}
        if row["eligible"] < t.min_eligible:
            result["status"] = "INSUFFICIENT_SIZE"
            output.append(result)
            continue
        municipality = (row["year"], row["round"], row["uf"], row["municipality"])
        key = municipality if aggregates[municipality]["count"] - 1 >= t.min_peers else municipality[:3]
        g = aggregates[key]
        m = g["count"] - 1
        if m < t.min_peers:
            output.append(result)
            continue
        pi = row["absent"] / row["eligible"]
        p = (g["a"] - row["absent"]) / (g["n"] - row["eligible"])
        sum_p, sum_p2 = g["sum_p"] - pi, g["sum_p2"] - pi*pi
        empirical = max(0, (sum_p2 - sum_p*sum_p/m) / (m-1))
        noise = max(0, (g["sum_noise"] - pi*(1-pi)/row["eligible"]) / m)
        tau2 = max(0, empirical - noise)
        deviation = math.sqrt(p*(1-p)/row["eligible"] + tau2)
        z = (pi-p)/deviation if deviation > 0 else None
        effect = 100*(pi-p)
        result.update(baseline=p, comparator="MUNICIPALITY" if len(key) == 4 else "UF", peer_sections=m,
                      tau2=tau2, z_score=z, effect_pp=effect, status="HEURISTIC_EXPLORATORY",
                      lower_band=max(0, p-3*deviation), upper_band=min(1, p+3*deviation),
                      percentile=bisect.bisect_left(g["rates"], pi)/m,
                      signal=("ABSTENTION_HIGH" if z > 0 else "ABSTENTION_LOW") if z is not None and
                      abs(z) >= t.z_threshold and abs(effect) >= t.min_effect_pp else None)
        output.append(result)
    return output


def benjamini_hochberg(pvalues: list[float], *, calibrated: bool = False):
    if not calibrated:
        raise ValueError("FDR exige p-values de um modelo validado; scores heurísticos não são p-values")
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in pvalues):
        raise ValueError("p-value inválido")
    n = len(pvalues)
    ordered = sorted(range(n), key=pvalues.__getitem__)
    adjusted, running = [0.0]*n, 1.0
    for rank in range(n, 0, -1):
        index = ordered[rank-1]
        running = min(running, pvalues[index]*n/rank)
        adjusted[index] = running
    return adjusted
