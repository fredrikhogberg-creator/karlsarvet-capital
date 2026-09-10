import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import numpy as np
import pandas as pd
from model import composite_score, WEIGHTS
from backtest import run_monthly_top10, performance_stats
from run_pipeline import latest_report, fundamentals, parse_prices, select_universe
from borsdata_client import get_json, BorsdataError


class ModelTests(unittest.TestCase):
    def test_partial_coverage_is_full_model_weight(self):
        result = composite_score(pd.DataFrame({"momentum": [80, 20]}))
        self.assertEqual(result.iloc[0].coverage, .25)
        self.assertEqual(result.iloc[0].score_available, 80)
        self.assertTrue(result.total_score.isna().all())

    def test_complete_and_missing_rows(self):
        data = pd.DataFrame({factor: [80., 60.] for factor in WEIGHTS})
        data.loc[1, "quality"] = np.nan
        result = composite_score(data)
        self.assertAlmostEqual(result.loc[0, "total_score"], 80)
        self.assertTrue(pd.isna(result.loc[1, "total_score"]))
        self.assertAlmostEqual(result.loc[1, "score_available"], 60)
        self.assertAlmostEqual(result.loc[1, "coverage"], .85)

    def test_no_factors_no_score(self):
        result = composite_score(pd.DataFrame({"name": ["x"]}))
        self.assertEqual(result.iloc[0].coverage, 0)
        self.assertTrue(pd.isna(result.iloc[0].score_available))

    def test_invalid_factor_not_ranked(self):
        result = composite_score(pd.DataFrame({"momentum": [np.inf, -1, 101]}))
        self.assertTrue(result.score_available.isna().all())


class EngineTests(unittest.TestCase):
    def test_no_same_day_or_execution_day_return(self):
        dates = pd.date_range("2026-01-30", periods=3, freq="B")
        prices = pd.DataFrame({"a": [100, 200, 220]}, index=dates)
        scores = pd.DataFrame({"a": [90]}, index=dates[:1])
        equity, returns, costs = run_monthly_top10(prices, scores, n=1, transaction_cost_bps=0)
        np.testing.assert_allclose(equity, [1e6, 1e6, 1.1e6])

    def test_holdings_drift_instead_of_daily_rebalance(self):
        dates = pd.date_range("2026-01-30", periods=4, freq="B")
        prices = pd.DataFrame({"a": [100,100,200,100], "b": [100,100,100,100]}, index=dates)
        scores = pd.DataFrame({"a": [90], "b": [80]}, index=dates[:1])
        equity, _, _ = run_monthly_top10(prices, scores, n=2, transaction_cost_bps=0)
        np.testing.assert_allclose(equity, [1e6,1e6,1.5e6,1e6])

    def test_entry_cost_in_return_and_drawdown(self):
        dates = pd.date_range("2026-01-30", periods=3, freq="B")
        prices = pd.DataFrame({"a": [100,100,100]}, index=dates)
        scores = pd.DataFrame({"a": [90]}, index=dates[:1])
        equity, returns, costs = run_monthly_top10(prices, scores, n=1)
        expected = 1e6 / 1.0015
        self.assertAlmostEqual(equity.iloc[-1], expected)
        self.assertAlmostEqual(costs.sum(), 1e6-expected)
        stats = performance_stats(returns, equity)
        self.assertAlmostEqual(stats["Total return"], expected/1e6-1)
        self.assertAlmostEqual(stats["Max drawdown"], expected/1e6-1)

    def test_missing_held_quote_fails(self):
        dates = pd.date_range("2026-01-30", periods=3, freq="B")
        prices = pd.DataFrame({"a": [100,100,np.nan]}, index=dates)
        scores = pd.DataFrame({"a": [90]}, index=dates[:1])
        with self.assertRaisesRegex(ValueError, "Missing held"):
            run_monthly_top10(prices, scores, n=1)

    def test_insufficient_holdings_fails(self):
        dates = pd.date_range("2026-01-30", periods=3, freq="B")
        with self.assertRaisesRegex(ValueError, "Fewer"):
            run_monthly_top10(pd.DataFrame({"a": [100]*3}, index=dates),
                             pd.DataFrame({"a": [90]}, index=dates[:1]))


class DataTests(unittest.TestCase):
    def test_future_publication_excluded(self):
        a = {"report_Date": "2026-07-15", "report_End_Date": "2026-06-30"}
        b = {"report_Date": "2026-10-20", "report_End_Date": "2026-09-30"}
        self.assertEqual(latest_report({"reportsR12": [a,b]}, pd.Timestamp("2026-09-09")), a)

    def test_missing_publication_never_inferred(self):
        self.assertIsNone(latest_report({"reportsR12": [{"year": 2020, "period": 1}]}, pd.Timestamp("2026-09-09")))

    def test_report_million_units(self):
        result = fundamentals({"number_of_shares": 10, "profit_to_Equity_Holders": 50,
                               "free_Cash_Flow": 40, "total_Equity": 500}, 100)
        self.assertEqual(result["earnings_yield"], .05)
        self.assertEqual(result["fcf_yield"], .04)
        self.assertEqual(result["roe"], .1)

    def test_future_prices_excluded(self):
        p = parse_prices({"stockPricesList": [{"d":"2026-09-09","c":10,"v":5},
                                              {"d":"2026-09-10","c":20,"v":5}]}, pd.Timestamp("2026-09-09"))
        self.assertEqual(len(p), 1)

    def test_client_does_not_leak_authkey(self):
        error = HTTPError("https://example.test?authKey=private-secret", 401, "failure", {}, io.BytesIO())
        with patch.dict(os.environ, {"BORSDATA_API_KEY": "private-secret"}), patch("borsdata_client.urlopen", side_effect=error):
            with self.assertRaises(BorsdataError) as caught:
                get_json("instruments")
        self.assertEqual(str(caught.exception), "Börsdata HTTP 401")


if __name__ == "__main__":
    unittest.main()
