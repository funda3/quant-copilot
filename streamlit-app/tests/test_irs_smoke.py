import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class _FakeQuoteResponse:
    status_code = 200

    def json(self):
        return {
            "request_id": "irs-smoke-test",
            "raw_prompt": "Pay fixed 8.5% on ZAR 100M 5Y quarterly IRS",
            "extracted_fields": {
                "instrument_type": "irs",
                "direction": "pay",
                "fixed_rate": 0.085,
                "notional": 100_000_000.0,
                "tenor": "5Y",
                "payment_frequency": "quarterly",
                "currency": "ZAR",
            },
            "missing_fields": [],
            "extraction_status": "ready",
            "pricing_attempted": True,
            "price_status": "indicative",
            "price": -17_204_877.02,
            "pv01": 111_353.18,
            "assumptions": ["Smoke-test IRS pricing assumption"],
            "warnings": [],
        }


class IRSPricingSmokeTest(unittest.TestCase):
    @patch("requests.post", return_value=_FakeQuoteResponse())
    def test_irs_pricing_page_renders_and_displays_result_metrics(self, mock_post):
        app = AppTest.from_file("app.py")

        app.run()
        app.radio(key="nav_page").set_value("IRS Pricing").run()

        self.assertEqual(app.title[0].value, "IRS Pricing")

        app.text_area(key="irs_prompt").set_value(
            "Pay fixed 8.5% on ZAR 100M 5Y quarterly IRS"
        )

        app.button(key="run_quote_btn").click().run()

        self.assertIn("Quote Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Extraction"], "ready")
        self.assertEqual(metrics["Price status"], "indicative")
        self.assertEqual(metrics["Price (NPV)"], "-17,204,877.02")
        self.assertEqual(metrics["PV01"], "111,353.18")

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        self.assertTrue(mock_post.call_args.args[0].endswith("/quote"))

        request_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            request_payload["prompt"],
            "Pay fixed 8.5% on ZAR 100M 5Y quarterly IRS",
        )


if __name__ == "__main__":
    unittest.main()
