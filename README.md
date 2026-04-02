# Market Radar One Page Stable

한 페이지 전체요약만 먼저 안정적으로 살린 버전입니다.

## 구조
- index.html
- data/latest.json
- data/history.json
- scripts/update_data.py
- .github/workflows/update-data.yml

## 데이터 소스
- Bitcoin: CoinGecko
- Fear & Greed: alternative.me
- USD/KRW: Frankfurter
- KOSPI/KOSDAQ: Naver Finance 일별지수 표
- Samsung Electronics: Naver Finance

## 사용법
1. 저장소 전체 파일 교체
2. GitHub Pages 유지
3. Actions → Update market snapshot → Run workflow
4. Pages 새로고침

미국지수/VIX/원자재/FRED는 이번 버전에서 제외했습니다. 먼저 한 페이지를 안정화하는 목적입니다.
