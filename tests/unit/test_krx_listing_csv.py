"""KRX 상장/상폐 CSV는 이름 추론 없이 canonical identity에만 연결한다."""

from datetime import date

from app.services.krx_listing_csv import (
    CanonicalInstrument,
    ExistingInstrument,
    build_krx_lifecycles,
    plan_identity_reconciliation,
    prepare_listing_events,
)


def test_prepare_listing_event_uses_exact_code_market_and_listing_date_from_cp949_csv():
    raw = (
        "번호,종목코드,종목명,시장구분,증권구분,주식종류,상장일,상장폐지일\n"
        '"1","005930","삼성전자","KOSPI","주권","보통주","2010/01/04",\n'
    ).encode("cp949")

    prepared = prepare_listing_events(
        [("listing.csv", raw)],
        [CanonicalInstrument(7, "005930", "KOSPI", date(2010, 1, 4), None)],
    )

    assert prepared.events == [{
        "instrument_id": 7,
        "source_record_key": "krx:listed:005930:KOSPI:2010-01-04",
        "event_type": "listed",
        "effective_from": "2010-01-04",
        "market": "KOSPI",
        "provider_code": "005930",
        "evidence_state": "observed",
        "payload": {
            "source_file": "listing.csv",
            "source_file_hash": prepared.source_files[0]["sha256"],
            "code": "005930",
            "name": "삼성전자",
            "market": "KOSPI",
            "security_kind": "주권",
            "stock_kind": "보통주",
            "listed_at": "2010-01-04",
            "delisted_at": None,
        },
    }]
    assert prepared.unresolved == []


def test_prepare_delisting_event_refuses_reused_or_unmatched_code_and_excludes_rights():
    raw = (
        "번호,종목코드,종목명,시장구분,증권구분,주식종류,상장일,폐지일\n"
        '"1","123456","구법인","KOSDAQ","주권","보통주","2000/01/01","2011/01/01"\n'
        '"2","6543211G","권리","KOSPI","신주인수권증서","보통주","2020/01/01","2020/01/10"\n'
    ).encode("cp949")

    prepared = prepare_listing_events(
        [("delisting.csv", raw)],
        [
            CanonicalInstrument(1, "123456", "KOSDAQ", date(2000, 1, 1), date(2010, 12, 31)),
            CanonicalInstrument(2, "123456", "KOSDAQ", date(2020, 1, 1), None),
        ],
    )

    assert prepared.events == []
    assert prepared.unresolved == [{
        "source_file": "delisting.csv", "code": "123456", "market": "KOSDAQ",
        "event_type": "delisted", "effective_date": "2011-01-01",
        "reason": "no_exact_instrument",
    }]
    assert prepared.excluded == {"security_kind_신주인수권증서": 1}


def test_identity_reconciliation_updates_only_the_unique_open_current_identity_and_creates_closed_history():
    listing = (
        "번호,종목코드,종목명,시장구분,증권구분,주식종류,상장일,상장폐지일\n"
        '"1","123456","현 법인","KOSDAQ","주권","보통주","2020/01/01",\n'
    ).encode("cp949")
    delisting = (
        "번호,종목코드,종목명,시장구분,증권구분,주식종류,상장일,폐지일\n"
        '"1","123456","구 법인","KOSDAQ","주권","보통주","2000/01/01","2010/01/01"\n'
    ).encode("cp949")

    lifecycles = build_krx_lifecycles([("listing.csv", listing), ("delisting.csv", delisting)])
    plan = plan_identity_reconciliation(
        lifecycles,
        [ExistingInstrument(7, "123456", "KOSDAQ", None, None, "listed")],
    )

    assert [(row.instrument_id, row.listed_at) for row in plan.updates] == [(7, date(2020, 1, 1))]
    assert [(row.krx_short_code, row.listed_at, row.delisted_at, row.listing_status) for row in plan.creates] == [
        ("123456", date(2000, 1, 1), date(2010, 1, 1), "delisted"),
    ]
    assert plan.unresolved == []


def test_identity_reconciliation_does_not_choose_between_conflicting_delisting_dates():
    listing = (
        "번호,종목코드,종목명,시장구분,증권구분,주식종류,상장일,상장폐지일\n"
        '"1","123456","법인","KOSDAQ","주권","보통주","2000/01/01","2010/01/02"\n'
    ).encode("cp949")
    delisting = (
        "번호,종목코드,종목명,시장구분,증권구분,주식종류,상장일,폐지일\n"
        '"1","123456","법인","KOSDAQ","주권","보통주","2000/01/01","2010/01/01"\n'
    ).encode("cp949")

    plan = plan_identity_reconciliation(
        build_krx_lifecycles([("listing.csv", listing), ("delisting.csv", delisting)]),
        [],
    )

    assert plan.updates == []
    assert plan.creates == []
    assert plan.unresolved == [{
        "code": "123456", "market": "KOSDAQ", "listed_at": "2000-01-01",
        "reason": "conflicting_delisted_at",
        "delisted_dates": ["2010-01-01", "2010-01-02"],
    }]
