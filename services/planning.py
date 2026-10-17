import math

import requests

PLANNING_API_URL = "https://www.planning.data.gov.uk/entity.json"
PLANNING_DATASETS = (
	"flood-risk-zone",
	"conservation-area",
	"listed-building",
	"green-belt",
	"article-4-direction-area",
)
REQUEST_TIMEOUT_SECONDS = 6
MAX_RESULTS = 100


class PlanningResponseError(ValueError):
	"""Raised when the planning API returns an unexpected response."""


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


def get_planning_flags(latitude: float, longitude: float) -> dict[str, bool]:
	"""Return datasets in which the API lists an entity at the coordinate.

	False means no matching entity was returned; it does not prove the area
	has no planning constraint because dataset coverage varies.
	"""
	_validate_coordinates(latitude, longitude)
	params = [
		("latitude", latitude),
		("longitude", longitude),
		*(("dataset", dataset) for dataset in PLANNING_DATASETS),
		("limit", MAX_RESULTS),
	]
	response = requests.get(
		PLANNING_API_URL,
		params=params,
		timeout=REQUEST_TIMEOUT_SECONDS,
	)
	response.raise_for_status()

	try:
		payload = response.json()
		entities = payload["entities"]
		if not isinstance(entities, list):
			raise TypeError
		if any(not isinstance(entity, dict) for entity in entities):
			raise TypeError
		if any(not isinstance(entity.get("dataset"), str) for entity in entities):
			raise TypeError
	except (KeyError, TypeError, ValueError) as error:
		raise PlanningResponseError(
			"planning API returned an unexpected response"
		) from error

	flags = {dataset: False for dataset in PLANNING_DATASETS}
	for entity in entities:
		dataset = entity["dataset"]
		if dataset in flags:
			flags[dataset] = True

	return flags


if __name__ == "__main__":
	import json

	print(json.dumps(get_planning_flags(51.4988, -0.1749), indent=2))
