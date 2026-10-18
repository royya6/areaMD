import json
import re
from functools import lru_cache
from pathlib import Path


WATER_QUALITY_DATA_PATH = (
	Path(__file__).resolve().parent.parent
	/ "static"
	/ "water_quality_london.json"
)


@lru_cache(maxsize=1)
def _load_snapshot() -> dict[str, object]:
	try:
		return json.loads(WATER_QUALITY_DATA_PATH.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}


def get_drinking_water_quality(postcode: str) -> dict[str, object] | None:
	"""Return a locally snapshotted Thames Water zone result for an exact postcode."""
	if not isinstance(postcode, str):
		return None

	postcode_key = re.sub(r"[^A-Z0-9]", "", postcode.upper())
	postcodes = _load_snapshot().get("postcodes")
	if not isinstance(postcodes, dict):
		return None

	result = postcodes.get(postcode_key)
	if not isinstance(result, dict):
		return None

	return {
		**result,
		"available": True,
		"source": _load_snapshot().get("source"),
		"source_url": _load_snapshot().get("source_url"),
		"snapshot_date": _load_snapshot().get("snapshot_date"),
		"summary": (
			f"Thames Water classifies this zone's water hardness as "
			f"{str(result.get('hardness_rating', '')).title()} at "
			f"{result.get('hardness_calcium_carbonate_mg_l')} mg/L as calcium carbonate. "
			"Hardness describes mineral content; it is not a drinking-water safety score."
		),
	}