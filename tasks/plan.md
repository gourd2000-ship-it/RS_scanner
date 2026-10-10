# 계획: MA50·ATR14 백테스트 운영 검증

작성일: 2026-10-09. 상태: 계획 수립 완료, 실행 작업 미착수.

## 목표

실제 데이터로 재현 가능한 백테스트를 운영 검증하고 일일 지표 갱신을 시작한다. 첫 작업 묶음은 **읽기 전용 현황·원인 조사(T1~T2)와 운영 도구 준비·격리 PostgreSQL 검증(T3~T4)**을 권장한다. 조사 결과로 실제 운영 쓰기의 대상과 범위를 결정한다.

이번 요청에서는 계획 문서만 작성한다. 기존 완료된 ATR14 백필 계획과 체크리스트는 `plan.legacy-20261008.md`, `todo.legacy-20261008.md`에 원문 그대로 보존한다.

## 기준선과 미확인 항목

- 기준 커밋: `32897a5`, 브랜치 `dryforge/atr14-storage`. 계획 시작 시 원격과 일치했다.
- 시뮬레이터, MA50·ATR14 조건, 고정 snapshot, 운영자 API·화면, 명시 실행 워커가 구현됐다.
- 보관된 `job_137`은 2026-10-08 기준 `blocked`: 검증 실패 206건(양수 OHLC 188, OHLC 순서 18), stale 201종목, coverage 94.8169%. 범주가 겹치므로 합산하여 고유 실패 종목 수로 해석하지 않는다.
- 운영 DB의 최신 품질 판정, migration 적용 상태, 실제 dataset·snapshot·워커 상태는 이번 계획에서 조회하지 않았다.
- 기존 검증은 MA50 snapshot 전체 실행을 SQLite에서, PostgreSQL에서는 RS 기반 전체 실행과 지표 migration을 확인했다. 두 지표를 동시에 사용하는 전체 경로의 PostgreSQL 검증을 추가한다.
- 백필 완료는 모든 값이 사용 가능하다는 뜻이 아니다. ATR14 완료 기록에는 warming_up 28,396행, data_unavailable 2,223,331행도 포함된다. 최초 기간·유니버스는 실제 가용성과 source 일치에 따라 정한다.

## 작업 순서

| 작업 | 결과물 | 선행 조건 | 실행 경계 |
|---|---|---|---|
| T1 현재 운영 상태 확인 | 조회 시각·job·정책·schema·dataset·지표 상태 보고서 | 없음 | 읽기 전용 |
| T2 품질 실패 원인 조사 | 근거·중복 제거 수량·제한 재처리 manifest | T1 | 읽기 전용 |
| T3 운영 입력 준비 절차 | dataset·RS·지표 snapshot 준비 진입점과 dry-run | 코드 조사 즉시 가능, manifest는 T1 이후 | 코드·격리 DB |
| T4 두 지표 PostgreSQL 검증 | 생성→사전 점검→워커→결과·replay 검증 | T3 | 격리 DB |
| T5 제한 재처리·품질 재검증 | 전후 대조·새 품질 보고서 | T2, 관련 코드 검증, 운영 결정 | 승인 범위의 운영 쓰기 |
| T6 최초 complete dataset 발행 | dataset·RS·두 snapshot ID/hash·replay 보고서 | T4, T5 통과, 발행 운영 결정 | 승인 범위의 운영 쓰기 |
| T7 워커 1건 실행·재현 | 최초 실행과 고정 입력 재실행 비교 | T6, 운영 실행 결정 | 별도 프로세스 1개 |
| T8 일일 지표 단계적 활성화 | 증분·재사용·오류 관측 결과 | T5, T7, 활성화 결정 | 운영 설정 적용 |

완료 기준·검증·예상 파일은 [todo.md](todo.md)에 기록한다. T3의 코드 조사와 격리 준비는 T2와 독립적으로 진행할 수 있다. 운영 쓰기는 선행 조건을 만족한 뒤 순서대로 진행한다.

## 실행 원칙

1. T1~T2는 DB read-only transaction/권한과 고정 조회 시점을 사용한다. `scripts/validate_data_quality.py --mode report_only`도 validation run/case를 저장하므로 읽기 전용 조사에 사용하지 않는다. 비밀값은 출력하지 않는다.
2. 전량 백필을 반복하지 않는다. 실제 과거 evidence 변경 대상만 새 generation 필요 여부를 산정한다. 최신 날짜 공백은 정책 일치 관측과 가용성을 확인해 제한 증분 계획에 포함한다.
3. 원문이 없는 실패는 공급자 오류라고 단정하지 않는다. 미확인으로 남기고 필요한 근거 확보 절차를 제안한다. 거래정지·상장 상태는 근거로만 판정한다.
4. 최초 입력은 complete 종목·연도 구간과 identity 확인된 생존 lifecycle로 제한한다. MA50·ATR14 준비 이력, RS, benchmark를 모두 충족하는 기간을 고른다. 임의 종목 제외나 품질 기준 완화로 통과시키지 않는다.
5. `create_clean_backtest_dataset.py --create`는 DB 쓰기다. 지표 snapshot 생성 서비스는 있으나 dataset·RS·snapshot을 운영에서 순서대로 준비하는 절차의 연결은 T3에서 확인하고 부족한 진입점만 보완한다.
6. `replay_backtest_dataset.py`의 replay_hash는 페이지 응답에 의존한다. 동일 dataset·필터·page_size로 반복 비교하고, 다른 page_size는 정렬된 행·건수·누락/중복으로 비교한다. 내부 page 호출과 실제 HTTP 인증·cursor 계약도 각각 확인한다.
7. 일일 validation이 passed 또는 passed_with_warnings여도 dataset은 별도 complete 구간 감사를 통과해야 한다. 보고서의 범위·기준일이 실행 입력과 맞는지 확인하고 경고·제외 내역을 보존한다.
8. 최초 worker 실행 전 queue와 running 상태를 확인해 승인된 한 건을 처리한다. 동일 전략·dataset·RS·두 지표·benchmark를 고정한 추가 실행에서 run ID·시각을 제외한 업무 결과를 대조한다. 강제 종료 복구 실험은 격리 DB에서 수행한다.

## 점검과 운영 결정

- T1~T2 뒤: 최신 근거로 원인·대상·기간·정책·예상 변경량을 확정한다. 연결이나 근거 부족은 미확인으로 기록한다.
- T3~T4 뒤: migration·입력 생성·두 지표 조건·실패 거부·불변성·재현성 검증이 갖춰진 실행안을 만든다.
- T5 직전: 실제 운영 DB 쓰기·재수집의 구체적 범위와 영향을 검토한다. 루트 AGENTS.md의 명시적 운영 결정 요구에 따른다. 계획 작성 자체는 운영 쓰기 승인이 아니다.
- T6~T8 직전: 발행·worker·일일 활성화 범위가 운영 결정에 포함됐는지 확인한다. 이미 승인된 범위를 반복 확인받을 필요는 없다.
- 최종 완료: 운영 dataset replay, 두 지표 실제 실행과 고정 입력 재현, 일일 증분·재사용·차단 동작 검증. 일일 관측 기간은 기본 3개 거래일을 제안한다.

## 위험과 중단·재개

| 위험 | 대응 |
|---|---|
| 보관본과 최신 DB 차이 | T1 조회 시각·job ID로 새 기준선 고정 |
| source·조정·identity 불일치 | snapshot 연결 거부, 근거 조사 후 별도 정책 결정 |
| 중복 writer | 호스트 PID namespace와 DB 연결을 함께 확인 |
| 준비 이력·target_date 관측 부족 | 사용 불가 사유 기록; 0 대체·이월 금지 |
| 부분 실패·프로세스 중단 | rollback/run 상태 확인, 종료 확인 후 문서화된 복구 |
| 과거 원본 변경 | 기존 dataset/run/snapshot 보존, 새 manifest/generation 계획 |

차단·hash 불일치·예상 밖 DB 상태가 확인되면 추가 호출을 멈추고 근거를 보존한다. 재개는 원인 해소, 같은 manifest/checkpoint, 단일 writer 확인 후 수행한다. 되돌림은 향후 호출·설정 비활성화가 우선이며 기존 결과 삭제나 적용된 migration 수정은 하지 않는다.

## 근거

- [실행 준비 보고서](../reports/operations/backtest_ma50_atr14_readiness_20261009.md)
- [운영 절차](../docs/operations.md), [미해결 사항](../docs/tracking/findings.md)
- [도메인 규칙](../docs/business-rules.md), [입력·API 계약](../docs/contracts.md)

대상 환경, 최신 job, 최초 dataset 기간과 source 정책은 T1~T2 결과로 확정하며 현재 값으로 추측하지 않는다.
