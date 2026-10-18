import unittest

from services.water import get_drinking_water_quality


class DrinkingWaterSnapshotTests(unittest.TestCase):
	def test_lookup_normalizes_postcode_and_returns_source_values(self):
		result = get_drinking_water_quality("sw1a 2aa")

		self.assertIsNotNone(result)
		self.assertEqual(result["zone_name"], "Parliament")
		self.assertEqual(result["hardness_calcium_carbonate_mg_l"], 264)
		self.assertEqual(result["hardness_rating"], "HARD")
		self.assertEqual(result["data_year"], 2025)
		self.assertEqual(result["fluoride_mg_l"], 0.15)

		whitechapel = get_drinking_water_quality("E1 6AN")
		self.assertEqual(
			whitechapel["regulated_parameters"]["Nitrate"]["mean"], 31.0
		)
		self.assertEqual(
			whitechapel["regulated_parameters"]["Lead"]["samples_above_limit"], 0
		)
		self.assertNotIn("THM", whitechapel["regulated_parameters"])

	def test_returns_none_when_postcode_is_not_in_local_snapshot(self):
		self.assertIsNone(get_drinking_water_quality("N1 1AA"))

	def test_returns_none_for_non_string_postcode(self):
		self.assertIsNone(get_drinking_water_quality(None))


if __name__ == "__main__":
	unittest.main()