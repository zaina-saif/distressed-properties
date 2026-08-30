import hashlib
import re
from dataclasses import dataclass
from typing import Optional


# Longer municipality names must be checked before shorter ones.
MONMOUTH_MUNICIPALITIES = sorted(
    {
        "Atlantic Highlands",
        "West Long Branch",
        "Freehold Township",
        "Middletown Township",
        "Neptune Township",
        "Upper Freehold",
        "Ocean Township",
        "Spring Lake Heights",
        "Sea Girt",
        "Spring Lake",
        "Allenhurst",
        "Allentown",
        "Asbury Park",
        "Avon-by-the-Sea",
        "Belmar",
        "Bradley Beach",
        "Brielle",
        "Clarksburg",
        "Cliffwood",
        "Cliffwood Beach",
        "Colts Neck",
        "Deal",
        "Eatontown",
        "Englishtown",
        "Fair Haven",
        "Farmingdale",
        "Freehold",
        "Hazlet",
        "Highlands",
        "Holmdel",
        "Howell",
        "Interlaken",
        "Keansburg",
        "Keyport",
        "Lake Como",
        "Leonardo",
        "Little Silver",
        "Loch Arbour",
        "Long Branch",
        "Manalapan",
        "Manasquan",
        "Marlboro",
        "Matawan",
        "Millstone",
        "Monmouth Beach",
        "Morganville",
        "Neptune",
        "Neptune City",
        "North Middletown",
        "Ocean Grove",
        "Oceanport",
        "Oakhurst",
        "Red Bank",
        "Roosevelt",
        "Rumson",
        "Sea Bright",
        "Shrewsbury",
        "Tinton Falls",
        "Union Beach",
        "Wall",
        "Wall Township",
        "West Allenhurst",
        "Audubon", "Barrington", "Bellmawr", "Blackwood", "Camden", "Cherry Hill",
        "Clementon", "Collingswood", "Gibbsboro", "Glendora", "Gloucester City",
        "Gloucester Township", "Haddon Heights", "Haddon Township", "Laurel Springs",
        "Lawnside", "Lindenwold", "Magnolia", "Mount Ephraim", "Oaklyn", "Pennsauken",
        "Pine Hill", "Runnemede", "Sicklerville", "Somerdale", "Stratford", "Voorhees",
        "Waterford Works", "West Berlin", "Winslow", "Winslow Township", "Woodlynne",
        "Avalon", "Cape May", "Cape May Court House", "Dennisville", "Goshen", "Marmora",
        "North Cape May", "Ocean City", "Rio Grande", "Sea Isle City", "Stone Harbor",
        "Villas", "Wildwood", "Wildwood Crest", "Woodbine",
        "Erma", "Green Creek", "Lower Township",
        "Belleville", "Bloomfield", "Caldwell", "Cedar Grove", "East Orange",
        "Essex Fells", "Fairfield", "Glen Ridge", "Irvington", "Livingston",
        "Maplewood", "Millburn", "Montclair", "Newark", "North Caldwell",
        "Nutley", "Orange", "Roseland", "Short Hills", "South Orange",
        "Verona", "West Caldwell", "West Orange",
        "Allendale", "Alpine", "Bergenfield", "Bogota", "Carlstadt",
        "Cliffside Park", "Closter", "Cresskill", "Demarest", "Dumont",
        "East Rutherford", "Edgewater", "Elmwood Park", "Emerson", "Englewood",
        "Englewood Cliffs", "Fair Lawn", "Fairview", "Fort Lee", "Franklin Lakes",
        "Garfield", "Glen Rock", "Hackensack", "Harrington Park",
        "Hasbrouck Heights", "Haworth", "Hillsdale", "Ho-Ho-Kus", "Leonia",
        "Little Ferry", "Lodi", "Lyndhurst", "Mahwah", "Maywood", "Midland Park",
        "Montvale", "Moonachie", "New Milford", "North Arlington", "Northvale",
        "Norwood", "Oakland", "Old Tappan", "Oradell", "Palisades Park", "Paramus",
        "Park Ridge", "Ramsey", "Ridgefield", "Ridgefield Park", "Ridgewood",
        "River Edge", "River Vale", "Rochelle Park", "Rockleigh", "Rutherford",
        "Saddle Brook", "Saddle River", "South Hackensack", "Teaneck", "Tenafly",
        "Teterboro", "Upper Saddle River", "Waldwick", "Wallington",
        "Township of Washington", "Washington Township", "Westwood", "Woodcliff Lake",
        "Wood Ridge", "Wood-Ridge", "Wyckoff",
        "Ocean View",
        "Avenel", "Carteret", "Colonia", "Cranbury", "Dunellen", "East Brunswick",
        "Edison", "Fords", "Fords (Woodbridge Twp.)", "Helmetta", "Highland Park", "Hopelawn", "Iselin",
        "Jamesburg", "Keasbey", "Laurence Harbor", "Metuchen", "Middlesex", "Milltown",
        "Kendall Park", "Monmouth Junction", "Monroe", "Monroe Township", "New Brunswick",
        "North Brunswick", "Old Bridge", "Parlin",
        "Perth Amboy", "Piscataway", "Plainsboro", "Princeton", "Port Reading", "Sayreville",
        "Sewaren", "South Amboy", "South Brunswick", "South Plainfield", "South River",
        "Spotswood", "Woodbridge", "Woodbridge Township", "Woodbridge Twp.",
        "Barnegat", "Bayville", "Beach Haven", "Beachwood", "Berkeley", "Berkeley Twp.",
        "Brick", "Forked River",
        "Island Heights", "Jackson", "Lacey Township", "Lakehurst", "Lakewood",
        "Lavallette", "Little Egg Harb", "Little Egg Harbor", "Manahawkin", "Manchester",
        "Mantoloking", "New Egypt", "Ocean Gate", "Pine Beach", "Point Pleasant",
        "Point Pleasant Beach", "Seaside Heights", "Seaside Park", "Ship Bottom-LBI",
        "Ship Bottom", "Stafford", "Stafford Twp.", "Surf City", "Toms River", "Tuckerton", "Waretown",
        "Whiting",
    },
    key=len,
    reverse=True,
)


UNIT_PATTERN = re.compile(
    r"\b(?:UNIT|APT|APARTMENT|SUITE|STE|#)\s*([A-Z0-9-]+)\b",
    re.IGNORECASE,
)

ZIP_PATTERN = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
STATE_PATTERN = re.compile(r"\bNJ\b", re.IGNORECASE)


@dataclass(frozen=True)
class NormalizedPropertyAddress:
    original_address: str
    normalized_address: str
    street_address: str
    unit_number: Optional[str]
    city: str
    state: str
    zip_code: Optional[str]
    address_hash: str
    data_quality_score: int
    needs_manual_review: bool
    review_reason: Optional[str]


def clean_whitespace(value: str) -> str:
    """Collapse repeated spaces and remove unnecessary spacing."""

    value = value.replace("\n", " ").replace("\t", " ")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+,", ",", value)
    return value.strip(" ,")


def title_case_address(value: str) -> str:
    """
    Apply readable title casing while preserving common abbreviations.
    """

    result = value.title()

    replacements = {
        " Nj": " NJ",
        " N.J.": " NJ",
        " Aka ": " a/k/a ",
        " Fka ": " f/k/a ",
        " Po Box": " PO Box",
    }

    for old, new in replacements.items():
        result = result.replace(old, new)

    return result


def extract_zip(address: str) -> Optional[str]:
    matches = ZIP_PATTERN.findall(address)
    return matches[-1] if matches else None


def extract_unit(address: str) -> tuple[str, Optional[str]]:
    match = UNIT_PATTERN.search(address)

    if not match:
        return address, None

    unit_number = match.group(1).upper()

    street_without_unit = (
        address[: match.start()] + address[match.end() :]
    )

    return clean_whitespace(street_without_unit), unit_number


def find_municipality(before_state: str) -> tuple[Optional[str], str]:
    """
    Find a known Monmouth County municipality at the end of the
    portion of the address before 'NJ'.
    """

    cleaned = clean_whitespace(before_state)

    for municipality in MONMOUTH_MUNICIPALITIES:
        pattern = re.compile(
            rf"(?:^|\s){re.escape(municipality)}$",
            re.IGNORECASE,
        )

        match = pattern.search(cleaned)

        if match:
            street = clean_whitespace(cleaned[: match.start()])
            return municipality, street

    return None, cleaned


def calculate_address_hash(
    street_address: str,
    unit_number: Optional[str],
    city: str,
    state: str,
    zip_code: Optional[str],
) -> str:
    hash_source = "|".join(
        [
            street_address.upper().strip(),
            (unit_number or "").upper().strip(),
            city.upper().strip(),
            state.upper().strip(),
            (zip_code or "").strip(),
        ]
    )

    return hashlib.sha256(
        hash_source.encode("utf-8")
    ).hexdigest()


def normalize_address(
    raw_address: str,
) -> NormalizedPropertyAddress:
    if not raw_address or not raw_address.strip():
        raise ValueError("Address is empty.")

    original = clean_whitespace(raw_address)
    working = original

    zip_code = extract_zip(working)

    if zip_code:
        working = re.sub(
            rf"\b{re.escape(zip_code)}(?:-\d{{4}})?\b",
            "",
            working,
        )

    state_match = list(STATE_PATTERN.finditer(working))

    if not state_match:
        raise ValueError(
            f"Could not find NJ in address: {original}"
        )

    # Use the last NJ occurrence because some source records contain
    # multiple address descriptions.
    last_state = state_match[-1]
    before_state = clean_whitespace(
        working[: last_state.start()]
    )

    municipality, street_with_unit = find_municipality(
        before_state
    )

    if not municipality:
        raise ValueError(
            f"Could not identify municipality: {original}"
        )

    street_address, unit_number = extract_unit(
        street_with_unit
    )

    street_address = title_case_address(street_address)
    city = title_case_address(municipality)
    state = "NJ"

    review_reasons: list[str] = []

    if not zip_code:
        review_reasons.append("ZIP code missing")

    if len(re.findall(r"\bNJ\b", original, re.IGNORECASE)) > 1:
        review_reasons.append(
            "Source may contain multiple addresses"
        )

    if " a/k/a " in original.lower() or " f/k/a " in original.lower():
        review_reasons.append(
            "Source contains an alternate address"
        )

    # Multiple street numbers often indicate multiple parcels or
    # concatenated property descriptions.
    street_numbers = re.findall(
        r"(?<![A-Za-z])\d+[A-Za-z]?(?!\d)",
        street_address,
    )

    if len(street_numbers) > 3:
        review_reasons.append(
            "Street field may contain multiple properties"
        )

    data_quality_score = 100

    if not zip_code:
        data_quality_score -= 15

    if review_reasons:
        data_quality_score -= 20

    data_quality_score = max(data_quality_score, 0)

    normalized_parts = [street_address]

    if unit_number:
        normalized_parts.append(f"Unit {unit_number}")

    normalized_parts.append(city)
    normalized_parts.append(state)

    if zip_code:
        normalized_parts.append(zip_code)

    normalized_address = ", ".join(normalized_parts)

    address_hash = calculate_address_hash(
        street_address=street_address,
        unit_number=unit_number,
        city=city,
        state=state,
        zip_code=zip_code,
    )

    return NormalizedPropertyAddress(
        original_address=original,
        normalized_address=normalized_address,
        street_address=street_address,
        unit_number=unit_number,
        city=city,
        state=state,
        zip_code=zip_code,
        address_hash=address_hash,
        data_quality_score=data_quality_score,
        needs_manual_review=bool(review_reasons),
        review_reason=(
            "; ".join(review_reasons)
            if review_reasons
            else None
        ),
    )


if __name__ == "__main__":
    test_addresses = [
        "180 Bernard Drive Red Bank NJ 07701",
        "1001 2nd Avenue Unit 112 Asbury Park NJ 07712",
        "11 Buttonwood Drive Marlboro NJ 07746",
    ]

    for test_address in test_addresses:
        result = normalize_address(test_address)
        print(result)
