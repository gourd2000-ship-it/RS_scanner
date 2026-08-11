# EOD 공급자 결정 기록

상태: 계약 확인 대기
작성일: 2026-08-11

## 현재 결정

RS Scanner에는 특정 상용 공급자를 하드코딩하지 않고 `BulkEodSource` 계약과
`EodBatch` 정규화 계층을 먼저 반영했다. 실제 운영 공급자는 아래 조건을 서면으로
확인한 뒤 설정으로 주입한다.

- 한국 주식시장 전체 eligible 종목의 일별 OHLCV 제공
- 거래일, 시장, 종목코드, 조정주가 여부가 명시된 데이터 계약
- 파일/API 응답의 checksum 또는 무결성 확인 방법
- 상업적 사용, 저장, 재배포, Hermes 서버 간 제공 범위에 대한 권리
- 장애 시 재시도·재전송·fallback을 허용하는 요청 제한

현재 코드의 EOD 경로는 계약이 확정되기 전까지 운영 공급자로 간주하지 않는다.
검증되지 않은 bulk 파일은 `complete=False`, 기준일 불일치, 알 수 없는 종목,
중복·무효 가격 행 중 하나라도 발견되면 저장하지 않고 시장 단위 실패로 처리한다.
누락 종목만 기존 Naver source fallback queue로 보낼 수 있다.

구현 위치:

- `app/crawler/sources/eod.py`: `EodBatch`, checksum/기준일/시장/행 수/중복/가격 검증,
  canary allowlist 계약
- `app/services/batch/sync_eod.py`: 시장별 bulk 저장, 종목별 상태 기록, 누락 종목 fallback
- `app/services/monitoring/eod_canary.py`: coverage·최신성·30분·provider health의 3회 연속
  성공 상태와 rollback 상태 저장

## 후보 검토

| 후보 | 적합성 | 보류 사유 |
|---|---|---|
| KRX 데이터 상품/API | 국내 시장 기준일·종목 체계에 적합한 후보 | 상품별 이용약관, 상업적 사용·저장·재배포 권한을 계약 단위로 확인해야 함 |
| OpenDART | 공시·기업 이벤트 보강 후보 | 일별 전종목 가격 bulk 공급자의 대체재로 사용하지 않음 |
| 계약된 상용 EOD 공급자 | 운영 목표에 가장 직접적으로 부합 | 공급자명, SLA, 라이선스, 요청 한도 확정 전에는 선택 불가 |

공식 참고 자료:

- [KRX Market Data Usage Policies](https://data.krx.co.kr/inc/datasale/Market%20Data%20Usage%20Polices_ko.pdf)
- [OpenDART 소개](https://opendart.fss.or.kr/intro/main.do)

## Go-live 승인 체크리스트

- [ ] 공급자명과 계약/상품 문서 식별자 기록
- [ ] 운영·staging·Hermes 제공 범위가 라이선스에 포함됨
- [ ] 기준일과 조정주가 정책을 `EodBatch` 계약과 샘플 fixture에 반영
- [ ] checksum 검증 방식과 불완전 파일 처리 확인
- [ ] 시장별 장애·fallback·재처리 예산 확인
- [ ] staging 3회 연속 coverage 99.5% 이상, 가격 단계 30분 이내
- [ ] provider feature flag off 및 마지막 정상 dataset 제공 rollback 리허설

따라서 현재 로드맵 상태는 CRAWL-08의 “후보 조사 및 위험 정리”까지이며,
운영 공급자 결정과 Gate 3는 계약 확인 이후로 남겨 둔다.
