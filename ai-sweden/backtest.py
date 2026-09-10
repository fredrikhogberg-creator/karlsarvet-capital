import numpy as np
import pandas as pd

TRADING_DAYS = 252

def _max_drawdown(equity: pd.Series) -> float:
    dd = equity / equity.cummax() - 1
    return float(dd.min())

def performance_stats(returns: pd.Series, equity: pd.Series) -> dict:
    r = returns.dropna()
    years = len(r) / TRADING_DAYS
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std(ddof=1) * np.sqrt(TRADING_DAYS)
    sharpe = (r.mean() * TRADING_DAYS) / vol if vol and vol > 0 else np.nan
    downside = r[r < 0].std(ddof=1) * np.sqrt(TRADING_DAYS)
    sortino = (r.mean() * TRADING_DAYS) / downside if downside and downside > 0 else np.nan
    mdd = _max_drawdown(equity)
    return {"CAGR": cagr, "Total return": equity.iloc[-1] / equity.iloc[0] - 1,
            "Volatility": vol, "Sharpe": sharpe, "Sortino": sortino,
            "Max drawdown": mdd, "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan}

def run_monthly_top10(prices: pd.DataFrame, scores: pd.DataFrame, start_capital=1_000_000,
                      n=10, transaction_cost_bps=15):
    prices = prices.sort_index().ffill()
    scores = scores.sort_index()
    daily_ret = prices.pct_change().fillna(0)
    rebalance_dates = [d for d in scores.index if d in daily_ret.index]
    holdings = pd.Series(0.0, index=prices.columns)
    equity = pd.Series(index=daily_ret.index, dtype=float)
    costs = pd.Series(0.0, index=daily_ret.index)
    value = float(start_capital)
    for d in daily_ret.index:
        if d in rebalance_dates:
            s = scores.loc[d].dropna().sort_values(ascending=False).head(n)
            target = pd.Series(0.0, index=prices.columns)
            if len(s): target.loc[s.index] = 1 / len(s)
            turnover = (target - holdings).abs().sum()
            cost = value * turnover * transaction_cost_bps / 10_000
            value -= cost
            costs.loc[d] = cost
            holdings = target
        value *= 1 + float((holdings * daily_ret.loc[d]).sum())
        equity.loc[d] = value
    ret = equity.pct_change().fillna(0)
    return equity, ret, costs
