from datetime import datetime, timezone

BASE_SEARCH_TERMS = ("fire", "smoke", "pollution", "water")
PLANNING_SOURCE = "Planning Data platform"
IMD_SOURCE = "English Indices of Deprivation 2019"
LAQN_SOURCE = "London Air Quality Network"


def _availability_state(value: object) -> str:
    if value is True:
        return "listed"
    if value is False:
        return "no_match_returned"
    return "unavailable"


def _derive_search_terms(address_profiles: list[dict[str, object]]) -> list[str]:
    terms = set(BASE_SEARCH_TERMS)
    for item in address_profiles:
        profile = item.get("profile", {})
        if not isinstance(profile, dict):
            continue
        planning_flags = profile.get("planning_flags", {})
        if (
            isinstance(planning_flags, dict)
            and planning_flags.get("flood-risk-zone") is True
        ):
            terms.add("flooding")
    return sorted(terms)


def build_environmental_evidence(
    address_profiles: list[dict[str, object]],
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """Normalize profiles into environmental evidence without patient data."""
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    elif generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    addresses = []
    for item in address_profiles:
        profile = item.get("profile", {})
        if not isinstance(profile, dict):
            continue

        location = profile.get("location", {})
        if not isinstance(location, dict):
            location = {}
        local_authority = location.get("local_authority")
        local_authority = (
            local_authority.strip()[:100]
            if isinstance(local_authority, str)
            else None
        )
        search_region = (
            "London"
            if location.get("in_london") is True
            else None
        )
        address_type = item.get("address_type")
        if not isinstance(address_type, str):
            address_type = "Address"
        address_type = address_type.strip()[:40] or "Address"

        evidence = []
        air_quality = profile.get("air_quality", {})
        if isinstance(air_quality, dict) and air_quality.get("available") is True:
            facts = {
                key: air_quality[key]
                for key in ("site_name", "site_type", "distance_km", "borough")
                if air_quality.get(key) is not None
            }
            evidence.append(
                {
                    "topic": "nearest_monitoring_site",
                    "state": "available",
                    "facts": facts,
                    "source": LAQN_SOURCE,
                    "reliability_context": {
                        "source_authority": "London Air Quality Network",
                        "freshness": "site metadata date is not provided by this client",
                        "geographic_scope": "nearest monitoring site, not the address",
                        "directness": "site metadata only; no pollutant measurement",
                        "coverage": "London monitoring network sites",
                        "limitations": [
                            "Site metadata only; no pollutant measurements are provided.",
                            "Nearest site is not an address-level measurement.",
                        ],
                    },
                }
            )
        else:
            evidence.append(
                {
                    "topic": "air_quality_monitoring_site",
                    "state": "unavailable",
                    "facts": {},
                    "source": LAQN_SOURCE,
                    "reliability_context": {
                        "source_authority": "London Air Quality Network",
                        "freshness": "not available",
                        "geographic_scope": "London monitoring network",
                        "directness": "not available",
                        "coverage": "no site metadata returned",
                        "limitations": ["No site metadata was returned."],
                    },
                }
            )

        planning_flags = profile.get("planning_flags", {})
        if isinstance(planning_flags, dict):
            for dataset, listed in sorted(planning_flags.items()):
                evidence.append(
                    {
                        "topic": "planning_dataset_lookup",
                        "dataset": dataset,
                        "state": _availability_state(listed),
                        "facts": {},
                        "source": PLANNING_SOURCE,
                        "reliability_context": {
                            "source_authority": "UK government planning data platform",
                            "freshness": "dataset observation date is not captured by this client",
                            "geographic_scope": "coordinate query",
                            "directness": "dataset match, not an environmental measurement",
                            "coverage": "coverage varies by dataset and location",
                            "limitations": [
                                "No match returned does not establish absence; dataset coverage varies."
                            ],
                        },
                    }
                )

        deprivation = profile.get("deprivation", {})
        if isinstance(deprivation, dict) and deprivation.get("available") is True:
            facts = {
                key: deprivation[key]
                for key in ("imd_decile", "living_env_decile")
                if deprivation.get(key) is not None
            }
            evidence.append(
                {
                    "topic": "area_deprivation_deciles",
                    "state": "available",
                    "facts": facts,
                    "source": IMD_SOURCE,
                    "reliability_context": {
                        "source_authority": "UK government statistics",
                        "freshness": "2019 dataset",
                        "dataset_year": 2019,
                        "geographic_scope": "2011 LSOA",
                        "directness": "area-level statistical measure, not an individual measure",
                        "coverage": "LSOA-level data for England",
                        "limitations": [
                            "Area-level context, not a measurement or assessment of an individual."
                        ],
                    },
                }
            )
        else:
            evidence.append(
                {
                    "topic": "area_deprivation_deciles",
                    "state": "unavailable",
                    "facts": {},
                    "source": IMD_SOURCE,
                    "reliability_context": {
                        "source_authority": "UK government statistics",
                        "freshness": "2019 dataset",
                        "dataset_year": 2019,
                        "geographic_scope": "2011 LSOA",
                        "directness": "area-level statistical measure, not an individual measure",
                        "coverage": "LSOA-level data for England",
                        "limitations": ["No matching LSOA row was available."],
                    },
                }
            )

        profile_errors = profile.get("errors", {})
        if isinstance(profile_errors, dict):
            for source, code in sorted(profile_errors.items()):
                evidence.append(
                    {
                        "topic": "source_error",
                        "state": "unavailable",
                        "facts": {"error_code": str(code)[:80]},
                        "source": str(source)[:80],
                        "reliability_context": {
                            "source_authority": str(source)[:80],
                            "freshness": "not available",
                            "geographic_scope": "not available",
                            "directness": "not available",
                            "coverage": "source request did not return usable data",
                            "limitations": ["The source request did not return usable data."],
                        },
                    }
                )

        addresses.append(
            {
                "address_type": address_type,
                "local_authority": local_authority,
                "search_region": search_region,
                "evidence": evidence,
            }
        )

    return {
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "addresses": addresses,
        "search_terms": _derive_search_terms(address_profiles),
    }