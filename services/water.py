import json
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
import requests

# Tap/drinking water: local Thames Water zone snapshot, not surface water.
WATER_QUALITY_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "static" / "water_quality_london.json"
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
    snapshot = _load_snapshot()
    postcodes = snapshot.get("postcodes")
    if not isinstance(postcodes, dict):
        return None
    result = postcodes.get(postcode_key)
    if not isinstance(result, dict):
        return None
    hardness = result.get("hardness_calcium_carbonate_mg_l")
    rating = str(result.get("hardness_rating") or "not specified").title()
    hardness_text = f"{hardness} mg/L as calcium carbonate" if hardness is not None else "not available"
    return {
        **result,
        "available": True,
        "source": snapshot.get("source"),
        "source_url": snapshot.get("source_url"),
        "snapshot_date": snapshot.get("snapshot_date"),
        "summary": (
            f"Thames Water classifies this zone's water hardness as {rating} "
            f"({hardness_text}). Hardness describes mineral content; it is not a drinking-water safety score."
        ),
    }

# Nearby surface water: Environment Agency observations, NOT household tap water.
WATER_QUALITY_API_URL = "https://environment.data.gov.uk/water-quality/data/observation"
REQUEST_TIMEOUT_SECONDS = 15
RADIUS_KM = 5
MAX_PARAMETERS = 8
EXCLUDED_POINT_TYPE_WORDS = ("DISCHARGE", "EFFLUENT", "SEWAGE")


class WaterQualityResponseError(ValueError):
    """Raised when the Environment Agency response is not usable."""


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if (
        isinstance(latitude, bool) or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float))
        or not math.isfinite(latitude) or not math.isfinite(longitude)
        or not -90 <= latitude <= 90 or not -180 <= longitude <= 180
    ):
        raise ValueError("latitude or longitude is invalid")


def _is_water_body(point_type: object) -> bool:
    # Fail closed: unknown point types are not confidently identifiable as water bodies.
    if not isinstance(point_type, str) or not point_type.strip():
        return False
    upper = point_type.upper()
    if any(word in upper for word in EXCLUDED_POINT_TYPE_WORDS):
        return False
    # Require a positive indication of a water body; do not assume unknown types qualify.
    return any(word in upper for word in ("RIVER", "LAKE", "CANAL", "WATER", "STREAM", "COAST", "ESTUARY"))


def get_water_quality(latitude: float, longitude: float) -> dict[str, object]:
    """Return per-parameter aggregates and sample metadata for nearby surface water.

    Averages are descriptive summaries of the observations returned by the API,
    not regulatory assessments or a single overall water-quality score. The API
    result is capped at 250 records, so results may be incomplete.
    """
    _validate_coordinates(latitude, longitude)
    today = date.today()
    params = {
        "latitude": latitude, "longitude": longitude, "radius": RADIUS_KM,
        "dateFrom": str(today - timedelta(days=364)),
        "dateTo": str(today - timedelta(days=1)), "limit": 250,
    }
    response = requests.post(
        WATER_QUALITY_API_URL, params=params,
        headers={"Accept": "application/ld+json"}, timeout=REQUEST_TIMEOUT_SECONDS,
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

    grouped = defaultdict(list)
    point_names = set()
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        sampling_point = observation.get("hasSamplingPoint")
        result = observation.get("hasResult", {})
        property_data = observation.get("observedProperty", {})
        if not isinstance(sampling_point, dict) or not isinstance(result, dict) or not isinstance(property_data, dict):
            continue
        point_type_obj = sampling_point.get("samplingPointType")
        point_type = point_type_obj.get("prefLabel") if isinstance(point_type_obj, dict) else None
        if not _is_water_body(point_type):
            continue
        parameter = property_data.get("prefLabel")
        sampled_at = observation.get("phenomenonTime")
        unit_obj = observation.get("hasUnit")
        unit = unit_obj.get("label") if isinstance(unit_obj, dict) else unit_obj
        value = result.get("numericValue")
        if (
            not isinstance(parameter, str) or not parameter.strip()
            or not isinstance(sampled_at, str)
            or not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            continue
        key = (parameter.strip(), str(unit or "unit not provided"))
        grouped[key].append({
            "sampling_point": sampling_point.get("prefLabel") or "Sampling point not named",
            "value": float(value),
            "sampled_at": sampled_at,
        })
        point_name = sampling_point.get("prefLabel") or sampling_point.get("notation")
        if point_name:
            point_names.add(point_name)

    summaries = []
    for (parameter, unit), rows in sorted(grouped.items(), key=lambda pair: pair[0][0].lower()):
        values = [row["value"] for row in rows]
        latest = max(rows, key=lambda row: row["sampled_at"])
        summaries.append({
            "parameter": parameter,
            "unit": unit,
            "average": round(sum(values) / len(values), 4),
            "reading_count": len(rows),
            "latest_value": latest["value"],
            "latest_sampled_at": latest["sampled_at"],
            "latest_sampling_point": latest["sampling_point"],
            "interpretation": "Descriptive average only; no overall water-quality score assigned.",
        })

    if not summaries:
        return {
            "available": False, "radius_km": RADIUS_KM, "sampling_point_count": 0,
            "observations": [], "summary": "No usable nearby surface-water readings were returned.",
            "overall_score": None,
            "limitations": ["No usable data is not evidence that water quality is good or poor."],
        }
    summaries = summaries[:MAX_PARAMETERS]
    return {
        "available": True,
        "radius_km": RADIUS_KM,
        "sampling_point_count": len(point_names),
        "observations": summaries,
        "overall_score": None,
        "summary": (
            f"Returned data includes {sum(item['reading_count'] for item in summaries)} readings "
            f"across {len(summaries)} parameters and {len(point_names)} named sampling points. "
            "Parameter averages are descriptive only; no validated overall score is available."
        ),
        "limitations": [
            "Results are limited to up to 250 API records from the prior 364 days.",
            "Averages may combine dates and sampling points; they are not a formal ecological assessment.",
            "This data describes surface water and does not measure household drinking water.",
            "Unknown sampling-point types are excluded because they cannot be confidently classified.",
        ],
    }
