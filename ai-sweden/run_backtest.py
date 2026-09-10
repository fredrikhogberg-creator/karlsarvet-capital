"""Run a historical test only from explicitly documented, validated input datasets."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from backtest import run_monthly_top10, performance_stats, benchmark_comparison

REQUIRED = {
    "historical_universe_includes_delisted": True,
    "universe_membership_is_point_in_time": True,
    "prices_are_total_return": True,
    "corporate_actions_verified": True,
    "scores_use_original_publication_vintages": True,
    "benchmark_name": "SIXRX",
    "benchmark_is_total_return": True,
}


def load_inputs(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    missing = [key for key, value in REQUIRED.items() if manifest.get(key) != value]
    if missing:
        raise ValueError("Unverified historical inputs: " + ", ".join(missing))
    if not manifest.get("sources") or not manifest.get("verification_notes"):
        raise ValueError("Source provenance and verification notes are required")
    frames = {}
    for name in ("prices", "scores", "membership"):
        frames[name] = pd.read_csv(folder / (name + ".csv"), index_col=0, parse_dates=True)
        frames[name].columns = frames[name].columns.astype(str)
    benchmark = pd.read_csv(folder / "sixrx.csv", index_col=0, parse_dates=True)["SIXRX"]
    prices, scores, membership = (frames[k] for k in ("prices", "scores", "membership"))
    if not scores.index.isin(membership.index).all() or not scores.columns.isin(membership.columns).all():
        raise ValueError("Historical membership does not cover all ranking observations")
    membership = membership.reindex(index=scores.index, columns=scores.columns)
    if membership.isna().any().any() or not membership.isin([0, 1]).all().all():
        raise ValueError("Membership must be explicit 0/1 for each observation")
    if (scores.notna() & membership.ne(1)).any().any():
        raise ValueError("Score assigned outside historical investable universe")
    if not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
        raise ValueError("Price dates must be ordered and unique")
    if not benchmark.index.is_unique:
        raise ValueError("Duplicate SIXRX dates")
    return prices, scores, benchmark, manifest


def run(folder, output):
    prices, scores, benchmark, manifest = load_inputs(folder)
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    prices = prices.loc[config["start_date"]:config["end_date"]]
    scores = scores.loc[config["start_date"]:config["end_date"]]
    if prices.empty or (prices.index[0] - pd.Timestamp(config["start_date"])).days > 7:
        raise ValueError("Dataset does not cover start of requested 2010–2026 period")
    if (pd.Timestamp(config["end_date"]) - prices.index[-1]).days > 4:
        raise ValueError("Dataset does not cover end of requested period")
    months = prices.index.to_period("M").unique()
    if not months.isin(scores.index.to_period("M")).all():
        raise ValueError("Monthly ranking history is incomplete")
    b = benchmark.reindex(prices.index)
    if b.isna().any() or not np.isfinite(b).all() or (b <= 0).any():
        raise ValueError("SIXRX is incomplete or invalid")
    output.mkdir(parents=True, exist_ok=True)
    initial = config["initial_capital_sek"]
    benchmark_equity = b / b.iloc[0] * initial
    benchmark_returns = benchmark_equity.pct_change(fill_method=None).fillna(0)
    metrics = {"SIXRX": performance_stats(benchmark_returns, benchmark_equity, initial)}
    all_equity = pd.DataFrame({"SIXRX": benchmark_equity})
    for cost in config["transaction_cost_scenarios_bps"]:
        equity, returns, costs = run_monthly_top10(
            prices, scores, initial, config["portfolio_size"], cost)
        label = f"strategy_{cost}bps"
        all_equity[label] = equity
        metrics[label] = {**performance_stats(returns, equity, initial),
                          **benchmark_comparison(returns, b),
                          "transaction_costs_sek": float(costs.sum()),
                          "total_two_way_turnover": sum(x["turnover"] for x in equity.attrs["trades"])}
        pd.DataFrame(equity.attrs["trades"]).to_csv(output / f"trades_{cost}bps.csv", index=False)
        yearly = (1+returns).groupby(returns.index.year).prod()-1
        yearly.to_csv(output / f"annual_returns_{cost}bps.csv")
    all_equity.to_csv(output / "equity.csv")
    pd.DataFrame(metrics).T.to_csv(output / "performance.csv")
    (output / "input_provenance.json").write_text(json.dumps(manifest, indent=2))
    print("Historical test complete: " + str(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("backtest-results"))
    args = parser.parse_args()
    run(args.inputs, args.output)
