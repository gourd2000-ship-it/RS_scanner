# KRX 유니버스 소스 계약 (T05)

상태: 주식 membership API 선정 · 운영 호출 검증 및 ETF/ETN 검증 대기<br>
작성일: 2026-08-20<br>
관련 작업: [T05](../tasks/todo.md#task-t05-krx-외부-계약-secret-fixture-승인)<br>
기준 PRD: [KRX 기준 유니버스와 가격 대상 정합성 복구](prd-krx-universe-authority.md)

## 1. 확정된 외부 사실

KRX Open API의 공식 서비스 목록에는 다음 유니버스 관련 서비스가 명시돼 있다.

| 대상 | 공식 서비스명 | 현재 계약 판단 |
|---|---|---|
| KOSPI 주식 membership | 유가증권 일별매매정보 | **기준일 상장 주권 membership의 기준 API로 선정** |
| KOSDAQ 주식 membership | 코스닥 일별매매정보 | **기준일 상장 주권 membership의 기준 API로 선정** |
| KOSPI 주식 | 유가증권 종목기본정보 | API ID·응답 필드 확인. 현재 상장 상태는 미제공 |
| KOSDAQ 주식 | 코스닥 종목기본정보 | API ID·응답 필드 확인. 현재 상장 상태는 미제공 |
| KONEX 주식 | 코넥스 종목기본정보 | PRD 비범위 |
| ETF | ETF 일별매매정보 | API ID·응답 필드 확인. 기준일의 거래 관측용 |
| ETN | ETN 일별매매정보 | API ID·응답 필드 확인. 기준일의 거래 관측용 |

- 공식 목록: <https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd>
- 이용 절차: 회원가입·인증키 신청·관리자 승인 후, 원하는 API 서비스별 활용 신청과 관리자 승인이 필요하다. <https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp>
- 유가증권 일별매매정보: <https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=JvJFzlAENzZlPBDNGAWC>
- 코스닥 일별매매정보: <https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=hZjGpkllgCBCWqeTsYFj>
- 인증키는 요청 헤더 `AUTH_KEY`로 전달되는 형식이 KRX 서비스 화면에 표시된다. 실제 key 값, URL, API ID는 인증된 운영 계정에서만 확인·보관한다.

공식 공개 화면은 API ID, 샘플 URL 및 출력 필드값을 비로그인 상태에서 비워서 표시한다. 따라서
운영 계정에서 확인하지 않은 값이나 endpoint를 추정해 기록하지 않는다.

### 1.1 운영 호출 검증 (2026-08-20)

운영 계정의 승인된 키를 `AUTH_KEY` 헤더로만 전달해 다음 endpoint를 확인했다. 키 값과 요청
로그는 저장하지 않았다.

| 대상 | 호출 경로 | 기준일 | 확인 결과 |
|---|---|---:|---|
| KOSPI 주식 | `https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd.json` | 2020-04-14 | `OutBlock_1` 정상, KOSPI/KOSDAQ 합계 2,329행 |
| KOSDAQ 주식 | `https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd.json` | 2020-04-14 | `OutBlock_1` 정상 |
| ETF | `https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd.json` | 2020-04-14 | `OutBlock_1` 정상, 451행 |
| ETN | `https://data-dbg.krx.co.kr/svc/apis/etp/etn_bydd_trd.json` | 2020-04-14 | `OutBlock_1` 정상, 196행 |

주식 source는 `KRX_API_BASE_URL=https://data-dbg.krx.co.kr/svc/apis/sto`와 각 API ID를
조합한다. ETF/ETN은 별도 `etp` base path를 쓰며, 아직 membership 승격에는 사용하지 않는다.
이 검증은 서비스 접근성과 최소 response schema만 확인한다. KRX 전종목 시세·KIND와의 동일
기준일 count/code 대조 및 사용조건 검토는 계속 T05의 미완료 조건이다.

## 2. membership 기준 결정

### 2.1 주식: 일별매매 API를 authoritative membership으로 사용

`stk_isu_base_info`와 `ksq_isu_base_info`는 2010년 이후 종목기본정보 서비스이며, 실제
응답에도 과거·상장폐지 종목이 포함될 수 있다. 이 둘은 ISIN, 상장일, 시장, 명칭을 보강하는
**identity metadata**로만 사용한다. 이 응답만으로 현재 `listed`를 판정하지 않는다.

반면 KRX 공식 서비스 설명은 `stk_bydd_trd`를 “유가증권시장에 상장되어 있는 주권의 매매정보”,
`ksq_bydd_trd`를 “코스닥시장에 상장되어 있는 주권의 매매정보”로 명시한다. 따라서 각 API의
성공한 거래일 `basDd` 결과에 나온 code 집합을 해당 기준일의 KOSPI/KOSDAQ **membership**으로
사용한다. 이는 종목기본정보 API를 current-listing API로 오인하는 방식과 다르다.

이 결정은 다음 범위로 제한한다.

- raw 응답에는 상장/거래정지 상태 필드가 없으므로 membership은 `listed_observed`로 기록하고,
  `trading_status`는 `unknown`으로 둔다.
- 종목이 결과에 없다는 사실만으로 상장폐지를 즉시 확정하지 않는다. 직전 completed snapshot,
  KRX 장 마감 여부, 일시적 API 오류를 확인한 뒤 audit/approval 경로로만 변경한다.
- 가격이 없거나 거래량이 0인 종목은 membership에서 제외하지 않는다. 가격 수집 단계가
  `expected_no_trade` 또는 오류 사유를 별도로 기록한다.
- `ISU_CD`/ISIN과 상세 종목유형은 종목기본정보와 조인해 보강하되, 조인 실패가 membership을
  삭제하는 근거가 되지 않는다.

ETF/ETN의 `etf_bydd_trd`/`etn_bydd_trd`는 기준일 거래 관측으로 계속 shadow 수집한다. 두 서비스의
공식 설명은 “매매정보 제공”까지이므로, 주식 API와 동일하게 상장 membership을 보장한다고
승격하기 전에는 KRX 전종목 시세와 1거래일 count/code 대조를 완료해야 한다.

### 2.2 API 외 공식 화면의 역할

KRX Data Marketplace의 [전종목 시세](https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd?screenId=MDCSTAT015)는
조회일자별 종목코드·시장구분·가격·상장주식수를 제공하고, KIND의
[상장종목현황](https://kind.krx.co.kr/corpgeneral/listedIssueStatus.do?method=loadInitPage)은 조회일자 및
Excel 조회를 제공한다. 둘 다 공식 KRX 화면이지만 이 프로젝트가 승인·버전·호출계약을 보유한
Open API는 아니다. 따라서 자동 운영의 primary source가 아니라 API snapshot의 **독립 대조/수동
복구용 source**로 사용한다.

## 3. 운영 계정에서 확인된 계약

| 계약 항목 | KOSPI membership | KOSDAQ membership | KOSPI identity | KOSDAQ identity |
|---|---|---|---|---|
| KRX 서비스 API ID | `stk_bydd_trd` | `ksq_bydd_trd` | `stk_isu_base_info` | `ksq_isu_base_info` |
| 서비스 이용 승인 | 별도 활용 신청 필요 | 별도 활용 신청 필요 | 샘플 응답 확인 | 샘플 응답 확인 |
| HTTP method·입력 | GET, `basDd` (8자리 기준일) | GET, `basDd` (8자리 기준일) | 운영 명세서 확인 필요 | 운영 명세서 확인 필요 |
| code, ISIN, name 필드 | `ISU_CD`, `ISU_NM` | `ISU_CD`, `ISU_NM` | `ISU_SRT_CD`, `ISU_CD`, `ISU_NM` | `ISU_SRT_CD`, `ISU_CD`, `ISU_NM` |
| market, security type 필드 | `MKT_NM=KOSPI`, stock 계열 | `MKT_NM=KOSDAQ`, stock 계열 | `MKT_TP_NM=KOSPI`, stock 고정 | `MKT_TP_NM=KOSDAQ`, stock 고정 |
| listing/trading status 필드 | raw 미제공; `listed_observed` 도출 | raw 미제공; `listed_observed` 도출 | 미제공 (`unknown`) | 미제공 (`unknown`) |
| pagination·호출 한도·재시도 조건 | 운영 명세서·실호출로 확정 | 운영 명세서·실호출로 확정 | 대기 | 대기 |

주식 일별 API의 공개 샘플 명세에는 단일 `basDd` 요청 인자와 `OutBlock_1` 결과 배열이 표시된다.
운영 endpoint는 승인된 계정의 개발 명세서·샘플 테스트로 확인해 고정한다. 문자열 코드는 숫자로
변환하지 않는다.

주식 기본정보 응답은 상장폐지일·현재 상장 상태·거래정지 상태를 제공하지 않는다. 따라서
`stk_isu_base_info`와 `ksq_isu_base_info`는 canonical identity/상장일 보강에는 사용할 수
있지만, membership API를 대체하지 않는다. ETF/ETN 응답도 기준일의 거래 정보를 제공할 뿐
ISIN·상장 상태는 제공하지 않으므로, 상장 membership 승격 전에는 KRX 전종목 시세와 대조한다.

무비밀 성공 fixture는 `tests/fixtures/krx/`에 고정했다. 주식 기본정보와 KOSPI/KOSDAQ 일별매매,
ETF/ETN fixture는 운영자가 제공한 2020-04-14 기준 실제 응답의 일부다. 오류 fixture는 현재
synthetic이며, 실제 redacted 오류 응답이 확보되면 교체한다.

## 4. 최소 응답 계약

T06/T07은 다음 값을 fixture에서 검증할 수 있을 때만 구현한다.

| 필드 | 필수 | 규칙 |
|---|---:|---|
| `as_of_date` | 예 | `YYYYMMDD` 또는 명시된 KRX 기준일을 날짜로 무손실 변환 |
| `krx_short_code` | 예 | 문자열 보존. 숫자 변환 금지, 6자리/영숫자 계약은 명세로 확정 |
| `name` | 예 | 원문과 정규화 비교용 값을 분리 |
| `market` | 예 | KOSPI/KOSDAQ/ETF/ETN을 소스 계약에 따라 명시 매핑 |
| `security_type` | 예 | stock/etf/etn을 소스 계약에 따라 명시 매핑 |
| `listing_status` | 예 | listed/delisted/suspended/unknown 중 하나. 미제공 시 `unknown` |
| `isin` | 권장 | 제공될 때만 정확 매핑의 보조 key로 사용 |
| `listing_date`, `delisting_date`, `trading_status` | 선택 | 제공될 때만 원문 보존·상태 정책에 사용 |

필수 필드 누락, 중복 code/ISIN, 빈 결과, 기준일 불일치, 또는 허용되지 않은 response
schema는 `completed` snapshot을 만들 수 없다. 결과는 `partial` 또는 `failed`이며 기존
Naver active/price target은 변경하지 않는다.

## 5. 보안·이용조건 및 fixture 수용 조건

1. `KRX_AUTH_KEY` 같은 비밀값은 운영 secret store/runtime environment에만 저장한다.
   `.env.example`, Git, report, fixture, exception/log에는 저장하지 않는다.
2. 운영 계정에서 각 서비스별 정상 응답을 1회 이상 수집한 뒤, 인증키·개인정보·계정 식별자를
   제거한 JSON fixture를 만든다.
3. 아래 네 fixture는 필수다: 정상, 빈 결과, 인증/권한 오류, 기준일 불일치 또는 schema 오류.
4. Fixture에는 `source_contract_version`, 수집일, 서비스명/API ID(공개해도 되는 경우만)를
   metadata로 남긴다. 원본 응답 hash는 보관 가능하되 비밀값을 포함하지 않아야 한다.
5. sample request는 운영 승인 계정에서만 수행하고, 응답과 로그의 `AUTH_KEY`를 redaction한
   뒤 code review한다.
6. KRX Open API 약관은 API 결과를 비상업적 목적으로만 이용하도록 정한다. rs_scanner가 유료
   서비스·외부 고객 서비스·재배포를 포함한다면 Open API를 production source로 사용하지 말고
   KRX 유료 데이터상품 또는 사용권이 명시된 공급자를 별도 계약해야 한다.

## 6. 완료 판정 및 다음 작업

T05는 다음 모두가 충족될 때 완료다.

- [ ] 운영 계정의 인증키와 `stk_bydd_trd`/`ksq_bydd_trd`를 포함한 각 서비스 이용승인이 확인됐다.
- [ ] 최근 마감 거래일 `basDd`로 주식 membership API를 호출하고, 무비밀 fixture와 count/code report를 고정했다.
- [ ] 주식 membership API count/code를 같은 기준일의 KRX 전종목 시세 및 KIND 상장종목현황과 대조했다.
- [ ] ETF/ETN API count/code를 같은 기준일 KRX 전종목 시세와 대조해 membership 승격 여부를 승인했다.
- [x] 최소 응답 계약을 만족하는 무비밀 성공 fixture가 주식 기본정보·KOSPI/KOSDAQ 일별매매·ETF/ETN에 대해 review됐다. (오류 fixture는 synthetic)
- [ ] KRX 이용조건(호출량, 보관·재배포 제한)이 운영 runbook에 반영됐다.

완료 전에는 T06의 migration과 T07의 HTTP source를 만들지 않는다. 계약이 바뀌어도
기존 Naver 가격 수집과 P0 audit/apply 경로는 영향을 받지 않는다.
