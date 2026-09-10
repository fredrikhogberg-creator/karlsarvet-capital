"""Fetch the Stockholm universe, prices and reports; produce an auditable base ranking."""
import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from borsdata_client import get_json, instruments, stockprices, reports, BorsdataError
from model import winsorized_percentile, momentum_score, composite_score


def rows(payload, key):
    value = payload.get(key, []) if isinstance(payload, dict) else payload
    if not isinstance(value, list):
        raise ValueError(f"Unexpected API schema: {key}")
    return value


def select_universe(inst, countries, markets):
    sweden = {x["id"] for x in countries if x.get("name", "").casefold() in ("sverige", "sweden")}
    allowed = {x["id"] for x in markets if x.get("countryId") in sweden
               and x.get("name", "").casefold() in ("large cap", "mid cap")
               and not x.get("isIndex", False)}
    if not sweden or not allowed:
        raise ValueError("Could not resolve Swedish Large/Mid Cap metadata")
    # Instrument=0 is the primary ordinary share; Stocks2 and preference shares excluded.
    result = [x for x in inst if x.get("countryId") in sweden and x.get("marketId") in allowed
              and x.get("instrument") == 0 and x.get("stockPriceCurrency") == "SEK"]
    if len(result) < 10:
        raise ValueError("Swedish stock universe unexpectedly small")
    return result


def parse_prices(payload, as_of):
    frame = pd.DataFrame(rows(payload, "stockPricesList"))
    if frame.empty:
        return pd.DataFrame(columns=["c", "v"], index=pd.DatetimeIndex([]))
    if not {"d", "c", "v"}.issubset(frame.columns):
        raise ValueError("Unexpected stock-price schema")
    frame["d"] = pd.to_datetime(frame["d"], errors="raise")
    if frame["d"].duplicated().any():
        raise ValueError("Duplicate price dates")
    frame = frame.set_index("d").sort_index().loc[:as_of]
    for col in ("c", "v"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def latest_report(payload, as_of):
    # Publication date is distinct from fiscal year/quarter end.
    candidates = []
    for report in rows(payload, "reportsR12"):
        date = pd.to_datetime(report.get("report_Date"), errors="coerce")
        end = pd.to_datetime(report.get("report_End_Date"), errors="coerce")
        if pd.notna(date) and pd.notna(end) and end <= date <= as_of and (as_of-date).days <= 550:
            candidates.append((end, date, report))
    return max(candidates, key=lambda x: (x[0], x[1]))[2] if candidates else None


def number(report, key):
    try:
        # API responses and older official clients differ in property casing.
        normalized = {k.casefold(): v for k, v in report.items()}
        n = float(normalized.get(key.casefold()))
        return n if np.isfinite(n) else np.nan
    except (TypeError, ValueError):
        return np.nan


def safe_ratio(a, b):
    return a / b if np.isfinite(a) and np.isfinite(b) and b > 0 else np.nan


def fundamentals(report, close):
    shares = number(report, "number_of_shares")  # million shares; report amounts in millions
    cap = close * shares
    profit = number(report, "profit_to_Equity_Holders")
    equity = number(report, "total_Equity")
    revenues = number(report, "revenues")
    ebit = number(report, "operating_Income")
    ocf = number(report, "cash_flow_from_operating_activities")
    return {
        "earnings_yield": safe_ratio(profit, cap),
        "fcf_yield": safe_ratio(number(report, "free_Cash_Flow"), cap),
        "roe": safe_ratio(profit, equity),
        "operating_margin": safe_ratio(ebit, revenues),
        "negative_debt_to_assets": -safe_ratio(number(report, "net_Debt"), number(report, "total_Assets")),
        "cash_conversion": safe_ratio(ocf, profit),
    }


def sector_percentile(frame, col):
    result = winsorized_percentile(frame[col])
    # Small sectors fall back to whole-universe comparison and are explicitly labelled.
    for _, group in frame.groupby("sectorId"):
        if group[col].notna().sum() >= 5:
            result.loc[group.index] = winsorized_percentile(group[col])
    return result


def rank_snapshot(frame):
    out = frame.copy()
    out["momentum"] = winsorized_percentile(out["momentum_raw"])
    value_cols = ["earnings_yield", "fcf_yield"]
    quality_cols = ["roe", "operating_margin", "negative_debt_to_assets", "cash_conversion"]
    for col in value_cols + quality_cols:
        out[col + "_percentile"] = sector_percentile(out, col)
    # Identical subfactor coverage for every ranked company.
    out["valuation"] = out[[c+"_percentile" for c in value_cols]].mean(axis=1).where(out[value_cols].notna().all(axis=1))
    out["quality"] = out[[c+"_percentile" for c in quality_cols]].mean(axis=1).where(out[quality_cols].notna().all(axis=1))
    out = composite_score(out)
    out["base_eligible"] = out[["momentum", "valuation", "quality"]].notna().all(axis=1)
    out["base_score"] = out["score_available"].where(out["base_eligible"])
    out["missing_metrics"] = out[value_cols + quality_cols].isna().apply(
        lambda row: ", ".join(row.index[row]), axis=1)
    return out.sort_values(["base_score", "insId"], ascending=[False, True], na_position="last")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def run(as_of, output, cache):
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    date = pd.Timestamp(as_of)
    if date >= pd.Timestamp.now(tz="Europe/Stockholm").tz_localize(None).normalize():
        raise ValueError("Use a completed market day before today")
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    all_instruments = rows(instruments(), "instruments")
    countries = rows(get_json("countries"), "countries")
    markets = rows(get_json("markets"), "markets")
    universe = select_universe(all_instruments, countries, markets)
    write_json(cache / "instruments.json", all_instruments)
    write_json(cache / "metadata.json", {"countries": countries, "markets": markets})
    observations, excluded, errors, coverage = [], [], [], []
    for i, item in enumerate(universe, 1):
        iid = item["insId"]
        print(f"Collecting {i}/{len(universe)}: {iid}", flush=True)
        try:
            price_payload = stockprices(iid, "2008-01-01", as_of)
            report_payload = reports(iid)
            write_json(cache / f"{iid}-prices.json", price_payload)
            write_json(cache / f"{iid}-reports.json", report_payload)
            p = parse_prices(price_payload, date)
            coverage.append({"insId": iid, "name": item["name"], "price_days": len(p),
                "first_price": str(p.index.min().date()) if len(p) else None,
                "last_price": str(p.index.max().date()) if len(p) else None,
                "r12_reports": len(rows(report_payload, "reportsR12")),
                "year_reports": len(rows(report_payload, "reportsYear")),
                "quarter_reports": len(rows(report_payload, "reportsQuarter")),
                "first_r12_period_end": min((str(r.get("report_End_Date", ""))
                    for r in rows(report_payload, "reportsR12")), default=None)})
            reason = None
            if len(p) < config["min_history_days"]:
                reason = "Otillräcklig kurshistorik"
            elif (date - p.index[-1]).days > 4:
                reason = "Inaktuell kurs"
            elif p["c"].tail(270).isna().any() or (p["c"].tail(270) <= 0).any():
                reason = "Ogiltiga historiska kurser"
            elif p["c"].iloc[-1] < config["min_price_sek"]:
                reason = "Kurs under 5 kr"
            elif p["v"].tail(63).isna().any() or (p["c"] * p["v"]).tail(63).median() < config["min_median_daily_turnover_sek"]:
                reason = "Otillräcklig omsättning"
            if reason:
                excluded.append({"insId": iid, "name": item["name"], "reason": reason})
                continue
            report = latest_report(report_payload, date)
            data = {**item, "price_date": str(p.index[-1].date()), "close": p["c"].iloc[-1],
                    "median_turnover_sek": (p["c"]*p["v"]).tail(63).median(),
                    "momentum_raw": momentum_score(p["c"].tail(270)),
                    "report_date": report.get("report_Date") if report else None,
                    **fundamentals(report or {}, p["c"].iloc[-1])}
            observations.append(data)
        except (BorsdataError, ValueError, KeyError) as exc:
            errors.append({"insId": iid, "error": type(exc).__name__})
            if isinstance(exc, BorsdataError) and ("401" in str(exc) or "403" in str(exc)):
                raise
    pd.DataFrame(coverage).to_csv(output / "data_coverage.csv", index=False)
    write_json(output / "excluded.json", excluded)
    write_json(output / "errors.json", errors)
    if not observations:
        raise RuntimeError("No valid observations; inspect data coverage")
    ranking = rank_snapshot(pd.DataFrame(observations))
    ranking.to_csv(output / "ranking.csv", index=False)
    eligible = ranking[ranking["base_eligible"]]
    complete = not errors and len(eligible) >= 10
    top = eligible.head(10).copy() if complete else eligible.head(0).copy()
    top["model_weight"] = .10
    top.to_csv(output / "top10.csv", index=False)
    benchmark_candidates = [dict(insId=x["insId"], name=x["name"], ticker=x.get("ticker"))
                            for x in all_instruments if "SIXRX" in (x.get("name","")+" "+x.get("ticker","")).upper()]
    summary = {
        "as_of": as_of, "built_at": datetime.now(timezone.utc).isoformat(),
        "status": "base_ranking_ready" if complete else "incomplete_data",
        "universe_count": len(universe), "valid_observations": len(ranking),
        "eligible_base_count": len(eligible), "excluded_count": len(excluded), "errors_count": len(errors),
        "full_model_coverage": .60, "active_factors": ["momentum", "valuation", "quality"],
        "missing_factors": ["earnings_revisions", "report_reaction", "report_ai"],
        "report_field_names": sorted(report.keys()) if report else [],
        "benchmark_candidates": benchmark_candidates,
        "backtest_status": "blocked_missing_verified_historical_inputs",
        "backtest_blockers": [
            "Historical Large/Mid Cap membership including delisted companies is not reconstructed.",
            "Total-return stock series (dividends and corporate actions) are not verified.",
            "SIXRX total-return history is not loaded and validated.",
            "Downloaded report history may contain revisions; original point-in-time report vintages are not verified."
        ],
        "method": "Base model only: 25/60 momentum, 20/60 valuation, 15/60 quality. Valuation uses earnings yield and FCF yield; quality uses ROE, operating margin, net debt/assets and operating cash flow/profit. No EV/EBITA or ROIC claim. Sector percentile if >=5 observations, otherwise whole universe.",
        "top10": json.loads(top[["name","ticker","base_score","momentum","valuation","quality","model_weight"]].to_json(orient="records"))
    }
    write_json(output / "run_summary.json", summary)
    lines = [f"# Karlsarvet AI Sweden v1.0 — {as_of}", "",
             "**Basmodell: 3 av 6 faktorer, 60 % av modellens ursprungliga vikt.**",
             f"Urval: {len(universe)} bolag. Jämförbart underlag: {len(eligible)}. Hämtningsfel: {len(errors)}.",
             "", "Ingen fullständig sexfaktorsranking eller verifierat 2010–2026-backtest ännu.", "",
             "| Bolag | Baspoäng | Momentum | Värdering | Kvalitet |",
             "|---|---:|---:|---:|---:|"]
    for r in summary["top10"]:
        lines.append(f"| {r['name']} | {r['base_score']:.1f} | {r['momentum']:.1f} | {r['valuation']:.1f} | {r['quality']:.1f} |")
    if not complete:
        lines += ["", "Top 10 publiceras först när datahämtningen är komplett och minst tio bolag kan jämföras."]
    lines += ["", "Värdering: vinstavkastning och FCF-avkastning. Kvalitet: ROE, rörelsemarginal, nettoskuld/tillgångar och kassakonvertering.",
              "Sektorjämförelse används vid minst fem giltiga observationer per nyckeltal, annars hela urvalet.",
              "", "## Underlag som återstår för historiskt test", *["- "+x for x in summary["backtest_blockers"]]]
    report_text = "\n".join(lines) + "\n"
    (output / "RESULTAT.md").write_text(report_text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as file:
            file.write(report_text)
    print(report_text, flush=True)
    if not complete:
        raise RuntimeError("Ranking incomplete; diagnostic files written")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-09-09")
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--cache", type=Path, default=Path("data"))
    args = parser.parse_args()
    run(args.as_of, args.output, args.cache)
