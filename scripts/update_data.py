import requests
import pandas as pd
from datetime import datetime
from pykrx import stock

def fetch_stooq(symbol):
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    df = pd.read_csv(url)
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])

def fetch_coingecko():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    return requests.get(url).json()["bitcoin"]["usd"]

data = {}

# 미국
data["sp500"] = fetch_stooq("spx")
data["nasdaq100"] = fetch_stooq("ndq")
data["dow"] = fetch_stooq("dji")
data["russell2000"] = fetch_stooq("rut")
data["vix"] = fetch_stooq("vix")

# 원자재
data["gold"] = fetch_stooq("xauusd")
data["wti"] = fetch_stooq("cl")

# 환율
data["usdkrw"] = fetch_stooq("usdkRW")
data["dxy"] = fetch_stooq("usdidx")

# 코인
data["bitcoin"] = fetch_coingecko()

# 한국
today = datetime.today().strftime("%Y%m%d")

kospi = stock.get_index_ohlcv_by_date("20240101", today, "1001")
kosdaq = stock.get_index_ohlcv_by_date("20240101", today, "2001")

data["kospi"] = float(kospi["종가"].iloc[-1]) if not kospi.empty else None
data["kosdaq"] = float(kosdaq["종가"].iloc[-1]) if not kosdaq.empty else None

# 삼성전자
samsung = stock.get_market_ohlcv_by_date("20240101", today, "005930")
data["samsung"] = float(samsung["종가"].iloc[-1]) if not samsung.empty else None

# 저장
import json
with open("data/latest.json", "w") as f:
    json.dump(data, f, indent=2)

print("DONE")
