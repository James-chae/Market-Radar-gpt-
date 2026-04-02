import json
import math
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
}
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")
LATEST_PATH = os.path.join(DATA_DIR, "latest.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")


def now_iso() -> str:
    return datetime.now(KST).isoformat()


def write_json(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_num(text: str) -> Optional[float]:
    if text is None:
        return None
    s = re.sub(r"[^0-9+\-.,]", "", str(text)).replace(",", "")
    if not s or s in {"-", ".", "+"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def asset_template(key: str, label: str, source: str, unit: str = "") -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": None,
        "prev": None,
        "change": None,
        "change_pct": None,
        "unit": unit,
        "source": source,
        "as_of": None,
        "error": None,
        "status": "error",
    }


def fill_asset(asset: Dict[str, Any], value: float, prev: Optional[float], as_of: Optional[str]):
    asset["value"] = round(float(value), 4)
    asset["prev"] = round(float(prev), 4) if prev is not None else None
    if prev not in (None, 0):
        asset["change"] = round(float(value) - float(prev), 4)
        asset["change_pct"] = round((float(value) - float(prev)) / float(prev) * 100.0, 4)
    else:
        asset["change"] = None
        asset["change_pct"] = None
    asset["as_of"] = as_of or now_iso()
    asset["status"] = "ok"
    asset["error"] = None


def safe_get_json(url: str, params: dict | None = None, timeout: int = 20):
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def safe_get_text(url: str, params: dict | None = None, timeout: int = 20, encoding: str | None = None):
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    if encoding:
        r.encoding = encoding
    return r.text


def fetch_fear_greed() -> Dict[str, Any]:
    out = {"score": None, "label": "데이터 없음", "as_of": None, "source": "alternative.me", "status": "error", "error": None}
    try:
        data = safe_get_json("https://api.alternative.me/fng/")
        row = data["data"][0]
        out["score"] = int(row["value"])
        out["label"] = row["value_classification"]
        out["as_of"] = datetime.fromtimestamp(int(row["timestamp"]), tz=timezone.utc).astimezone(KST).isoformat()
        out["status"] = "ok"
    except Exception as e:
        out["error"] = str(e)
    return out


def fetch_bitcoin() -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    asset = asset_template("bitcoin", "Bitcoin", "CoinGecko", "USD")
    hist: List[Dict[str, Any]] = []
    try:
        j = safe_get_json(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": 120, "interval": "daily"},
            timeout=30,
        )
        prices = j.get("prices", [])
        if len(prices) < 2:
            raise RuntimeError("bitcoin prices missing")
        latest_ts, latest_val = prices[-1]
        prev_val = prices[-2][1]
        as_of = datetime.fromtimestamp(latest_ts / 1000, tz=timezone.utc).astimezone(KST).isoformat()
        fill_asset(asset, latest_val, prev_val, as_of)
        for ts, val in prices:
            hist.append({
                "date": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(KST).strftime("%Y-%m-%d"),
                "value": round(float(val), 4),
            })
    except Exception as e:
        asset["error"] = str(e)
    return asset, hist


def fetch_frankfurter_usdkrw() -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    asset = asset_template("usdkrw", "USD/KRW", "Frankfurter", "KRW")
    hist: List[Dict[str, Any]] = []
    try:
        end = datetime.now(KST).date()
        start = end - timedelta(days=180)
        j = safe_get_json(f"https://api.frankfurter.app/{start.isoformat()}..{end.isoformat()}", params={"from": "USD", "to": "KRW"}, timeout=30)
        rates = j.get("rates", {})
        items = sorted((d, v.get("KRW")) for d, v in rates.items() if v.get("KRW") is not None)
        if len(items) < 2:
            raise RuntimeError("usdkrw rates missing")
        for d, v in items[-120:]:
            hist.append({"date": d, "value": round(float(v), 4)})
        latest_d, latest_v = items[-1]
        prev_v = items[-2][1]
        fill_asset(asset, latest_v, prev_v, f"{latest_d}T00:00:00+09:00")
    except Exception as e:
        asset["error"] = str(e)
    return asset, hist


def fetch_naver_index(code: str, label: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    asset = asset_template(code.lower(), label, f"Naver Finance ({label})", "KRW")
    hist: List[Dict[str, Any]] = []
    try:
        frames = pd.read_html(f"https://finance.naver.com/sise/sise_index_day.naver?code={code}&page=1", encoding="euc-kr")
        df = next((f for f in frames if "날짜" in f.columns and any("종가" in str(c) for c in f.columns)), None)
        if df is None:
            raise RuntimeError("index table missing")
        close_col = next(c for c in df.columns if "종가" in str(c))
        df = df[["날짜", close_col]].dropna().copy()
        df[close_col] = df[close_col].astype(str).str.replace(",", "", regex=False)
        df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
        df = df.dropna().sort_values("날짜")
        if len(df) < 2:
            raise RuntimeError("index rows missing")
        latest = float(df[close_col].iloc[-1])
        prev = float(df[close_col].iloc[-2])
        latest_date = pd.to_datetime(df["날짜"].iloc[-1]).strftime("%Y-%m-%d")
        fill_asset(asset, latest, prev, f"{latest_date}T15:30:00+09:00")
        for _, row in df.tail(120).iterrows():
            hist.append({"date": pd.to_datetime(row["날짜"]).strftime("%Y-%m-%d"), "value": round(float(row[close_col]), 4)})
    except Exception as e:
        asset["error"] = str(e)
    return asset, hist


def fetch_naver_stock(code: str, label: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    asset = asset_template(code, label, f"Naver Finance ({code})", "KRW")
    hist: List[Dict[str, Any]] = []
    try:
        text = safe_get_text(f"https://finance.naver.com/item/main.naver?code={code}", encoding="euc-kr")
        m = re.search(r"현재가\s*([0-9,]+).*?전일가\s*([0-9,]+)", text, re.S)
        d = re.search(r"([0-9]{4}년\s*[0-9]{2}월\s*[0-9]{2}일\s*[0-9]{2}시\s*[0-9]{2}분)\s*기준", text)
        if not m:
            raise RuntimeError("stock quote parse failed")
        value = parse_num(m.group(1))
        prev = parse_num(m.group(2))
        as_of = now_iso()
        if d:
            dt = datetime.strptime(re.sub(r"\s+", " ", d.group(1).replace("년", "-").replace("월", "-").replace("일", "").replace("시", ":").replace("분", "")), "%Y-%m-%d %H:%M")
            as_of = dt.replace(tzinfo=KST).isoformat()
        fill_asset(asset, value, prev, as_of)

        frames = pd.read_html(f"https://finance.naver.com/item/sise_day.naver?code={code}&page=1", encoding="euc-kr")
        df = next((f for f in frames if "날짜" in f.columns and "종가" in f.columns), None)
        if df is not None:
            df = df[["날짜", "종가"]].dropna().copy()
            df["종가"] = df["종가"].astype(str).str.replace(",", "", regex=False)
            df["종가"] = pd.to_numeric(df["종가"], errors="coerce")
            df = df.dropna().sort_values("날짜")
            for _, row in df.tail(120).iterrows():
                hist.append({"date": pd.to_datetime(row["날짜"]).strftime("%Y-%m-%d"), "value": round(float(row["종가"]), 4)})
    except Exception as e:
        asset["error"] = str(e)
    return asset, hist


def main():
    logs: List[str] = []
    assets: Dict[str, Dict[str, Any]] = {}
    history: Dict[str, List[Dict[str, Any]]] = {}

    fg = fetch_fear_greed()
    btc_asset, btc_hist = fetch_bitcoin()
    usdkrw_asset, usdkrw_hist = fetch_frankfurter_usdkrw()
    kospi_asset, kospi_hist = fetch_naver_index("KOSPI", "KOSPI")
    kosdaq_asset, kosdaq_hist = fetch_naver_index("KOSDAQ", "KOSDAQ")
    samsung_asset, samsung_hist = fetch_naver_stock("005930", "Samsung Electronics")

    items = [btc_asset, usdkrw_asset, kospi_asset, kosdaq_asset, samsung_asset]
    for a in items:
        assets[a["key"] if a["key"] not in {"005930"} else "samsung"] = a
        if a["status"] != "ok":
            logs.append(f"{a['label']}: {a['error']}")

    history["bitcoin"] = btc_hist
    history["usdkrw"] = usdkrw_hist
    history["kospi"] = kospi_hist
    history["kosdaq"] = kosdaq_hist
    history["samsung"] = samsung_hist

    latest = {
        "generated_at": now_iso(),
        "timezone": "Asia/Seoul",
        "mode": "onepage-stable",
        "repo_note": "Minimal stable snapshot for GitHub Pages. Browser reads only this JSON.",
        "logs": logs,
        "fear_greed": fg,
        "assets": assets,
    }

    write_json(LATEST_PATH, latest)
    write_json(HISTORY_PATH, {
        "generated_at": now_iso(),
        "series": history,
    })
    print(f"Wrote {LATEST_PATH}")
    print(f"Wrote {HISTORY_PATH}")


if __name__ == "__main__":
    main()
