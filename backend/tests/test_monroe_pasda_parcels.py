from pipeline.import_monroe_pasda_parcels import (
    deduplicate_rows,
    feature_rows,
    polygon_centroid,
    validate_metadata,
)
from pipeline.pa_parcel_numbers import normalize_map_number


def test_normalize_map_number_preserves_meaningful_characters() -> None:
    assert normalize_map_number(" 09-13B / 1.77 ") == "09.13B.1.77"
    assert normalize_map_number("03634701161838") == "03634701161838"


def test_validate_metadata_uses_real_schema_capabilities() -> None:
    metadata = {
        "fields": [{"name": "OBJECTID"}, {"name": "MAPNUMBER"}],
        "maxRecordCount": 2000,
        "supportedQueryFormats": "JSON, geoJSON",
        "advancedQueryCapabilities": {"supportsPagination": True},
    }
    assert validate_metadata(metadata) == ("OBJECTID", 2000)


def test_polygon_centroid_and_feature_row() -> None:
    geometry = {"type": "Polygon", "coordinates": [[
        [-75.0, 40.0], [-74.0, 40.0], [-74.0, 41.0],
        [-75.0, 41.0], [-75.0, 40.0],
    ]]}
    latitude, longitude = polygon_centroid(geometry)
    assert round(latitude, 6) == 40.5
    assert round(longitude, 6) == -74.5
    rows = feature_rows([{"properties": {
        "OBJECTID": 1, "MAPNUMBER": "03634701161838",
    }, "geometry": geometry}])
    assert rows[0]["normalized_map_number"] == "03634701161838"


def test_duplicate_normalized_parcels_keep_latest_source_feature() -> None:
    rows = [
        {"normalized_map_number": "09.13B.1.77", "source_object_id": 10},
        {"normalized_map_number": "09.13B.1.77", "source_object_id": 12},
        {"normalized_map_number": "10.2.3", "source_object_id": 11},
    ]
    unique_rows, duplicate_count = deduplicate_rows(rows)
    assert duplicate_count == 1
    assert [row["source_object_id"] for row in unique_rows] == [11, 12]
