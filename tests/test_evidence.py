import unittest
from datetime import datetime, timezone

from services.evidence import build_environmental_evidence


class BuildEnvironmentalEvidenceTests(unittest.TestCase):
    def test_normalizes_current_profile_without_identifiers_or_health_data(self):
        profile = {
            "postcode": "SW7 2AZ",
            "location": {
                "postcode": "SW7 2AZ",
                "latitude": 51.5,
                "longitude": -0.12,
                "local_authority": " Westminster ",
                "in_london": True,
            },
            "air_quality": {
                "available": True,
                "site_name": "Local monitor",
                "distance_km": 1.2,
            },
            "planning_flags": {
                "flood-risk-zone": False,
                "green-belt": None,
            },
            "deprivation": {
                "available": True,
                "imd_decile": 4,
                "living_env_decile": 3,
                "health_decile": 5,
            },
            "errors": {},
        }

        evidence = build_environmental_evidence(
            [{"address_type": "Home", "profile": profile}],
            generated_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
        )

        serialized = str(evidence)
        self.assertNotIn("SW7 2AZ", serialized)
        self.assertNotIn("51.5", serialized)
        self.assertNotIn("-0.12", serialized)
        self.assertEqual(evidence["addresses"][0]["local_authority"], "Westminster")
        self.assertEqual(evidence["addresses"][0]["search_region"], "London")
        self.assertEqual(
            evidence["search_terms"], ["fire", "pollution", "smoke", "water"]
        )
        observations = evidence["addresses"][0]["evidence"]
        states = {
            (item.get("dataset"), item["state"])
            for item in observations
            if item["topic"] == "planning_dataset_lookup"
        }
        self.assertEqual(
            states,
            {("flood-risk-zone", "no_match_returned"), ("green-belt", "unavailable")},
        )
        nearest_site = next(
            item for item in observations if item["topic"] == "nearest_monitoring_site"
        )
        self.assertEqual(
            nearest_site["reliability_context"]["freshness"],
            "site metadata date is not provided by this client",
        )
        self.assertIn(
            "not an address-level measurement",
            nearest_site["reliability_context"]["limitations"][1],
        )
        deprivation = next(
            item for item in observations if item["topic"] == "area_deprivation_deciles"
        )
        self.assertNotIn("health_decile", deprivation["facts"])
        self.assertEqual(evidence["generated_at"], "2026-10-17T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()