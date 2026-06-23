# timeseries_forecasting

**Multi-Model Stock Forecasting with Monte Carlo Risk Analysis** — plus a live FVG paper-trading bot (Alpaca) and an AWS Lambda S3 backup pipeline.

## Overview

This repo has three connected parts:

1. **Forecasting research** (`multimodelfinancialforecast.ipynb`) — multiple regressors (Random Forest, AdaBoost, Gradient Boosting) and classifiers benchmarked on next-day S&P 500 returns, with Monte Carlo risk analysis and statistical-significance testing of direction accuracy.
2. **FVG paper-trading bot** (`paper_trading_bot.py`) — a real-time Fair Value Gap strategy running on Alpaca paper trading.
3. **AWS Lambda backup** (`index.mjs`) — an S3-triggered function that mirrors uploaded files to a backup bucket.

## Honest Findings

The research reaches a deliberately negative result: the best regressor (AdaBoost, RMSE ≈ 0.0049) **matches the trivial zero-return baseline**, and direction classifiers hover around ~50–54% accuracy. This is consistent with the Efficient Market Hypothesis — daily index returns on a deeply liquid market are dominated by noise, and any edge is arbitraged away. The notebook tests whether the modest 54% direction signal is statistically significant rather than overclaiming.

## Trading Bot

- Strategy: 1-minute Fair Value Gap (FVG) with configurable risk/reward
- Broker: Alpaca (paper trading only — `PAPER = True`)
- Symbols: SPY, MSFT, TSLA, META
- Optional Telegram notifications
- Risk controls: max daily trades, fixed position sizing

> ⚠️ **For paper trading and research only. Not financial advice.** Do not point this at a live brokerage account without understanding the risks.

## Tech Stack

Python · scikit-learn · pandas · NumPy · alpaca-py · AWS Lambda (`@aws-sdk/client-s3`) · Docker

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env     # add ALPACA_API_KEY / ALPACA_SECRET_KEY (and optional Telegram)
python paper_trading_bot.py
```

Keys are read from environment variables — never commit your `.env`.
