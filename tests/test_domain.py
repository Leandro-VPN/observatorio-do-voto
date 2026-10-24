from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from auditabr.domain import YEARS, check_scope, offices, seats, section_id, temporal_status


@pytest.mark.parametrize("year", [2014, 2018, 2022, 2026])
def test_only_president_in_general(year):
    assert seats(year, "PRESIDENTE") == 1
    with pytest.raises(ValueError):
        check_scope(year, 2, office="SENADOR")


@given(st.sampled_from(YEARS))
def test_rf010_office_scope(year):
    assert set(offices(year)) <= {"PRESIDENTE", "PREFEITO"}
    with pytest.raises(ValueError):
        check_scope(year, office="VEREADOR")


def test_future_and_identity():
    assert temporal_status(2026, 2, date(2026, 10, 13)) == "FUTURE"
    assert section_id(2022, 1, "MA", "00001", "001", "001") != section_id(2022, 1, "MA", "00002", "001", "001")
    with pytest.raises(ValueError):
        check_scope(2024, uf="DF")

