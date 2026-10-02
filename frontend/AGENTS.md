# 프런트엔드 작업 규칙

`frontend`는 Next.js 16과 React 19로 RS 조회 화면을 제공한다. Python 모듈·DB·공급자 credential에 직접 의존하지 않고, `types/api.ts`와 HTTP 계약을 통해서만 백엔드 데이터를 소비한다.

Next.js 버전의 API·관례는 학습 데이터와 다를 수 있다. 코드를 바꾸기 전에 설치된 `node_modules/next/dist/docs/`의 관련 문서와 deprecation 안내를 확인한다.

RS·백테스트 화면은 data status, coverage, 기간, 제외 사실을 숨기지 않는다. 개인 연구용 결과를 매매 추천이나 수익 보장으로 표현하지 않는다. 브라우저 환경 변수에는 공개 가능한 값만 넣고 token·DB URL·공급자 키를 포함하지 않는다.

변경 후 `npm run lint`와 `npm run build`를 실행한다.
