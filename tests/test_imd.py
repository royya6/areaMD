import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.imd import IMDDataError, _load_imd, get_imd_data


IMD_HEADERS = (
    "LSOA code (2011)",
    "Index of Multiple Deprivation (IMD) Decile "
    "(where 1 is most deprived 10% of LSOAs)",
    "Living Environment Decile (where 1 is most deprived 10% of LSOAs)",
    "Health Deprivation and Disability Decile "
    "(where 1 is most deprived 10% of LSOAs)",
)


class GetImdDataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.temp_dir.name) / "imd.csv"
        _load_imd.cache_clear()

    def tearDown(self):
        _load_imd.cache_clear()
        self.temp_dir.cleanup()

    def write_csv(self, header=IMD_HEADERS, row=None):
        values = row or ("E01000001", "3", "2", "4")
        self.csv_path.write_text(
            ",".join(header) + "\n" + ",".join(values) + "\n",
            encoding="utf-8",
        )

    def test_returns_numeric_deciles_for_lsoa(self):
        self.write_csv()

        with patch("services.imd.IMD_CSV_PATH", self.csv_path):
            result = get_imd_data(" E01000001 ")

        self.assertEqual(
            result,
            {
                "available": True,
                "imd_decile": 3,
                "living_env_decile": 2,
                "health_decile": 4,
            },
        )

    def test_reports_missing_dataset(self):
        with patch("services.imd.IMD_CSV_PATH", self.csv_path):
            result = get_imd_data("E01000001")

        self.assertEqual(
            result, {"available": False, "reason": "dataset_missing"}
        )

    def test_reports_missing_lsoa(self):
        self.write_csv()

        with patch("services.imd.IMD_CSV_PATH", self.csv_path):
            result = get_imd_data("E01099999")

        self.assertEqual(
            result, {"available": False, "reason": "lsoa_not_found"}
        )

    def test_rejects_csv_with_incompatible_headers(self):
        self.write_csv(header=("LSOA", "Decile"), row=("E01000001", "3"))

        with patch("services.imd.IMD_CSV_PATH", self.csv_path):
            with self.assertRaises(IMDDataError):
                get_imd_data("E01000001")


if __name__ == "__main__":
    unittest.main()