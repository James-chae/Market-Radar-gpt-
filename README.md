# Market Radar · GitHub Pages + GitHub Actions + JSON Snapshot

이번 교체본은 **브라우저가 외부 시세 API를 직접 호출하지 않는 구조**로 다시 정리했습니다.

## 구조

```text
index.html
requirements.txt
data/
  latest.json
  history.json
scripts/
  update_data.py
.github/
  workflows/
    update-data.yml
```

## 핵심 원칙

- 브라우저는 `data/latest.json`, `data/history.json`만 읽음
- 데이터 수집은 GitHub Actions가 수행
- 차트도 외부 위젯이 아니라 `history.json` 기준으로 그림
- 외부 소스가 일부 실패해도 나머지 카드와 차트는 계속 동작

## 데이터 소스

- 미국 지수 / VIX / 금 / WTI / DXY / USDKRW: Stooq
- KOSPI / KOSDAQ / 삼성전자: Naver Finance HTML 표 파싱
- Bitcoin: CoinGecko
- Fear & Greed: alternative.me
- US 10Y / US 2Y / HY Spread: FRED (선택 사항)

## FRED 사용 방법

FRED는 공식 문서상 API 키가 필요합니다. 키가 없으면 금리 카드만 비워집니다.

1. FRED에서 API 키 발급
2. GitHub 저장소에서 `Settings → Secrets and variables → Actions`
3. `New repository secret`
4. 이름: `FRED_API_KEY`
5. 값: 발급받은 32자리 키

FRED 공식 문서는 API 키가 필요하다고 설명합니다. `abcdefghijklmnopqrstuvwxyz123456`는 데모용 예시 키입니다.

## 배포 순서

1. 새 저장소 또는 기존 저장소 루트에 전체 파일 업로드
2. `Settings → Pages`
3. `Deploy from a branch`
4. `main` / `/(root)` 선택 후 저장
5. `Actions → Update market snapshot → Run workflow`
6. 1~2분 뒤 `data/latest.json` 확인
7. Pages 주소 새로고침

## 확인 주소 예시

- 대시보드: `https://계정명.github.io/저장소명/`
- latest JSON: `https://계정명.github.io/저장소명/data/latest.json`
- history JSON: `https://계정명.github.io/저장소명/data/history.json`

## 주의

- 이 구조는 **실시간 틱 데이터**가 아니라 **주기 갱신 스냅샷**입니다.
- GitHub Actions의 스케줄 실행은 수 분 지연될 수 있습니다.
- FRED 키가 없으면 금리 카드는 비어도 나머지 대시보드는 정상 동작합니다.
- Stooq와 Naver는 비공식 웹 소스이므로, 사이트 구조 변경 시 수집 코드 조정이 필요할 수 있습니다.

## 참고

Stooq에서 `^SPX`와 `^KOSPI`의 히스토리 페이지가 제공되는 점을 확인할 수 있습니다.

Pandas DataReader 문서에는 Naver Finance가 한국 시장 데이터 소스를 제공한다고 설명되어 있습니다.
