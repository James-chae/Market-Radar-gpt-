# Market Radar · GitHub Pages + GitHub Actions + JSON Snapshot

이 프로젝트는 **정적 GitHub Pages 대시보드**와 **GitHub Actions 데이터 생성기**를 분리한 구조입니다.

핵심 원칙:
- 브라우저가 Yahoo, 프록시, TradingView 위젯을 직접 두드리지 않음
- 화면은 `index.html`이 담당
- 숫자와 차트 데이터는 `data/latest.json`, `data/history.json`만 사용
- GitHub Actions가 주기적으로 데이터를 수집하고 JSON을 갱신

## 폴더 구조

```text
index.html
requirements.txt
scripts/
  update_data.py
data/
  latest.json
  history.json
.github/workflows/
  update-data.yml
```

## 데이터 소스

- KOSPI / KOSDAQ / 삼성전자: `pykrx`
- S&P500 / Nasdaq100 / Dow / Russell / VIX / Gold / WTI / DXY / USDKRW: `Stooq`
- Bitcoin: `CoinGecko`
- US 10Y / US 2Y / HY Spread: `FRED CSV`
- Fear & Greed: `alternative.me`

## 배포 순서

1. 새 GitHub 저장소 생성
2. 이 파일 전체를 저장소 루트에 업로드
3. GitHub 저장소에서 **Settings → Pages** 이동
4. Source를 **Deploy from a branch**로 설정
5. Branch를 `main`, folder를 `/ (root)`로 설정
6. 저장
7. **Actions 탭**에서 `Update market snapshot` 워크플로를 수동 실행
8. 첫 실행이 끝나면 `data/latest.json`, `data/history.json`이 생성 또는 갱신됨
9. Pages 주소에서 대시보드 확인

## 갱신 주기

기본값은 30분마다 1회입니다.

워크플로 파일에서 아래 cron을 수정하면 됩니다.

```yml
schedule:
  - cron: '*/30 * * * *'
```

## 주의

- 이 구조는 **실시간 스트리밍 차트**가 아니라 **주기 갱신 스냅샷 대시보드**입니다.
- GitHub Actions 스케줄은 약간 지연될 수 있습니다.
- 한국 주식시장은 거래일 / 장중 여부에 따라 최신 종가 기준으로 반영될 수 있습니다.
- 일부 외부 소스가 일시 실패하면 해당 카드만 `데이터 없음`으로 보이고, 오류 로그에 원인이 남습니다.

## 추천 운영 방식

- GitHub Pages는 화면만 담당
- GitHub Actions는 데이터만 생성
- 브라우저는 오직 내 저장소의 JSON만 읽음

이 구조가 현재 요구사항인 **"내 PC를 켜두지 않고도 안정적으로 보는 대시보드"**에 가장 잘 맞습니다.
