# 운영 계획: ATR14 역사 DB 백필

## 목표

승인된 ATR14 manifest를 변경하지 않고 2013-01-02~2026-09-04의 2,175개
대상에 대해 append-only calculation run·공용 OHLC evidence·ATR14 value를
운영 DB에 저장한다. 이번 실행은 기존 DB schema를 바꾸지 않으며, 일일 ATR14
활성화·공개 API·RS·백테스트 입력을 변경하지 않는다.

승인 manifest hash는
`191847c06960c06bebb6835dcbae7448ff32c7f8237064e89da58f77e68cdb15`다.
계획은 7,303,650 input evidence와 7,303,650 result value를 예상한다.

## 순서

1. 읽기 전용 preflight: manifest hash와 정의·정책, DB migration head,
   Volume MA50 완료 상태, ATR series/run의 시작 수량, 디스크 여유, 활성 batch와
   기존 checkpoint 부재를 확인한다. 이 중 하나라도 계획과 다르면 쓰기를 시작하지 않는다.
2. 고정 manifest hash와 새 checkpoint 경로를 사용해
   `scripts/backfill_atr14.py --apply`를 실행한다. 이 단계가 실제 운영 DB에
   ATR14 run·evidence·value를 append-only로 저장하는 유일한 단계다.
3. 실행 중에는 checkpoint와 실패 사유를 보존한다. 중단 후에는 같은 manifest hash와
   같은 checkpoint에만 `--resume`을 사용한다. 대상·기간·source policy·가격·품질
   근거를 바꾸거나 추정해서 재개하지 않는다.
4. 완료 후 manifest의 2,175개 대상과 checkpoint, apply report, DB의 ATR series,
   completed run, value 및 상태별 수량·hash를 대조한다. 보고서를 보존하고 현재 상태를 갱신한다.

## 실행 명령

```bash
APP_ENV=production .venv/bin/python scripts/backfill_atr14.py \
  --manifest reports/atr14/plan_20130102_20260904.json \
  --manifest-hash 191847c06960c06bebb6835dcbae7448ff32c7f8237064e89da58f77e68cdb15 \
  --checkpoint reports/atr14/checkpoint_20130102_20260904.json \
  --apply --output reports/atr14/apply_20130102_20260904.json
```

## 위험과 중단 기준

- migration head, manifest/checkpoint hash, 선택 evidence 또는 lifecycle이 계획과 다르면 쓰기를 시작·재개하지 않는다.
- 활성 일일 batch와 충돌하거나 디스크 여유가 부족하면 실행을 시작하지 않는다.
- 개별 대상 실패는 checkpoint와 원인만 보존한다. 가격·OHLCV·adjustment·quality 근거를 자동 보정하거나 실패를 정상 완료로 바꾸지 않는다.
- apply report와 DB 집계가 불일치하거나 failed run이 있으면 ATR14 일일 활성화나 공개 연결을 하지 않는다.

## 완료 기준

- manifest의 2,175개 대상 모두에 completed ATR run이 존재한다.
- created·reused·failed 수와 checkpoint 및 apply report가 같은 manifest hash를 가리킨다.
- DB series/run/value와 상태별 수량·result hash가 manifest의 기대치와 일치한다.
- 실패 run이 없고, 실행 증거와 대조 결과가 보존된다.
