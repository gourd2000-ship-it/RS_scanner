"""공급자 거래량을 손실 없이 읽는지 검사한다."""

from app.crawler.parsers.kiwoom import parse_kiwoom_daily_prices


def _row(volume: str) -> dict:
    return {"dt": "20260904", "open_pric": "100", "high_pric": "101",
            "low_pric": "99", "cur_prc": "100", "trde_qty": volume}


def test_kiwoom_parser_rejects_fractional_volume_without_truncating_it():
    parsed = parse_kiwoom_daily_prices({"rows": [_row("12.5"), _row("13")]})
    assert len(parsed) == 1
    assert parsed[0].volume == 13
    assert parsed.invalid_rows == 1
