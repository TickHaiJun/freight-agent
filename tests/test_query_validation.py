import unittest

from graph.query_validation import build_origin_clarify_message, validate_rate_slots


class QueryValidationTests(unittest.TestCase):
    def test_same_origin_and_destination_forces_origin_reask(self):
        result = validate_rate_slots(
            {
                "sfg": "lax",
                "mdg": "lax",
                "inputWeight": 600,
                "inputVol": 4,
                "packageType": "散货",
                "hbrq": "2026-06-09",
            }
        )

        self.assertFalse(result["valid"])
        self.assertIsNone(result["normalized_slots"]["sfg"])
        self.assertEqual(result["clarify_slot"], "sfg")
        self.assertEqual(result["clarify_message"], build_origin_clarify_message())
        self.assertIn("sfg", result["missing_slots"])

    def test_destination_code_is_removed_from_multi_origin_list(self):
        result = validate_rate_slots(
            {
                "sfg": "nkg,pvg,lax",
                "mdg": "lax",
                "inputWeight": 890,
                "inputVol": 9,
                "packageType": "托盘",
                "hbrq": "2026-06-09",
            }
        )

        self.assertEqual(result["normalized_slots"]["sfg"], "nkg,pvg")
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
