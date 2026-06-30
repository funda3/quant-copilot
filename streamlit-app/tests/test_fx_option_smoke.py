import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakeFXOptionResponse:
    status_code = 200

    def json(self):
        return {
            "status": "indicative",
            "domestic_currency": "ZAR",
            "foreign_currency": "USD",
            "year_fraction": 0.498630,
            "settlement_year_fraction": 0.498630,
            "domestic_discount_factor": 0.960900,
            "foreign_discount_factor": 0.975376,
            "forward_rate": 18.5250,
            "premium_domestic": 805231.44,
            "premium_foreign": 44122.2707,
            "delta": 593221.1054,
            "gamma": 124321.553211,
            "vega": 3712458.22,
            "pv_currency": "ZAR",
            "model_source": "garman_kohlhagen",
            "request_id": "fx-option-smoke-test",
            "assumptions": ["Smoke-test FX option assumption"],
            "warnings": [],
        }


class FXOptionPricingSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakeFXOptionResponse())
    def test_fx_option_page_renders_and_displays_result_metrics(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("European FX Option").run()

        self.assertEqual(app.title[0].value, "European FX Option")

        app.text_input(key="fxopt_val_date").set_value("2024-01-01")
        app.text_input(key="fxopt_expiry_date").set_value("2024-07-01")
        app.text_input(key="fxopt_settlement_date").set_value("2024-07-01")
        app.number_input(key="fxopt_notional_foreign").set_value(1_000_000.0)
        app.number_input(key="fxopt_spot_rate").set_value(18.25)
        app.number_input(key="fxopt_strike_rate").set_value(18.40)
        app.number_input(key="fxopt_domestic_rate").set_value(0.08)
        app.number_input(key="fxopt_foreign_rate").set_value(0.05)
        app.number_input(key="fxopt_volatility").set_value(0.18)
        app.text_input(key="fxopt_domestic_currency").set_value("ZAR")
        app.text_input(key="fxopt_foreign_currency").set_value("USD")
        app.selectbox(key="fxopt_day_count").set_value("ACT_365F")
        app.selectbox(key="fxopt_option_type").set_value("call")
        app.selectbox(key="fxopt_position").set_value("long")

        app.button(key="price_fxoption_btn").click().run()

        self.assertIn("European FX Option Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Premium (ZAR)"], "805,231.44")
        self.assertEqual(metrics["Premium (Foreign)"], "44,122.2707")
        self.assertEqual(metrics["Delta"], "593,221.1054")
        self.assertEqual(metrics["Gamma"], "124,321.553211")
        self.assertEqual(metrics["Vega"], "3,712,458.22")
        self.assertEqual(metrics["Expiry Year Fraction"], "0.498630")
        self.assertEqual(metrics["Settlement Year Fraction"], "0.498630")
        self.assertEqual(metrics["Forward Rate"], "18.5250")
        self.assertEqual(metrics["Domestic Discount Factor"], "0.960900")
        self.assertEqual(metrics["Foreign Discount Factor"], "0.975376")
        self.assertEqual(metrics["Model Source"], "garman_kohlhagen")
        self.assertEqual(metrics["Domestic Currency"], "ZAR")
        self.assertEqual(metrics["Foreign Currency"], "USD")

        expander_labels = [expander.label for expander in app.expander]
        self.assertIn("European FX Option Assumptions", expander_labels)

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        self.assertTrue(mock_post.call_args.args[0].endswith("/price/fx-option"))

        request_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(request_payload["valuation_date"], "2024-01-01")
        self.assertEqual(request_payload["expiry_date"], "2024-07-01")
        self.assertEqual(request_payload["settlement_date"], "2024-07-01")
        self.assertEqual(request_payload["notional_foreign"], 1_000_000.0)
        self.assertEqual(request_payload["spot_rate"], 18.25)
        self.assertEqual(request_payload["strike_rate"], 18.40)
        self.assertEqual(request_payload["domestic_rate"], 0.08)
        self.assertEqual(request_payload["foreign_rate"], 0.05)
        self.assertEqual(request_payload["volatility"], 0.18)
        self.assertEqual(request_payload["domestic_currency"], "ZAR")
        self.assertEqual(request_payload["foreign_currency"], "USD")
        self.assertEqual(request_payload["day_count"], "ACT_365F")
        self.assertEqual(request_payload["option_type"], "call")
        self.assertEqual(request_payload["position"], "long")


if __name__ == "__main__":
    unittest.main()