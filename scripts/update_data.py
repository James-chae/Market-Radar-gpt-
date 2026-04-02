from __future__ import annotations

import csv
import io
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "MarketRadarSnapshot/1.0 (+https://github.com/)"
    }
)


@dataclass
class AssetSnapshot:
    key: str
    label: str
    market: str
    source: str
    price: Optional[float]
    previous_close: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]
    currency: str
    asof: str
    status: str = "ok"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "market": self.market,
            "source": self.source,
            "price": self.price,
            "previous_close": self.previous_close,
            "change": self.change,
            "change_pct": self.change_pct,
            "currency": self.currency,
            "asof": self.asof,
            "status": self.status,
            "note": self.note,
        }


def now_seoul() -> datetime:
    return datetime.now(SEOUL)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, str) and v.strip() in {"", ".", "null", "None", "-"}:
            return None
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except Exception:
        return None


def get_json(url: str, timeout: int = 20) -> Any:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_text(url: str, timeout: int = 20) -> str:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def fred_csv_series(series_id: str) -> List[Tuple[str, float]]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    text = get_text(url)
    reader = csv.DictReader(io.StringIO(text))
    rows: List[Tuple[str, float]] = []
    for row in reader:
        value = safe_float(row.get(series_id))
        if value is None:
            continue
        date = row.get("DATE")
        if not date:
            continue
        rows.append((date, value))
    if not rows:
        raise ValueError(f"No FRED rows for {series_id}")
    return rows


def fred_latest(series_id: str) -> Tuple[str, float, Optional[float]]:
    rows = fred_csv_series(series_id)
    latest_date, latest_val = rows[-1]
    prev_val = rows[-2][1] if len(rows) >= 2 else None
    return latest_date, latest_val, prev_val


def stooq_daily(symbol: str, label: str, key: str, currency: str, market: str) -> AssetSnapshot:
    # Stooq daily endpoint, e.g. ^spx, ^ndq, ^vix, cl.f, xauusd, usdkrw, dx.f
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    text = get_text(url)
    reader = csv.DictReader(io.StringIO(text))
    rows = [row for row in reader if row.get("Close")]
    if len(rows) < 1:
        raise ValueError(f"No rows for {symbol}")
    latest = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    latest_close = safe_float(latest.get("Close"))
    prev_close = safe_float(prev.get("Close")) if prev else None
    asof_dt = datetime.strptime(latest["Date"], "%Y-%m-%d").replace(tzinfo=UTC)
    change = (latest_close - prev_close) if (latest_close is not None and prev_close is not None) else None
    pct = (change / prev_close * 100) if (change is not None and prev_close not in (None, 0)) else None
    return AssetSnapshot(
        key=key,
        label=label,
        market=market,
        source="Stooq",
        price=latest_close,
        previous_close=prev_close,
        change=change,
        change_pct=pct,
        currency=currency,
        asof=iso(asof_dt),
    )


def stooq_history(symbol: str, days: int = 220) -> List[Dict[str, Any]]:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    text = get_text(url)
    reader = csv.DictReader(io.StringIO(text))
    rows = [row for row in reader if row.get("Close")]
    out = []
    for row in rows[-days:]:
        close = safe_float(row.get("Close"))
        if close is None:
            continue
        out.append({"date": row["Date"], "close": close})
    return out


def krx_index_snapshot(index_code: str, key: str, label: str) -> AssetSnapshot:
    from pykrx import stock

    end = now_seoul().strftime("%Y%m%d")
    start = (now_seoul() - timedelta(days=40)).strftime("%Y%m%d")
    df = stock.get_index_ohlcv_by_date(start, end, index_code)
    if df is None or df.empty:
        raise ValueError(f"No KRX index data for {index_code}")
    df = df.tail(2)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None
    price = safe_float(latest["종가"])
    prev_close = safe_float(prev["종가"]) if prev is not None else None
    dt = df.index[-1].to_pydatetime().replace(tzinfo=SEOUL)
    change = (price - prev_close) if (price is not None and prev_close is not None) else None
    pct = (change / prev_close * 100) if (change is not None and prev_close not in (None, 0)) else None
    return AssetSnapshot(
        key=key,
        label=label,
        market="KR",
        source="KRX via pykrx",
        price=price,
        previous_close=prev_close,
        change=change,
        change_pct=pct,
        currency="KRW",
        asof=iso(dt),
    )


def krx_index_history(index_code: str, days: int = 220) -> List[Dict[str, Any]]:
    from pykrx import stock

    end = now_seoul().strftime("%Y%m%d")
    start = (now_seoul() - timedelta(days=days * 2)).strftime("%Y%m%d")
    df = stock.get_index_ohlcv_by_date(start, end, index_code)
    if df is None or df.empty:
        return []
    df = df.tail(days)
    out = []
    for idx, row in df.iterrows():
        out.append({"date": idx.strftime("%Y-%m-%d"), "close": float(row["종가"])})
    return out


def krx_stock_snapshot(ticker: str, key: str, label: str) -> AssetSnapshot:
    from pykrx import stock

    end = now_seoul().strftime("%Y%m%d")
    start = (now_seoul() - timedelta(days=40)).strftime("%Y%m%d")
    df = stock.get_market_ohlcv_by_date(start, end, ticker)
    if df is None or df.empty:
        raise ValueError(f"No KRX stock data for {ticker}")
    df = df.tail(2)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None
    price = safe_float(latest["종가"])
    prev_close = safe_float(prev["종가"]) if prev is not None else None
    dt = df.index[-1].to_pydatetime().replace(tzinfo=SEOUL)
    change = (price - prev_close) if (price is not None and prev_close is not None) else None
    pct = (change / prev_close * 100) if (change is not None and prev_close not in (None, 0)) else None
    return AssetSnapshot(
        key=key,
        label=label,
        market="KR",
        source="KRX via pykrx",
        price=price,
        previous_close=prev_close,
        change=change,
        change_pct=pct,
        currency="KRW",
        asof=iso(dt),
    )


def krx_stock_history(ticker: str, days: int = 220) -> List[Dict[str, Any]]:
    from pykrx import stock

    end = now_seoul().strftime("%Y%m%d")
    start = (now_seoul() - timedelta(days=days * 2)).strftime("%Y%m%d")
    df = stock.get_market_ohlcv_by_date(start, end, ticker)
    if df is None or df.empty:
        return []
    df = df.tail(days)
    return [{"date": idx.strftime("%Y-%m-%d"), "close": float(row["종가"])} for idx, row in df.iterrows()]


def coin_gecko_snapshot(coin_id: str, key: str, label: str, currency: str = "USD") -> AssetSnapshot:
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={coin_id}&vs_currencies=usd&include_24hr_change=true&include_last_updated_at=true"
    )
    data = get_json(url)
    obj = data.get(coin_id, {})
    price = safe_float(obj.get("usd"))
    pct = safe_float(obj.get("usd_24h_change"))
    last_updated_at = obj.get("last_updated_at")
    asof_dt = datetime.fromtimestamp(last_updated_at, tz=UTC) if last_updated_at else datetime.now(UTC)
    prev_close = price / (1 + pct / 100) if (price is not None and pct is not None and pct != -100) else None
    change = (price - prev_close) if (price is not None and prev_close is not None) else None
    return AssetSnapshot(
        key=key,
        label=label,
        market="CRYPTO",
        source="CoinGecko",
        price=price,
        previous_close=prev_close,
        change=change,
        change_pct=pct,
        currency=currency,
        asof=iso(asof_dt),
    )


def coin_gecko_history(coin_id: str, days: int = 180) -> List[Dict[str, Any]]:
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}&interval=daily"
    data = get_json(url)
    prices = data.get("prices", [])
    out = []
    for ts_ms, close in prices:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
        out.append({"date": dt.strftime("%Y-%m-%d"), "close": round(float(close), 6)})
    return out


def fear_greed_snapshot() -> Dict[str, Any]:
    url = "https://api.alternative.me/fng/?limit=1"
    data = get_json(url)
    row = data["data"][0]
    score = int(row["value"])
    return {
        "score": score,
        "label": row.get("value_classification", ""),
        "asof": iso(datetime.fromtimestamp(int(row["timestamp"]), tz=UTC)),
        "source": "alternative.me",
    }


def build_rate_snapshot(series_id: str, key: str, label: str) -> AssetSnapshot:
    asof_date, value, prev = fred_latest(series_id)
    change = value - prev if prev is not None else None
    pct = (change / prev * 100) if (change is not None and prev not in (None, 0)) else None
    dt = datetime.strptime(asof_date, "%Y-%m-%d").replace(tzinfo=UTC)
    return AssetSnapshot(
        key=key,
        label=label,
        market="MACRO",
        source=f"FRED {series_id}",
        price=value,
        previous_close=prev,
        change=change,
        change_pct=pct,
        currency="PCT",
        asof=iso(dt),
    )


def fred_history(series_id: str, days: int = 220) -> List[Dict[str, Any]]:
    rows = fred_csv_series(series_id)
    return [{"date": d, "close": v} for d, v in rows[-days:]]


def make_error_asset(key: str, label: str, market: str, source: str, note: str) -> AssetSnapshot:
    return AssetSnapshot(
        key=key,
        label=label,
        market=market,
        source=source,
        price=None,
        previous_close=None,
        change=None,
        change_pct=None,
        currency="",
        asof=iso(datetime.now(UTC)),
        status="error",
        note=note,
    )


def build_latest() -> Dict[str, Any]:
    assets: Dict[str, AssetSnapshot] = {}
    errors: List[Dict[str, str]] = []

    def attempt(name: str, fn, *args, **kwargs):
        try:
            asset = fn(*args, **kwargs)
            assets[asset.key] = asset
        except Exception as exc:
            errors.append({"name": name, "error": str(exc)})

    attempt("S&P 500", stooq_daily, "^spx", "S&P 500", "sp500", "USD", "US")
    attempt("Nasdaq 100", stooq_daily, "^ndq", "Nasdaq 100", "ndx", "USD", "US")
    attempt("Dow Jones", stooq_daily, "^dji", "Dow Jones", "dji", "USD", "US")
    attempt("Russell 2000", stooq_daily, "^rut", "Russell 2000", "rut", "USD", "US")
    attempt("VIX", stooq_daily, "^vix", "VIX", "vix", "INDEX", "VOL")
    attempt("Gold", stooq_daily, "xauusd", "Gold", "gold", "USD", "MACRO")
    attempt("WTI", stooq_daily, "cl.f", "WTI", "oil", "USD", "MACRO")
    attempt("DXY", stooq_daily, "dx.f", "DXY", "dxy", "INDEX", "MACRO")
    attempt("USDKRW", stooq_daily, "usdkrw", "USD/KRW", "usdkrw", "KRW", "FX")
    attempt("Bitcoin", coin_gecko_snapshot, "bitcoin", "Bitcoin", "btc", "USD")

    attempt("KOSPI", krx_index_snapshot, "1001", "kospi", "KOSPI")
    attempt("KOSDAQ", krx_index_snapshot, "2001", "kosdaq", "KOSDAQ")
    attempt("Samsung", krx_stock_snapshot, "005930", "samsung", "Samsung Electronics")

    attempt("US 10Y", build_rate_snapshot, "DGS10", "t10y", "US 10Y")
    attempt("US 2Y", build_rate_snapshot, "DGS2", "t2y", "US 2Y")
    attempt("HY Spread", build_rate_snapshot, "BAMLH0A0HYM2", "hy_spread", "HY Spread")

    for expected in [
        ("sp500", "S&P 500", "US", "Stooq"),
        ("ndx", "Nasdaq 100", "US", "Stooq"),
        ("dji", "Dow Jones", "US", "Stooq"),
        ("rut", "Russell 2000", "US", "Stooq"),
        ("vix", "VIX", "VOL", "Stooq"),
        ("gold", "Gold", "MACRO", "Stooq"),
        ("oil", "WTI", "MACRO", "Stooq"),
        ("dxy", "DXY", "MACRO", "Stooq"),
        ("usdkrw", "USD/KRW", "FX", "Stooq"),
        ("btc", "Bitcoin", "CRYPTO", "CoinGecko"),
        ("kospi", "KOSPI", "KR", "KRX via pykrx"),
        ("kosdaq", "KOSDAQ", "KR", "KRX via pykrx"),
        ("samsung", "Samsung Electronics", "KR", "KRX via pykrx"),
        ("t10y", "US 10Y", "MACRO", "FRED DGS10"),
        ("t2y", "US 2Y", "MACRO", "FRED DGS2"),
        ("hy_spread", "HY Spread", "MACRO", "FRED BAMLH0A0HYM2"),
    ]:
        key, label, market, source = expected
        if key not in assets:
            err_text = "; ".join([e["error"] for e in errors if e["name"].lower().startswith(label.lower().split()[0].lower())])
            assets[key] = make_error_asset(key, label, market, source, err_text or "fetch failed")

    spread_note = ""
    if assets["t10y"].price is not None and assets["t2y"].price is not None:
        spread = assets["t10y"].price - assets["t2y"].price
        spread_note = f"10Y-2Y: {spread:.3f}%p"

    fear_greed = None
    try:
        fear_greed = fear_greed_snapshot()
    except Exception as exc:
        errors.append({"name": "FearGreed", "error": str(exc)})

    latest = {
        "meta": {
            "generated_at": iso(datetime.now(UTC)),
            "generated_at_seoul": now_seoul().strftime("%Y-%m-%d %H:%M:%S KST"),
            "mode": "snapshot",
            "note": "Static dashboard fed by GitHub Actions snapshots. Not tick-by-tick streaming.",
            "spread_note": spread_note,
        },
        "assets": {k: v.to_dict() for k, v in assets.items()},
        "fear_greed": fear_greed,
        "errors": errors,
    }
    return latest


def build_history() -> Dict[str, Any]:
    history: Dict[str, List[Dict[str, Any]]] = {}
    errors: List[Dict[str, str]] = []

    mapping = {
        "sp500": lambda: stooq_history("^spx"),
        "ndx": lambda: stooq_history("^ndq"),
        "dji": lambda: stooq_history("^dji"),
        "rut": lambda: stooq_history("^rut"),
        "vix": lambda: stooq_history("^vix"),
        "gold": lambda: stooq_history("xauusd"),
        "oil": lambda: stooq_history("cl.f"),
        "dxy": lambda: stooq_history("dx.f"),
        "usdkrw": lambda: stooq_history("usdkrw"),
        "btc": lambda: coin_gecko_history("bitcoin"),
        "kospi": lambda: krx_index_history("1001"),
        "kosdaq": lambda: krx_index_history("2001"),
        "samsung": lambda: krx_stock_history("005930"),
        "t10y": lambda: fred_history("DGS10"),
        "t2y": lambda: fred_history("DGS2"),
        "hy_spread": lambda: fred_history("BAMLH0A0HYM2"),
    }

    for key, fn in mapping.items():
        try:
            history[key] = fn()
        except Exception as exc:
            history[key] = []
            errors.append({"name": key, "error": str(exc)})

    return {
        "meta": {
            "generated_at": iso(datetime.now(UTC)),
            "generated_at_seoul": now_seoul().strftime("%Y-%m-%d %H:%M:%S KST"),
            "bars": "daily",
            "window": 220,
        },
        "series": history,
        "errors": errors,
    }


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    latest = build_latest()
    history = build_history()
    write_json(DATA_DIR / "latest.json", latest)
    write_json(DATA_DIR / "history.json", history)
    print("Wrote", DATA_DIR / "latest.json")
    print("Wrote", DATA_DIR / "history.json")
