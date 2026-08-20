# EOD 공급자 결정 기록

상태: Naver 주 공급자·Kiwoom 읽기 전용 폴백 결정 (PostgreSQL queue 구현 대기)
작성일: 2026-08-14

## 현재 결정

RS Scanner는 Naver를 주 공급자로 사용하고, Naver에서 실패한 종목만 Kiwoom으로
재조회한다. 특정 공급자 의존성을 코드 곳곳에 하드코딩하지 않고 `PriceSource` abstraction
뒤에 두며, Kiwoom은 실패 종목 전용 폴백·교차검증 경로로 제한한다. 운영 목표 경로는
PostgreSQL repair queue → Sam 전용 Repair API → autobot reconciler이며, 공유 폴더
파일 브리지는 전환 전 legacy 경로다.

Kiwoom REST API 사용 전 아래 조건을 확인한다.

- Sam 스킬의 `kiwoomcli domestic candles daily`가 실제 국내 주식 일봉을 반환하는지와
  내부 API ID/TR 매핑
- 계정·앱키·시크릿·IP 허용·토큰 만료 및 국내 조회 rate limit
- 상업적 사용, 저장, 재배포, Hermes 서버 간 제공 범위에 대한 권리
- 장애 시 재시도·재전송·fallback을 허용하는 요청 제한

Kiwoom은 전종목 bulk 공급자가 아니므로 전체 universe 재조회에는 사용하지 않는다.
Naver 응답과 Kiwoom 응답의 기준일·조정주가·OHLC가 다르면 자동 덮어쓰지 않고
`provider_conflict` 또는 보류 상태로 기록한다. 외부 bulk EOD 공급자 도입은 별도
후속 결정으로 남긴다.

구현 위치:

- `app/crawler/sources/naver.py`: Naver 주 공급자
- `app/crawler/sources/kiwoom.py`: 전환 전 직접 REST adapter
- 예정 `crawl_repair_requests/attempts/results`: 실패 종목 업무와 결과 lineage
- 예정 Sam Repair API: claim·complete·fail 업무 계약
- 예정 autobot reconciler: Kiwoom 결과 검증·canonical 반영
- `app/services/batch/sync_prices.py`: 공급자별 결과·재시도·target result 저장
- `app/services/monitoring`: provider별 coverage·복구율·충돌·rate limit 관측

## 후보 검토

| 후보 | 적합성 | 보류 사유 |
|---|---|---|
| Naver | 현재 주 공급자·universe/가격 수집 경로 | 응답 공백·파싱 실패와 요청량을 계속 관측해야 함 |
| Kiwoom REST API | 실패 종목의 독립적인 일봉 폴백·교차검증 | 계정·앱키·요청 제한·데이터 사용 범위를 확인해야 함 |
| KRX 데이터 상품/API | 향후 전종목 bulk 공급자 후보 | 상품별 이용약관, 상업적 사용·저장·재배포 권한을 계약 단위로 확인해야 함 |
| OpenDART | 공시·기업 이벤트 보강 후보 | 일별 전종목 가격 bulk 공급자의 대체재로 사용하지 않음 |
| 계약된 상용 EOD 공급자 | 향후 bulk 성능 개선 후보 | 공급자명, SLA, 라이선스, 요청 한도 확정 전에는 선택 불가 |

공식 참고 자료:

- [KRX Market Data Usage Policies](https://data.krx.co.kr/inc/datasale/Market%20Data%20Usage%20Polices_ko.pdf)
- [OpenDART 소개](https://opendart.fss.or.kr/intro/main.do)

## Go-live 승인 체크리스트

- [x] 주 공급자 Naver와 실패 종목 전용 Kiwoom 폴백 결정
- [ ] PostgreSQL repair queue migration·Repair API·reconciler 구현
- [ ] Kiwoom API 사용 등록, 계정·앱키·IP 정책 확인
- [ ] 운영·staging·Hermes 제공 범위가 라이선스에 포함됨
- [ ] 기준일과 조정주가 정책을 provider contract와 샘플 fixture에 반영
- [ ] Kiwoom rate limit·토큰 갱신·실패 재처리 예산 확인
- [ ] Naver/Kiwoom 샘플 데이터의 기준일·조정주가·OHLC 일치 확인
- [ ] staging 3회 연속 coverage 99.5% 이상, 가격 단계 30분 이내
- [ ] Kiwoom feature flag off 및 마지막 정상 dataset 제공 rollback 리허설

따라서 현재 로드맵 상태는 공급자 방향 결정, 로컬 adapter와 Sam 읽기 전용 스킬 준비까지
완료했으며, queue/API/reconciler 구현, Kiwoom 계정·계약 확인, canary 3회와 Gate 3
운영 검증은 후속 작업으로 남겨 둔다.
