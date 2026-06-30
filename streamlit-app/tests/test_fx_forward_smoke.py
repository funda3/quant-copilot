import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakeFXForwardResponse:
    status_code = 200

    def json(self):
        return {
            "status": "indicative",
            "domestic_currency": "ZAR",
            "foreign_currency": "USD",
            "year_fraction": 0.498630,
            "domestic_discount_factor": 0.961640,
            "foreign_discount_factor": 0.975679,
            "implied_forward_rate": 18.5163,
            "forward_points": 0.2663,
            "payoff_undiscounted_domestic": -83700.00,
            "present_value_domestic": -80488.27,
            "pv_currency": "ZAR",
            "rate_source": "flat_interest_rate_inputs",
            "request_id": "fx-forward-smoke-test",
            "assumptions": ["Smoke-test FX forward assumption"],
            "warnings": [],
        }


class FXForwardPricingSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakeFXForwardResponse())
    def test_fx_forward_page_renders_and_displays_result_metrics(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("FX Forward Pricing").run()

        self.assertEqual(app.title[0].value, "FX Forward Pricing")

        app.text_input(key="fxfwd_val_date").set_value("2024-01-01")
        app.text_input(key="fxfwd_maturity_date").set_value("2024-07-01")
        app.number_input(key="fxfwd_notional_foreign").set_value(1_000_000.0)
        app.number_input(key="fxfwd_spot_rate").set_value(18.25)
        app.number_input(key="fxfwd_contract_forward_rate").set_value(18.60)
        app.number_input(key="fxfwd_domestic_rate").set_value(0.08)
        app.number_input(key="fxfwd_foreign_rate").set_value(0.05)
        app.text_input(key="fxfwd_domestic_currency").set_value("ZAR")
        app.text_input(key="fxfwd_foreign_currency").set_value("USD")
        app.selectbox(key="fxfwd_day_count").set_value("ACT_365F")
        app.selectbox(key="fxfwd_position").set_value("long_foreign")

        app.button(key="price_fxfwd_btn").click().run()

        self.assertIn("FX Forward Pricing Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Implied Forward"], "18.5163")
        self.assertEqual(metrics["PV (ZAR)"], "-80,488.27")
        self.assertEqual(metrics["Year Fraction"], "0.498630")
        self.assertEqual(metrics["Domestic Discount Factor"], "0.961640")
        self.assertEqual(metrics["Foreign Discount Factor"], "0.975679")
        self.assertEqual(metrics["Forward Points"], "0.2663")
        self.assertEqual(metrics["Payoff Undiscounted"], "-83,700.00")
        self.assertEqual(metrics["Rate Source"], "flat_interest_rate_inputs")
        self.assertEqual(metrics["Domestic Currency"], "ZAR")
        self.assertEqual(metrics["Foreign Currency"], "USD")

        expander_labels = [expander.label for expander in app.expander]
        self.assertIn("FX Forward Assumptions", expander_labels)

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        self.assertTrue(mock_post.call_args.args[0].endswith("/price/fx-forward"))

        request_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(request_payload["valuation_date"], "2024-01-01")
        self.assertEqual(request_payload["maturity_date"], "2024-07-01")
        self.assertEqual(request_payload["notional_foreign"], 1_000_000.0)
        self.assertEqual(request_payload["spot_rate"], 18.25)
        self.assertEqual(request_payload["contract_forward_rate"], 18.60)
        self.assertEqual(request_payload["domestic_rate"], 0.08)
        self.assertEqual(request_payload["foreign_rate"], 0.05)
        self.assertEqual(request_payload["domestic_currency"], "ZAR")
        self.assertEqual(request_payload["foreign_currency"], "USD")
        self.assertEqual(request_payload["day_count"], "ACT_365F")
        self.assertEqual(request_payload["position"], "long_foreign")


if __name__ == "__main__":
    unittest.main()