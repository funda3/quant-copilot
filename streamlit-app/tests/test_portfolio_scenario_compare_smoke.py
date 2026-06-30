import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakeScenarioCompareResponse:
    status_code = 200

    def json(self):
        return {
            "request_id": "scenario-compare-smoke",
            "portfolio_name": "Pack Portfolio",
            "valuation_date": "2026-03-26",
            "status": "indicative",
            "scenario_pack": "Core Market Moves",
            "scenario_conventions": {
                "rates_bps": "Parallel rate shock in basis points.",
                "fx_spot_pct": "FX spot shock in percent; +5 means spot_rate x 1.05.",
                "equity_spot_pct": "Equity spot shock in percent; -5 means spot_price x 0.95.",
                "vol_pct": "Relative volatility shock in percent; +5 means volatility x 1.05.",
            },
            "scenario_count": 3,
            "position_count": 2,
            "scenarios": [
                {
                    "scenario_name": "Rates Up",
                    "description": "Parallel +100bp rate shock.",
                    "shocks": {"rates_bps": 100.0, "fx_spot_pct": 0.0, "equity_spot_pct": 0.0, "vol_pct": 0.0},
                    "status": "indicative",
                    "base_portfolio_pv": 10000.0,
                    "shocked_portfolio_pv": 9900.0,
                    "delta_portfolio_pv": -100.0,
                    "valued_count": 2,
                    "unsupported_count": 0,
                    "largest_contributor": "eqopt-1",
                    "largest_contributor_delta_pv": 20.0,
                    "largest_loser": "fxfwd-1",
                    "largest_loser_delta_pv": -120.0,
                    "warnings": [],
                },
                {
                    "scenario_name": "FX Up",
                    "description": "FX spot +5%.",
                    "shocks": {"rates_bps": 0.0, "fx_spot_pct": 5.0, "equity_spot_pct": 0.0, "vol_pct": 0.0},
                    "status": "indicative",
                    "base_portfolio_pv": 10000.0,
                    "shocked_portfolio_pv": 11250.0,
                    "delta_portfolio_pv": 1250.0,
                    "valued_count": 2,
                    "unsupported_count": 0,
                    "largest_contributor": "fxfwd-1",
                    "largest_contributor_delta_pv": 1250.0,
                    "largest_loser": None,
                    "largest_loser_delta_pv": 0.0,
                    "warnings": ["eqopt-1: fx_spot_pct shock ignored for non-FX position."],
                },
                {
                    "scenario_name": "Combined Stress",
                    "description": "Rates +100bp, FX spot +5%, equity spot -5%, volatility +5%.",
                    "shocks": {"rates_bps": 100.0, "fx_spot_pct": 5.0, "equity_spot_pct": -5.0, "vol_pct": 5.0},
                    "status": "indicative",
                    "base_portfolio_pv": 10000.0,
                    "shocked_portfolio_pv": 10800.0,
                    "delta_portfolio_pv": 800.0,
                    "valued_count": 2,
                    "unsupported_count": 0,
                    "largest_contributor": "fxfwd-1",
                    "largest_contributor_delta_pv": 1100.0,
                    "largest_loser": "eqopt-1",
                    "largest_loser_delta_pv": -300.0,
                    "warnings": [],
                },
            ],
            "grouped_delta_by_instrument_type": {
                "Rates Up": {"fx_forward": -120.0, "equity_option": 20.0},
                "FX Up": {"fx_forward": 1250.0, "equity_option": 0.0},
                "Combined Stress": {"fx_forward": 1100.0, "equity_option": -300.0},
            },
            "grouped_delta_by_asset_class": {
                "Rates Up": {"fx": -120.0, "equity": 20.0},
                "FX Up": {"fx": 1250.0, "equity": 0.0},
                "Combined Stress": {"fx": 1100.0, "equity": -300.0},
            },
            "positions": [
                {
                    "position_id": "fxfwd-1",
                    "instrument_type": "fx_forward",
                    "asset_class": "fx",
                    "deltas_by_scenario": {"Rates Up": -120.0, "FX Up": 1250.0, "Combined Stress": 1100.0},
                    "warnings_by_scenario": {"Rates Up": [], "FX Up": [], "Combined Stress": []},
                },
                {
                    "position_id": "eqopt-1",
                    "instrument_type": "equity_option",
                    "asset_class": "equity",
                    "deltas_by_scenario": {"Rates Up": 20.0, "FX Up": 0.0, "Combined Stress": -300.0},
                    "warnings_by_scenario": {
                        "Rates Up": [],
                        "FX Up": ["fx_spot_pct shock ignored for non-FX position."],
                        "Combined Stress": [],
                    },
                },
            ],
            "warnings": [],
        }


class PortfolioScenarioCompareSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakeScenarioCompareResponse())
    def test_portfolio_scenario_pack_renders_comparison_outputs(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("Portfolio / Scenario").run()
        app.text_input(key="portfolio_name").set_value("Pack Portfolio")
        app.text_input(key="portfolio_valuation_date").set_value("2026-03-26")

        app.button(key="run_scenario_pack_btn").click().run()

        self.assertIn("Multi-scenario Comparison", [node.value for node in app.subheader])
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Scenario pack"], "Core Market Moves")
        self.assertEqual(metrics["Scenarios"], "3")

        rendered_markdown = "\n".join(node.value for node in app.markdown)
        self.assertIn("Scenario comparison conventions", rendered_markdown)
        self.assertIn("Scenario summary table", rendered_markdown)
        self.assertIn("Grouped delta by instrument_type", rendered_markdown)
        self.assertIn("Grouped delta by asset_class", rendered_markdown)
        self.assertIn("Position comparison by scenario", rendered_markdown)
        self.assertIn("Scenario contributor comparison", rendered_markdown)
        self.assertIn("Scenario comparison warnings", rendered_markdown)
        self.assertIn("Combined Stress", rendered_markdown)

        download_labels = [button.label for button in app.get("download_button")]
        self.assertIn("Download Scenario Comparison JSON", download_labels)
        self.assertIn("Download Scenario Comparison CSV Summary", download_labels)
        self.assertIn("Download Scenario Position Comparison CSV", download_labels)
        self.assertTrue(mock_post.call_args.args[0].endswith("/portfolio/scenario-compare"))


if __name__ == "__main__":
    unittest.main()
