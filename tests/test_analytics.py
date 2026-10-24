import pytest
from hypothesis import given
from hypothesis import strategies as st

from auditabr.analytics import benjamini_hochberg, score_sections, weighted_rate


def test_weighted_not_mean():
    assert weighted_rate([{"eligible":10,"absent":5},{"eligible":100,"absent":10}]) == pytest.approx(15/110)


def test_leave_one_out_and_negative_control():
    records = [{"section_id":str(i),"year":2022,"round":1,"uf":"MA","municipality":"00001","eligible":1000,"absent":100} for i in range(10)]
    records[0]["absent"] = 800
    result = score_sections(records)
    assert result[0]["baseline"] == .1
    assert result[0]["signal"] == "ABSTENTION_HIGH"
    assert all(r["p_value"] is None for r in result)
    control = score_sections(records[1:])
    assert all(r["signal"] is None for r in control)


def test_small_group_and_fdr():
    records = [{"section_id":"1","year":2022,"round":1,"uf":"MA","municipality":"00001","eligible":100,"absent":0}]
    assert score_sections(records)[0]["z_score"] is None
    with pytest.raises(ValueError):
        benjamini_hochberg([.01,.1])
    assert benjamini_hochberg([.01,.04,.03],calibrated=True) == pytest.approx([.03,.04,.04])


@given(st.lists(st.tuples(st.integers(1,10000),st.floats(0,1,allow_nan=False)),min_size=1,max_size=30))
def test_weighted_rate_bounds(values):
    records=[{"eligible":n,"absent":int(n*p)} for n,p in values]
    assert 0 <= weighted_rate(records) <= 1
