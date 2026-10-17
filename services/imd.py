import csv
from functools import lru_cache
from pathlib import Path

IMD_CSV_PATH = (
	Path(__file__).resolve().parents[1]
	/ "static"
	/ "imd"
	/ "imd2019_lsoa.csv"
)
LSOA_CODE_COLUMN = "LSOA code (2011)"
IMD_DECILE_COLUMN = (
	"Index of Multiple Deprivation (IMD) Decile "
	"(where 1 is most deprived 10% of LSOAs)"
)
LIVING_ENVIRONMENT_DECILE_COLUMN = (
	"Living Environment Decile (where 1 is most deprived 10% of LSOAs)"
)
HEALTH_DECILE_COLUMN = (
	"Health Deprivation and Disability Decile "
	"(where 1 is most deprived 10% of LSOAs)"
)
REQUIRED_COLUMNS = (
	LSOA_CODE_COLUMN,
	IMD_DECILE_COLUMN,
	LIVING_ENVIRONMENT_DECILE_COLUMN,
	HEALTH_DECILE_COLUMN,
)


class IMDDataError(ValueError):
	"""Raised when the bundled IMD data has an incompatible format."""


@lru_cache(maxsize=1)
def _load_imd() -> dict[str, dict[str, str]]:
	lookup = {}
	with IMD_CSV_PATH.open(encoding="utf-8-sig", newline="") as csv_file:
		reader = csv.DictReader(csv_file)
		fieldnames = reader.fieldnames or []
		missing_columns = set(REQUIRED_COLUMNS).difference(fieldnames)
		if missing_columns:
			raise IMDDataError("IMD CSV is missing required columns")

		for row in reader:
			lsoa_code = row.get(LSOA_CODE_COLUMN)
			if lsoa_code:
				lookup[lsoa_code.strip()] = row

	return lookup


def _parse_decile(value: str | None) -> int | None:
	if value is None or not value.strip():
		return None
	try:
		return int(value)
	except ValueError:
		return None


def get_imd_data(lsoa_code: str | None) -> dict[str, object]:
	"""Return 2019 LSOA deprivation deciles, or an explicit unavailable state."""
	if not isinstance(lsoa_code, str) or not lsoa_code.strip():
		return {"available": False, "reason": "lsoa_code_missing"}

	try:
		row = _load_imd().get(lsoa_code.strip())
	except FileNotFoundError:
		return {"available": False, "reason": "dataset_missing"}

	if row is None:
		return {"available": False, "reason": "lsoa_not_found"}

	return {
		"available": True,
		"imd_decile": _parse_decile(row.get(IMD_DECILE_COLUMN)),
		"living_env_decile": _parse_decile(
			row.get(LIVING_ENVIRONMENT_DECILE_COLUMN)
		),
		"health_decile": _parse_decile(row.get(HEALTH_DECILE_COLUMN)),
	}
