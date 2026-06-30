import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakeEquityOptionResponse:
    status_code = 200

    def json(self):
        return {
            "status": "indicative",
            "underlying_name": "ACME",
            "currency": "USD",
            "year_fraction": 0.498630,
            "discount_factor": 0.975376,
            "dividend_discount_factor": 0.990077,
            "forward_price": 101.5076,
            "premium": 5241.37,
            "delta": 481.2241,
            "gamma": 27.441982,
            "vega": 34122.44,
            "pv_currency": "USD",
            "model_source": "black_scholes_merton",
            "request_id": "equity-option-smoke-test",
            "assumptions": ["Smoke-test equity option assumption"],
            "warnings": [],
        }


class EquityOptionPricingSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakeEquityOptionResponse())
    def test_equity_option_page_renders_and_displays_result_metrics(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("European Equity Option").run()

        self.assertEqual(app.title[0].value, "European Equity Option")

        app.text_input(key="eqopt_val_date").set_value("2024-01-01")
        app.text_input(key="eqopt_expiry_date").set_value("2024-07-01")
        app.text_input(key="eqopt_underlying_name").set_value("ACME")
        app.number_input(key="eqopt_quantity_shares").set_value(1_000.0)
        app.number_input(key="eqopt_spot_price").set_value(100.0)
        app.number_input(key="eqopt_strike_price").set_value(105.0)
        app.number_input(key="eqopt_risk_free_rate").set_value(0.05)
        app.number_input(key="eqopt_dividend_yield").set_value(0.02)
        app.number_input(key="eqopt_volatility").set_value(0.25)
        app.text_input(key="eqopt_currency").set_value("USD")
        app.selectbox(key="eqopt_day_count").set_value("ACT_365F")
        app.selectbox(key="eqopt_option_type").set_value("call")
        app.selectbox(key="eqopt_position").set_value("long")

        app.button(key="price_eqoption_btn").click().run()

        self.assertIn("European Equity Option Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Premium (USD)"], "5,241.37")
        self.assertEqual(metrics["Delta"], "481.2241")
        self.assertEqual(metrics["Gamma"], "27.441982")
        self.assertEqual(metrics["Vega"], "34,122.44")
        self.assertEqual(metrics["Year Fraction"], "0.498630")
        self.assertEqual(metrics["Forward Price"], "101.5076")
        self.assertEqual(metrics["Risk-Free Discount Factor"], "0.975376")
        self.assertEqual(metrics["Dividend Discount Factor"], "0.990077")
        self.assertEqual(metrics["Currency"], "USD")
        self.assertEqual(metrics["Model Source"], "black_scholes_merton")
        self.assertEqual(metrics["Underlying"], "ACME")

        expander_labels = [expander.label for expander in app.expander]
        self.assertIn("European Equity Option Assumptions", expander_labels)

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        self.assertTrue(mock_post.call_args.args[0].endswith("/price/equity-option"))

        request_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(request_payload["valuation_date"], "2024-01-01")
        self.assertEqual(request_payload["expiry_date"], "2024-07-01")
        self.assertEqual(request_payload["underlying_name"], "ACME")
        self.assertEqual(request_payload["quantity_shares"], 1_000.0)
        self.assertEqual(request_payload["spot_price"], 100.0)
        self.assertEqual(request_payload["strike_price"], 105.0)
        self.assertEqual(request_payload["risk_free_rate"], 0.05)
        self.assertEqual(request_payload["dividend_yield"], 0.02)
        self.assertEqual(request_payload["volatility"], 0.25)
        self.assertEqual(request_payload["currency"], "USD")
        self.assertEqual(request_payload["day_count"], "ACT_365F")
        self.assertEqual(request_payload["option_type"], "call")
        self.assertEqual(request_payload["position"], "long")


if __name__ == "__main__":
    unittest.main()