"""RF-010..025: domínio fechado e identidades temporais."""
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

YEARS = (2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026)
REGIONS = {"NORTE": ("AC", "AP", "AM", "PA", "RO", "RR", "TO"),
           "NORDESTE": ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE")}
UFS = frozenset(uf for states in REGIONS.values() for uf in states)
DATES = {
    2012: ("2012-10-07", "2012-10-28"), 2014: ("2014-10-05", "2014-10-26"),
    2016: ("2016-10-02", "2016-10-30"), 2018: ("2018-10-07", "2018-10-28"),
    2020: ("2020-11-15", "2020-11-29"), 2022: ("2022-10-02", "2022-10-30"),
    2024: ("2024-10-06", "2024-10-27"), 2026: ("2026-10-04", "2026-10-25"),
}


class Office(StrEnum):
    PRESIDENTE = "PRESIDENTE"
    PREFEITO = "PREFEITO"


def today() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def check_scope(year: int, round: int = 1, uf: str | None = None, office: str | None = None) -> None:
    if year not in YEARS or round not in (1, 2):
        raise ValueError("Pleito ou turno fora do escopo")
    if uf is not None and uf not in UFS:
        raise ValueError("UF fora do escopo Norte/Nordeste")
    if office is not None and office not in offices(year, round):
        raise ValueError("Cargo não aplicável ao pleito/turno")
    if uf == "ZZ" and (year % 4 == 0 or office not in (None, "PRESIDENTE")):
        raise ValueError("Exterior só participa da disputa presidencial")
    if uf == "DF" and year % 4 == 0:
        raise ValueError("DF não possui eleição municipal")


def offices(year: int, round: int = 1) -> list[str]:
    if year not in YEARS or round not in (1, 2):
        raise ValueError("Pleito ou turno fora do escopo")
    return ["PREFEITO"] if year % 4 == 0 else ["PRESIDENTE"]


def seats(year: int, office: str) -> int:
    check_scope(year, office=office)
    return 1


def election_id(year: int) -> str:
    check_scope(year)
    return f"BR-{year}-{'MUNICIPAL' if year % 4 == 0 else 'GERAL'}"


def round_id(year: int, round: int) -> str:
    check_scope(year, round)
    return f"{election_id(year)}-T{round}"


def election_date(year: int, round: int) -> date:
    check_scope(year, round)
    return date.fromisoformat(DATES[year][round - 1])


def temporal_status(year: int, round: int, as_of: date | None = None) -> str:
    return "FUTURE" if election_date(year, round) > (as_of or today()) else "NOT_DISCOVERED"


def section_id(year: int, round: int, uf: str, municipality: str, zone: str, section: str) -> str:
    check_scope(year, round, uf)
    if any(not str(v).isdigit() for v in (municipality, zone, section)):
        raise ValueError("Identificadores eleitorais devem ser strings numéricas")
    return f"{round_id(year, round)}:{uf}:{municipality}:{zone}:{section}"

