import json

import numpy as np
import pandas as pd
import pytest

from timeatlas.TAEnums import (
    CLASS_NAME_TO_RDE,
    LAYER_TYPE_TO_ENUM,
    METADATA_TAG_TO_ENUM,
    METADATA_TYPE_TO_ENUM,
    PARADATA_VALUE_TO_ENUM,
    LayerType,
    MetadataTag,
    MetadataType,
    ParadataValues,
    RDEType,
)
from timeatlas.helpers import (
    _clean_metadata,
    _datetime_from_int,
    _get_area_uuids,
    _get_filepath_like,
    _get_layer_uuid,
    _get_likely_type,
    _python_type_to_metadata_type,
    _seed,
)


def test_enum_values_and_compatibility_mappings_are_complete():
    assert LAYER_TYPE_TO_ENUM == {"RASTER": LayerType.RASTER, "VECTOR": LayerType.VECTOR}
    assert set(METADATA_TAG_TO_ENUM.values()) == set(MetadataTag)
    assert set(METADATA_TYPE_TO_ENUM.values()) == set(MetadataType)
    assert PARADATA_VALUE_TO_ENUM["m"] is PARADATA_VALUE_TO_ENUM["MANUAL"]
    assert PARADATA_VALUE_TO_ENUM["ai"] is ParadataValues.AI
    assert CLASS_NAME_TO_RDE["hr"] is RDEType.HR
    assert CLASS_NAME_TO_RDE["pointofinterest"] is RDEType.POI
    assert CLASS_NAME_TO_RDE["layer_configuration"] is RDEType.LAYER_CONFIGURATION


def test_seed_matches_legacy_csv_serialization():
    row = pd.Series({"number": 1, "name": "Venice"})
    assert _seed(row, ["number", "name"], suffix="end") == "1\nVenice\nend"


def test_get_layer_uuid_requires_exactly_one_match(tmp_path):
    path = tmp_path / "layers.json"
    path.write_text(
        json.dumps(
            {
                "rde_objects": [
                    {"slug": "base-map", "id": "base"},
                    {"slug": "parcel-map", "id": "parcel"},
                ]
            }
        )
    )

    assert _get_layer_uuid(str(path), "parcel") == "parcel"
    with pytest.raises(ValueError, match="found 0"):
        _get_layer_uuid(str(path), "missing")
    with pytest.raises(ValueError, match="found 2"):
        _get_layer_uuid(str(path), "map")


def test_get_filepath_like_returns_latest_sorted_recursive_match(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "scan-01.png").touch()
    expected = nested / "scan-02.png"
    expected.touch()

    assert _get_filepath_like(str(tmp_path / "scan-"), "png") == str(expected)


def test_clean_metadata_normalizes_collections_and_missing_values():
    cleaned = _clean_metadata(
        {
            "list": (1, 2),
            "array": np.array([3, 4]),
            "series": pd.Series([5, 6]),
            "nan": np.nan,
            "nan_string": "NaN",
            "value": "kept",
        }
    )

    assert cleaned == {
        "list": [1, 2],
        "array": [3, 4],
        "series": [5, 6],
        "nan": None,
        "nan_string": None,
        "value": "kept",
    }


@pytest.mark.parametrize(
    ("series", "expected"),
    [
        (pd.Series([1, 2], dtype="int64"), "int64"),
        (pd.Series([None, "text"], dtype="object"), str),
        (pd.Series([None, [1, 2]], dtype="object"), list),
        (pd.Series([None, np.nan], dtype="object"), None),
    ],
)
def test_get_likely_type(series, expected):
    assert _get_likely_type(series) == expected


@pytest.mark.parametrize(
    ("python_type", "metadata_type"),
    [
        (int, MetadataType.INTEGER),
        ("int64", MetadataType.INTEGER),
        (float, MetadataType.FLOAT),
        ("float32", MetadataType.FLOAT),
        (list, MetadataType.LIST),
        (np.ndarray, MetadataType.LIST),
        (bool, MetadataType.STRING),
        (None, MetadataType.STRING),
    ],
)
def test_python_type_to_metadata_type(python_type, metadata_type):
    assert _python_type_to_metadata_type(python_type) is metadata_type


def test_get_area_uuids_reads_first_rde_from_each_file(tmp_path):
    paths = []
    for index in range(2):
        path = tmp_path / f"area-{index}.json"
        path.write_text(json.dumps({"rde_objects": [{"id": f"area-{index}"}]}))
        paths.append(str(path))

    assert _get_area_uuids(paths) == ["area-0", "area-1"]


@pytest.mark.parametrize(
    ("value", "match_to_end", "expected"),
    [
        (1808, False, "1808-01-01T00:00:00"),
        ("1808", True, "1808-12-31T23:59:59"),
        (18080102, False, "1808-01-02T00:00:00"),
        ("18080102", True, "1808-01-02T23:59:59"),
        (808, False, "0808-01-01T00:00:00"),
        (8080102, False, "0808-01-02T00:00:00"),
    ],
)
def test_datetime_from_int(value, match_to_end, expected):
    assert _datetime_from_int(value, match_to_end=match_to_end) == expected


def test_datetime_from_int_rejects_unsupported_values():
    with pytest.raises(ValueError, match="Invalid date value"):
        _datetime_from_int("1808-01-01")
