"""County assessor parcels for Arizona trustee sales (an ArcGIS parcel layer per county).

Maricopa: gis.mcassessor.maricopa.gov Parcels/MapServer/0 (open, no robots.txt). Only the
fields named in the county's config are requested: APN, situs address, position, full
cash and limited values, use code, legal class and the latest deed's recording number.
Owner and mailing fields are never requested. Legal class 3 is Arizona's owner-occupied
primary residence class, which gives the owner-occupied flag without any names.

Pima: gisdata.pima.gov GISOpenData/LandRecords/MapServer/0 (Parcel Centroids; open, no robots.txt).
Its PARCEL is undashed ("136175140"; `apn_digits` in the config) and it has no postal city
(JURIS_OL is the jurisdiction) or legal class; its MAIL1-MAIL5 owner/mailing fields are never requested.
"""
import re

from pipeline.scraping.http import PoliteClient

BATCH = 100


def number(value) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value or "").split(".")[0])
    return int(digits) if digits else None


class ParcelLayer:
    def __init__(self, config: dict, client: PoliteClient):
        self.layer, self.fields, self.client = config["layer"], config["fields"], client
        self.digits = bool(config.get("apn_digits"))

    def key(self, apn: str) -> str:
        """The layer's form of a dashed APN."""
        return apn.replace("-", "") if self.digits else apn

    def dashed(self, value: str | None) -> str | None:
        """A Pima layer APN ("136175140") in the notices' form ("136-17-5140")."""
        if self.digits and value and re.fullmatch(r"\d{8}[\dA-Z]", value):
            return f"{value[:3]}-{value[3:5]}-{value[5:]}"
        return value

    def query(self, where: str) -> list[dict]:
        response = self.client.get(f"{self.layer}/query", params={
            "where": where, "outFields": ",".join(self.fields.values()), "returnGeometry": "false", "f": "json"})
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(f"parcel layer: {payload['error']}")
        return [self.record(feature["attributes"]) for feature in payload.get("features", [])]

    def record(self, attributes: dict) -> dict:
        value = {key: attributes.get(name) for key, name in self.fields.items()}
        street = re.split(r"\s{2,}", (value.get("street") or "").strip())[0].strip()
        legal_class = str(value.get("legal_class") or "").strip() or None
        return {"apn": self.dashed(value.get("apn")), "street": street or None, "city": (value.get("city") or "").strip().title() or None,
                "zip": (value.get("zip") or "").strip()[:5] or None, "latitude": value.get("latitude"),
                "longitude": value.get("longitude"), "full_cash_value": number(value.get("full_cash_value")),
                "limited_value": number(value.get("limited_value")), "tax_year": value.get("tax_year"),
                "use_code": (value.get("use_code") or "").strip() or None, "legal_class": legal_class,
                "owner_occupied": legal_class.startswith("3") if legal_class else None,
                "deed_number": (value.get("deed_number") or "").strip() or None}

    def by_apn(self, apns: list[str]) -> dict[str, dict]:
        found = {}
        unique = sorted(set(apns))
        for start in range(0, len(unique), BATCH):
            quoted = ",".join(f"'{self.key(apn)}'" for apn in unique[start:start + BATCH] if re.fullmatch(r"[\dA-Z-]+", apn))
            for parcel in self.query(f"{self.fields['apn']} IN ({quoted})"):
                found[parcel["apn"]] = parcel
        return found

    def by_address(self, street: str, city: str | None) -> dict | None:
        """The one parcel whose situs starts with this house number and street name; None when not exactly one."""
        words = re.findall(r"[A-Z0-9]+", street.upper())
        if len(words) < 2 or not words[0].isdigit():
            return None
        name = next((word for word in words[1:] if word not in {"N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST"}), None)
        if not name:
            return None
        where = f"{self.fields['street']} LIKE '{words[0]} %{name}%'"
        if city and "city" in self.fields:
            where += f" AND UPPER({self.fields['city']}) = '{re.sub(r'[^A-Z ]', '', city.upper())}'"
        found = self.query(where)
        return found[0] if len(found) == 1 else None

    def by_deed_number(self, numbers: list[str]) -> dict[str, dict]:
        found = {}
        for start in range(0, len(numbers), BATCH):
            quoted = ",".join(f"'{n}'" for n in numbers[start:start + BATCH] if n.isdigit())
            for parcel in self.query(f"{self.fields['deed_number']} IN ({quoted})"):
                found[parcel["deed_number"]] = parcel
        return found
