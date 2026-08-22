import re


def normalize_map_number(value: str | None) -> str | None:
    """Normalize presentation differences without discarding parcel semantics."""
    if value is None:
        return None
    normalized = re.sub(r"\s+", "", value.strip().upper())
    normalized = re.sub(r"[._/\\-]+", ".", normalized).strip(".")
    return normalized or None
