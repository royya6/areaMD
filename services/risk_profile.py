import requests

from services.imd import IMDDataError, get_imd_data
from services.laqn import LAQNResponseError, get_air_quality
from services.planning import (
    PLANNING_DATASETS,
    PlanningResponseError,
    get_planning_flags,
)
from services.postcodes import PostcodeResponseError, lookup_postcode
from services.water import get_drinking_water_quality


class RiskProfileError(RuntimeError):
    """Raised when an address cannot be resolved into a risk profile."""


def _unavailable_planning_flags() -> dict[str, None]:
    return {dataset: None for dataset in PLANNING_DATASETS}


def get_full_risk_profile(postcode: str) -> dict[str, object]:
    """Return location and environmental context for one UK postcode.

    A postcode lookup failure prevents downstream lookups. Other source
    failures are represented as partial results so report generation can
    continue without claiming unavailable data is absent.
    """
    if not isinstance(postcode, str) or not postcode.strip():
        raise ValueError("postcode must be a non-empty string")

    try:
        location = lookup_postcode(postcode)
    except (requests.RequestException, PostcodeResponseError) as error:
        raise RiskProfileError("postcode_lookup_failed") from error

    latitude = location["latitude"]
    longitude = location["longitude"]
    errors = {}

    try:
        air_quality = get_air_quality(latitude, longitude)
    except (requests.RequestException, LAQNResponseError, ValueError):
        air_quality = {"available": False}
        errors["air_quality"] = "provider_unavailable"

    try:
        planning_flags = get_planning_flags(latitude, longitude)
    except (requests.RequestException, PlanningResponseError, ValueError):
        planning_flags = _unavailable_planning_flags()
        errors["planning"] = "provider_unavailable"

    try:
        deprivation = get_imd_data(location.get("lsoa_code"))
    except (IMDDataError, OSError):
        deprivation = {"available": False, "reason": "lookup_failed"}
        errors["deprivation"] = "lookup_failed"

    drinking_water = get_drinking_water_quality(location["postcode"])

    return {
        "postcode": location["postcode"],
        "location": location,
        "air_quality": air_quality,
        "planning_flags": planning_flags,
        "deprivation": deprivation,
        "drinking_water": drinking_water,
        "errors": errors,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(get_full_risk_profile("SW7 2AZ"), indent=2))