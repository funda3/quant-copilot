import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakeBondPricingResponse:
    status_code = 200

    def json(self):
        return {
            "status": "indicative",
            "instrument_type": "bond",
            "clean_price": 952341.83,
            "dirty_price": 952341.83,
            "accrued_interest": 0.0,
            "n_remaining_coupons": 5,
            "request_id": "bond-smoke-test",
            "assumptions": ["Smoke-test bond pricing assumption"],
            "warnings": [],
        }


class BondPricingSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakeBondPricingResponse())
    def test_bond_pricing_page_renders_and_displays_result_metrics(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("Bond Pricing").run()

        self.assertEqual(app.title[0].value, "Bond Pricing")

        app.text_input(key="bond_val_date").set_value("2024-01-01")
        app.text_input(key="bond_issue_date").set_value("2024-01-01")
        app.text_input(key="bond_maturity_date").set_value("2029-01-01")
        app.number_input(key="bond_face_value").set_value(1_000_000.0)
        app.number_input(key="bond_coupon_rate").set_value(0.085)
        app.selectbox(key="bond_coupon_freq").set_value("annual")
        app.selectbox(key="bond_day_count").set_value("ACT_365F")

        app.button(key="price_bond_btn").click().run()

        self.assertIn("Bond Pricing Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Clean Price"], "952,341.83")
        self.assertEqual(metrics["Dirty Price"], "952,341.83")
        self.assertEqual(metrics["Accrued Interest"], "0.00")
        self.assertEqual(metrics["Remaining Coupons"], "5")
        self.assertEqual(metrics["Request ID"], "bond-smoke-test")

        expander_labels = [expander.label for expander in app.expander]
        self.assertIn("Bond Pricing Assumptions", expander_labels)

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        self.assertTrue(mock_post.call_args.args[0].endswith("/price/bond"))

        request_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(request_payload["valuation_date"], "2024-01-01")
        self.assertEqual(request_payload["issue_date"], "2024-01-01")
        self.assertEqual(request_payload["maturity_date"], "2029-01-01")
        self.assertEqual(request_payload["face_value"], 1_000_000.0)
        self.assertEqual(request_payload["coupon_rate"], 0.085)
        self.assertEqual(request_payload["coupon_frequency"], "annual")
        self.assertEqual(request_payload["day_count"], "ACT_365F")


if __name__ == "__main__":
    unittest.main()
