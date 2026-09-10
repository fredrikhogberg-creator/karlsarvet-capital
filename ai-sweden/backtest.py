"""Close-to-close simulator. Scores execute at the NEXT trading day's close.

Inputs must be point-in-time scores and comparable total-return price series.
No implicit forward filling; held assets with missing quotes stop the test.
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def performance_stats(returns, equity, initial_capital=None):
    r = returns.dropna()
    if r.empty or equity.empty or not np.isfinite(r).all() or (r <= -1).any():
        raise ValueError("Invalid or empty return series")
    initial = initial_capital or equity.attrs.get("initial_capital")
    if initial is None:
        initial = equity.iloc[0] / (1 + r.iloc[0])
    growth = equity.iloc[-1] / initial
    years = len(r) / TRADING_DAYS
    cagr = growth ** (1 / years) - 1
    vol = float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))
    downside = float(np.sqrt(np.mean(np.minimum(r, 0) ** 2)) * np.sqrt(TRADING_DAYS))
    peak = np.maximum.accumulate(np.r_[initial, equity.to_numpy()])
    mdd = float((np.r_[initial, equity.to_numpy()] / peak - 1).min())
    return {"CAGR": cagr, "Total return": growth - 1, "Volatility": vol,
            "Sharpe": r.mean() * TRADING_DAYS / vol if vol > 0 else np.nan,
            "Sortino": r.mean() * TRADING_DAYS / downside if downside > 0 else np.nan,
            "Max drawdown": mdd, "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan}


def run_monthly_top10(prices, scores, start_capital=1_000_000, n=10,
                      transaction_cost_bps=15):
    if not 0 <= transaction_cost_bps < 10000 or n < 1 or start_capital <= 0:
        raise ValueError("Invalid simulation parameters")
    prices = prices.sort_index().astype(float)
    scores = scores.sort_index().astype(float)
    if prices.empty or scores.empty:
        raise ValueError("Prices and scores are required")
    for frame in (prices, scores):
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
            raise ValueError("Unique DatetimeIndex required")
        if frame.columns.has_duplicates:
            raise ValueError("Duplicate instrument columns")
    if not set(scores.columns).issubset(prices.columns):
        raise ValueError("Score contains an unknown instrument")
    if scores.index.to_period("M").duplicated().any():
        raise ValueError("At most one ranking per month")
    if ((prices <= 0) | np.isinf(prices)).any().any():
        raise ValueError("Nonpositive or infinite price")
    if np.isinf(scores).any().any():
        raise ValueError("Infinite score")
    executions = {}
    for date, row in scores.iterrows():
        i = prices.index.searchsorted(date, side="right")
        if i < len(prices):
            executions[prices.index[i]] = row
    shares = pd.Series(0.0, index=prices.columns)
    cash = float(start_capital)
    value = cash
    equity = pd.Series(index=prices.index, dtype=float)
    returns = equity.copy()
    costs = pd.Series(0.0, index=prices.index)
    trades = []
    rate = transaction_cost_bps / 10_000
    for date, quote in prices.iterrows():
        held = shares > 0
        if quote[held].isna().any():
            raise ValueError(f"Missing held-asset quote on {date.date()}; explicit corporate-action handling required")
        old_positions = shares * quote.fillna(0)
        pretrade = cash + old_positions.sum()
        if date in executions:
            row = executions[date].dropna().sort_values(ascending=False, kind="stable")
            chosen = row.head(n).index
            if len(chosen) < n:
                raise ValueError(f"Fewer than {n} eligible assets on {date.date()}")
            if quote.loc[chosen].isna().any():
                raise ValueError(f"Selected asset cannot trade on {date.date()}")
            target = pd.Series(0.0, index=prices.columns)
            target.loc[chosen] = 1 / n
            # Self-financing target: invest exactly NAV less actual buy+sell fees.
            lo, hi = 0.0, pretrade
            for _ in range(60):
                mid = (lo + hi) / 2
                fees = (target * mid - old_positions).abs().sum() * rate
                if mid + fees > pretrade:
                    hi = mid
                else:
                    lo = mid
            invested = (lo + hi) / 2
            trade_value = (target * invested - old_positions).abs().sum()
            costs.loc[date] = trade_value * rate
            shares = (target * invested).div(quote).fillna(0)
            cash = max(0.0, pretrade - invested - costs.loc[date])
            trades.append({"date": str(date.date()), "turnover": trade_value / pretrade,
                           "cost_sek": costs.loc[date], "instruments": list(chosen)})
        new_value = cash + (shares * quote.fillna(0)).sum()
        returns.loc[date] = new_value / value - 1
        equity.loc[date] = new_value
        value = new_value
    equity.attrs["initial_capital"] = start_capital
    equity.attrs["trades"] = trades
    return equity, returns, costs


def benchmark_comparison(strategy_returns, benchmark_prices):
    benchmark = benchmark_prices.reindex(strategy_returns.index)
    if benchmark.isna().any() or (benchmark <= 0).any():
        raise ValueError("SIXRX must cover every strategy date")
    b = benchmark.pct_change(fill_method=None).iloc[1:]
    s = strategy_returns.iloc[1:]
    variance = b.var(ddof=1)
    beta = s.cov(b) / variance if variance > 0 else np.nan
    result = {"beta": beta, "annualized_alpha_rf0": (s.mean() - beta * b.mean()) * 252}
    for months in (12, 36, 60):
        periods = months * 21
        relative = (1+s).rolling(periods).apply(np.prod, raw=True) / (1+b).rolling(periods).apply(np.prod, raw=True) - 1
        valid = relative.dropna()
        result[f"outperformance_hit_rate_{months}m_approx"] = float((valid > 0).mean()) if len(valid) else np.nan
    return result
