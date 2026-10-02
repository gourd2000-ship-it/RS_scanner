# 운영 스크립트 규칙

`scripts`는 배치·감사·import·보정·dataset 발행의 명시적 운영 진입점이다. 각 스크립트는 입력 기간, 대상, source/adjustment policy, dry-run 또는 read-only 여부와 출력 경로를 명확히 받아야 한다.

감사·계획은 기본적으로 읽기 전용이다. 운영 DB 쓰기, 대량 재수집, 가격 보정, dataset 발행을 수행하는 새 스크립트는 실행 전 manifest·예상 영향·재개 방법을 제공하고, 상장폐지 lifecycle과 `complete` 외 구간을 자동으로 포함해서는 안 된다.

비밀값을 인수·출력·보고서에 넣지 않는다. 실행 결과는 run ID, 수량, 실패 사유, output path를 남기며, 공급자 실패를 정상 0건으로 바꾸지 않는다.
