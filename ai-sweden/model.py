import numpy as np
import pandas as pd

WEIGHTS = {"momentum": .25, "earnings_revisions": .20, "valuation": .20,
           "quality": .15, "report_reaction": .10, "report_ai": .10}


def winsorized_percentile(s, higher_is_better=True):
    s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if s.notna().sum() < 3:
        return pd.Series(np.nan, index=s.index)
    lo, hi = s.quantile([.02, .98])
    rank = s.clip(lo, hi).rank(method="average")
    score = (rank - 1) / (s.notna().sum() - 1) * 100
    return score if higher_is_better else 100 - score


def momentum_score(price):
    p = pd.to_numeric(price, errors="coerce")
    if len(p) < 270 or p.isna().any() or (p <= 0).any():
        return np.nan
    return float(np.mean([p.iloc[-1] / p.iloc[-1-n] - 1 for n in (63, 126, 252)]))


def composite_score(df):
    out = df.copy()
    factors = out.reindex(columns=list(WEIGHTS)).apply(pd.to_numeric, errors="coerce")
    factors = factors.where(np.isfinite(factors) & factors.ge(0) & factors.le(100))
    weights = pd.Series(WEIGHTS)
    coverage = factors.notna().mul(weights).sum(axis=1)
    weighted = factors.mul(weights).sum(axis=1, min_count=1)
    out["coverage"] = coverage
    out["score_available"] = weighted / coverage.replace(0, np.nan)
    out["total_score"] = weighted.where(factors.notna().all(axis=1))
    return out.sort_values(["total_score", "score_available"], ascending=False,
                           na_position="last", kind="stable")
