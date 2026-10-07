# ATR14 역사 DB 백필 작업 목록

## Task 1: 운영 preflight — 대기

**Acceptance criteria:** 고정 manifest hash, migration head, ATR 시작 수량, Volume MA50 완료, 디스크 여유, 동시 batch 및 checkpoint 상태를 읽기 전용으로 대조한다.

**Verification:** manifest 대상 2,175개·예상 input/result 각 7,303,650행과 DB 상태를 기록한다.

**Dependencies:** None

## Task 2: 승인 manifest 적용 — 대기

**Acceptance criteria:** 고정 manifest hash와 새 checkpoint를 사용해 `--apply`로 운영 DB에 ATR14 evidence·run·value를 append-only 저장한다.

**Verification:** checkpoint 완료 수와 DB completed run 수가 증가하며, 실패 사유는 checkpoint에 보존된다.

**Dependencies:** Task 1

## Task 3: 중단·재개 확인 — 조건부

**Acceptance criteria:** 중단이 발생한 경우에만 동일 checkpoint·manifest hash로 `--resume`을 실행하며 대상·정책은 변경하지 않는다.

**Verification:** 이미 완료된 run은 재사용되고 중복 series/run/value가 생기지 않는다.

**Dependencies:** Task 2

## Task 4: 완료 대조 및 상태 갱신 — 대기

**Acceptance criteria:** 2,175개 대상과 상태별 result row를 manifest, checkpoint, apply report, DB 집계로 상호 대조하고 현재 상태를 갱신한다.

**Verification:** failed run 0건, series/run/value 수와 result hash가 일치하며 실행 증거가 보존된다.

**Dependencies:** Task 2 또는 Task 3
