import math
from urllib.parse import quote

import requests

POSTCODES_BASE_URL = "https://api.postcodes.io/postcodes"
REQUEST_TIMEOUT_SECONDS = 5


class PostcodeResponseError(ValueError):
    """Raised when the postcode API returns an unexpected response."""


def lookup_postcode(postcode: str) -> dict[str, object]:
    """Return normalized location details, including 2011 and 2021 LSOAs."""
    if not isinstance(postcode, str) or not postcode.strip():
        raise ValueError("postcode must be a non-empty string")

    clean_postcode = "".join(postcode.split()).upper()
    response = requests.get(
        f"{POSTCODES_BASE_URL}/{quote(clean_postcode, safe='')}",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        result = response.json()["result"]
        if not isinstance(result, dict):
            raise TypeError
        codes = result["codes"]
        if not isinstance(codes, dict):
            raise TypeError
        latitude = float(result["latitude"])
        longitude = float(result["longitude"])
        lsoa_code = codes.get("lsoa11")
        lsoa_code_2021 = codes.get("lsoa")
        canonical_postcode = result["postcode"]
    except (KeyError, TypeError, ValueError) as error:
        raise PostcodeResponseError(
            "postcode API returned an unexpected response"
        ) from error

    if (
        not isinstance(canonical_postcode, str)
        or not canonical_postcode.strip()
        or isinstance(result["latitude"], bool)
        or isinstance(result["longitude"], bool)
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise PostcodeResponseError("postcode API returned an unexpected response")

    return {
        "postcode": canonical_postcode,
        "latitude": latitude,
        "longitude": longitude,
        "lsoa_code": lsoa_code,
        "lsoa_code_2021": lsoa_code_2021,
        "lsoa_name": result.get("lsoa"),
        "lsoa_name_2011": result.get("lsoa11"),
        "ward": result.get("admin_ward"),
        "local_authority": result.get("admin_district"),
        "in_london": result.get("region") == "London",
    }

if __name__ == "__main__":
    import json

    print(json.dumps(lookup_postcode("SW6 5PG"), indent=2))