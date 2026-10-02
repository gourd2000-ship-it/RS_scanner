# 개발 메모

## 수정주가를 섞으면 생기는 오류

증상: 같은 종목·날짜의 canonical 가격과 Kiwoom 관측이 크게 다르다. 원인: Naver와 Kiwoom의 수정 기준·기준일이 다를 수 있다. 대응: 차이를 자동 오류나 자동 보정으로 처리하지 말고 `source_conflicts.csv`와 adjustment policy를 함께 보존한다. 새 dataset은 하나의 명시된 선택 정책만 사용한다.

## 결측이 조용히 사라지는 오류

증상: 가격 테이블만 조회한 백테스트 결과가 높은 coverage처럼 보인다. 원인: 기대 유니버스에 있으나 가격이 없는 종목·거래일이 join에서 사라진다. 대응: coverage 분모는 가격 행이 아니라 lifecycle × 거래일에서 만들고, `missing`과 `provider_unsupported`를 별도 노출한다.

## 데이터셋 재현성의 함정

증상: 페이지를 넘기는 동안 가격 upsert가 발생하면 같은 cursor가 다른 행을 가리킨다. 원인: 최대 ID만 watermark로 쓰면 기존 행의 in-place 변경을 식별하지 못한다. 대응: 물질화 dataset과 manifest·content hash를 사용하고, replay는 dataset ID·필터·cursor의 일치를 검증한다.

## 장기 OHLCV 감사 체크

1. `--read-only` 감사로 대상·기간·cutoff·선택 정책을 manifest에 고정한다.
2. `expected = valid + missing + invalid + review_required`를 확인한다.
3. extreme return, corporate action, source conflict를 근거와 함께 검토한다.
4. `complete` 구간만 dataset 후보로 만들고, 격리 DB에서 migration·replay를 확인한다.
5. 운영 DB 변경과 dataset 발행은 감사 수량·제외 목록·리소스 영향을 사람이 검토한 뒤 실행한다.

## 파일 브리지와 로컬 실행

Kiwoom 파일 브리지는 요청·응답 파일을 공유 디렉터리로 교환한다. timeout이나 continuation 실패를 빈 가격 이력으로 저장하지 말고 run 실패와 재개 지점을 기록한다. `.env.production` 같은 로컬 설정 파일은 출력 명령으로 확인할 때에도 값 자체가 터미널·대화에 남지 않도록 key 이름만 검사한다.
