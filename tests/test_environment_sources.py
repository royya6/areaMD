import unittest
from unittest.mock import Mock, patch

from services.laqn import (
    EARTH_RADIUS_KM,
    LAQNResponseError,
    SITES_API_URL,
    _distance_km,
    get_air_quality,
    nearest_site,
)
from services.planning import (
    PLANNING_API_URL,
    PLANNING_DATASETS,
    PlanningResponseError,
    get_planning_flags,
)


class PlanningFlagsTests(unittest.TestCase):
    @patch("services.planning.requests.get")
    def test_batches_datasets_and_returns_triaged_flags(self, get):
        response = Mock()
        response.json.return_value = {
            "entities": [{"dataset": "green-belt"}, {"dataset": "brownfield-land"}]
        }
        get.return_value = response

        flags = get_planning_flags(51.5, -0.12)

        self.assertTrue(flags["green-belt"])
        self.assertTrue(flags["brownfield-land"])
        self.assertFalse(flags["conservation-area"])
        self.assertEqual(set(flags), set(PLANNING_DATASETS))
        get.assert_called_once()
        args, kwargs = get.call_args
        self.assertEqual(args[0], PLANNING_API_URL)
        self.assertEqual(kwargs["params"].count(("dataset", "green-belt")), 1)
        self.assertEqual(kwargs["params"].count(("dataset", "brownfield-land")), 1)
        self.assertEqual(
            kwargs["params"].count(("dataset", "planning-application")), 1
        )
        self.assertEqual(kwargs["timeout"], 6)

    def test_rejects_invalid_coordinates_without_request(self):
        with patch("services.planning.requests.get") as get:
            with self.assertRaises(ValueError):
                get_planning_flags(float("nan"), -0.12)

        get.assert_not_called()

    @patch("services.planning.requests.get")
    def test_rejects_unexpected_response_shape(self, get):
        response = Mock()
        response.json.return_value = {"entities": None}
        get.return_value = response

        with self.assertRaises(PlanningResponseError):
            get_planning_flags(51.5, -0.12)


class LAQNTests(unittest.TestCase):
    @patch("services.laqn.requests.get")
    def test_accepts_single_site_and_returns_new_normalized_result(self, get):
        site = {
            "@Latitude": "51.4988",
            "@Longitude": "-0.1749",
            "@SiteName": "South Kensington",
            "@SiteType": "Urban Background",
            "@LocalAuthorityName": "Kensington and Chelsea",
        }
        response = Mock()
        response.json.return_value = {"Sites": {"Site": site}}
        get.return_value = response

        result = get_air_quality(51.4988, -0.1749)

        self.assertEqual(
            result,
            {
                "available": True,
                "site_name": "South Kensington",
                "site_type": "Urban Background",
                "distance_km": 0.0,
                "borough": "Kensington and Chelsea",
            },
        )
        self.assertNotIn("_distance_km", site)
        get.assert_called_once_with(SITES_API_URL, timeout=8)

    @patch("services.laqn.requests.get")
    def test_handles_empty_site_list(self, get):
        response = Mock()
        response.json.return_value = {"Sites": {"Site": []}}
        get.return_value = response

        self.assertEqual(get_air_quality(51.5, -0.12), {"available": False})

    @patch("services.laqn.requests.get")
    def test_skips_sites_with_invalid_coordinates(self, get):
        response = Mock()
        response.json.return_value = {
            "Sites": {
                "Site": [
                    {"@Latitude": "invalid", "@Longitude": "0"},
                ]
            }
        }
        get.return_value = response

        self.assertIsNone(nearest_site(51.5, -0.12))

    def test_distance_uses_named_earth_radius(self):
        self.assertGreater(EARTH_RADIUS_KM, 6000)
        self.assertEqual(_distance_km(51.5, -0.12, 51.5, -0.12), 0)

    @patch("services.laqn.requests.get")
    def test_rejects_unexpected_response_shape(self, get):
        response = Mock()
        response.json.return_value = {"Sites": None}
        get.return_value = response

        with self.assertRaises(LAQNResponseError):
            nearest_site(51.5, -0.12)


if __name__ == "__main__":
    unittest.main()