from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from pykrx import stock

BASE_DIR = Path(__file__).resolve().parent.parent if (Path(__file__).resolve().parent.name == 'scripts') else Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
LATEST_PATH = DATA_DIR / 'latest.json'
HISTORY_PATH = DATA_DIR / 'history.json'

KST = timezone(timedelta(hours=9))
UTC = timezone.utc
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


@dataclass
class AssetSnapshot:
    key: str
    label: str
    value: float | None = None
    prev: float | None = None
    change: float | None = None
    change_pct: float | None = None
    unit: str = ''
    source: str = ''
    as_of: str = ''
    error: str | None = None
    status: str = 'ok'

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.value is None:
            data['status'] = 'error'
        return data


def now_kst() -> datetime:
    return datetime.now(KST)


def iso_kst(dt: datetime | None = None) -> str:
    return (dt or now_kst()).astimezone(KST).isoformat()


def request_json(url: str, timeout: int = 25, **kwargs: Any) -> Any:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = SESSION.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def request_text(url: str, timeout: int = 25, **kwargs: Any) -> str:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = SESSION.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def safe_float(v: Any) -> float | None:
    try:
        if v is None or v == '' or (isinstance(v, str) and v.strip() == ''):
            return None
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except Exception:
        return None


def build_asset(key: str, label: str, value: float | None, prev: float | None, unit: str, source: str, as_of: str, error: str | None = None) -> AssetSnapshot:
    if value is None:
        return AssetSnapshot(key=key, label=label, unit=unit, source=source, as_of=as_of, error=error, status='error')
    change = None if prev is None else value - prev
    change_pct = None if prev in (None, 0) else (change / prev) * 100
    return AssetSnapshot(
        key=key,
        label=label,
        value=round(value, 6),
        prev=None if prev is None else round(prev, 6),
        change=None if change is None else round(change, 6),
        change_pct=None if change_pct is None else round(change_pct, 6),
        unit=unit,
        source=source,
        as_of=as_of,
        error=error,
    )


def yahoo_chart(symbol: str, range_: str = '6mo', interval: str = '1d') -> pd.DataFrame:
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
    params = {'range': range_, 'interval': interval, 'includePrePost': 'false', 'events': 'div,splits'}
    data = request_json(url, params=params)
    result = data['chart']['result'][0]
    timestamps = result.get('timestamp', [])
    quote = result['indicators']['quote'][0]
    closes = quote.get('close', [])
    rows: list[dict[str, Any]] = []
    for ts, close in zip(timestamps, closes):
        c = safe_float(close)
        if c is None:
            continue
        dt = datetime.fromtimestamp(int(ts), tz=UTC).astimezone(KST)
        rows.append({'date': dt.strftime('%Y-%m-%d'), 'close': c})
    if not rows:
        raise ValueError(f'No rows for {symbol}')
    return pd.DataFrame(rows)


def yahoo_quote(symbol: str) -> tuple[float | None, float | None, str]:
    df = yahoo_chart(symbol, range_='10d', interval='1d')
    if df.empty:
        raise ValueError(f'No quote rows for {symbol}')
    value = safe_float(df.iloc[-1]['close'])
    prev = safe_float(df.iloc[-2]['close']) if len(df) >= 2 else None
    return value, prev, df.iloc[-1]['date']


def fetch_us_asset(label: str, key: str, symbol: str, unit: str = '') -> tuple[AssetSnapshot, list[dict[str, Any]]]:
    try:
        hist = yahoo_chart(symbol, range_='1y', interval='1d')
        value = safe_float(hist.iloc[-1]['close'])
        prev = safe_float(hist.iloc[-2]['close']) if len(hist) >= 2 else None
        asset = build_asset(key, label, value, prev, unit, f'Yahoo Finance ({symbol})', hist.iloc[-1]['date'])
        series = [{'date': str(r['date']), 'close': round(float(r['close']), 6)} for _, r in hist.tail(260).iterrows()]
        return asset, series
    except Exception as exc:
        return build_asset(key, label, None, None, unit, f'Yahoo Finance ({symbol})', iso_kst(), str(exc)), []


def fetch_bitcoin() -> tuple[AssetSnapshot, list[dict[str, Any]]]:
    try:
        latest = request_json('https://api.coingecko.com/api/v3/coins/bitcoin', timeout=30,
                              params={'localization': 'false', 'tickers': 'false', 'market_data': 'true', 'community_data': 'false', 'developer_data': 'false', 'sparkline': 'false'})
        md = latest['market_data']
        value = safe_float(md['current_price']['usd'])
        prev = None
        pct = safe_float(md.get('price_change_percentage_24h'))
        if value is not None and pct is not None:
            prev = value / (1 + pct / 100)
        hist = request_json('https://api.coingecko.com/api/v3/coins/bitcoin/market_chart', timeout=30,
                            params={'vs_currency': 'usd', 'days': '365', 'interval': 'daily'})
        prices = hist.get('prices', [])
        series = []
        for ts, price in prices:
            dt = datetime.fromtimestamp(ts / 1000, tz=UTC).astimezone(KST)
            p = safe_float(price)
            if p is not None:
                series.append({'date': dt.strftime('%Y-%m-%d'), 'close': round(p, 6)})
        asset = build_asset('bitcoin', 'Bitcoin', value, prev, 'USD', 'CoinGecko', iso_kst())
        return asset, series[-365:]
    except Exception as exc:
        return build_asset('bitcoin', 'Bitcoin', None, None, 'USD', 'CoinGecko', iso_kst(), str(exc)), []


def latest_business_date(days_back: int = 10) -> str:
    for i in range(days_back):
        day = now_kst().date() - timedelta(days=i)
        if day.weekday() < 5:
            return day.strftime('%Y%m%d')
    return now_kst().strftime('%Y%m%d')


def fetch_kr_index(code: str, key: str, label: str) -> tuple[AssetSnapshot, list[dict[str, Any]]]:
    end = latest_business_date(15)
    start = (datetime.strptime(end, '%Y%m%d') - timedelta(days=420)).strftime('%Y%m%d')
    try:
        df = stock.get_index_ohlcv_by_date(start, end, code)
        if df.empty:
            raise ValueError(f'No rows for index code {code}')
        close_col = '종가'
        if close_col not in df.columns:
            raise KeyError(f'종가 column missing: {list(df.columns)}')
        series = []
        for idx, row in df.tail(260).iterrows():
            val = safe_float(row[close_col])
            if val is not None:
                date_str = pd.Timestamp(idx).strftime('%Y-%m-%d')
                series.append({'date': date_str, 'close': round(val, 6)})
        value = safe_float(df.iloc[-1][close_col])
        prev = safe_float(df.iloc[-2][close_col]) if len(df) >= 2 else None
        asset = build_asset(key, label, value, prev, 'KRW', f'pykrx index {code}', series[-1]['date'])
        return asset, series
    except Exception as exc:
        return build_asset(key, label, None, None, 'KRW', f'pykrx index {code}', iso_kst(), str(exc)), []


def fetch_kr_stock(ticker: str, key: str, label: str) -> tuple[AssetSnapshot, list[dict[str, Any]]]:
    end = latest_business_date(15)
    start = (datetime.strptime(end, '%Y%m%d') - timedelta(days=420)).strftime('%Y%m%d')
    try:
        df = stock.get_market_ohlcv_by_date(start, end, ticker)
        if df.empty:
            raise ValueError(f'No rows for {ticker}')
        close_col = '종가'
        series = []
        for idx, row in df.tail(260).iterrows():
            val = safe_float(row[close_col])
            if val is not None:
                series.append({'date': pd.Timestamp(idx).strftime('%Y-%m-%d'), 'close': round(val, 6)})
        value = safe_float(df.iloc[-1][close_col])
        prev = safe_float(df.iloc[-2][close_col]) if len(df) >= 2 else None
        asset = build_asset(key, label, value, prev, 'KRW', f'pykrx stock {ticker}', series[-1]['date'])
        return asset, series
    except Exception as exc:
        return build_asset(key, label, None, None, 'KRW', f'pykrx stock {ticker}', iso_kst(), str(exc)), []


def fred_series(series_id: str, key: str, label: str, unit: str = '%') -> AssetSnapshot:
    try:
        url = 'https://api.stlouisfed.org/fred/series/observations'
        params = {
            'series_id': series_id,
            'api_key': 'abcdefghijklmnopqrstuvwxyz123456',
            'file_type': 'json',
            'sort_order': 'desc',
            'limit': 10,
        }
        data = request_json(url, timeout=45, params=params)
        obs = [o for o in data.get('observations', []) if o.get('value') not in ('.', None, '')]
        if not obs:
            raise ValueError(f'No rows for {series_id}')
        value = safe_float(obs[0]['value'])
        prev = safe_float(obs[1]['value']) if len(obs) >= 2 else None
        as_of = obs[0]['date']
        return build_asset(key, label, value, prev, unit, f'FRED {series_id}', as_of)
    except Exception as exc:
        return build_asset(key, label, None, None, unit, f'FRED {series_id}', iso_kst(), str(exc))


def fetch_fear_greed() -> dict[str, Any]:
    try:
        data = request_json('https://api.alternative.me/fng/', timeout=30)
        row = data['data'][0]
        score = int(row['value'])
        classification = row.get('value_classification', '')
        ts = datetime.fromtimestamp(int(row['timestamp']), tz=UTC).astimezone(KST)
        return {
            'score': score,
            'label': classification,
            'as_of': iso_kst(ts),
            'source': 'alternative.me',
            'status': 'ok',
            'error': None,
        }
    except Exception as exc:
        return {
            'score': None,
            'label': None,
            'as_of': iso_kst(),
            'source': 'alternative.me',
            'status': 'error',
            'error': str(exc),
        }


def make_output() -> tuple[dict[str, Any], dict[str, Any]]:
    assets: dict[str, AssetSnapshot] = {}
    history: dict[str, list[dict[str, Any]]] = {}
    logs: list[str] = []

    us_map = [
        ('sp500', 'S&P 500', '^GSPC', ''),
        ('nasdaq100', 'Nasdaq 100', '^NDX', ''),
        ('dow', 'Dow Jones', '^DJI', ''),
        ('russell2000', 'Russell 2000', '^RUT', ''),
        ('vix', 'VIX', '^VIX', ''),
        ('gold', 'Gold', 'GC=F', 'USD'),
        ('wti', 'WTI', 'CL=F', 'USD'),
        ('dxy', 'DXY', 'DX-Y.NYB', ''),
        ('usdkrw', 'USD/KRW', 'KRW=X', 'KRW'),
    ]

    for key, label, symbol, unit in us_map:
        asset, series = fetch_us_asset(label, key, symbol, unit)
        assets[key] = asset
        history[key] = series
        if asset.error:
            logs.append(f'{label}: {asset.error}')

    btc_asset, btc_series = fetch_bitcoin()
    assets['bitcoin'] = btc_asset
    history['bitcoin'] = btc_series
    if btc_asset.error:
        logs.append(f'Bitcoin: {btc_asset.error}')

    kospi_asset, kospi_series = fetch_kr_index('1001', 'kospi', 'KOSPI')
    kosdaq_asset, kosdaq_series = fetch_kr_index('2001', 'kosdaq', 'KOSDAQ')
    samsung_asset, samsung_series = fetch_kr_stock('005930', 'samsung', 'Samsung Electronics')
    for asset, series in [(kospi_asset, kospi_series), (kosdaq_asset, kosdaq_series), (samsung_asset, samsung_series)]:
        assets[asset.key] = asset
        history[asset.key] = series
        if asset.error:
            logs.append(f'{asset.label}: {asset.error}')

    t10 = fred_series('DGS10', 'us10y', 'US 10Y')
    t2 = fred_series('DGS2', 'us2y', 'US 2Y')
    hy = fred_series('BAMLH0A0HYM2', 'hy_spread', 'HY Spread')
    for asset in [t10, t2, hy]:
        assets[asset.key] = asset
        if asset.error:
            logs.append(f'{asset.label}: {asset.error}')

    fear_greed = fetch_fear_greed()
    if fear_greed.get('error'):
        logs.append(f"Fear & Greed: {fear_greed['error']}")

    # computed spread
    spread_value = None
    spread_prev = None
    if assets['us10y'].value is not None and assets['us2y'].value is not None:
        spread_value = assets['us10y'].value - assets['us2y'].value
    if assets['us10y'].prev is not None and assets['us2y'].prev is not None:
        spread_prev = assets['us10y'].prev - assets['us2y'].prev
    spread_asset = build_asset('yield_spread', 'US 10Y-2Y', spread_value, spread_prev, '%p', 'computed', iso_kst())
    assets['yield_spread'] = spread_asset

    latest: dict[str, Any] = {
        'generated_at': iso_kst(),
        'timezone': 'Asia/Seoul',
        'mode': 'snapshot',
        'repo_note': 'Generated by GitHub Actions. Browser reads only this JSON.',
        'logs': logs,
        'fear_greed': fear_greed,
        'assets': {k: v.to_dict() for k, v in assets.items()},
    }
    # duplicate top-level keys for simpler front-end compatibility
    latest.update({k: v.to_dict() for k, v in assets.items()})

    history_out: dict[str, Any] = {
        'generated_at': iso_kst(),
        'timezone': 'Asia/Seoul',
        'series': history,
    }
    return latest, history_out


def write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'Wrote {path}')


if __name__ == '__main__':
    latest, history = make_output()
    write_json(LATEST_PATH, latest)
    write_json(HISTORY_PATH, history)
