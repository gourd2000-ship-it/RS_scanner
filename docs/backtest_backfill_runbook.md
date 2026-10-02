# 과거 기록

이 문서는 이전 백필 계획을 기록한다. 현재 발행 조건은 [도메인 규칙](business-rules.md)의 complete 구간 정책과 [운영 절차](operations.md)를 따른다.

# BT12/BT13 역사 백테스트 적재 runbook

갱신일: 2026-09-07

## 현재 판정

BT12 lifecycle evidence와 전체 가격 manifest dry-run, BT13 승인 범위 적재·검증·불변
dataset·RS·전 페이지 replay를 완료했다. 결과는 상폐 OHLC와 일부 identity가 미확보인
`partial` dataset이며, 완전한 상폐 수익률이나 생존편향 제거 완료를 주장하지 않는다.

- KRX CSV 46개(CP949)에서 보통주 lifecycle 4,130개를 읽었다. 상장 목록과
  상폐 목록의 폐지일이 서로 다른 160개 lifecycle, 또는 열린 lifecycle을 현재
  identity에 정확히 대응하지 못한 287개는 자동 적용하지 않았다.
- 재사용 code 제약을 제거한 후, 유일한 현재 identity 2,175개에 상장일을 보완하고
  종료가 명확한 과거 identity 1,508개를 별도 생성했다. `(code, market,
  listed_at)` 중복은 0건이다.
- `krx_listing_delisting_csv` contract v1으로 immutable event 4,691개를 저장했다
  (상장 3,225 / 상폐 1,466). 원본 행 기준 unresolved 608개는 계속 검토 대상이다.
- 현재 KRX code·market, legacy Symbol, Naver mapping이 모두 정확히 일치한 2,175개에
  한해 Kiwoom mapping을 만들었다. 역사 상폐 identity와 증거 부족 identity는
  provider mapping을 추론하지 않았다.
- `bt12-2013-20260904-dry-v4` (`manifest_hash`
  `81c05ed02cddc332fc4362888912fa1bdbbc03713f8e9415fda290aec9df65f1`)는
  `target_count=2,659`, `expected_rows=5,768,408`, `unresolved_targets=484`였다.
  가격 요청·관측·RS 기록은 모두 0이다.

따라서 coverage 상태는 `partial`이다. 484개는 provider code 또는 가격 소유
Symbol이 확정되지 않은 lifecycle이며, 가격을 0 수익이나 마지막 가격 연장으로
바꾸지 않는다.

## BT13 partial execution

`bt13-2013-20260904-v1`은 위 dry-run과 동일한 lifecycle/가격 manifest
(`fd10a7522723c7073cfddbc6c87b85e94815d8fe9bcd6309957ab33db133e178`)로 실행했다.
2026-09-06에 9,691/15,500 요청을 사용해 수집 단계를 종결했다.

- checkpoint: 정상 수집 완료 2,125개, 명시적 실패 534개, pending/running 0개.
  484개는 provider code 또는 price owner가 확정되지 않은 lifecycle이고, 나머지
  50개는 provider가 지원하지 않음을 기록한 대상이다.
- run lineage가 붙은 price observation은 5,101,865건이며, 전체 canonical
  `daily_prices`는 6,444,237건이다. 기존 canonical 값과 다른 payload는 overwrite하지
  않고 conflict candidate로 보존한다.
- 이전 checkpoint 구현은 공급자가 범위 시작일까지 정상 수집했어도 기대 거래일 중 하나가
  비어 있으면 `running`으로 남겼다. 첫 기대일이 저장된 기존 checkpoint 2,096개를
  네트워크 재조회 없이 완료 처리하도록 보정했고, 남은 76개만 실제 재조회했다.
- BT07 validation run 41은 17,436개 case를 저장했다. 유효 가격 coverage는
  88.0765%이므로 이 run의 상태는 `completed_partial`이며, 상폐 종목 가격·청산값을
  0 수익 또는 마지막 가격 연장으로 바꾸지 않는다.

### 최종 dataset·RS·replay 결과

- immutable dataset: `backtest-d5d93cda58bd5719e832cb5c`; final manifest hash는
  `0f81b118e0a5f26fb26213cbea6c815b0d802ef6e3d74739303918f4761a8ebb`이다.
  membership 5,768,408행과 immutable price 5,085,882행을 저장했으며, 기대 가격 중
  실제 관측된 행은 5,080,612행이다.
- 역사 RS(`rs-historical-v1`): 5,768,408행 중 4,545,817행은 available이고,
  1,222,591행은 `price_missing` 또는 `insufficient_history`로 명시했다. 미래 가격을
  사용하지 않으며, RS input hash와 result hash는 dataset manifest에 고정된다.
- 과거 universe는 2,659개 lifecycle로, 현재 상장 survivor-only 2,175개보다
  484개 많다. 이 중 상폐 event가 있는 lifecycle은 448개이며 상폐 lifecycle의 기대
  가격 564,415행은 0건만 확보됐다. 이를 0 수익이나 마지막 가격으로 대체하지 않는다.
- 전 API replay는 5,000행 keyset page 1,154개, 총 5,768,408 item을 순회했다.
  결과 파일은 [`bt13_dataset_replay_20260906.json`](../reports/backtest/bt13_dataset_replay_20260906.json)이며,
  replay hash는 `57e9fadca990ff48ea947dd1b3ed64e6b460017e4f9ac91c02313dbfee2ccdc1`이다.
  partial 1,222,591행의 사유는 `price_missing` 687,796건, `insufficient_history`
  534,795건이다.
- API의 materialized page query는 전체 relation을 메모리에 적재하지 않도록 keyset cursor와
  dataset/date/instrument composite index를 사용한다. 첫 수집 시점의 strict 응답은 준비
  기간 부족으로 0행이고, 2026-09-04 strict page는 1,000행에서 price/RS coverage 100%를
  확인했다.

따라서 수집과 검수는 종료됐지만 coverage 상태는 계속 `partial`이다. 534개 미확보
lifecycle, validation run 41, 상폐 terminal value unknown은 dataset manifest와 최종 replay
보고서의 제약으로 유지된다.

연결 DB의 Alembic revision은 `o8b9c0d1e2f3` head다. 기존에 `create_all`로 생성된
테이블은 migration에서 재생성하지 않고, `final_manifest_hash`, `requests_used`, price
backfill lineage와 materialized replay용 composite index를 additive reconciliation으로 보완했다.

## Kiwoom read-only probe

증거 파일: `reports/backtest/bt12_kiwoom_probe_20260904.json`

고정 base date `20260904`, target date `20130101`, 최대 8페이지로 probe했다.

| 표본 | 결과 | 페이지/행 | 응답 바이트 | 시간 |
| --- | --- | ---: | ---: | ---: |
| 005930, 000660, 035420, 068270 | 2013-01-01 도달 | 각 6 / 3,600 | 합계 2,883,631 | 합계 6.580275초 |
| 230980, 032980 (상폐 후보) | `parse_failed` | 각 1 / 0 | 합계 522 | 합계 0.268822초 |

성공 표본은 재시도 0회였다. 이 값은 현재 상장 표본의 제한된 네트워크/파싱
측정일 뿐이며, 상폐 종목 지원·전체 명부 coverage·대량 저장 시간을 보장하지 않는다.

## 승인 전 필수 입력과 preflight

1. 이용·보관·재배포 권한이 확인된 KRX/KIND 또는 허용된 역사 공급자 lifecycle
   export를 제공한다. importer는 명시적 `instrument_id`만 허용한다.
2. export를 dry-run으로 검증한 뒤 실제 import 결과의 source file hash와 event 수를
   기록한다. current symbol/snapshot에서 상폐일을 보완하거나 추론하지 않는다.
3. 고정 base date와 범위로 history dry-run을 다시 만든다. 최초 후보 범위는
   `2013-01-01`부터 `2026-09-04`까지, KOSPI/KOSDAQ 보통주다. 다만 import 결과와
   provider 지원 범위에 따라 대상·미확보 구간은 다시 확정한다.
4. 별도 검증 DB에서 제한 probe를 저장·검증·RS·dataset 생성까지 수행하여
   `BackfillProbe`의 fetch/store/validation/RS 시간과 DB 증가량을 수집한다.
   운영 가격 테이블에는 이 단계에서도 쓰지 않는다.
5. `df -h`와 PostgreSQL relation/index 크기를 함께 기록한다. 승인 요청에는
   예상 DB 증가량의 두 배 이상 여유 공간 또는 명시적 운영자 예외가 필요하다.

## 재현 명령

```bash
.venv/bin/python scripts/import_listing_history.py \
  --input /secure/path/approved_listing_events.json \
  --source kind_export \
  --source-contract-version kind-delisting-export-v1 \
  --source-url https://kind.krx.co.kr/investwarn/delcompany.do \
  --dry-run

.venv/bin/python scripts/backfill_historical_prices.py \
  --start 2013-01-01 --end 2026-09-04 --base-date 20260904 \
  --market KOSPI --market KOSDAQ --request-budget 500 \
  --dry-run --run-id bt12-2013-20260904-dry-v2
```

`--request-budget`은 run 전체 한도다. 한도를 다 쓰면 아직 처리하지 않은
target은 pending으로 남으므로, 다음 승인 manifest는 새 run ID와 새 hash로 만든다.

## BT13 승인 형식

아래 값이 실제 dry-run report에 모두 채워진 뒤에만 사용자가 명시적으로 승인한다.

```text
승인: run_id=<값>, manifest_hash=<값>, 범위=<값>, request_budget=<값>,
예상 요청/시간/DB 증가량=<값>, partial/미확보 구간=<값>
```

승인 후에는 같은 command에서 `--dry-run`만 제거한다. 완료 뒤에는 historical
validation, RS run, immutable dataset 생성, 모든 API 페이지 hash/RS replay와
survivor-only 차이·coverage 보고를 수행한다. 상폐 가격/청산값이 미확보면 이를
0 수익이나 마지막 가격 연장으로 바꾸지 않고 `partial`/`terminal_value_unknown`로
공개한다.
