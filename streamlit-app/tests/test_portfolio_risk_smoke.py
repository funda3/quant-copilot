import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakePortfolioRiskResponse:
    status_code = 200

    def json(self):
        return {
            "request_id": "portfolio-risk-smoke",
            "portfolio_name": "Risk Portfolio",
            "valuation_date": "2026-03-26",
            "status": "partial",
            "position_count": 3,
            "valued_count": 3,
            "unsupported_count": 0,
            "total_portfolio_pv": 10000.0,
            "sensitivity_conventions": {
                "rates_sensitivity": "PV change for a parallel +1bp rate move.",
                "fx_spot_sensitivity": "PV change for a +1% FX spot move.",
                "equity_spot_sensitivity": "PV change for a +1% equity spot move.",
                "vol_sensitivity": "PV change for a +1 vol point move (volatility +0.01).",
            },
            "total_sensitivities": {
                "rates_sensitivity": 12.5,
                "fx_spot_sensitivity": 1200.0,
                "equity_spot_sensitivity": 450.0,
                "vol_sensitivity": 90.0,
            },
            "grouped_sensitivities_by_instrument_type": {
                "fx_forward": {
                    "rates_sensitivity": 10.0,
                    "fx_spot_sensitivity": 1200.0,
                    "equity_spot_sensitivity": 0.0,
                    "vol_sensitivity": 0.0,
                },
                "equity_option": {
                    "rates_sensitivity": 2.5,
                    "fx_spot_sensitivity": 0.0,
                    "equity_spot_sensitivity": 450.0,
                    "vol_sensitivity": 90.0,
                },
            },
            "grouped_sensitivities_by_asset_class": {
                "fx": {
                    "rates_sensitivity": 10.0,
                    "fx_spot_sensitivity": 1200.0,
                    "equity_spot_sensitivity": 0.0,
                    "vol_sensitivity": 0.0,
                },
                "equity": {
                    "rates_sensitivity": 2.5,
                    "fx_spot_sensitivity": 0.0,
                    "equity_spot_sensitivity": 450.0,
                    "vol_sensitivity": 90.0,
                },
            },
            "positions": [
                {
                    "position_id": "fxfwd-1",
                    "instrument_type": "fx_forward",
                    "asset_class": "fx",
                    "quantity": 1.0,
                    "base_pricing_status": "indicative",
                    "status": "valued",
                    "base_pv": 7000.0,
                    "rates_sensitivity": 10.0,
                    "fx_spot_sensitivity": 1200.0,
                    "equity_spot_sensitivity": 0.0,
                    "vol_sensitivity": 0.0,
                    "warnings": ["equity_spot_sensitivity not applicable to fx_forward."],
                },
                {
                    "position_id": "eqopt-1",
                    "instrument_type": "equity_option",
                    "asset_class": "equity",
                    "quantity": 1.0,
                    "base_pricing_status": "indicative",
                    "status": "valued",
                    "base_pv": 3000.0,
                    "rates_sensitivity": 2.5,
                    "fx_spot_sensitivity": 0.0,
                    "equity_spot_sensitivity": 450.0,
                    "vol_sensitivity": 90.0,
                    "warnings": [],
                },
            ],
            "warnings": [],
        }


class PortfolioRiskSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakePortfolioRiskResponse())
    def test_portfolio_risk_page_renders_grouped_and_position_sensitivities(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("Portfolio / Scenario").run()
        app.text_input(key="portfolio_name").set_value("Risk Portfolio")
        app.text_input(key="portfolio_valuation_date").set_value("2026-03-26")

        app.button(key="run_portfolio_risk_btn").click().run()

        self.assertIn("Portfolio Risk Decomposition", [node.value for node in app.subheader])
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Rates sensitivity (+1bp)"], "+12.50")
        self.assertEqual(metrics["FX spot sensitivity (+1%)"], "+1,200.00")
        self.assertEqual(metrics["Equity spot sensitivity (+1%)"], "+450.00")
        self.assertEqual(metrics["Vol sensitivity (+1pt)"], "+90.00")

        rendered_markdown = "\n".join(node.value for node in app.markdown)
        self.assertIn("Sensitivity conventions", rendered_markdown)
        self.assertIn("Grouped sensitivities by instrument_type", rendered_markdown)
        self.assertIn("Grouped sensitivities by asset_class", rendered_markdown)
        self.assertIn("Position-level sensitivities", rendered_markdown)
        self.assertIn("Largest positive fx spot sensitivity contributors", rendered_markdown)
        self.assertIn("Risk warning summary", rendered_markdown)
        self.assertIn("equity_spot_sensitivity not applicable", rendered_markdown)

        download_labels = [button.label for button in app.get("download_button")]
        self.assertIn("Download Risk CSV Summary", download_labels)
        self.assertTrue(mock_post.call_args.args[0].endswith("/portfolio/risk"))


if __name__ == "__main__":
    unittest.main()
