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