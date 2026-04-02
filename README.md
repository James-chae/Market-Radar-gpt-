# Market Radar integrated replacement

This package keeps the GitHub Pages + GitHub Actions + JSON snapshot structure,
but integrates the source chain from the user's working HTML file:

- Yahoo Finance chart via proxy fallbacks
- Binance for Bitcoin
- alternative.me for Fear & Greed
- FRED CSV without API key
- Naver Finance as fallback for KOSPI / KOSDAQ / Samsung

Replace the whole repository contents with this package, then run:
Actions → Update market snapshot → Run workflow
