import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakePortfolioReportingScenarioResponse:
    status_code = 200

    def json(self):
        return {
            "request_id": "portfolio-reporting-smoke",
            "portfolio_name": "Reporting Portfolio",
            "valuation_date": "2026-03-26",
            "status": "partial",
            "position_count": 4,
            "valued_count": 3,
            "unsupported_count": 1,
            "base_portfolio_pv": 10000.0,
            "shocked_portfolio_pv": 10900.0,
            "delta_portfolio_pv": 900.0,
            "grouped_base_pv_by_instrument_type": {
                "fx_forward": 5000.0,
                "equity_option": 4000.0,
                "fra": 1000.0,
            },
            "grouped_shocked_pv_by_instrument_type": {
                "fx_forward": 6200.0,
                "equity_option": 3700.0,
                "fra": 1000.0,
            },
            "grouped_delta_pv_by_instrument_type": {
                "fx_forward": 1200.0,
                "equity_option": -300.0,
                "fra": 0.0,
            },
            "grouped_delta_pv_by_asset_class": {
                "fx": 1200.0,
                "equity": -300.0,
                "rates": 0.0,
            },
            "positions": [
                {
                    "position_id": "fxfwd-1",
                    "instrument_type": "fx_forward",
                    "asset_class": "fx",
                    "quantity": 1.0,
                    "base_pricing_status": "indicative",
                    "shocked_pricing_status": "indicative",
                    "status": "valued",
                    "base_pv": 5000.0,
                    "shocked_pv": 6200.0,
                    "delta_pv": 1200.0,
                    "warnings": [],
                },
                {
                    "position_id": "eqopt-1",
                    "instrument_type": "equity_option",
                    "asset_class": "equity",
                    "quantity": 1.0,
                    "base_pricing_status": "indicative",
                    "shocked_pricing_status": "indicative",
                    "status": "valued",
                    "base_pv": 4000.0,
                    "shocked_pv": 3700.0,
                    "delta_pv": -300.0,
                    "warnings": [],
                },
                {
                    "position_id": "fra-1",
                    "instrument_type": "fra",
                    "asset_class": "rates",
                    "quantity": 1.0,
                    "base_pricing_status": "indicative",
                    "shocked_pricing_status": "indicative",
                    "status": "valued",
                    "base_pv": 1000.0,
                    "shocked_pv": 1000.0,
                    "delta_pv": 0.0,
                    "warnings": [
                        "rates_bps shock ignored for bond/FRA position without curve_inputs."
                    ],
                },
                {
                    "position_id": "bad-1",
                    "instrument_type": "bond",
                    "asset_class": "rates",
                    "quantity": 1.0,
                    "base_pricing_status": "validation_error",
                    "shocked_pricing_status": "validation_error",
                    "status": "unsupported",
                    "base_pv": 0.0,
                    "shocked_pv": 0.0,
                    "delta_pv": 0.0,
                    "warnings": ["Schema validation error at 'face_value': Input should be positive."],
                },
            ],
            "warnings": [],
        }


class PortfolioReportingSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakePortfolioReportingScenarioResponse())
    def test_reporting_depth_blocks_render(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("Portfolio / Scenario").run()
        app.text_input(key="portfolio_name").set_value("Reporting Portfolio")
        app.text_input(key="portfolio_valuation_date").set_value("2026-03-26")

        app.button(key="run_portfolio_scenario_btn").click().run()

        rendered_markdown = "\n".join(node.value for node in app.markdown)
        self.assertIn("Grouped delta by asset class", rendered_markdown)
        self.assertIn("Largest positive contributors", rendered_markdown)
        self.assertIn("Largest negative contributors", rendered_markdown)
        self.assertIn("Warning summary", rendered_markdown)
        self.assertIn("Scenario interpretation", rendered_markdown)
        self.assertIn("fxfwd-1", rendered_markdown)
        self.assertIn("eqopt-1", rendered_markdown)
        self.assertIn("Ignored shocks", rendered_markdown)
        self.assertIn("Unsupported rows", rendered_markdown)
        self.assertIn("unchanged because one or more shocks were ignored", rendered_markdown)

        download_labels = [button.label for button in app.get("download_button")]
        self.assertIn("Download Scenario CSV Summary", download_labels)
        self.assertTrue(mock_post.call_args.args[0].endswith("/portfolio/scenario"))


if __name__ == "__main__":
    unittest.main()
