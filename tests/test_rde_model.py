import json
import uuid

import pandas as pd
import pytest
import shapely
from shapely.geometry import Point, Polygon

from timeatlas import (
    Area,
    Dataset,
    DatasetConfiguration,
    FreeFormMetadata,
    GeographicalExtent,
    Geometry,
    HeightInfo,
    HistoricalRecord,
    Layer,
    LayerConfiguration,
    LayerConfigurationService,
    LayerType,
    Map,
    MetadataFieldConfig,
    MetadataTag,
    MetadataType,
    MultiLingualValue,
    Observation,
    ParadataValues,
    PointOfInterest,
    RDE,
    RDETimeRange,
    RDEType,
    UUIDEntity,
    UUIDManager,
)


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


def test_uuid_manager_supports_url_and_uuid_namespaces():
    url_manager = UUIDManager("https://example.test/dataset")
    uuid_manager = UUIDManager(url_manager.namespace)

    assert url_manager._generate_uuid("record") == uuid_manager._generate_uuid("record")
    assert UUIDManager.generate_uuid(url_manager.namespace, "record") == url_manager._generate_uuid(
        "record"
    )
    assert UUIDManager.is_valid_uuid(UUIDManager.generate_uuid(None))


@pytest.mark.parametrize("namespace", ["dataset", 123, None])
def test_uuid_manager_rejects_invalid_namespaces(namespace):
    with pytest.raises(ValueError, match="Invalid namespace"):
        UUIDManager(namespace)


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        (uid(1), True),
        ("not-a-uuid", False),
        (None, False),
        (123, False),
    ],
)
def test_is_valid_uuid(value, valid):
    assert UUIDManager.is_valid_uuid(value) is valid


def test_uuid_entity_normalizes_supported_ids_and_namespaces_by_entity_type():
    manager = UUIDManager("https://example.test/dataset")
    generated_dataset = Dataset(
        id=(manager, "same"),
        slug="dataset",
        name=MultiLingualValue(),
        time_range=RDETimeRange("1900-01-01", "1900-01-02"),
    )
    generated_area = Area(
        id=(manager, "same"),
        slug="area",
        name=MultiLingualValue(),
        geometry=Point(0, 0),
    )
    native_uuid = uuid.uuid4()

    assert generated_dataset.id != generated_area.id
    assert UUIDEntity(native_uuid).id == str(native_uuid)
    assert UUIDManager.is_valid_uuid(UUIDEntity(None).id)
    assert UUIDEntity.parse_uuid(f"https://example.test/rde/{uid(9)}") == uid(9)
    assert UUIDEntity(uid(8)).get_ref() == uid(8)


@pytest.mark.parametrize("invalid_id", ["invalid", 42, object()])
def test_uuid_entity_rejects_invalid_ids(invalid_id):
    with pytest.raises(ValueError, match="Invalid"):
        UUIDEntity(invalid_id)


def test_time_range_validates_iso_format_and_order():
    assert RDETimeRange("1900-01-01", "1900-01-01").start_time == "1900-01-01"
    assert RDETimeRange("1900-01-01T00:00:00Z", "1900-01-02T00:00:00Z")
    with pytest.raises(ValueError):
        RDETimeRange("not-a-date", "1900-01-01")
    with pytest.raises(AssertionError, match="start_time"):
        RDETimeRange("1900-01-02", "1900-01-01")


def test_rde_base_contract_and_type_lookup():
    assert RDE().get_type() is None
    with pytest.raises(NotImplementedError):
        RDE.constructor_from_json_obj({})


def test_metadata_configuration_defaults_parsing_and_serialization():
    config = MetadataFieldConfig.constructor_from_json_obj(
        {
            "id": "owner",
            "type": "STRING",
            "display_label": {"en": ["Owner"]},
            "nullable": False,
            "indexable": True,
            "short_display": True,
            "hidden": True,
            "tag": "PEOPLE",
            "paradata": "sa",
        }
    )
    defaults = MetadataFieldConfig.constructor_from_json_obj({"id": "unknown"})

    assert config.type is MetadataType.STRING
    assert config.tag is MetadataTag.PEOPLE
    assert config.paradata is ParadataValues.SEMIAUTOMATIC
    assert config.to_dict()["display_label"] == {"en": ["Owner"]}
    assert defaults.type is MetadataType.STRING
    assert defaults.display_label.values == {}


def test_free_form_metadata_serializes_multilingual_values():
    metadata = FreeFormMetadata(
        type=MetadataType.URL,
        label=MultiLingualValue({"en": ["Source"]}),
        value=MultiLingualValue({"en": ["https://example.test"]}),
    )
    assert metadata.to_dict() == {
        "type": "URL",
        "label": {"en": ["Source"]},
        "value": {"en": ["https://example.test"]},
    }


def test_dataset_configuration_accepts_flat_and_legacy_nested_shapes():
    field = {"id": "name", "type": "STRING"}
    flat = DatasetConfiguration.constructor_from_json_obj(
        {
            "metadata_field_config": [field],
            "main_label": "{name}",
            "sub_label": "sub",
            "display_thumbnail": True,
            "external_source": True,
        }
    )
    nested = DatasetConfiguration.constructor_from_json_obj(
        {"metadata_field_config": [field], "dataset_config": {"main_label": "legacy"}}
    )

    assert flat.main_label == "{name}"
    assert flat.display_thumbnail is True
    assert nested.main_label == "legacy"
    assert flat.to_dict() == flat.to_dict()
    assert isinstance(flat.metadata_field_config[0], MetadataFieldConfig)


def test_dataset_constructor_and_to_dict_are_idempotent(sample_object):
    raw = sample_object("dataset.json")
    dataset = Dataset.constructor_from_json_obj(raw)

    first = dataset.to_dict()
    second = dataset.to_dict()

    assert first == second
    assert dataset.slug == "venice-1808-sommarioni"
    assert dataset.configuration.main_label == raw["configuration"]["main_label"]
    assert first["configuration"]["metadata_field_config"][0]["id"] == "parcel_number"
    assert first["rde_type"] == RDEType.DATASET.value
    assert "hrs" not in first and "obs" not in first


def test_dataset_can_be_built_from_configuration_and_dataframe(tmp_path):
    area_id = uid(40)
    area_path = tmp_path / "area.json"
    area_path.write_text(json.dumps({"rde_objects": [{"id": area_id}]}))
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "UUID_NAMESPACE": "https://example.test/dataset",
                "TIMERANGE_MINIMUM": 1808,
                "TIMERANGE_MAXIMUM": 1809,
                "AREA_LOCS": [str(area_path)],
                "DATASET_CONFIGURATION": {
                    "slug": "land-register",
                    "name": {"en": ["Land register"]},
                    "indexed": ["owner"],
                    "short_display": ["owner"],
                    "hidden": ["score"],
                    "automatic_fields": ["score"],
                    "semi_automatic_fields": [],
                    "manual_fields": ["owner"],
                    "ai_fields": ["tags"],
                    "tagged_fields": {"owner": "PEOPLE"},
                    "labels": {
                        "owner": {"en": ["Owner"]},
                        "score": {"en": ["Score"]},
                        "tags": {"en": ["Tags"]},
                    },
                    "main_label": "{owner}",
                    "sub_label": "{score}",
                    "display_thumbnail": True,
                    "external_source": False,
                    "dataset_metadata_config": {
                        "description": {
                            "type": "STRING",
                            "display_label": {"en": ["Description"]},
                            "value": {"en": ["Example"]},
                        }
                    },
                },
            }
        )
    )
    dataframe = pd.DataFrame(
        {
            "tags": [["a"], ["b"]],
            "owner": ["Ada", None],
            "score": [1.5, 2.5],
            "ignored": ["x", "y"],
        }
    )

    dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
        str(config_path), dataframe, sources=["manifest"], ds_id="invalid"
    )
    fields = {field.id: field for field in dataset.configuration.metadata_field_config}

    assert UUIDManager.is_valid_uuid(dataset.id)
    assert list(fields) == ["owner", "score", "tags"]
    assert fields["owner"].nullable is True
    assert fields["owner"].indexable is True
    assert fields["owner"].tag is MetadataTag.PEOPLE
    assert fields["owner"].paradata is ParadataValues.MANUAL
    assert fields["score"].type is MetadataType.FLOAT
    assert fields["score"].hidden is True
    assert fields["tags"].type is MetadataType.LIST
    assert fields["tags"].paradata is ParadataValues.AI
    assert dataset.has_areas == [area_id]
    assert dataset.time_range.end_time == "1809-12-31T23:59:59"
    assert dataset.sources == ["manifest"]


def test_dataset_instantiates_related_records_and_observations(entity_graph):
    dataset = entity_graph["dataset"]
    dataset.instantiate_all_rde_members(entity_graph["all"])

    assert dataset.hrs == [entity_graph["historical_record"]]
    assert dataset.obs == [entity_graph["observation"]]


def test_historical_record_constructors_reference_actualization_and_flattening():
    observation = Observation(
        id=uid(52),
        historical_record=uid(51),
        geometry=Point(0, 0),
    )
    raw = {
        "id": f"https://example.test/hr/{uid(51)}",
        "dataset": {"id": uid(50)},
        "start_time": "1808-01-01",
        "end_time": "1808-12-31",
        "paradata": "m",
        "has_observations": [observation.id],
        "metadata": {"owner": "Ada"},
    }
    record = HistoricalRecord.constructor_from_json_obj(raw)
    record.actualize_observations_references({observation.id: observation})

    assert record.dataset == uid(50)
    assert record.paradata is ParadataValues.MANUAL
    assert record.has_observations == [observation]
    assert record.to_dict(flatten_metadata=True)["owner"] == "Ada"
    assert "metadata" not in record.to_dict(flatten_metadata=True)


def test_historical_record_constructor_from_dataframe_row():
    row = pd.Series(
        {
            "uuid": uid(60),
            "dataset": uid(61),
            "start_time": "1900-01-01",
            "end_time": "1900-12-31",
            "paradata": "a",
            "has_observations": [],
            "rights_attribution": "Public domain",
            "owner": "Grace",
        }
    )
    record = HistoricalRecord.constructor_from_dataframe_row(row)

    assert record.id == uid(60)
    assert record.paradata is ParadataValues.AUTOMATIC
    assert record.metadata == {"owner": "Grace"}


def test_point_of_interest_supports_flat_and_geojson_feature_shapes():
    flat = {
        "id": uid(70),
        "geometry": {"type": "Point", "coordinates": [7, 46]},
        "terrain_height": 12,
        "building_height": 3,
    }
    feature = {
        "type": "Feature",
        "geometry": flat["geometry"],
        "properties": {key: value for key, value in flat.items() if key != "geometry"},
    }

    for raw in (flat, feature):
        point = PointOfInterest.constructor_from_json_obj(raw)
        assert point.geometry.equals(Point(7, 46))
        assert point.height == HeightInfo(12, 3)
        assert point.to_dict()["geometry"]["type"] == "Point"
        assert point.to_dict()["terrain_height"] == 12


def test_observation_supports_current_and_legacy_historical_record_fields(sample_object):
    raw = sample_object("observations.json")
    observation = Observation.constructor_from_json_obj(raw)
    legacy = Observation.constructor_from_json_obj(
        {
            "id": uid(81),
            "documented_in": [uid(82)],
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }
    )

    assert observation.historical_record == raw["historical_record"]
    assert observation.to_dict()["geometry"]["type"] == "Point"
    assert legacy.historical_record == uid(82)


def test_observation_actualizes_all_reference_types(entity_graph):
    observation = entity_graph["observation"]
    cache = {
        entity_graph["historical_record"].id: entity_graph["historical_record"],
        entity_graph["geometry"].id: entity_graph["geometry"],
        entity_graph["point_of_interest"].id: entity_graph["point_of_interest"],
    }
    observation.actualize_references(cache)

    assert observation.historical_record is entity_graph["historical_record"]
    assert observation.has_geometries == [entity_graph["geometry"]]
    assert observation.part_of_point_of_interest is entity_graph["point_of_interest"]


@pytest.mark.parametrize(
    "coordinates",
    [
        [],
        [0, 0, 1],
        [1, 0, 0, 1],
        [0, 1, 1, 0],
    ],
)
def test_geographical_extent_rejects_invalid_bounds(coordinates):
    with pytest.raises(AssertionError):
        GeographicalExtent(coordinates)


def test_map_constructor_and_serialization_use_sample_schema(sample_object):
    raw = sample_object("map.json")
    map_object = Map.constructor_from_json_obj(raw)

    assert map_object.extent is None
    assert map_object.layers == raw["layers"]
    assert map_object.to_dict() == map_object.to_dict()
    assert map_object.to_dict()["metadata"][0]["label"] == raw["metadata"][0]["label"]


def test_layer_configuration_and_layer_round_trip_sample_data(sample_object):
    raw = sample_object("layers.json")
    layer = Layer.constructor_from_json_obj(raw)
    serialized = layer.to_dict()

    assert layer.map == raw["map"]
    assert layer.type is LayerType.RASTER
    assert layer.layer_configurations[0].extent.coordinates == raw["layer_configurations"][0][
        "extent"
    ]
    assert serialized == layer.to_dict()
    assert serialized["layer_configurations"][0]["service"] == raw["layer_configurations"][0][
        "service"
    ]


def test_layer_configuration_defaults_without_extent():
    config = LayerConfiguration.constructor_from_json_obj(
        {"id": uid(90), "service": {"url": "https://tiles", "type": "xyz"}}
    )
    assert config.min_zoom_level == 0
    assert config.max_zoom_level == 22
    assert config.extent is None
    assert config.to_dict()["extent"] is None


def test_geometry_accepts_dicts_raw_geojson_and_can_repair_invalid_shapes(sample_object):
    raw = sample_object("geometries.json")
    geometry = Geometry.constructor_from_json_obj(raw)
    line = json.dumps(
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [1, 2]},
            "properties": {},
        }
    )
    from_line = Geometry.constructor_from_raw_geojson_line(line, uid(101), uid(102))
    invalid = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])

    assert geometry.id == raw["id"]
    assert geometry.part_of_layer == raw["part_of_layer"]
    assert geometry.to_dict()["geometry"]["type"] == raw["geometry"]["type"]
    assert from_line.geometry.equals(Point(1, 2))
    assert from_line.part_of_layer == uid(102)
    with pytest.raises(ValueError, match="Invalid geometry"):
        Geometry(id=uid(103), geometry=invalid)
    repaired = Geometry(id=uid(104), geometry=invalid, force_valid=True)
    assert repaired.geometry.is_valid


def test_geometry_rejects_invalid_uuid_even_with_custom_post_init():
    with pytest.raises(ValueError, match="Invalid UUID"):
        Geometry(id="invalid", geometry=Point(0, 0))


def test_area_constructor_uses_slug_and_json_safe_geometry(sample_object):
    raw = sample_object("city-venice-area.json")
    area = Area.constructor_from_json_obj(raw)

    assert area.slug == "city-venice-area"
    assert area.to_dict()["geometry"] == raw["geometry"]
    assert area.get_type() == RDEType.AREA.value
