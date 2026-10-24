from datetime import datetime

import pytest

from auditabr.logs import cutoff, parse_log, state_machine


def events(kinds):
    return [{"device":"a","kind":k,"timestamp":datetime(2022,10,2,17),"line":i} for i,k in enumerate(kinds)]


@pytest.mark.parametrize("kinds,classification", [
    (["VOTE"],"HABILITATION_UNCLASSIFIED"),
    (["START","BIO","VOTE"],"BIO_CONFIRMED"),
    (["START","MANUAL_REQUEST","VOTE"],"HABILITATION_UNCLASSIFIED"),
    (["START","MANUAL_REQUEST","MANUAL_APPROVED","VOTE"],"ALT_MANUAL_CONFIRMED"),
    (["START","BIOGRAPHIC_EVIDENCE","VOTE"],"HABILITATION_UNCLASSIFIED"),
    (["START","BIO","CANCEL","START","VOTE"],"HABILITATION_UNCLASSIFIED"),
    (["START","BIO","NO_ENROLLMENT","VOTE"],"HABILITATION_CONFLICT"),
])
def test_habilitation_conservative(kinds,classification):
    assert state_machine(events(kinds))[0]["classification"] == classification


def logline(ts,message,app="VOTA"):
    return f"{ts}\tINFO\t0001\t{app}\t{message}\tchecksum\n"


def test_strict_cutoff_and_original_time():
    data="".join(logline(f"02/10/2022 {t}","O voto do eleitor foi computado") for t in ("16:59:59","17:00:00","17:00:01"))
    result=parse_log(data.encode(),2022,1,"synthetic",zone="America/Sao_Paulo",rule="BRT_17",rule_evidence="synthetic-test",clock_validated=True)
    assert result["metric"]["after_cutoff"] == 1
    assert result["metric"]["vote_events"] == 3


def test_clock_jump_blocks_ranking_same_second_not_deduped():
    data="".join(logline(f"02/10/2022 {t}","O voto do eleitor foi computado") for t in ("18:00:00","18:00:00","16:30:00"))
    result=parse_log(data.encode(),2022,1,"synthetic",zone="America/Sao_Paulo",rule="BRT_17",rule_evidence="synthetic-test",clock_validated=True)
    assert result["metric"]["clock_quality"] == "CLOCK_JUMP"
    assert result["metric"]["after_cutoff"] is None
    assert result["metric"]["vote_events"] == 3


def test_other_days_and_transmission_are_not_votes():
    data=logline("01/10/2022 18:00:00","O voto do eleitor foi computado")
    data+=logline("02/10/2022 22:00:00","Boletim recebido",app="TRANSMISSAO")
    result=parse_log(data.encode(),2022,1,"synthetic")
    assert result["metric"]["vote_events"] == 0
    assert result["metric"]["manual"] is None


def test_historical_rule_not_retrojected():
    with pytest.raises(ValueError):
        cutoff(2012,1,"America/Rio_Branco","BRT_17","test")
    a=cutoff(2012,1,"America/Rio_Branco","LOCAL_17","test")
    b=cutoff(2012,1,"America/Sao_Paulo","LOCAL_17","test")
    assert a != b
def test_future_log_rejected_before_reading(tmp_path):
    from datetime import date
    from unittest.mock import patch

    import pytest

    from auditabr.logs import ingest_log
    with patch("auditabr.domain.today", return_value=date(2026, 10, 13)), pytest.raises(ValueError, match="FUTURE"):
        ingest_log(tmp_path, {}, 2026, 2, "AC", "01392", "0009", "0463")

