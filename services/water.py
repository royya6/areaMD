<<<<<<< HEAD
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
=======
from datetime import date, timedelta
import math

import requests


WATER_QUALITY_API_URL = (
    "https://environment.data.gov.uk/water-quality/data/observation"
)
REQUEST_TIMEOUT_SECONDS = 15
RADIUS_KM = 10


class WaterQualityResponseError(ValueError):
    """Raised when the Environment Agency response is not usable."""


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("latitude or longitude is invalid")


def get_water_quality(latitude: float, longitude: float) -> dict[str, object]:
    """Return recent EA water observations within ten kilometres."""
    _validate_coordinates(latitude, longitude)
    today = date.today()
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "radius": RADIUS_KM,
        "dateFrom": str(today - timedelta(days=364)),
        "dateTo": str(today - timedelta(days=1)),
        "limit": 250,
    }
    response = requests.post(
        WATER_QUALITY_API_URL,
        params=params,
        headers={"Accept": "application/ld+json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        payload = response.json()
        observations = payload["member"]
        if not isinstance(observations, list):
            raise TypeError
    except (KeyError, TypeError, ValueError) as error:
        raise WaterQualityResponseError(
            "water quality API returned an unexpected response"
        ) from error

    usable = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        sampling_point = observation.get("hasSamplingPoint")
        result = observation.get("hasResult", {})
        property_data = observation.get("observedProperty", {})
        if not isinstance(sampling_point, dict) or not isinstance(result, dict):
            continue
        numeric_value = result.get("numericValue")
        phenomenon_time = observation.get("phenomenonTime")
        if (
            not isinstance(numeric_value, (int, float))
            or isinstance(numeric_value, bool)
            or not math.isfinite(numeric_value)
            or not isinstance(phenomenon_time, str)
        ):
            continue
        usable.append(
            {
                "sampling_point": sampling_point.get("prefLabel"),
                "sampling_point_code": sampling_point.get("notation"),
                "sampling_point_type": (
                    sampling_point.get("samplingPointType", {}).get("prefLabel")
                    if isinstance(sampling_point.get("samplingPointType"), dict)
                    else None
                ),
                "parameter": (
                    property_data.get("prefLabel")
                    if isinstance(property_data, dict)
                    else None
                ),
                "value": numeric_value,
                "unit": observation.get("hasUnit"),
                "sampled_at": phenomenon_time,
            }
        )

    if not usable:
        return {
            "available": False,
            "radius_km": RADIUS_KM,
            "observations": [],
        }
    usable.sort(key=lambda item: item["sampled_at"], reverse=True)
    return {
        "available": True,
        "radius_km": RADIUS_KM,
        "observations": usable[:12],
    }
>>>>>>> 80879e743150af7eda17b3138d54a6666bdc1bf0
