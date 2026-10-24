from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from auditabr.analytics import VERSION, Thresholds, score_sections
from auditabr.domain import check_scope, temporal_status
from auditabr.storage import current_manifest, reader, rows
from auditabr.utils import read_json

Group = Literal["uf", "municipality", "zone", "place", "section"]
GROUPS = {
    "uf": ["uf"], "municipality": ["uf", "municipality"],
    "zone": ["uf", "municipality", "zone"], "place": ["uf", "municipality", "zone", "place"],
    "section": ["section_id", "uf", "municipality", "zone", "place", "section"],
}


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = 2022
    round: int = Field(1, ge=1, le=2)
    uf: str | None = None
    municipality: str | None = None
    zone: str | None = None
    place: str | None = None
    section: str | None = None
    office: Literal["PRESIDENTE", "PREFEITO"] | None = None
    snapshot: str | None = None

    @model_validator(mode="after")
    def valid(self):
        check_scope(self.year, self.round, self.uf, self.office)
        for child, parent in [("municipality", "uf"), ("zone", "municipality"), ("place", "zone"), ("section", "zone")]:
            value = getattr(self, child)
            if value and not getattr(self, parent):
                raise ValueError(f"{child} requer {parent}")
            if value and not value.isdigit():
                raise ValueError(f"{child} deve ser código numérico")
        if self.snapshot and (len(self.snapshot) != 24 or not self.snapshot.isalnum()):
            raise ValueError("Snapshot inválido")
        return self


def where(scope: Scope, alias="", include_office=False):
    prefix = f"{alias}." if alias else ""
    clauses, params = [], []
    for key in ("year", "round", "uf", "municipality", "zone", "place", "section") + (("office",) if include_office else ()):
        value = getattr(scope, key)
        if value is not None:
            clauses.append(f"{prefix}{key}=?")
            params.append(value)
    return " AND ".join(clauses), params


def pin_scope(root: Path, scope: Scope) -> Scope:
    """Resolve the published version once, so facts and metadata cannot drift."""
    manifest = current_manifest(root, scope.snapshot)
    if scope.snapshot and not manifest:
        raise ValueError("Snapshot não encontrado")
    if manifest:
        if manifest.get("scope_offices") != ["PRESIDENTE", "PREFEITO"]:
            raise ValueError("Snapshot anterior à restrição de cargos; consulte uma versão atual")
        return scope.model_copy(update={"snapshot": manifest["snapshot_id"]})
    return scope


def envelope(root: Path, scope: Scope, data: list, *, family="turnout", has_more=False, offset=0):
    manifest = current_manifest(root, scope.snapshot)
    if scope.snapshot and not manifest:
        raise ValueError("Snapshot não encontrado")
    sql, params = where(scope)
    with reader(root, scope.snapshot) as db:
        count = db.execute(f"SELECT count(*) FROM section_turnout WHERE {sql}", params).fetchone()[0]
        ops = db.execute(f"SELECT count(*) FROM operational_section_metrics WHERE {sql}", params).fetchone()[0]
        excluded = db.execute("SELECT count(*) FROM quality_issue WHERE code='TURNOUT_ARITHMETIC_INVALID' AND section_id LIKE ?",
                              [f"BR-{scope.year}-%-T{scope.round}:{scope.uf or '%'}:%"]).fetchone()[0]
    status = temporal_status(scope.year, scope.round)
    if status != "FUTURE":
        status = "PARTIAL" if data else "MISSING"
        observation = root / "coverage" / f"{scope.year}-{scope.round}-{scope.uf}-{family}.json"
        if not data and scope.uf and observation.exists() and read_json(observation).get("status") == "NOT_APPLICABLE":
            status = "NOT_APPLICABLE"
    limitations = ["Cobertura refere-se aos arquivos carregados nesta instalação; universo externo não validado.",
                   "Diferenças estatísticas não demonstram irregularidade nem causalidade."]
    if family in ("times", "habilitation"):
        limitations.append("Eventos operacionais não identificam candidato, eleitor ou assinatura física.")
    return {"data": data, "meta": {"snapshot_id": manifest and manifest["snapshot_id"],
            "as_of": manifest and manifest["published_at"], "scope": scope.model_dump(),
            "mode": manifest["mode"] if manifest else "official", "availability_status": status,
            "source_coverage": {"status": status, "sections_observed": count,
                "excluded_sections_in_uf_scope": excluded,
                "sections_expected": None, "operational_sections": ops, "operational_ratio": ops/count if count else None},
            "scope_regions": ["NORTE","NORDESTE"],
            "methodology_version": VERSION, "turnout_basis_office": "PREFEITO" if scope.year%4==0 else "PRESIDENTE", "limitations": limitations},
            "pagination": {"offset": offset, "has_more": has_more, "next_offset": offset+len(data) if has_more else None}}


def turnout(root: Path, scope: Scope, group_by: Group = "uf", limit=500, offset=0):
    scope = pin_scope(root, scope)
    columns = GROUPS[group_by]
    labels = []
    if "municipality" in columns:
        labels.append("MIN(municipality_name) municipality_name")
    if "place" in columns:
        labels.append("MIN(place_name) place_name")
    label_sql = (",".join(labels) + ",") if labels else ""
    sql, params = where(scope)
    with reader(root, scope.snapshot) as db:
        data = rows(db, f"""SELECT {','.join(columns)},
            {label_sql}
            count(*) sections, sum(eligible)::BIGINT eligible, sum(present)::BIGINT present,
            sum(absent)::BIGINT absent, sum(absent)::DOUBLE/NULLIF(sum(eligible),0) abstention_rate,
            avg(absent::DOUBLE/NULLIF(eligible,0)) mean_section_rate
            FROM section_turnout WHERE {sql} GROUP BY {','.join(columns)}
            ORDER BY {','.join(columns)} LIMIT ? OFFSET ?""", [*params, limit+1, offset])
    return envelope(root, scope, data[:limit], has_more=len(data)>limit, offset=offset)


def votes(root: Path, scope: Scope, group_by: Group = "uf", limit=500, offset=0):
    scope = pin_scope(root, scope)
    if not scope.office:
        raise ValueError("Selecione um cargo para consultar votos")
    columns = GROUPS[group_by]
    sql, params = where(scope, include_office=True)
    with reader(root, scope.snapshot) as db:
        data = rows(db, f"""WITH totals AS (
            SELECT {','.join(columns)},office,candidate_id,candidate_number,candidate_name,party,vote_status,vote_class,
            SUM(votes)::BIGINT votes FROM candidate_vote WHERE {sql} GROUP BY ALL)
            SELECT *,CASE WHEN vote_class='NOMINAL' THEN votes::DOUBLE /
                NULLIF(SUM(CASE WHEN vote_class='NOMINAL' THEN votes ELSE 0 END)
                OVER (PARTITION BY {','.join(columns)},office),0) END nominal_share
            FROM totals ORDER BY votes DESC,candidate_id LIMIT ? OFFSET ?""", [*params, limit+1, offset])
    result = envelope(root, scope, data[:limit], family="votes", has_more=len(data)>limit, offset=offset)
    from auditabr.domain import seats
    result["meta"]["ballot_slots"] = seats(scope.year, scope.office)
    result["meta"]["denominator"] = "Soma dos votos nominais publicados do cargo no grupo; não percentual de eleitores"
    return result


def operational(root: Path, scope: Scope, family="times", limit=500, offset=0):
    scope = pin_scope(root, scope)
    sql, params = where(scope)
    with reader(root, scope.snapshot) as db:
        data = rows(db, f"SELECT * FROM operational_section_metrics WHERE {sql} ORDER BY section_id LIMIT ? OFFSET ?",
                    [*params, limit+1, offset])
    return envelope(root, scope, data[:limit], family=family, has_more=len(data)>limit, offset=offset)


def geography(root: Path, scope: Scope, level: str):
    scope = pin_scope(root, scope)
    if level not in GROUPS:
        raise ValueError("Nível geográfico inválido")
    # Geography can be discovered from votes even while turnout is unavailable.
    column = {"section": "section", "uf": "uf", "municipality": "municipality", "zone": "zone", "place": "place"}[level]
    sql, params = where(scope)
    with reader(root, scope.snapshot) as db:
        data = rows(db, f"""SELECT DISTINCT {column} code FROM (
            SELECT year,round,uf,municipality,zone,place,section FROM section_turnout
            UNION ALL SELECT year,round,uf,municipality,zone,place,section FROM candidate_vote)
            WHERE {sql} AND {column} IS NOT NULL ORDER BY code""", params)
    return envelope(root, scope, data)


def analysis(root: Path, scope: Scope, thresholds: Thresholds | None = None, limit=500, offset=0, signals_only=False):
    scope = pin_scope(root, scope)
    # Baselines use the whole UF/round, before narrower display filters.
    base = Scope(year=scope.year, round=scope.round, uf=scope.uf, snapshot=scope.snapshot)
    sql, params = where(base)
    with reader(root, scope.snapshot) as db:
        records = rows(db, f"SELECT * FROM section_turnout WHERE {sql}", params)
    scored = score_sections(records, thresholds)
    filtered = [r for r in scored if all(getattr(scope, k) is None or getattr(scope, k) == r[k]
                for k in ("municipality", "zone", "place", "section"))]
    if signals_only:
        filtered = [r for r in filtered if r["signal"]]
    filtered.sort(key=lambda r: (-(abs(r["z_score"]) if r["z_score"] is not None else -1), r["section_id"]))
    return envelope(root, scope, filtered[offset:offset+limit], has_more=len(filtered)>offset+limit, offset=offset)


def historical(root: Path, scope: Scope, years: list[int]):
    scope = pin_scope(root, scope)
    if scope.section or scope.place or scope.zone:
        result = envelope(root, scope, [])
        result["meta"]["availability_status"] = "NOT_COMPARABLE"
        result["meta"]["limitations"].append("Seção/local exigem vínculo histórico documental; use município/UF.")
        return result
    result = []
    for year in sorted(set(years)):
        historical_scope = Scope(year=year, round=scope.round, uf=scope.uf, municipality=scope.municipality,
                                 snapshot=scope.snapshot)
        aggregate = turnout(root, historical_scope, "municipality" if scope.municipality else "uf", 1000)
        records = aggregate["data"]
        n = sum(r["eligible"] for r in records) if records else None
        a = sum(r["absent"] for r in records) if records else None
        result.append({"year": year, "eligible": n, "absent": a, "abstention_rate": a/n if n else None,
                       "status": aggregate["meta"]["availability_status"],
                       "comparison": "Agregado territorial; alterações de composição e cadastro não ajustadas"})
    return envelope(root, scope, result)
