from __future__ import annotations

from copy import deepcopy


SCAN_PROFILE_CATALOG: list[dict] = [
    {
        "key": "rtl_priority_search",
        "label": "RTL Priority Search",
        "description": "Tighter, high-yield RTL-SDR coverage for common local voice and practical digital bands.",
        "ranges": [
            {"label": "NOAA Weather", "start_mhz": 162.4, "end_mhz": 162.55, "step_khz": 25, "priority": 22},
            {"label": "Marine VHF", "start_mhz": 156.0, "end_mhz": 163.0, "step_khz": 25, "priority": 21},
            {"label": "Airband Voice", "start_mhz": 118.0, "end_mhz": 137.0, "step_khz": 25, "priority": 20},
            {"label": "Broadcast FM", "start_mhz": 88.0, "end_mhz": 108.0, "step_khz": 200, "priority": 23},
            {"label": "2m Amateur", "start_mhz": 144.0, "end_mhz": 148.0, "step_khz": 25, "priority": 19},
            {"label": "MURS", "start_mhz": 151.82, "end_mhz": 154.6, "step_khz": 12.5, "priority": 18},
            {"label": "Pager / POCSAG", "start_mhz": 152.0, "end_mhz": 159.0, "step_khz": 12.5, "priority": 18},
            {"label": "433 MHz ISM", "start_mhz": 433.0, "end_mhz": 435.0, "step_khz": 25, "priority": 19},
            {"label": "FRS/GMRS", "start_mhz": 462.55, "end_mhz": 467.725, "step_khz": 12.5, "priority": 18},
        ],
    },
    {
        "key": "likely_local_voice",
        "label": "Likely Local Voice",
        "description": "Fast coverage of the most common local voice services and repeaters.",
        "ranges": [
            {"label": "Broadcast FM", "start_mhz": 88.0, "end_mhz": 108.0, "step_khz": 200, "priority": 23},
            {"label": "Airband Voice", "start_mhz": 118.0, "end_mhz": 137.0, "step_khz": 25, "priority": 19},
            {"label": "2m Amateur", "start_mhz": 144.0, "end_mhz": 148.0, "step_khz": 25, "priority": 17},
            {"label": "Marine VHF", "start_mhz": 156.0, "end_mhz": 163.0, "step_khz": 25, "priority": 19},
            {"label": "NOAA Weather", "start_mhz": 162.4, "end_mhz": 162.55, "step_khz": 25, "priority": 20},
            {"label": "70cm Amateur", "start_mhz": 420.0, "end_mhz": 450.0, "step_khz": 25, "priority": 16},
            {"label": "FRS/GMRS", "start_mhz": 462.55, "end_mhz": 467.725, "step_khz": 12.5, "priority": 18},
            {"label": "Public Safety 700", "start_mhz": 769.0, "end_mhz": 776.0, "step_khz": 12.5, "priority": 15},
            {"label": "Public Safety 800", "start_mhz": 851.0, "end_mhz": 869.0, "step_khz": 12.5, "priority": 15},
        ],
    },
    {
        "key": "civil_aircraft",
        "label": "Civil Aircraft",
        "description": "Aviation voice plus digital aircraft data and tracking signals.",
        "ranges": [
            {"label": "Airband Voice", "start_mhz": 118.0, "end_mhz": 137.0, "step_khz": 25, "priority": 19},
            {"label": "ACARS", "start_mhz": 129.0, "end_mhz": 132.0, "step_khz": 25, "priority": 20},
            {"label": "VDL2 / Aero Data", "start_mhz": 136.65, "end_mhz": 136.975, "step_khz": 25, "priority": 18},
            {"label": "ADS-B 1090", "start_mhz": 1088.0, "end_mhz": 1092.0, "step_khz": 250, "priority": 20},
        ],
    },
    {
        "key": "marine_weather",
        "label": "Marine + Weather",
        "description": "Marine channels, NOAA weather, and weather satellite downlinks.",
        "ranges": [
            {"label": "Marine VHF", "start_mhz": 156.0, "end_mhz": 163.0, "step_khz": 25, "priority": 19},
            {"label": "NOAA Weather", "start_mhz": 162.4, "end_mhz": 162.55, "step_khz": 25, "priority": 20},
            {"label": "NOAA APT", "start_mhz": 137.0, "end_mhz": 138.0, "step_khz": 25, "priority": 16},
        ],
    },
    {
        "key": "digital_signal_hunting",
        "label": "Digital Signal Hunting",
        "description": "Common digital data and short-burst bands for sensors, pagers, RC, and key fobs.",
        "ranges": [
            {"label": "MURS", "start_mhz": 151.82, "end_mhz": 154.6, "step_khz": 12.5, "priority": 15},
            {"label": "Pager / POCSAG", "start_mhz": 152.0, "end_mhz": 159.0, "step_khz": 12.5, "priority": 17},
            {"label": "315 MHz ISM", "start_mhz": 314.8, "end_mhz": 315.3, "step_khz": 25, "priority": 18},
            {"label": "390 MHz ISM", "start_mhz": 389.8, "end_mhz": 390.3, "step_khz": 25, "priority": 17},
            {"label": "433 MHz ISM", "start_mhz": 433.0, "end_mhz": 435.0, "step_khz": 25, "priority": 20},
            {"label": "915 MHz ISM", "start_mhz": 902.0, "end_mhz": 928.0, "step_khz": 100, "priority": 18},
        ],
    },
    {
        "key": "tv_and_wideband",
        "label": "TV + Wideband",
        "description": "Broadcast TV allocations and other wideband carriers worth identifying.",
        "ranges": [
            {"label": "TV VHF Low", "start_mhz": 54.0, "end_mhz": 88.0, "step_khz": 250, "priority": 12},
            {"label": "TV VHF High", "start_mhz": 174.0, "end_mhz": 216.0, "step_khz": 250, "priority": 12},
            {"label": "TV UHF", "start_mhz": 470.0, "end_mhz": 608.0, "step_khz": 250, "priority": 12},
        ],
    },
]

DEFAULT_SCAN_PROFILE_KEYS = [
    "rtl_priority_search",
]


def get_scan_profile_catalog() -> list[dict]:
    return deepcopy(SCAN_PROFILE_CATALOG)


def resolve_scan_profile_keys(scanner_config: dict) -> list[str]:
    keys = scanner_config.get("scan_profiles")
    if not keys:
        return list(DEFAULT_SCAN_PROFILE_KEYS)
    return [str(key) for key in keys]


def resolve_sweep_ranges(scanner_config: dict) -> list[dict]:
    """Return the final list of ranges to sweep.

    Precedence rule: when the user has any explicit `sweep_ranges`, those
    are authoritative and Scan Profiles are ignored. Profiles only fill in
    when `sweep_ranges` is empty — that keeps the "first-run, pick a
    profile" workflow working while matching the mental model that the
    Scan Ranges list in Settings is exactly what gets scanned.
    """
    ranges = [deepcopy(r) for r in scanner_config.get("sweep_ranges", [])]
    if not ranges:
        enabled = set(resolve_scan_profile_keys(scanner_config))
        for profile in SCAN_PROFILE_CATALOG:
            if profile["key"] not in enabled:
                continue
            for rng in profile["ranges"]:
                ranges.append(deepcopy(rng))

    deduped: dict[tuple[float, float, float], dict] = {}
    for rng in ranges:
        normalized = _normalize_range(rng)
        dedupe_key = (
            normalized["start_mhz"],
            normalized["end_mhz"],
            normalized["step_khz"],
        )
        existing = deduped.get(dedupe_key)
        if existing is None or normalized["priority"] > existing["priority"]:
            deduped[dedupe_key] = normalized
            continue
        if existing and not existing.get("label") and normalized.get("label"):
            existing["label"] = normalized["label"]

    resolved = list(deduped.values())
    resolved.sort(
        key=lambda item: (
            -item["priority"],
            item["end_mhz"] - item["start_mhz"],
            item["start_mhz"],
            item.get("label", ""),
        )
    )
    return resolved


def _normalize_range(rng: dict) -> dict:
    step_khz = float(rng.get("step_khz", 200))
    priority = int(rng.get("priority", 10))
    return {
        "label": rng.get("label", ""),
        "start_mhz": float(rng["start_mhz"]),
        "end_mhz": float(rng["end_mhz"]),
        "step_khz": step_khz,
        "priority": priority,
    }
