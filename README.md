# 공모 레이더

문화재단 공모부터 소상공인 지원사업까지 지역·분야별로 찾는 페이지.

- `index.html`: 앱. 열릴 때 `data.json`을 읽는다.
- `data.json`: 접수 중 공고 목록. GitHub Actions가 매일 9시·12시·15시·18시(한국 시간)에 다시 만든다.
- `scripts/collect.py`: 수집기. 문화포털 문화지원사업, 경기기업비서, 기업마당에서 접수 중 공고를 모은다. 표준 라이브러리만 쓴다.

직접 돌리기: `python scripts/collect.py data.json`

GitHub의 예약 실행은 몇 분에서 30분쯤 늦게 시작될 수 있다.
