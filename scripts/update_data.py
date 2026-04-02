from __future__ import annotations

import io
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import quote

import pandas as pd
import requests

KST = 'Asia/Seoul'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8'})
TIMEOUT = 25


def now_iso() -> str:
    return pd.Timestamp.now(tz=KST).isoformat()


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def safe_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace(',', '').replace('%', '').replace('₩', '').replace('$', '').strip()
        if value in {'', '-', 'nan', 'NaN', 'None'}:
            return None
    try:
        v = float(value)
        if math.isnan(v):
            return None
        return v
    except Exception:
        return None


@dataclass
class AssetSpec:
    key: str
    label: str
    unit: str
    source_label: str
    history_loader: Callable[[], pd.DataFrame]


class Collector:
    def __init__(self):
        self.logs: list[str] = []
        self.assets: dict[str, dict] = {}
        self.history: dict[str, list[dict]] = {}

    def log(self, message: str) -> None:
        print(message)
        self.logs.append(message)

    def asset_error(self, key: str, label: str, unit: str, source: str, error: str) -> dict:
        payload = {
            'key': key,
            'label': label,
            'value': None,
            'prev': None,
            'change': None,
            'change_pct': None,
            'unit': unit,
            'source': source,
            'as_of': now_iso(),
            'error': error,
            'status': 'error',
        }
        self.assets[key] = payload
        self.history[key] = []
        self.log(f'{label}: {error}')
        return payload

    def asset_ok(self, key: str, label: str, unit: str, source: str, frame: pd.DataFrame) -> dict:
        frame = frame.copy()
        frame['date'] = pd.to_datetime(frame['date'])
        frame = frame.sort_values('date').dropna(subset=['close'])
        frame = frame[['date', 'close']]
        if frame.empty:
            return self.asset_error(key, label, unit, source, 'empty history')
        last = safe_float(frame.iloc[-1]['close'])
        prev = safe_float(frame.iloc[-2]['close']) if len(frame) > 1 else None
        change = None if prev is None or last is None else last - prev
        pct = None if prev in (None, 0) or last is None else (change / prev) * 100
        payload = {
            'key': key,
            'label': label,
            'value': last,
            'prev': prev,
            'change': change,
            'change_pct': pct,
            'unit': unit,
            'source': source,
            'as_of': now_iso(),
            'error': None,
            'status': 'ok',
        }
        self.assets[key] = payload
        self.history[key] = [
            {'date': pd.Timestamp(d).strftime('%Y-%m-%d'), 'close': round(float(c), 6)}
            for d, c in frame.tail(260).itertuples(index=False, name=None)
        ]
        return payload


def fetch_text(url: str) -> str:
    r = SESSION.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def stooq_history(symbols: list[str]) -> pd.DataFrame:
    last_error = None
    for sym in symbols:
        try:
            url = f'https://stooq.com/q/d/l/?s={quote(sym)}&i=d'
            text = fetch_text(url)
            df = pd.read_csv(io.StringIO(text))
            if 'Date' not in df.columns or 'Close' not in df.columns or df.empty:
                raise ValueError(f'no rows for {sym}')
            df = df.rename(columns={'Date': 'date', 'Close': 'close'})
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df = df.dropna(subset=['close'])
            if df.empty:
                raise ValueError(f'no valid close for {sym}')
            return df[['date', 'close']]
        except Exception as e:
            last_error = e
    raise last_error or RuntimeError('stooq failed')


def naver_stock_history(code: str, pages: int = 20) -> pd.DataFrame:
    dfs = []
    for page in range(1, pages + 1):
        url = f'https://finance.naver.com/item/sise_day.naver?code={code}&page={page}'
        html = fetch_text(url)
        tables = pd.read_html(io.StringIO(html))
        for tb in tables:
            if '날짜' in tb.columns and '종가' in tb.columns:
                dfs.append(tb[['날짜', '종가']])
                break
    if not dfs:
        raise ValueError('no naver stock rows')
    df = pd.concat(dfs, ignore_index=True).dropna()
    df = df.rename(columns={'날짜': 'date', '종가': 'close'})
    df['close'] = df['close'].astype(str).str.replace(',', '', regex=False)
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['date'] = pd.to_datetime(df['date'])
    df = df.dropna(subset=['close']).sort_values('date').drop_duplicates('date')
    return df[['date', 'close']]


def naver_index_history(code: str, pages: int = 20) -> pd.DataFrame:
    dfs = []
    for page in range(1, pages + 1):
        url = f'https://finance.naver.com/sise/sise_index_day.naver?code={code}&page={page}'
        html = fetch_text(url)
        tables = pd.read_html(io.StringIO(html))
        for tb in tables:
            if '날짜' in tb.columns and '종가' in tb.columns:
                dfs.append(tb[['날짜', '종가']])
                break
    if not dfs:
        raise ValueError(f'no naver index rows for {code}')
    df = pd.concat(dfs, ignore_index=True).dropna()
    df = df.rename(columns={'날짜': 'date', '종가': 'close'})
    df['close'] = df['close'].astype(str).str.replace(',', '', regex=False)
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['date'] = pd.to_datetime(df['date'])
    df = df.dropna(subset=['close']).sort_values('date').drop_duplicates('date')
    return df[['date', 'close']]


def fetch_coingecko_history() -> pd.DataFrame:
    url = 'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=365&interval=daily'
    r = SESSION.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    prices = r.json()['prices']
    rows = [{'date': pd.to_datetime(ts, unit='ms').date(), 'close': float(val)} for ts, val in prices]
    return pd.DataFrame(rows)


def fetch_fear_greed() -> dict:
    try:
        url = 'https://api.alternative.me/fng/'
        r = SESSION.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        row = r.json()['data'][0]
        return {
            'score': int(row['value']),
            'label': row.get('value_classification') or 'Unknown',
            'as_of': now_iso(),
            'source': 'alternative.me',
            'status': 'ok',
            'error': None,
        }
    except Exception as e:
        return {
            'score': None,
            'label': 'Unavailable',
            'as_of': now_iso(),
            'source': 'alternative.me',
            'status': 'error',
            'error': str(e),
        }


def fred_series(series_id: str) -> pd.DataFrame:
    api_key = os.getenv('FRED_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('FRED_API_KEY not configured')
    url = 'https://api.stlouisfed.org/fred/series/observations'
    params = {
        'series_id': series_id,
        'api_key': api_key,
        'file_type': 'json',
        'sort_order': 'asc',
        'limit': 1000,
    }
    r = SESSION.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    rows = []
    for obs in r.json().get('observations', []):
        val = safe_float(obs.get('value'))
        if val is not None:
            rows.append({'date': obs['date'], 'close': val})
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f'No FRED rows for {series_id}')
    return df


def main() -> None:
    collector = Collector()

    specs = [
        AssetSpec('sp500', 'S&P 500', '', 'Stooq (^SPX)', lambda: stooq_history(['^spx', 'spx'])),
        AssetSpec('nasdaq100', 'Nasdaq 100', '', 'Stooq (^NDQ)', lambda: stooq_history(['^ndq', 'ndq'])),
        AssetSpec('dow', 'Dow Jones', '', 'Stooq (^DJI)', lambda: stooq_history(['^dji', 'dji'])),
        AssetSpec('russell2000', 'Russell 2000', '', 'Stooq (^RUT)', lambda: stooq_history(['^rut', 'rut'])),
        AssetSpec('vix', 'VIX', '', 'Stooq (^VIX)', lambda: stooq_history(['^vix', 'vix'])),
        AssetSpec('gold', 'Gold', 'USD', 'Stooq (XAUUSD)', lambda: stooq_history(['xauusd'])),
        AssetSpec('wti', 'WTI', 'USD', 'Stooq (CL.F)', lambda: stooq_history(['cl.f', 'cl'])),
        AssetSpec('dxy', 'DXY', '', 'Stooq (DX.F)', lambda: stooq_history(['dx.f', 'usd_i'])),
        AssetSpec('usdkrw', 'USD/KRW', 'KRW', 'Stooq (USDKRW)', lambda: stooq_history(['usdkrw'])),
        AssetSpec('bitcoin', 'Bitcoin', 'USD', 'CoinGecko', fetch_coingecko_history),
        AssetSpec('kospi', 'KOSPI', 'KRW', 'Naver Finance (KOSPI)', lambda: naver_index_history('KOSPI', pages=25)),
        AssetSpec('kosdaq', 'KOSDAQ', 'KRW', 'Naver Finance (KOSDAQ)', lambda: naver_index_history('KOSDAQ', pages=25)),
        AssetSpec('samsung', 'Samsung Electronics', 'KRW', 'Naver Finance (005930)', lambda: naver_stock_history('005930', pages=25)),
        AssetSpec('us10y', 'US 10Y', '%', 'FRED DGS10', lambda: fred_series('DGS10')),
        AssetSpec('us2y', 'US 2Y', '%', 'FRED DGS2', lambda: fred_series('DGS2')),
        AssetSpec('hy_spread', 'HY Spread', '%', 'FRED BAMLH0A0HYM2', lambda: fred_series('BAMLH0A0HYM2')),
    ]

    for spec in specs:
        try:
            frame = spec.history_loader()
            collector.asset_ok(spec.key, spec.label, spec.unit, spec.source_label, frame)
        except Exception as e:
            collector.asset_error(spec.key, spec.label, spec.unit, spec.source_label, str(e))

    # computed spread
    us10 = collector.assets.get('us10y', {})
    us2 = collector.assets.get('us2y', {})
    yield_payload = {
        'key': 'yield_spread',
        'label': 'US 10Y-2Y',
        'value': None,
        'prev': None,
        'change': None,
        'change_pct': None,
        'unit': '%p',
        'source': 'computed from FRED',
        'as_of': now_iso(),
        'error': None,
        'status': 'error',
    }
    if us10.get('value') is not None and us2.get('value') is not None:
        val = us10['value'] - us2['value']
        prev = None if us10.get('prev') is None or us2.get('prev') is None else us10['prev'] - us2['prev']
        chg = None if prev is None else val - prev
        yield_payload.update({'value': val, 'prev': prev, 'change': chg, 'change_pct': None, 'status': 'ok'})
        s10 = collector.history.get('us10y', [])
        s2 = collector.history.get('us2y', [])
        by_date = {}
        for row in s10:
            by_date.setdefault(row['date'], {})['a'] = row['close']
        for row in s2:
            by_date.setdefault(row['date'], {})['b'] = row['close']
        spread_rows = []
        for d, vals in sorted(by_date.items()):
            if 'a' in vals and 'b' in vals:
                spread_rows.append({'date': d, 'close': round(vals['a'] - vals['b'], 6)})
        collector.history['yield_spread'] = spread_rows
    else:
        yield_payload['error'] = 'requires us10y and us2y'
        collector.history['yield_spread'] = []
    collector.assets['yield_spread'] = yield_payload

    latest = {
        'generated_at': now_iso(),
        'timezone': KST,
        'mode': 'snapshot',
        'repo_note': 'Generated by GitHub Actions. Browser reads only this JSON.',
        'logs': collector.logs,
        'fear_greed': fetch_fear_greed(),
        'assets': collector.assets,
    }
    history = {
        'generated_at': latest['generated_at'],
        'timezone': KST,
        'series': collector.history,
    }

    ensure_parent('data/latest.json')
    ensure_parent('data/history.json')
    with open('data/latest.json', 'w', encoding='utf-8') as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)
    with open('data/history.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print('Wrote data/latest.json')
    print('Wrote data/history.json')


if __name__ == '__main__':
    main()
