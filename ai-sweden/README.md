# Karlsarvet AI Sweden v1.0

First runnable foundation for the Sweden AI/quant model.

## Locked strategy

- Universe: Nasdaq Stockholm Large + Mid Cap
- Portfolio: monthly Top 10, equal weighted
- Benchmark: SIXRX total-return index
- Backtest: 2010-01-01 to 2026-09-09
- Initial capital: SEK 1,000,000
- Base transaction cost: 15 bps per buy/sell; sensitivity 5/15/30 bps
- Score: Momentum 25%, earnings revisions 20%, valuation 20%, quality 15%, report reaction 10%, AI report analysis 10%

## Security

The API key is **not** included in this project. GitHub Actions reads it from the repository secret `BORSDATA_API_KEY`.

Never commit `.env` or the key to GitHub.

## Local install and verify connection

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
export BORSDATA_API_KEY='YOUR_KEY'
python run_bootstrap.py
```

This downloads metadata plus a small official-example stock-price sample and never prints the key.

## GitHub Actions

A manual workflow is included at `.github/workflows/ai-sweden-bootstrap.yml`. Once the repository secret `BORSDATA_API_KEY` has been added in GitHub, run the workflow from the Actions tab. It will test the Börsdata connection and upload the downloaded metadata/sample as a workflow artifact.

## Backtest design

The engine in `backtest.py` is deliberately point-in-time: the monthly score matrix passed into it must contain only information known at each rebalance date. This prevents look-ahead bias.

The production data pipeline should also reconstruct the historical investable universe, rather than using today's surviving companies back to 2010. This is necessary to reduce survivorship bias.

## Phase 1 factor implementation

- Momentum: 3/6/12 month price momentum.
- Valuation: P/E, EV/EBITA and FCF yield, ranked cross-sectionally and ideally sector-relative.
- Quality: ROIC/ROE, margins, leverage and cash conversion.
- Report reaction: 1-5 trading-day abnormal return/volume after publication.
- Earnings revisions: point-in-time consensus revision data; keep disabled until a reliable historical source is loaded.
- Report AI: compare latest report vs previous quarter and prior-year quarter for guidance, order intake, organic growth, margins, cash flow and CEO language. Keep disabled until source PDFs/text are timestamped and ingested.

## Important limitation

Börsdata can provide historical prices, reports, KPIs and splits, but a robust 2010-2026 backtest also needs publication timestamps and historical universe handling. Analyst-estimate revisions are a separate point-in-time dataset and should not be approximated with today's estimates.
