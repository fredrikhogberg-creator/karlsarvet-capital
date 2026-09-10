import numpy as np
import pandas as pd

WEIGHTS = {
    "momentum": 0.25,
    "earnings_revisions": 0.20,
    "valuation": 0.20,
    "quality": 0.15,
    "report_reaction": 0.10,
    "report_ai": 0.10,
}

def winsorized_percentile(s: pd.Series, higher_is_better=True) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    if s.notna().sum() < 3:
        return pd.Series(np.nan, index=s.index)
    lo, hi = s.quantile([0.02, 0.98])
    x = s.clip(lo, hi)
    rank = x.rank(pct=True, method="average") * 100
    return rank if higher_is_better else 100 - rank

def momentum_score(price: pd.Series) -> float:
    p = price.dropna()
    if len(p) < 270:
        return np.nan
    rets = []
    for n in (63, 126, 252):
        if len(p) > n:
            rets.append(p.iloc[-1] / p.iloc[-1-n] - 1)
    if len(rets) != 3:
        return np.nan
    return float(np.mean(rets))

def composite_score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    factor_cols = list(WEIGHTS)
    present = [c for c in factor_cols if c in out.columns]
    if not present:
        raise ValueError("No factor columns found")
    weighted = pd.DataFrame(index=out.index)
    for c in present:
        weighted[c] = pd.to_numeric(out[c], errors="coerce") * WEIGHTS[c]
    effective_weight = sum(WEIGHTS[c] for c in present)
    out["score_available"] = weighted.sum(axis=1, min_count=1) / effective_weight
    out["coverage"] = out[present].notna().mul(pd.Series({c: WEIGHTS[c] for c in present})).sum(axis=1) / effective_weight
    out["total_score"] = np.where(out[present].notna().all(axis=1) and len(present)==6, weighted.sum(axis=1), np.nan)
    return out.sort_values(["total_score", "score_available"], ascending=False, na_position="last")
