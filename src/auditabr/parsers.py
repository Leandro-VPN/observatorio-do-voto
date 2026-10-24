"""Streaming readers for the observed TSE semicolon CSV layouts (2012–2026)."""
from __future__ import annotations

import csv
import io
import unicodedata
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from auditabr.acquisition import safe_members
from auditabr.domain import check_scope, election_date, seats, section_id
from auditabr.utils import digest

VERSION = "csv-tse-1.1.0"
REQUIRED = {"ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "DS_CARGO", "CD_CARGO"}
OFFICE_CODES = {"PRESIDENTE": "1", "PREFEITO": "11"}


def normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.upper().strip()) if not unicodedata.combining(c))


def optional(value):
    return None if value is None or value.strip() in ("", "#NULO#", "#NE#", "-1", "-3") else value.strip()


def identifier(value: str, width: int) -> str:
    value = str(value).strip()
    if not value.isdigit():
        raise ValueError("Identificador eleitoral inválido")
    return value.zfill(width)


def count(row: dict, field: str, required=True):
    value = optional(row.get(field))
    if value is None and not required:
        return None
    if value is None or not value.isdigit():
        raise ValueError(f"Contagem inválida: {field}")
    number = int(value)
    if number > 2**63 - 1:
        raise ValueError("Contagem excede int64")
    return number


@contextmanager
def csv_streams(path: Path, uf: str):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = [i for i in safe_members(archive) if i.filename.lower().endswith((".csv", ".txt"))]
            # National BR/BRASIL duplicates are not mixed with state files automatically.
            state = [i for i in members if f"_{uf}." in i.filename]
            selected = state or members if len(members) == 1 or state else []
            if not selected:
                raise ValueError("ZIP contém múltiplos recortes; selecione membro explícito")
            yield [(i.filename, archive.open(i)) for i in selected]
    else:
        with path.open("rb") as stream:
            yield [(path.name, stream)]


def read_rows(path: Path, uf: str, family: str, observations: dict):
    expected = REQUIRED | ({"QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES"} if family == "turnout"
                           else {"NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"})
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq
        source = pq.ParquetFile(path)
        columns = source.schema_arrow.names
        if not expected <= set(columns):
            raise ValueError("Captura projetada sem campos obrigatórios")
        observations.setdefault("schemas", []).append({"member": path.name, "columns": columns,
            "encoding": "PARQUET_PROJECTED_STRINGS", "fingerprint": digest(columns), "parser": VERSION})
        for batch in source.iter_batches(batch_size=10000):
            for row in batch.to_pylist():
                observations["source_rows"] = observations.get("source_rows", 0) + 1
                line = row.pop("_SOURCE_ROW", observations["source_rows"] + 1)
                if row["SG_UF"] == uf:
                    yield line, row
        return
    with csv_streams(path, uf) as streams:
        for member, binary in streams:
            # Current official layouts are Latin-1; UTF-8 BOM is unambiguous.
            buffered = io.BufferedReader(binary)
            prefix = buffered.peek(65536)
            if prefix.startswith(b"\xef\xbb\xbf"):
                encoding = "utf-8-sig"
            else:
                try:
                    prefix.decode("utf-8")
                    encoding = "utf-8" if any(b >= 128 for b in prefix) else "latin-1"
                except UnicodeDecodeError:
                    encoding = "latin-1"
            with io.TextIOWrapper(buffered, encoding=encoding, newline="", errors="strict") as text:
                reader = csv.reader(text, delimiter=";")
                columns = next(reader, [])
                if len(columns) != len(set(columns)) or not expected <= set(columns):
                    raise ValueError(f"Layout não suportado; faltam: {sorted(expected - set(columns))}")
                observations.setdefault("schemas", []).append({"member": member, "columns": columns,
                    "encoding": encoding, "fingerprint": digest(columns), "parser": VERSION})
                uf_index = columns.index("SG_UF")
                office_index = columns.index("DS_CARGO")
                for line, values in enumerate(reader, 2):
                    observations["source_rows"] = observations.get("source_rows", 0) + 1
                    if len(values) != len(columns):
                        raise ValueError(f"Linha {line}: quantidade de campos divergente")
                    # Discard other UFs/offices before allocating dictionaries or parsing counts.
                    if values[uf_index] != uf or normalized(values[office_index]) not in OFFICE_CODES:
                        continue
                    row = dict(zip(columns, values, strict=True))
                    yield line, row


def parse_record(row: dict, year: int, round: int, uf: str, asset_id: str, family: str):
    if int(row["ANO_ELEICAO"]) != year:
        raise ValueError("Ano do arquivo diverge do catálogo/seleção")
    if int(row["NR_TURNO"]) != round or row["SG_UF"] != uf:
        return None
    if "DT_ELEICAO" in row and datetime.strptime(row["DT_ELEICAO"], "%d/%m/%Y").date() != election_date(year, round):
        return None  # Supplementary elections are not the ordinary election scope.
    office = normalized(row["DS_CARGO"])
    if office not in {"PRESIDENTE", "PREFEITO"}:
        return None
    check_scope(year, round, uf, office)
    if row["CD_CARGO"] != OFFICE_CODES[office]:
        raise ValueError("Código/descrição de cargo divergem do layout observado")
    municipality, zone, section = (identifier(row[k], n) for k, n in
                                   [("CD_MUNICIPIO", 5), ("NR_ZONA", 4), ("NR_SECAO", 4)])
    sid = section_id(year, round, uf, municipality, zone, section)
    place = optional(row.get("NR_LOCAL_VOTACAO"))
    base = {"section_id": sid, "year": year, "round": round, "uf": uf, "municipality": municipality,
            "zone": zone, "section": section, "place": identifier(place, 4) if place else None, "asset_id": asset_id}
    if family == "turnout":
        turnout = {**base, "municipality_name": optional(row.get("NM_MUNICIPIO")),
                   "place_name": optional(row.get("NM_LOCAL_VOTACAO")),
                   "eligible": count(row, "QT_APTOS"), "present": count(row, "QT_COMPARECIMENTO"),
                   "absent": count(row, "QT_ABSTENCOES")}
        if turnout["eligible"] != turnout["present"] + turnout["absent"]:
            raise ValueError(f"Seção {sid}: aptos != presentes + ausentes")
        summary = {"section_id": sid, "year": year, "round": round, "uf": uf, "office": office,
                   "nominal": count(row, "QT_VOTOS_NOMINAIS", False), "blank": count(row, "QT_VOTOS_BRANCOS", False),
                   "null_votes": count(row, "QT_VOTOS_NULOS", False),
                   "other": count(row, "QT_VOTOS_ANULADOS_APU_SEP", False),
                   "total": None, "slots": seats(year, office), "asset_id": asset_id}
        values = [summary[k] for k in ("nominal", "blank", "null_votes", "other")]
        if all(v is not None for v in values):
            summary["total"] = sum(values)
        return turnout, summary
    name = normalized(row["NM_VOTAVEL"])
    vote_class = ("BLANK" if name in {"BRANCO", "VOTO BRANCO", "VOTOS BRANCOS"} else
                  "NULL" if name in {"NULO", "VOTO NULO", "VOTOS NULOS"} else
                  "OTHER" if "ANULAD" in name or "LEGENDA" in name else "NOMINAL")
    number = row["NR_VOTAVEL"]
    candidate = optional(row.get("SQ_CANDIDATO"))
    district = "BR" if office == "PRESIDENTE" else f"{uf}:{municipality}" if office == "PREFEITO" else uf
    cid = f"{year}:{office}:{district}:{candidate or number}"
    return {**base, "office": office, "candidate_id": cid, "candidate_number": number,
            "candidate_name": row["NM_VOTAVEL"], "party": optional(row.get("SG_PARTIDO")),
            "vote_status": optional(row.get("DS_SIT_TOT_TURNO")) or "AS_PUBLISHED",
            "vote_class": vote_class, "votes": count(row, "QT_VOTOS")}

