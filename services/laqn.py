import math
from datetime import date, timedelta

import requests

SITES_API_URL = (
	"https://api.erg.ic.ac.uk/AirQuality/Information/MonitoringSites/"
	"GroupName=London/Json"
)
EARTH_RADIUS_KM = 6371
REQUEST_TIMEOUT_SECONDS = 8
MEASUREMENT_TIMEOUT_SECONDS = 12
MEASUREMENT_LOOKBACK_OFFSETS = (0, 30, 90, 180, 365)


class LAQNResponseError(ValueError):
	"""Raised when the LAQN API returns an unexpected response."""


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


def _distance_km(
	latitude_1: float,
	longitude_1: float,
	latitude_2: float,
	longitude_2: float,
) -> float:
	latitude_delta = math.radians(latitude_2 - latitude_1)
	longitude_delta = math.radians(longitude_2 - longitude_1)
	haversine = (
		math.sin(latitude_delta / 2) ** 2
		+ math.cos(math.radians(latitude_1))
		* math.cos(math.radians(latitude_2))
		* math.sin(longitude_delta / 2) ** 2
	)
	central_angle = 2 * math.asin(math.sqrt(min(1.0, haversine)))
	return EARTH_RADIUS_KM * central_angle


def nearest_site(latitude: float, longitude: float) -> dict[str, object] | None:
	"""Return normalized details for the nearest London monitoring site."""
	_validate_coordinates(latitude, longitude)
	response = requests.get(SITES_API_URL, timeout=REQUEST_TIMEOUT_SECONDS)
	response.raise_for_status()

	try:
		payload = response.json()
		sites = payload["Sites"]["Site"]
	except (KeyError, TypeError, ValueError) as error:
		raise LAQNResponseError("LAQN API returned an unexpected response") from error

	if sites is None:
		return None
	if isinstance(sites, dict):
		sites = [sites]
	if not isinstance(sites, list) or any(not isinstance(site, dict) for site in sites):
		raise LAQNResponseError("LAQN API returned an unexpected response")

	closest_site = None
	closest_distance = math.inf
	for site in sites:
		if site.get("@DateClosed"):
			continue
		try:
			site_latitude = float(site["@Latitude"])
			site_longitude = float(site["@Longitude"])
		except (KeyError, TypeError, ValueError):
			continue
		if (
			not math.isfinite(site_latitude)
			or not math.isfinite(site_longitude)
			or not -90 <= site_latitude <= 90
			or not -180 <= site_longitude <= 180
		):
			continue

		distance = _distance_km(
			latitude,
			longitude,
			site_latitude,
			site_longitude,
		)
		if distance < closest_distance:
			closest_site = site
			closest_distance = distance

	if closest_site is None:
		return None

	result = {
		"site_name": closest_site.get("@SiteName"),
		"site_type": closest_site.get("@SiteType"),
		"distance_km": round(closest_distance, 2),
		"borough": closest_site.get("@LocalAuthorityName"),
	}
	if closest_site.get("@SiteCode"):
		result["site_code"] = closest_site["@SiteCode"]
	return result


def _latest_measurements(site_code: str) -> dict[str, object]:
	"""Return the latest numeric readings available for an open LAQN site."""
	today = date.today()
	for offset in MEASUREMENT_LOOKBACK_OFFSETS:
		start = today - timedelta(days=offset + 2)
		end = today - timedelta(days=offset)
		url = (
			"https://api.erg.ic.ac.uk/AirQuality/Data/Site/"
			f"SiteCode={site_code}/StartDate={start}/EndDate={end}/Json"
		)
		response = requests.get(url, timeout=MEASUREMENT_TIMEOUT_SECONDS)
		response.raise_for_status()
		try:
			data = response.json()["AirQualityData"]["Data"]
			if isinstance(data, dict):
				data = [data]
			if not isinstance(data, list) or any(
				not isinstance(item, dict) for item in data
			):
				raise TypeError
		except (KeyError, TypeError, ValueError) as error:
			raise LAQNResponseError(
				"LAQN measurements API returned an unexpected response"
			) from error

		latest = {}
		for item in data:
			species = item.get("@SpeciesCode")
			value = item.get("@Value")
			measured_at = item.get("@MeasurementDateGMT")
			if not isinstance(species, str) or not isinstance(measured_at, str):
				continue
			try:
				numeric_value = float(value)
			except (TypeError, ValueError):
				continue
			if not math.isfinite(numeric_value):
				continue
			previous = latest.get(species)
			if previous is None or measured_at > previous["measured_at"]:
				latest[species] = {
					"value": numeric_value,
					"measured_at": measured_at,
				}
		if latest:
			return {
				"measurements": latest,
				"measurement_window": {
					"from": str(start),
					"to": str(end),
				},
			}

	return {"measurements": {}, "measurement_window": None}


def get_air_quality(latitude: float, longitude: float) -> dict[str, object]:
	"""Return nearest open-site metadata and its latest numeric readings."""
	site = nearest_site(latitude, longitude)
	if site is None:
		return {"available": False}
	result = {"available": True, **site}
	site_code = site.get("site_code")
	if not isinstance(site_code, str) or not site_code:
		return result
	try:
		result.update(_latest_measurements(site_code))
	except (requests.RequestException, LAQNResponseError):
		return {
			**result,
			"measurements": {},
			"measurement_window": None,
			"measurements_available": False,
		}
	result["measurements_available"] = bool(result["measurements"])
	return result


if __name__ == "__main__":
	import json

	print(json.dumps(get_air_quality(51.4988, -0.1749), indent=2))
