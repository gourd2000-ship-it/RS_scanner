# BT01 역사 데이터 공급 범위 계약

상태: 완료 (2026-09-05, BT01 범위에 한함)<br>
개정일: 2026-09-05<br>
관련 작업: [BT01](../tasks/todo.md#bt01-역사-공급-범위-표본-검증)

## 목적

이 문서는 대량 적재 전에 Kiwoom의 과거 일봉 범위와 KRX/KIND의 상장·상폐 이력 근거를
작은 표본으로 확인하는 계약이다. 성공한 가격 응답 하나만으로 상폐 이력이나 전체 기간
coverage를 주장하지 않는다. probe는 읽기 전용이며 DB 가격·유니버스·RS를 변경하지 않는다.

## 공식 근거와 사용 경계

- Kiwoom의 주식 일봉 차트 요청은 ka10081, POST /api/dostk/chart이며 stk_cd, base_dt,
  upd_stkpc_tp를 받는다. 다음 페이지는 응답의 cont-yn/next-key를 다시 보낸다.
  수정주가 조회는 권리발생일 이후의 base_dt 또는 연속조회가 필요하다고 명시한다.
  [Kiwoom REST 일봉 가이드](https://openapi.kiwoom.com/m/guide/apiguide/07/ka10081)
- KRX 종목검색은 시장 선택과 “상장폐지종목포함”을 제공하며 종목코드·종목명·상장폐지일을
  보여 준다. 이는 상폐 후보의 독립 대조와 수동 복구용 근거다.
  [KRX 종목검색](https://data.krx.co.kr/comm/finder/finder_datastkisu.jsp)
- KIND는 조회일자 기반 상장종목현황과 상장폐지현황을 제공한다. 이후 자동 importer는
  BT03에서 서비스별 이용조건·정확한 다운로드 계약을 확정한 뒤 구현한다.
  [KIND 상장종목현황](https://kind.krx.co.kr/corpgeneral/listedIssueStatus.do?method=loadInitPage),
  [KIND 상장폐지현황](https://kind.krx.co.kr/investwarn/delcompany.do?method=searchDelCompanyMain)

KRX Open API의 현행 membership source/인증·이용조건의 세부 확인은
[KRX source contract](krx-universe-source-contract.md)에 보관한다. BT01은 KRX/KIND를
자동 수집하지 않는다. 해당 화면의 기준일·상폐일은 Kiwoom 가격의 첫/마지막 거래일과
같다고 가정하지 않는다.

## 표본과 실행 규칙

기본 표본은 6개다. 005930은 2018년 액면분할을 포함하는 현재 상장 종목,
000660과 035420은 장기 이력 현재 상장 종목이다. 068270(셀트리온)은 시장 이전 표본이다.
KRX 일별 membership 실측에서 2018-02-08에는 KOSDAQ, 2018-02-09에는 KOSPI에 각각
나타났다. 230980, 032980은 로컬 `delisted_at` 기록에서 뽑은 KOSDAQ 상폐 후보다.
마지막 두 값은 검증 대상일 뿐, 로컬 상태만으로 상폐 사실을 확정하지 않는다.

모든 페이지에 동일한 base_date를 보낸다. 00000000은 허용하지 않는다.
이렇게 해야 수정주가 기준일과 페이지 경계가 실행 내내 동일하고, 중복 날짜·페이지
반복·목표 과거일 미도달을 보고서에 드러낼 수 있다. 기본 8페이지는 실제 제공 범위를
측정하는 상한이며 전체 이력 완료 선언이 아니다.

~~~bash
.venv/bin/python scripts/probe_historical_sources.py \
  --base-date 20260904 \
  --target-date 20130101 \
  --max-pages 8 \
  --output reports/backtest/bt01_kiwoom_20260904.json
~~~

특정 표본은 --sample 005930:current_corporate_action처럼 반복 지정한다. 출력 JSON에는
응답 payload·접근 토큰·URL·오류 메시지를 넣지 않는다. 각 표본의 page/행/중복 날짜/최초·최종
날짜/목표일 도달/실패 종류만 남긴다.

## 실측 결과

실행 리포트: [`bt01_kiwoom_20260905T160753Z.json`](../reports/backtest/bt01_kiwoom_20260905T160753Z.json)

| 구분 | 표본 | 고정 `base_dt` / 조정 | 페이지·범위 | 판정 |
|---|---|---|---|---|
| 현재 상장·기업행위 | 005930 | 20260904 / `upd_stkpc_tp=1` | 6페이지, 3,600행, 2012-01-10~2026-09-04 | 2013-01-01 도달 |
| 현재 장기 이력 | 000660, 035420 | 동일 | 각 6페이지, 3,600행, 2012-01-10~2026-09-04 | 2013-01-01 도달 |
| 시장 이전 | 068270 | 동일 | 6페이지, 3,600행, 2012-01-10~2026-09-04 | 2013-01-01 도달. KRX membership은 2018-02-08 KOSDAQ, 2018-02-09 KOSPI |
| 상폐 후보 | 230980, 032980 | 20260904 / `1` | 각 1페이지, 유효 행 0, 261 bytes | `PriceParseError`; 목표일 미도달 |

현재 상장 4개 표본은 연속조회 6페이지에서 중복 날짜 0건, malformed 행 0건이었다.
probe 계약 테스트는 의도적으로 겹치는 페이지 fixture를 넣어 날짜 중복을 집계하는지도 확인한다.
목표일에 도달하면 탐색을 멈추므로, 위 결과는 2012년 이전 또는 Kiwoom의 전체 보존 범위를
증명하지 않는다.

상폐 후보는 기준일을 상폐 직전으로 바꿔 한 번 더 읽기 전용 확인을 했다.
[`230980 / 2026-06-04`](../reports/backtest/bt01_kiwoom_230980_20260604.json)와
[`032980 / 2026-06-30`](../reports/backtest/bt01_kiwoom_032980_20260630.json) 모두 같은
`PriceParseError`(261 bytes, 유효 행 0)였다. 반면 KRX 일별 membership 실측은 각각
230980이 2026-06-04에는 포함되고 06-05에는 제외, 032980이 2026-06-30에는 포함되고
07-01에는 제외됨을 보였다. KIND 상장폐지현황 수동 대조의 상폐일도 각각 2026-06-05,
2026-07-01이다. 즉 현재 Kiwoom 계약만으로는 이 상폐 종목의 과거 OHLC를 확보할 수 없다는
증거이며, 가격의 첫/마지막 일자를 상폐 효력일로 사용하지 않는다.

## Source matrix와 사용 조건

| source | BT01에서 확인한 범위 | 백테스트 사용 판정 | 미확인·필요 조치 |
|---|---|---|---|
| Kiwoom REST `ka10081` | 현재 상장 표본 4개에서 2013-01-01 이전까지 연속 6페이지 조회. 상폐 후보 2개는 직전 기준일도 parse 불가 | 현재 상장 표본의 제한된 OHLC 수집은 가능 | 전 기간 보존 범위, 상폐/재상장/코드재사용 가격은 미확정. BT05에서 기간 제한 iterator와 source collision 기록 필요 |
| KRX Open API 일별매매 membership | 068270의 시장 이전, 230980·032980의 마지막 포함/다음 거래일 제외를 기준일별로 관측 | 날짜별 `listed_observed` 보강용 | event master·거래정지·상폐 사유를 주지 않으며, 완전한 역사 명부로 단독 사용 불가 |
| KIND 상장폐지현황 | 두 상폐 후보의 시장·상폐일·사유를 공식 화면에서 수동 대조 | 독립 검증·수동 복구용 | 자동 import의 endpoint/파일 형식, 호출량·보관·재배포 조건은 미계약. BT03 선행 조건 |
| 허용된 역사 EOD 공급자 또는 KRX 계약 export | 아직 미확보 | 상폐 종목 OHLC와 전체 역사 coverage의 필수 대체 경로 | BT03에서 사용권, 원문 hash, 정정 이력, 보관·재배포 범위를 계약하고 fixture로 검증 |

KRX Open API의 비밀값은 runtime secret에만 두며, 결과의 보관·재배포는 현행
[KRX source contract](krx-universe-source-contract.md#5-보안이용조건-및-fixture-수용-조건)의
비상업적 이용 조건과 서비스별 승인을 넘어서면 안 된다. KIND 화면도 자동 수집 허가를
의미하지 않는다. 이 때문에 BT01은 대량 upsert나 “생존편향 제거 완료”를 수행하거나 주장하지
않는다.

## 완료 판정

BT01은 다음 증거를 함께 남길 때 완료다.

1. 현재 상장, 수정주가 기업행위, 상폐 후보, 2013년 이전 목표를 포함한 5~10개 표본의
   JSON 결과. 적어도 한 표본은 두 페이지 이상을 확인한다.
2. 각 표본에서 고정 기준일·연속조회·중복 경계·목표일 도달 또는 미도달 사유가 드러난다.
3. KRX 종목검색/KIND 결과로 상폐 후보의 코드·시장·상폐일을 대조하고, 이용·보관·재배포
   조건과 명부 전체 coverage의 미확인 부분을 기록한다.
4. 결과를 근거로 Kiwoom만으로 가능한 기간/종목과 별도 역사 공급자 또는 import가 필요한
   기간/종목을 source matrix에 구분한다.

BT01 결과는 **partial**이다. BT02는 가격과 독립된 역사 identity를 먼저 만들고, BT03은
상폐·시장 이전 이벤트의 허용된 import source를 계약해야 한다. 그 전에는 전체 backfill 시간·용량
또는 생존편향 제거 완료를 주장하지 않는다.
