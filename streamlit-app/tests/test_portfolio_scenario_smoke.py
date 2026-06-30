import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakePortfolioValueResponse:
    status_code = 200

    def json(self):
        return {
            "request_id": "portfolio-value-smoke",
            "portfolio_name": "Demo Portfolio",
            "valuation_date": "2024-01-01",
            "status": "indicative",
            "position_count": 2,
            "valued_count": 2,
            "unsupported_count": 0,
            "total_portfolio_pv": 12345.67,
            "grouped_pv_by_instrument_type": {"bond": 10000.0, "fx_forward": 2345.67},
            "grouped_pv_by_asset_class": {"rates": 10000.0, "fx": 2345.67},
            "positions": [
                {
                    "position_id": "bond-1",
                    "instrument_type": "bond",
                    "asset_class": "rates",
                    "quantity": 1.0,
                    "pricing_status": "indicative",
                    "status": "valued",
                    "pv": 10000.0,
                    "warnings": [],
                },
                {
                    "position_id": "fxfwd-1",
                    "instrument_type": "fx_forward",
                    "asset_class": "fx",
                    "quantity": 1.0,
                    "pricing_status": "indicative",
                    "status": "valued",
                    "pv": 2345.67,
                    "warnings": [],
                },
            ],
            "warnings": [],
        }


class _FakePortfolioScenarioResponse:
    status_code = 200

    def json(self):
        return {
            "request_id": "portfolio-scenario-smoke",
            "portfolio_name": "Demo Portfolio",
            "valuation_date": "2024-01-01",
            "status": "indicative",
            "position_count": 2,
            "valued_count": 2,
            "unsupported_count": 0,
            "base_portfolio_pv": 12345.67,
            "shocked_portfolio_pv": 13345.67,
            "delta_portfolio_pv": 1000.0,
            "grouped_base_pv_by_instrument_type": {"bond": 10000.0, "fx_forward": 2345.67},
            "grouped_shocked_pv_by_instrument_type": {"bond": 10500.0, "fx_forward": 2845.67},
            "grouped_delta_pv_by_instrument_type": {"bond": 500.0, "fx_forward": 500.0},
            "positions": [
                {
                    "position_id": "bond-1",
                    "instrument_type": "bond",
                    "asset_class": "rates",
                    "quantity": 1.0,
                    "base_pricing_status": "indicative",
                    "shocked_pricing_status": "indicative",
                    "status": "valued",
                    "base_pv": 10000.0,
                    "shocked_pv": 10500.0,
                    "delta_pv": 500.0,
                    "warnings": [],
                },
                {
                    "position_id": "fxfwd-1",
                    "instrument_type": "fx_forward",
                    "asset_class": "fx",
                    "quantity": 1.0,
                    "base_pricing_status": "indicative",
                    "shocked_pricing_status": "indicative",
                    "status": "valued",
                    "base_pv": 2345.67,
                    "shocked_pv": 2845.67,
                    "delta_pv": 500.0,
                    "warnings": [],
                },
            ],
            "warnings": [],
        }


class PortfolioScenarioSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakePortfolioValueResponse())
    def test_portfolio_value_page_renders_and_posts_expected_payload(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("Portfolio / Scenario").run()

        self.assertEqual(app.title[0].value, "Portfolio / Scenario")

        app.text_input(key="portfolio_name").set_value("Demo Portfolio")
        app.text_input(key="portfolio_valuation_date").set_value("2024-01-01")

        app.button(key="run_portfolio_value_btn").click().run()

        self.assertIn("Portfolio Value Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Positions"], "2")
        self.assertEqual(metrics["Valued"], "2")
        self.assertEqual(metrics["Unsupported"], "0")
        self.assertEqual(metrics["Total Portfolio PV"], "12,345.67")

        mock_post.assert_called_once()
        self.assertTrue(mock_post.call_args.args[0].endswith("/portfolio/value"))
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["portfolio_name"], "Demo Portfolio")
        self.assertEqual(payload["valuation_date"], "2024-01-01")
        self.assertIsInstance(payload["positions"], list)
        self.assertGreater(len(payload["positions"]), 0)
        value_download_labels = [d.label for d in app.get("download_button")]
        self.assertIn("Download Value CSV Summary", value_download_labels)

    @patch("requests.post", return_value=_FakePortfolioScenarioResponse())
    def test_portfolio_scenario_page_renders_and_posts_expected_payload(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("Portfolio / Scenario").run()

        app.text_input(key="portfolio_name").set_value("Demo Portfolio")
        app.text_input(key="portfolio_valuation_date").set_value("2024-01-01")

        app.button(key="run_portfolio_scenario_btn").click().run()

        self.assertIn("Portfolio Scenario Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Base Portfolio PV"], "12,345.67")
        self.assertEqual(metrics["Shocked Portfolio PV"], "13,345.67")
        self.assertEqual(metrics["Delta vs Base"], "+1,000.00")

        mock_post.assert_called_once()
        self.assertTrue(mock_post.call_args.args[0].endswith("/portfolio/scenario"))
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["portfolio_name"], "Demo Portfolio")
        self.assertEqual(payload["valuation_date"], "2024-01-01")
        self.assertIsInstance(payload["positions"], list)
        self.assertIsInstance(payload["shocks"], dict)
        scenario_download_labels = [d.label for d in app.get("download_button")]
        self.assertIn("Download Scenario CSV Summary", scenario_download_labels)

    @patch("requests.post", return_value=_FakePortfolioValueResponse())
    def test_pasted_csv_positions_are_normalized_and_sent(self, mock_post):
        csv_text = """position_id,instrument_type,quantity,maturity_date,notional_foreign,spot_rate,contract_forward_rate,domestic_rate,foreign_rate,domestic_currency,foreign_currency,day_count,position
fxfwd_csv_1,fx_forward,2,2026-09-26,1000000,18.25,18.40,0.082,0.051,ZAR,USD,ACT_365F,long_foreign
"""

        app = AppTest.from_file("app.py")
        app.run()
        app.radio(key="nav_page").set_value("Portfolio / Scenario").run()

        app.radio(key="portfolio_positions_input_mode").set_value("Pasted CSV/Table").run()
        app.text_area(key="portfolio_positions_table_text").set_value(csv_text)
        app.text_input(key="portfolio_name").set_value("CSV Import Portfolio")
        app.text_input(key="portfolio_valuation_date").set_value("2024-01-01")

        app.button(key="run_portfolio_value_btn").click().run()

        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["portfolio_name"], "CSV Import Portfolio")
        self.assertEqual(len(payload["positions"]), 1)
        row = payload["positions"][0]
        self.assertEqual(row["position_id"], "fxfwd_csv_1")
        self.assertEqual(row["instrument_type"], "fx_forward")
        self.assertEqual(row["quantity"], 2.0)
        self.assertEqual(row["fields"]["maturity_date"], "2026-09-26")
        self.assertEqual(row["fields"]["notional_foreign"], 1000000.0)
        self.assertEqual(row["fields"]["spot_rate"], 18.25)

    @patch("requests.post")
    def test_invalid_import_rows_block_backend_calls(self, mock_post):
        bad_csv_text = """position_id,instrument_type,quantity,expiry_date,spot_price,strike_price,risk_free_rate,dividend_yield,volatility,quantity_shares,option_type,currency
eq_bad_1,equity_option,1,2026-09-26,100,105,0.08,0.02,0.25,1000,call,ZAR
"""

        app = AppTest.from_file("app.py")
        app.run()
        app.radio(key="nav_page").set_value("Portfolio / Scenario").run()

        app.radio(key="portfolio_positions_input_mode").set_value("Pasted CSV/Table").run()
        app.text_area(key="portfolio_positions_table_text").set_value(bad_csv_text)

        app.button(key="run_portfolio_value_btn").click().run()

        mock_post.assert_not_called()
        self.assertTrue(any("validation error" in e.value.lower() for e in app.error))


if __name__ == "__main__":
    unittest.main()
