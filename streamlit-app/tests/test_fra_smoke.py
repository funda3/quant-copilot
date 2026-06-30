import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakeFRAResponse:
    status_code = 200

    def json(self):
        return {
            "status": "indicative",
            "forward_rate": 0.0812,
            "pv": 1234.56,
            "year_fraction": 0.252055,
            "discount_factor_to_payment": 0.960123,
            "payoff_undiscounted": 1285.33,
            "curve_source": "flat_fallback",
            "request_id": "fra-smoke-test",
            "assumptions": ["Smoke-test FRA assumption"],
            "warnings": [],
        }


class _FakeBootstrappedFRAResponse:
    status_code = 200

    def json(self):
        return {
            "status": "indicative",
            "forward_rate": 0.0821,
            "pv": 2345.67,
            "year_fraction": 0.252055,
            "discount_factor_to_payment": 0.958321,
            "payoff_undiscounted": 2447.89,
            "curve_source": "bootstrapped_mixed_curve",
            "request_id": "fra-boot-smoke-test",
            "assumptions": ["Bootstrapped smoke-test FRA assumption"],
            "warnings": [],
        }


class FRAPricingSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakeFRAResponse())
    def test_fra_pricing_page_renders_and_displays_result_metrics(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("FRA Pricing").run()

        self.assertEqual(app.title[0].value, "FRA Pricing")

        app.text_input(key="fra_val_date").set_value("2024-01-01")
        app.text_input(key="fra_start_date").set_value("2024-07-01")
        app.text_input(key="fra_end_date").set_value("2025-01-01")
        app.number_input(key="fra_notional").set_value(1_000_000.0)
        app.number_input(key="fra_contract_rate").set_value(0.08)
        app.selectbox(key="fra_day_count").set_value("ACT_365F")
        app.selectbox(key="fra_position").set_value("payer")

        app.button(key="price_fra_btn").click().run()

        self.assertIn("FRA Pricing Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Forward Rate"], "8.1200%")
        self.assertEqual(metrics["Year Fraction"], "0.252055")
        self.assertEqual(metrics["Discount Factor to Payment"], "0.960123")
        self.assertEqual(metrics["Payoff Undiscounted"], "1,285.33")
        self.assertEqual(metrics["PV"], "1,234.56")
        self.assertEqual(metrics["Curve Source"], "flat_fallback")

        expander_labels = [expander.label for expander in app.expander]
        self.assertIn("FRA Assumptions", expander_labels)

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        self.assertTrue(mock_post.call_args.args[0].endswith("/price/fra"))

        request_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(request_payload["valuation_date"], "2024-01-01")
        self.assertEqual(request_payload["start_date"], "2024-07-01")
        self.assertEqual(request_payload["end_date"], "2025-01-01")
        self.assertEqual(request_payload["notional"], 1_000_000.0)
        self.assertEqual(request_payload["contract_rate"], 0.08)
        self.assertEqual(request_payload["day_count"], "ACT_365F")
        self.assertEqual(request_payload["position"], "payer")
        self.assertNotIn("curve_inputs", request_payload)

    @patch("requests.post", return_value=_FakeBootstrappedFRAResponse())
    def test_fra_bootstrapped_pricing_branch_sends_curve_payload_and_renders_result(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("FRA Pricing").run()

        app.text_input(key="fra_val_date").set_value("2024-01-01")
        app.text_input(key="fra_start_date").set_value("2024-07-01")
        app.text_input(key="fra_end_date").set_value("2025-01-01")
        app.number_input(key="fra_notional").set_value(1_000_000.0)
        app.number_input(key="fra_contract_rate").set_value(0.08)
        app.selectbox(key="fra_day_count").set_value("ACT_365F")
        app.selectbox(key="fra_position").set_value("payer")

        app.text_input(key="fra_curve_val_date").set_value("2024-01-01")
        app.selectbox(key="fra_curve_freq").set_value("annual")
        app.selectbox(key="fra_curve_day_count").set_value("ACT_365F")
        app.text_area(key="fra_curve_deposits_text").set_value("1M 0.078\n3M 0.079\n6M 0.080")
        app.text_area(key="fra_curve_fras_text").set_value("6x9 0.081\n9x12 0.0815")
        app.text_area(key="fra_curve_swaps_text").set_value("2Y 0.082\n3Y 0.083\n5Y 0.085")
        app.checkbox(key="fra_curve_use_curve").set_value(True)

        app.button(key="price_fra_btn").click().run()

        self.assertIn("FRA Pricing Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Curve Source"], "bootstrapped_mixed_curve")
        self.assertIn("Forward Rate", metrics)
        self.assertIn("Year Fraction", metrics)
        self.assertIn("Discount Factor to Payment", metrics)
        self.assertIn("Payoff Undiscounted", metrics)
        self.assertIn("PV", metrics)

        expander_labels = [expander.label for expander in app.expander]
        self.assertIn("FRA Assumptions", expander_labels)

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        self.assertTrue(mock_post.call_args.args[0].endswith("/price/fra"))

        request_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(request_payload["valuation_date"], "2024-01-01")
        self.assertEqual(request_payload["start_date"], "2024-07-01")
        self.assertEqual(request_payload["end_date"], "2025-01-01")
        self.assertEqual(request_payload["notional"], 1_000_000.0)
        self.assertEqual(request_payload["contract_rate"], 0.08)
        self.assertEqual(request_payload["day_count"], "ACT_365F")
        self.assertEqual(request_payload["position"], "payer")

        self.assertIn("curve_inputs", request_payload)
        self.assertEqual(
            request_payload["curve_inputs"],
            {
                "valuation_date": "2024-01-01",
                "payment_frequency": "annual",
                "day_count": "ACT_365F",
                "deposits": [
                    {"tenor_months": 1, "rate": 0.078},
                    {"tenor_months": 3, "rate": 0.079},
                    {"tenor_months": 6, "rate": 0.08},
                ],
                "fras": [
                    {"start_months": 6, "end_months": 9, "rate": 0.081},
                    {"start_months": 9, "end_months": 12, "rate": 0.0815},
                ],
                "swaps": [
                    {"tenor_years": 2, "par_rate": 0.082},
                    {"tenor_years": 3, "par_rate": 0.083},
                    {"tenor_years": 5, "par_rate": 0.085},
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()