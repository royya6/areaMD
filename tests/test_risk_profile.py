import json
import unittest
from unittest.mock import patch

import requests

from services.planning import PLANNING_DATASETS
from services.risk_profile import RiskProfileError, get_full_risk_profile


LOCATION = {
    "postcode": "SW7 2AZ",
    "latitude": 51.4988,
    "longitude": -0.1749,
    "lsoa_code": "E01004736",
    "lsoa_name": "Knightsbridge and Belgravia",
    "ward": "Knightsbridge and Belgravia",
    "local_authority": "Kensington and Chelsea",
    "in_london": True,
}


class GetFullRiskProfileTests(unittest.TestCase):
    @patch("services.risk_profile.get_imd_data")
    @patch("services.risk_profile.get_planning_flags")
    @patch("services.risk_profile.get_air_quality")
    @patch("services.risk_profile.lookup_postcode")
    def test_returns_json_serializable_profile(
        self, lookup_postcode, get_air_quality, get_planning_flags, get_imd_data
    ):
        lookup_postcode.return_value = LOCATION
        get_air_quality.return_value = {"available": False}
        get_planning_flags.return_value = {
            dataset: False for dataset in PLANNING_DATASETS
        }
        get_imd_data.return_value = {
            "available": True,
            "imd_decile": 3,
            "living_env_decile": 2,
            "health_decile": 4,
        }

        profile = get_full_risk_profile("SW7 2AZ")

        self.assertEqual(profile["postcode"], "SW7 2AZ")
        self.assertEqual(profile["location"], LOCATION)
        self.assertEqual(profile["errors"], {})
        self.assertEqual(json.loads(json.dumps(profile)), profile)
        get_air_quality.assert_called_once_with(51.4988, -0.1749)
        get_planning_flags.assert_called_once_with(51.4988, -0.1749)
        get_imd_data.assert_called_once_with("E01004736")

    @patch("services.risk_profile.get_imd_data", side_effect=OSError)
    @patch(
        "services.risk_profile.get_planning_flags",
        side_effect=requests.Timeout,
    )
    @patch(
        "services.risk_profile.get_air_quality",
        side_effect=requests.ConnectionError,
    )
    @patch("services.risk_profile.lookup_postcode", return_value=LOCATION)
    def test_retains_partial_results_on_source_failures(
        self, lookup_postcode, get_air_quality, get_planning_flags, get_imd_data
    ):
        profile = get_full_risk_profile("SW7 2AZ")

        self.assertEqual(profile["air_quality"], {"available": False})
        self.assertEqual(
            profile["planning_flags"],
            {dataset: None for dataset in PLANNING_DATASETS},
        )
        self.assertEqual(
            profile["deprivation"],
            {"available": False, "reason": "lookup_failed"},
        )
        self.assertEqual(
            profile["errors"],
            {
                "air_quality": "provider_unavailable",
                "planning": "provider_unavailable",
                "deprivation": "lookup_failed",
            },
        )
        json.dumps(profile)

    @patch(
        "services.risk_profile.lookup_postcode",
        side_effect=requests.Timeout,
    )
    def test_raises_stable_error_when_postcode_lookup_fails(self, lookup_postcode):
        with self.assertRaisesRegex(RiskProfileError, "postcode_lookup_failed"):
            get_full_risk_profile("SW7 2AZ")

    @patch("services.risk_profile.lookup_postcode")
    def test_does_not_call_lookup_for_empty_postcode(self, lookup_postcode):
        with self.assertRaises(ValueError):
            get_full_risk_profile("  ")

        lookup_postcode.assert_not_called()


if __name__ == "__main__":
    unittest.main()