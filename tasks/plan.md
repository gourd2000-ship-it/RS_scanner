# 운영 계획: ATR14 역사 DB 백필

## 2026-10-08 완료 결과

원래 호스트 writer는 재개 없이 종료했다. apply report의 실패 17건은 동시 writer
충돌로 생긴 checkpoint 표기이며, 최종 reconciliation은 승인된 2,175개 대상의
completed run과 저장된 input/result 각 7,303,650행을 검증했다. 상태별 결과는
available 5,051,923행, warming_up 28,396행, data_unavailable 2,223,331행이다.
DB의 ATR series·completed run은 각각 2,175개이며 실패 run은 없다. 일치한
17개 checkpoint 표기만 복구했고 DB 결과는 변경하지 않았다. 감시 컨테이너는
exit 0으로 종료했다. 일일 활성화는 품질 gate가 `blocked`여서 별도 보류한다.

## 2026-10-08 복구 계획(완료)

현재 운영 DB에는 ATR14 완료 run이 계속 늘고 있다. 2026-10-07 15:11 UTC에 시작한
호스트 프로세스가 살아 있었는데, 격리된 셸의 프로세스 목록에 나타나지 않아 별도의
Docker 백필을 기동했다. 동일 DB·체크포인트를 두 프로세스가 동시에 사용하면서
일부 checkpoint에 `IntegrityError`가 남았다. Docker 프로세스는 중지했고,
호스트 프로세스 한 개만 남겨 진행 중이다. 잠금 파일 경로를 삭제·재생성한 탓에
파일 잠금만으로는 이 사고를 막지 못했다.

1. 호스트 백필의 PostgreSQL 연결과 checkpoint 증가를 확인하고, 추가 writer를
   기동하지 않는다. DB 완료 run에 비해 checkpoint가 뒤처질 수 있으므로 양쪽을
   별도로 집계한다.
2. 실패 표기 종목은 승인 manifest와 기존 완료 run의 불변 입력 sequence·결과
   hash가 일치하는지 읽기 전용으로 확인한다. 일치하지 않는 종목은 자동 복구하지
   않고 원인과 DB 상태를 별도 기록한다.
3. 호스트 백필이 마지막 대상까지 처리하고 DB 쓰기가 끝난 뒤에만 checkpoint를
   원자적으로 대사한다. 완료된 DB run을 재계산하거나 덮어쓰지 않는다.
4. 최종 검증은 대상 2,175개 각각의 current generation·completed run,
   manifest 결과 hash, run input/value 건수와 전체 7,303,650개 예상값을
   대조한다. 불일치가 있으면 완료로 선언하지 않는다.
5. 검증 보고서와 운영 상태를 기록한다. 일일 ATR14 및 RS·화면 활성화는 별도
   품질 gate와 운영 판단에 따른다.

실행 중인 호스트 writer가 끝나기를 기다리는 독립 감시 컨테이너는
`scripts/watch_atr14_backfill.py`를 사용한다. 호스트 PID namespace에서
실제 `backfill_atr14.py` 프로세스가 사라진 것을 확인한 뒤, 정상 완료 보고서가
없으면 동일 manifest·checkpoint로 한 번 재개한다. 완료 보고서가 생기면
`scripts/reconcile_atr14_checkpoint.py --apply`로 전체 종목의 불변 입력과
실제 저장값의 hash를 검증하고 일치하는 실패 표기만 복구한다. 결과는
`reports/atr14/reconciliation_20130102_20260904.json`에 남긴다.
감시 컨테이너의 `app/`·`scripts/` 코드는 기동 시 내부 snapshot으로 복사하여
작업 공간의 후속 편집이 실행 중인 검증 절차를 바꾸지 않게 한다.

중단 기준: 동시 writer가 다시 나타나거나 완료 run의 hash가 승인 manifest와
다르면 호스트 백필을 안전 중지하고 원인을 조사한다.

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
