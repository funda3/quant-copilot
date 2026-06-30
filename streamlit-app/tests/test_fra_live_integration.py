import unittest

import pytest
import requests
from streamlit.testing.v1 import AppTest


BACKEND = "http://127.0.0.1:8001"


def _backend_is_up():
    try:
        r = requests.get("http://127.0.0.1:8001/healthz", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _backend_is_up(),
    reason="Live backend not available — skipping integration test"
)


class FRALiveIntegrationTest(unittest.TestCase):
    def test_fra_pricing_page_round_trips_against_live_backend(self):
        health_response = requests.get(f"{BACKEND}/healthz", timeout=3)
        self.assertEqual(
            health_response.status_code,
            200,
            "Live FRA integration proof requires a running backend at http://127.0.0.1:8001.",
        )

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

        app.button(key="price_fra_btn").click().run()

        self.assertIn("FRA Pricing Result", [node.value for node in app.subheader])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Status"], "indicative")
        self.assertEqual(metrics["Curve Source"], "flat_fallback")
        self.assertTrue(metrics["Forward Rate"].endswith("%"))
        self.assertGreater(float(metrics["Year Fraction"]), 0.0)
        self.assertGreater(float(metrics["Discount Factor to Payment"]), 0.0)
        self.assertLessEqual(float(metrics["Discount Factor to Payment"]), 1.0)
        self.assertNotEqual(metrics["PV"], "0.00")
        self.assertTrue(metrics["Request ID"])

        expander_labels = [expander.label for expander in app.expander]
        self.assertIn("FRA Assumptions", expander_labels)


if __name__ == "__main__":
    unittest.main()