import unittest
from unittest.mock import Mock, patch

from services.postcodes import (
    POSTCODES_BASE_URL,
    PostcodeResponseError,
    lookup_postcode,
)


class LookupPostcodeTests(unittest.TestCase):
    @patch("services.postcodes.requests.get")
    def test_returns_normalized_location(self, get):
        response = Mock()
        response.json.return_value = {
            "result": {
                "postcode": "SW7 2AZ",
                "latitude": 51.4988,
                "longitude": -0.1749,
                "codes": {"lsoa": "E01099999", "lsoa11": "E01004736"},
                "lsoa": "Knightsbridge and Belgravia",
                "admin_ward": "Knightsbridge and Belgravia",
                "admin_district": "Kensington and Chelsea",
                "region": "London",
            }
        }
        get.return_value = response

        location = lookup_postcode(" sw7  2az ")

        self.assertEqual(location["postcode"], "SW7 2AZ")
        self.assertEqual(location["latitude"], 51.4988)
        self.assertEqual(location["longitude"], -0.1749)
        self.assertEqual(location["lsoa_code"], "E01004736")
        self.assertEqual(location["lsoa_code_2021"], "E01099999")
        self.assertTrue(location["in_london"])
        get.assert_called_once_with(
            f"{POSTCODES_BASE_URL}/SW72AZ", timeout=5
        )
        response.raise_for_status.assert_called_once_with()

    @patch("services.postcodes.requests.get")
    def test_rejects_empty_postcode_without_request(self, get):
        with self.assertRaises(ValueError):
            lookup_postcode("   ")

        get.assert_not_called()

    @patch("services.postcodes.requests.get")
    def test_rejects_unexpected_response_shape(self, get):
        response = Mock()
        response.json.return_value = {"result": None}
        get.return_value = response

        with self.assertRaises(PostcodeResponseError):
            lookup_postcode("SW7 2AZ")

    @patch("services.postcodes.requests.get")
    def test_rejects_non_finite_coordinates(self, get):
        response = Mock()
        response.json.return_value = {
            "result": {
                "postcode": "SW7 2AZ",
                "latitude": float("nan"),
                "longitude": -0.1749,
                "codes": {"lsoa": "E01004736"},
            }
        }
        get.return_value = response

        with self.assertRaises(PostcodeResponseError):
            lookup_postcode("SW7 2AZ")


if __name__ == "__main__":
    unittest.main()