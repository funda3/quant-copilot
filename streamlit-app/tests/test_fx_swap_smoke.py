import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakeFXSwapResponse:
    status_code = 200

    def json(self):
        return {
            "status": "indicative",
            "domestic_currency": "ZAR",
            "foreign_currency": "USD",
            "year_fraction_near": 0.005479,
            "year_fraction_far": 0.498630,
            "domestic_discount_factor_near": 0.999562,
            "domestic_discount_factor_far": 0.961640,
            "near_leg_value_domestic": -19991.23,
            "far_leg_value_domestic": 384655.88,
            "swap_points": 0.3800,
            "present_value_domestic": 364664.65,
            "pv_currency": "ZAR",
            "rate_source": "flat_domestic_discount_rate_input",
            "request_id": "fx-swap-smoke-test",
            "assumptions": ["Smoke-test FX swap assumption"],
            "warnings": [],
        }


class FXSwapPricingSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakeFXSwapResponse())
    def test_fx_swap_page_renders_and_displays_result_metrics(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("FX Swap Pricing").run()

        self.assertEqual(app.title[0].value, "FX Swap Pricing")

        app.text_input(key="fxswap_val_date").set_value("2024-01-01")
        app.text_input(key="fxswap_near_date").set_value("2024-01-03")
        app.text_input(key="fxswap_far_date").set_value("2024-07-01")
        app.number_input(key="fxswap_notional_foreign").set_value(1_000_000.0)
        app.number_input(key="fxswap_spot_rate").set_value(18.25)
        app.number_input(key="fxswap_near_rate").set_value(18.27)
        app.number_input(key="fxswap_far_rate").set_value(18.65)
        app.number_input(key="fxswap_domestic_rate").set_value(0.08)
        app.text_input(key="fxswap_domestic_currency").set_value("ZAR")
        app.text_input(key="fxswap_foreign_currency").set_value("USD")
        app.selectbox(key="fxswap_day_count").set_value("ACT_365F")
        app.selectbox(key="fxswap_position").set_value("long_foreign")

        app.button(key="price_fxswap_btn").click().run()

        self.assertIn("FX Swap Pricing Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Swap Points"], "0.3800")
        self.assertEqual(metrics["PV (ZAR)"], "364,664.65")
        self.assertEqual(metrics["Near Year Fraction"], "0.005479")
        self.assertEqual(metrics["Far Year Fraction"], "0.498630")
        self.assertEqual(metrics["Rate Source"], "flat_domestic_discount_rate_input")
        self.assertEqual(metrics["Near Domestic Discount Factor"], "0.999562")
        self.assertEqual(metrics["Far Domestic Discount Factor"], "0.961640")
        self.assertEqual(metrics["Near Leg Value Domestic"], "-19,991.23")
        self.assertEqual(metrics["Far Leg Value Domestic"], "384,655.88")
        self.assertEqual(metrics["Domestic Currency"], "ZAR")
        self.assertEqual(metrics["Foreign Currency"], "USD")

        expander_labels = [expander.label for expander in app.expander]
        self.assertIn("FX Swap Assumptions", expander_labels)

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        self.assertTrue(mock_post.call_args.args[0].endswith("/price/fx-swap"))

        request_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(request_payload["valuation_date"], "2024-01-01")
        self.assertEqual(request_payload["near_settlement_date"], "2024-01-03")
        self.assertEqual(request_payload["far_settlement_date"], "2024-07-01")
        self.assertEqual(request_payload["notional_foreign"], 1_000_000.0)
        self.assertEqual(request_payload["spot_rate"], 18.25)
        self.assertEqual(request_payload["near_rate"], 18.27)
        self.assertEqual(request_payload["far_rate"], 18.65)
        self.assertEqual(request_payload["domestic_rate"], 0.08)
        self.assertEqual(request_payload["domestic_currency"], "ZAR")
        self.assertEqual(request_payload["foreign_currency"], "USD")
        self.assertEqual(request_payload["day_count"], "ACT_365F")
        self.assertEqual(request_payload["position"], "long_foreign")


if __name__ == "__main__":
    unittest.main()