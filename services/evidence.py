from datetime import datetime, timezone

BASE_SEARCH_TERMS = ("fire", "smoke", "pollution", "water")
PLANNING_SOURCE = "Planning Data platform"
IMD_SOURCE = "English Indices of Deprivation 2019"
LAQN_SOURCE = "London Air Quality Network"
EA_WATER_SOURCE = "Environment Agency Water Quality Archive"
TAP_WATER_SOURCE = "Thames Water zone water quality"
DEFAULT_WATER_RADIUS_KM = 5


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


def _indicator(
    category: str,
    status: str,
    title: str,
    detail: str,
    source: str,
) -> dict[str, str]:
    return {
        "category": category,
        "status": status,
        "title": title,
        "detail": detail,
        "source": source,
    }


def _tap_water_over_limit_count(drinking_water: dict[str, object]) -> int | None:
    """Return how many regulated parameters had samples over limit, or None."""
    parameters = drinking_water.get("regulated_parameters")
    if not isinstance(parameters, dict) or not parameters:
        return None
    over = 0
    for parameter in parameters.values():
        if not isinstance(parameter, dict):
            continue
        samples_over = parameter.get("samples_above_limit")
        if isinstance(samples_over, (int, float)) and samples_over > 0:
            over += 1
    return over


def _tap_water_indicator(
    address_type: str,
    profile: dict[str, object],
) -> dict[str, str]:
    drinking_water = profile.get("drinking_water")
    if not isinstance(drinking_water, dict) or drinking_water.get("available") is not True:
        return _indicator(
            "Tap water",
            "unavailable",
            "Tap water data unavailable",
            f"{address_type}: no supply-zone data is held for this postcode.",
            TAP_WATER_SOURCE,
        )

    zone = drinking_water.get("zone_name") or "supply zone"
    over = _tap_water_over_limit_count(drinking_water)
    if over is None:
        return _indicator(
            "Tap water",
            "unavailable",
            "Hardness and fluoride only",
            f"{address_type}: {zone} zone hardness and fluoride are available, "
            "but no regulatory sample results, so safety cannot be screened.",
            TAP_WATER_SOURCE,
        )
    if over > 0:
        return _indicator(
            "Tap water",
            "high",
            "Tap water samples over a limit",
            f"{address_type}: {over} parameter(s) in the {zone} zone had samples over the regulatory limit.",
            TAP_WATER_SOURCE,
        )
    return _indicator(
        "Tap water",
        "low",
        "Tap water samples within limits",
        f"{address_type}: no screened parameter in the {zone} zone had samples over its limit (zone level, not this tap).",
        TAP_WATER_SOURCE,
    )


def _build_indicators(
    address_type: str,
    profile: dict[str, object],
) -> list[dict[str, str]]:
    indicators = []
    air_quality = profile.get("air_quality", {})
    readings = air_quality.get("measurements", {}) if isinstance(air_quality, dict) else {}
    air_levels = []
    if isinstance(readings, dict):
        for species, reading in readings.items():
            if not isinstance(reading, dict):
                continue
            value = reading.get("value")
            if not isinstance(value, (int, float)):
                continue
            if species == "NO2":
                air_levels.append("high" if value > 200 else "moderate" if value > 40 else "low")
            elif species == "PM10":
                air_levels.append("high" if value > 100 else "moderate" if value > 50 else "low")
            elif species in {"PM25", "PM2.5"}:
                air_levels.append("high" if value > 50 else "moderate" if value > 25 else "low")
    if air_levels:
        status = "high" if "high" in air_levels else "moderate" if "moderate" in air_levels else "low"
        title = {
            "high": "Elevated air pollution",
            "moderate": "Moderate air pollution",
            "low": "No elevated air readings",
        }[status]
        indicators.append(
            _indicator(
                "Air quality",
                status,
                title,
                f"{address_type}: measured NO2/particulate readings screened against indicative thresholds.",
                LAQN_SOURCE,
            )
        )
    else:
        indicators.append(
            _indicator(
                "Air quality",
                "unavailable",
                "Air readings unavailable",
                f"{address_type}: no numeric reading was returned from a nearby open monitor.",
                LAQN_SOURCE,
            )
        )

    indicators.append(_tap_water_indicator(address_type, profile))

    water_quality = profile.get("water_quality", {})
    observations = water_quality.get("observations", []) if isinstance(water_quality, dict) else []
    water_levels = []
    if isinstance(observations, list):
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            parameter = observation.get("parameter")
            value = observation.get("value")
            if parameter == "pH" and isinstance(value, (int, float)):
                water_levels.append("high" if value < 6.5 or value > 8.5 else "low")
            elif parameter == "Nitrate as N" and isinstance(value, (int, float)):
                water_levels.append("high" if value > 11.3 else "low")
    if water_levels:
        status = "high" if "high" in water_levels else "low"
        indicators.append(
            _indicator(
                "Water observations",
                status,
                "Nearby water body readings need attention" if status == "high" else "No elevated nearby water body readings",
                f"{address_type}: nearby river and lake samples (not tap water) were screened for pH and nitrate where available.",
                EA_WATER_SOURCE,
            )
        )
    else:
        indicators.append(
            _indicator(
                "Water observations",
                "unavailable",
                "Nearby water body readings unavailable",
                f"{address_type}: no usable nearby river or lake sample was returned.",
                EA_WATER_SOURCE,
            )
        )

    planning_flags = profile.get("planning_flags", {})
    if isinstance(planning_flags, dict) and planning_flags.get("flood-risk-zone") is True:
        indicators.append(
            _indicator(
                "Flood context",
                "moderate",
                "Flood-zone match",
                f"{address_type}: the planning data platform returned a flood-risk-zone match.",
                PLANNING_SOURCE,
            )
        )
    else:
        indicators.append(
            _indicator(
                "Flood context",
                "low",
                "No flood-zone match returned",
                f"{address_type}: no flood-risk-zone entity was returned; coverage varies.",
                PLANNING_SOURCE,
            )
        )
    return indicators


def _tap_water_evidence(profile: dict[str, object]) -> dict[str, object]:
    drinking_water = profile.get("drinking_water")
    limitations_base = [
        "Zone-level data describes the supply zone, not an individual tap.",
        "This is not an overall drinking-water safety score.",
    ]
    if not isinstance(drinking_water, dict) or drinking_water.get("available") is not True:
        return {
            "topic": "tap_water_supply_zone",
            "state": "unavailable",
            "facts": {},
            "source": TAP_WATER_SOURCE,
            "reliability_context": {
                "source_authority": "Thames Water",
                "freshness": "not available",
                "geographic_scope": "water supply zone",
                "directness": "no supply-zone data held for this postcode",
                "coverage": "only some Thames Water zones in London are held locally",
                "limitations": [
                    "No data for this postcode does not mean the water is a concern, only that it was not looked up.",
                ],
            },
        }

    facts = {}
    if drinking_water.get("zone_name"):
        facts["supply_zone"] = drinking_water["zone_name"]
    hardness = drinking_water.get("hardness_calcium_carbonate_mg_l")
    if hardness is not None:
        rating = str(drinking_water.get("hardness_rating") or "").title()
        facts["hardness"] = f"{hardness} mg/L as calcium carbonate" + (f" ({rating})" if rating else "")
    if drinking_water.get("fluoride_mg_l") is not None:
        facts["fluoride"] = f"{drinking_water['fluoride_mg_l']} mg/L"
    if drinking_water.get("calcium_mg_l") is not None:
        facts["calcium"] = f"{drinking_water['calcium_mg_l']} mg/L"

    parameters = drinking_water.get("regulated_parameters")
    if isinstance(parameters, dict) and parameters:
        rows = []
        for name, parameter in parameters.items():
            if not isinstance(parameter, dict):
                continue
            unit = parameter.get("unit") or ""
            rows.append(
                {
                    "parameter": name,
                    "mean": f"{parameter.get('mean')} {unit}".strip(),
                    "maximum": f"{parameter.get('maximum')} {unit}".strip(),
                    "limit": f"{parameter.get('limit')} {unit}".strip(),
                    "over_limit": f"{parameter.get('samples_above_limit', 0)} of {parameter.get('sample_count', '?')} samples",
                }
            )
        if rows:
            facts["annual_zone_samples"] = rows
    else:
        limitations_base.append(
            "Regulatory sample results (such as lead and nitrate) are not available for this zone."
        )

    data_year = drinking_water.get("data_year")
    return {
        "topic": "tap_water_supply_zone",
        "state": "available",
        "facts": facts,
        "source": TAP_WATER_SOURCE,
        "reliability_context": {
            "source_authority": "Thames Water",
            "freshness": f"zone data for {data_year}" if data_year else "data year not stated",
            "geographic_scope": "water supply zone, not the address",
            "directness": "supply-zone measurements of the water delivered to customers",
            "coverage": "only some Thames Water zones in London are held locally",
            "limitations": limitations_base,
        },
    }


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
                for key in (
                    "site_name",
                    "site_type",
                    "distance_km",
                    "borough",
                    "measurements",
                    "measurement_window",
                )
                if air_quality.get(key) is not None
            }
            evidence.append(
                {
                    "topic": (
                        "air_quality_measurements"
                        if air_quality.get("measurements_available") is True
                        else "nearest_monitoring_site"
                    ),
                    "state": "available",
                    "facts": facts,
                    "source": LAQN_SOURCE,
                    "reliability_context": {
                        "source_authority": "London Air Quality Network",
                        "freshness": "site metadata date is not provided by this client",
                        "geographic_scope": "nearest monitoring site, not the address",
                        "directness": (
                            "numeric readings from the nearest open monitoring site"
                            if air_quality.get("measurements_available") is True
                            else "site metadata only; no pollutant measurement"
                        ),
                        "coverage": "London monitoring network sites",
                        "limitations": [
                            "Readings are from the monitoring site, not an address-level measurement.",
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

        evidence.append(_tap_water_evidence(profile))

        water_quality = profile.get("water_quality", {})
        water_observations = (
            water_quality.get("observations", [])
            if isinstance(water_quality, dict)
            else []
        )
        water_radius = (
            water_quality.get("radius_km", DEFAULT_WATER_RADIUS_KM)
            if isinstance(water_quality, dict)
            else DEFAULT_WATER_RADIUS_KM
        )
        if isinstance(water_quality, dict) and water_quality.get("available") is True:
            water_facts = {
                "radius_km": water_radius,
                "observations": water_observations,
            }
            if water_quality.get("sampling_point_count") is not None:
                water_facts["sampling_point_count"] = water_quality["sampling_point_count"]
            evidence.append(
                {
                    "topic": "nearby_water_bodies",
                    "state": "available",
                    "facts": water_facts,
                    "source": EA_WATER_SOURCE,
                    "reliability_context": {
                        "source_authority": "Environment Agency",
                        "freshness": "latest observation returned in the prior 364 days",
                        "geographic_scope": f"sampling points within {water_radius} km",
                        "directness": "measured sample result at a nearby river, lake or canal sampling point",
                        "coverage": "Environment Agency water-quality sampling network (England)",
                        "limitations": [
                            "Water observations describe a nearby sampling point and do not measure household drinking water.",
                            "Industrial and sewage discharge points are excluded.",
                            "Different determinands are sampled at different times and locations.",
                        ],
                    },
                }
            )
        else:
            evidence.append(
                {
                    "topic": "nearby_water_bodies",
                    "state": "unavailable",
                    "facts": {},
                    "source": EA_WATER_SOURCE,
                    "reliability_context": {
                        "source_authority": "Environment Agency",
                        "freshness": "no usable observation returned",
                        "geographic_scope": f"sampling points within {water_radius} km",
                        "directness": "no nearby measured sample result available",
                        "coverage": "Environment Agency water-quality sampling network (England)",
                        "limitations": [
                            "No nearby water body observation was returned; this does not prove that water quality is poor or good.",
                            "This source does not measure household drinking water.",
                        ],
                    },
                }
            )

        planning_flags = profile.get("planning_flags", {})
        if isinstance(planning_flags, dict):
            for dataset, listed in sorted(planning_flags.items()):
                is_brownfield = dataset == "brownfield-land"
                is_planning_application = dataset == "planning-application"
                limitations = (
                    [
                        "A register match identifies mapped brownfield land only; it does not establish active construction, contamination, or exposure.",
                        "No match returned does not establish absence; dataset coverage varies.",
                    ]
                    if is_brownfield
                    else [
                        "A planning application match does not establish that construction has started or that exposure is occurring.",
                        "No match returned does not establish absence; dataset coverage varies.",
                    ]
                    if is_planning_application
                    else [
                        "No match returned does not establish absence; dataset coverage varies."
                    ]
                )
                evidence.append(
                    {
                        "topic": (
                            "brownfield_land_register_match"
                            if is_brownfield
                            else "planning_application_lookup"
                            if is_planning_application
                            else "planning_dataset_lookup"
                        ),
                        "dataset": dataset,
                        "state": _availability_state(listed),
                        "facts": {},
                        "source": PLANNING_SOURCE,
                        "reliability_context": {
                            "source_authority": "UK government planning data platform",
                            "freshness": "dataset observation date is not captured by this client",
                            "geographic_scope": "coordinate query",
                            "directness": (
                                "mapped land-register entry, not evidence of current activity"
                                if is_brownfield
                                else "planning register match, not evidence of current activity"
                                if is_planning_application
                                else "dataset match, not an environmental measurement"
                            ),
                            "coverage": "coverage varies by dataset and location",
                            "limitations": limitations,
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
            living_environment_decile = deprivation.get("living_env_decile")
            if (
                isinstance(living_environment_decile, int)
                and living_environment_decile <= 3
            ):
                evidence.append(
                    {
                        "topic": "living_environment_quality_proxy",
                        "state": "flagged",
                        "facts": {
                            "living_env_decile": living_environment_decile,
                        },
                        "source": IMD_SOURCE,
                        "reliability_context": {
                            "source_authority": "UK government statistics",
                            "freshness": "2019 dataset",
                            "geographic_scope": "2011 LSOA",
                            "directness": (
                                "area-level composite proxy, not a greenspace "
                                "measurement or individual assessment"
                            ),
                            "coverage": "LSOA-level data for England",
                            "limitations": [
                                "The living environment domain is a composite of area indicators; it does not measure access to a specific park or greenspace.",
                                "Area-level context is not a measurement or assessment of an individual.",
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
                "indicators": _build_indicators(address_type, profile),
                "evidence": evidence,
            }
        )

    return {
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "addresses": addresses,
        "indicators": [
            {
                "address_type": address["address_type"],
                "items": address["indicators"],
            }
            for address in addresses
        ],
        "search_terms": _derive_search_terms(address_profiles),
    }