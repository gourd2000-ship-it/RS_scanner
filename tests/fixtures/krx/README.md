# KRX fixture 규칙

이 fixture는 KRX 운영 계정에서 받은 응답 계약을 검증하기 위한 무비밀 샘플이다.

- `kospi_isu_base_info_success.json`: API ID `stk_isu_base_info`
- `kosdaq_isu_base_info_success.json`: API ID `ksq_isu_base_info`
- `etf_bydd_trd_success.json`: API ID `etf_bydd_trd`
- `etn_bydd_trd_success.json`: API ID `etn_bydd_trd`
- `stk_bydd_trd_success.json`: API ID `stk_bydd_trd` (유가증권 일별매매정보)
- `ksq_bydd_trd_success.json`: API ID `ksq_bydd_trd` (코스닥 일별매매정보)

성공 fixture에는 인증키, 요청 헤더, 세션, 계정 정보 및 인증키를 포함한 URL을 넣지 않는다.
`empty_response.json`, `unauthorized_response.json`, `as_of_date_mismatch.json`은 오류 처리를
고정하기 위한 synthetic fixture다. 실제 운영 오류 응답이 확보되면 민감 정보를 제거한 뒤
교체한다.

주식 기본정보의 `OutBlock_1`에는 상장 상태가 없고 과거 종목도 포함될 수 있다. ETF/ETN
일별매매정보는 해당 `BAS_DD`의 거래 관측 자료이며 상장 상태·ISIN을 제공하지 않는다. 따라서
이 fixture들은 instrument identity 또는 거래 관측 보강용이며, 현재 상장 유니버스 판정에는 별도
기준일 listing feed가 필요하다.
