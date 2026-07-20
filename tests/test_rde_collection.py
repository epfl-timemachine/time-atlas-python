import copy
import importlib
import json
import uuid
from datetime import datetime

import pytest
from shapely.geometry import Point

from timeatlas import (
    Geometry,
    HistoricalRecord,
    Map,
    Observation,
    RDE,
    RDECollection,
    RDEEnvelopeWriter,
)
from timeatlas.TimeAtlas import _ShapelyEncoder


timeatlas_module = importlib.import_module("timeatlas.TimeAtlas")


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


def test_collection_add_accepts_single_entities_and_lists(entity_graph):
    collection = RDECollection([])
    collection.add(entity_graph["dataset"])
    collection.add([entity_graph["historical_record"], entity_graph["observation"]])
    assert collection.rdes == [
        entity_graph["dataset"],
        entity_graph["historical_record"],
        entity_graph["observation"],
    ]


def test_shapely_encoder_serializes_geometry_and_delegates_unknown_values():
    assert json.loads(json.dumps(Point(1, 2), cls=_ShapelyEncoder)) == {
        "type": "Point",
        "coordinates": [1.0, 2.0],
    }
    with pytest.raises(TypeError):
        json.dumps(object(), cls=_ShapelyEncoder)


def test_collection_save_and_read_round_trip_all_supported_entity_types(
    tmp_path, entity_graph
):
    collection = RDECollection(entity_graph["all"])
    collection.save_rde_to_files(str(tmp_path))

    expected_files = {
        "dataset.json",
        "historical_records.json",
        "observations.json",
        "points_of_interest.json",
        "geometries.json",
        "maps.json",
        "layers.json",
    }
    assert {path.name for path in tmp_path.glob("*.json")} == expected_files

    restored = RDECollection.read_rde_from_files(str(tmp_path))
    assert {type(item) for item in restored.rdes} == {type(item) for item in entity_graph["all"]}
    assert {item.id for item in restored.rdes} == {item.id for item in entity_graph["all"]}


def test_collection_save_is_idempotent_unless_overwrite_is_requested(
    tmp_path, entity_graph, monkeypatch
):
    class InitialDateTime:
        @staticmethod
        def now():
            return datetime(2020, 1, 1)

    class LaterDateTime:
        @staticmethod
        def now():
            return datetime(2021, 1, 1)

    collection = RDECollection([entity_graph["geometry"]])
    monkeypatch.setattr(timeatlas_module, "datetime", InitialDateTime)
    collection.save_rde_to_files(str(tmp_path))
    path = tmp_path / "geometries.json"
    initial = json.loads(path.read_text())

    monkeypatch.setattr(timeatlas_module, "datetime", LaterDateTime)
    collection.save_rde_to_files(str(tmp_path))
    unchanged = json.loads(path.read_text())
    collection.save_rde_to_files(str(tmp_path), overwrite=True)
    overwritten = json.loads(path.read_text())

    assert unchanged["creation_time"] == initial["creation_time"]
    assert overwritten["creation_time"] == "2021-01-01T00:00:00"


def test_collection_save_infers_dataset_slug_for_dataset_tied_files(
    tmp_path, entity_graph
):
    collection = RDECollection(
        [
            entity_graph["dataset"],
            entity_graph["historical_record"],
            entity_graph["observation"],
        ]
    )

    collection.save_rde_to_files(str(tmp_path))

    for filename in ("dataset.json", "historical_records.json", "observations.json"):
        envelope = json.loads((tmp_path / filename).read_text())
        assert envelope["related_dataset_slugs"] == ["demo"]


def test_collection_save_adds_dataset_slug_to_every_resource_file(
    tmp_path, entity_graph
):
    collection = RDECollection(entity_graph["all"])
    collection.save_rde_to_files(str(tmp_path))

    for path in tmp_path.glob("*.json"):
        assert json.loads(path.read_text())["related_dataset_slugs"] == ["demo"]


def test_collection_save_rewrites_when_only_related_dataset_slugs_change(
    tmp_path, entity_graph
):
    collection = RDECollection([entity_graph["dataset"]])
    collection.save_rde_to_files(str(tmp_path), dataset_slug="old-slug")

    collection.save_rde_to_files(str(tmp_path), dataset_slug="demo")

    envelope = json.loads((tmp_path / "dataset.json").read_text())
    assert envelope["related_dataset_slugs"] == ["demo"]


def test_collection_save_filters_types_and_skips_unknown_rdes(tmp_path, entity_graph):
    collection = RDECollection(entity_graph["all"] + [RDE()])
    collection.save_rde_to_files(
        str(tmp_path), rde_types=[HistoricalRecord, Observation]
    )
    assert {path.name for path in tmp_path.glob("*.json")} == {
        "historical_records.json",
        "observations.json",
    }


def test_envelope_writer_writes_dicts_and_rdes(tmp_path, entity_graph):
    writer = RDEEnvelopeWriter(tmp_path)
    path = writer.write(
        "mixed",
        [entity_graph["geometry"], entity_graph["dataset"].to_dict()],
        "mixed_name",
        ["geom", "dataset"],
    )

    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["name"] == "mixed_name"
    assert envelope["type_in_file"] == ["geom", "dataset"]
    assert envelope["rde_objects"][0]["geometry"]["type"] == "Polygon"
    assert envelope["rde_objects"][1]["id"] == entity_graph["dataset"].id


def test_envelope_writer_streams_iterables(tmp_path, entity_graph):
    writer = RDEEnvelopeWriter(tmp_path)
    path = writer.write_stream(
        "geometries",
        (copy.deepcopy(entity_graph["geometry"]) for _ in range(2)),
        "geometries",
        "geom",
    )

    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["type_in_file"] == ["geom"]
    assert len(envelope["rde_objects"]) == 2


def test_envelope_writer_batches_by_estimated_json_size(tmp_path, entity_graph):
    writer = RDEEnvelopeWriter(tmp_path)
    objects = []
    for index in range(6):
        geom = copy.deepcopy(entity_graph["geometry"])
        geom.id = uid(200 + index)
        objects.append(geom)

    paths = writer.write_batches_by_size(
        "geometries_batch",
        objects,
        "demo_geometries_batch",
        "geom",
        max_size_bytes=450,
        start_index=0,
    )

    assert len(paths) > 1
    assert paths[0].name == "geometries_batch_0.json"
    assert paths[1].name == "geometries_batch_1.json"
    assert json.loads(paths[0].read_text(encoding="utf-8"))["name"] == "demo_geometries_batch_0"


def test_collection_read_ignores_non_json_unknown_and_empty_envelopes(tmp_path):
    (tmp_path / "notes.txt").write_text("ignored")
    (tmp_path / "unknown.json").write_text(
        json.dumps({"rde_objects": [{"id": uid(1), "rde_type": "unknown"}]})
    )
    (tmp_path / "empty.json").write_text(json.dumps({"rde_objects": []}))
    assert RDECollection.read_rde_from_files(str(tmp_path)).rdes == []


def test_collection_read_propagates_malformed_json(tmp_path):
    (tmp_path / "broken.json").write_text("{")
    with pytest.raises(json.JSONDecodeError):
        RDECollection.read_rde_from_files(str(tmp_path))


def test_collection_read_requires_existing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        RDECollection.read_rde_from_files(str(tmp_path / "missing"))


def test_collection_consolidates_observations_and_serializes_pois(tmp_path, entity_graph):
    first = entity_graph["observation"]
    first.part_of_point_of_interest = True
    second = copy.deepcopy(first)
    second.id = uid(30)
    second.geometry = Point(0.250004, 0.250004)
    third = copy.deepcopy(first)
    third.id = uid(31)
    third.geometry = Point(0.3, 0.4)

    collection = RDECollection(
        [
            item
            for item in entity_graph["all"]
            if item is not entity_graph["point_of_interest"]
        ]
        + [second, third]
    )
    pois = collection.consolidate_data()

    expected_first_poi = str(
        uuid.uuid5(
            RDECollection._POI_NAMESPACE,
            "poi_0.25_0.25",
        )
    )
    assert len(pois) == 2
    assert first.part_of_point_of_interest == expected_first_poi
    assert second.part_of_point_of_interest == expected_first_poi
    assert third.part_of_point_of_interest == pois[1].id
    assert [poi for poi in collection.rdes if type(poi) is type(pois[0])] == pois

    collection.save_rde_to_files(str(tmp_path))
    saved_pois = json.loads((tmp_path / "points_of_interest.json").read_text())
    saved_observations = json.loads((tmp_path / "observations.json").read_text())
    assert len(saved_pois["rde_objects"]) == 2
    assert {
        observation["part_of_point_of_interest"]
        for observation in saved_observations["rde_objects"]
    } == {expected_first_poi, pois[1].id}


def test_collection_consolidation_skips_false_and_missing_geometry(entity_graph):
    without_poi = copy.deepcopy(entity_graph["observation"])
    without_poi.id = uid(32)
    without_poi.part_of_point_of_interest = False
    without_geometry = copy.deepcopy(entity_graph["observation"])
    without_geometry.id = uid(33)
    without_geometry.geometry = None

    collection = RDECollection([without_poi, without_geometry])
    assert collection.consolidate_data() == []
    assert without_poi.part_of_point_of_interest is None
    assert without_geometry.part_of_point_of_interest is None


def test_collection_consolidation_is_idempotent_and_preserves_heights(entity_graph):
    observation = entity_graph["observation"]
    poi = entity_graph["point_of_interest"]
    poi.id = str(uuid.uuid5(RDECollection._POI_NAMESPACE, "poi_0.25_0.25"))
    observation.part_of_point_of_interest = poi
    collection = RDECollection([observation, poi])

    first_result = collection.consolidate_data()
    second_result = collection.consolidate_data()

    assert first_result == [poi]
    assert second_result == [poi]
    assert poi.height.terrain == 10.0
    assert len([item for item in collection.rdes if type(item) is type(poi)]) == 1


def test_collection_consolidation_replaces_obsolete_poi_and_keeps_unrelated_one(
    entity_graph,
):
    observation = entity_graph["observation"]
    obsolete_poi = entity_graph["point_of_interest"]
    unrelated_poi = copy.deepcopy(obsolete_poi)
    unrelated_poi.id = uid(34)
    observation.part_of_point_of_interest = obsolete_poi.id
    collection = RDECollection([observation, obsolete_poi, unrelated_poi])

    generated = collection.consolidate_data()
    collection_poi_ids = {
        item.id for item in collection.rdes if type(item) is type(obsolete_poi)
    }

    assert generated[0].id in collection_poi_ids
    assert obsolete_poi.id not in collection_poi_ids
    assert unrelated_poi.id in collection_poi_ids


def test_collection_consolidation_skips_empty_point(entity_graph):
    observation = entity_graph["observation"]
    observation.geometry = Point()
    collection = RDECollection([observation])

    assert collection.consolidate_data() == []
    assert observation.part_of_point_of_interest is None


def test_collection_consolidation_rejects_invalid_inputs(entity_graph):
    collection = RDECollection([entity_graph["observation"]])
    with pytest.raises(ValueError, match="coordinate_precision"):
        collection.consolidate_data(-1)

    entity_graph["observation"].geometry = entity_graph["geometry"].geometry
    with pytest.raises(ValueError, match="must have a Point geometry"):
        collection.consolidate_data()


def test_collection_validation_accepts_complete_graph_and_marks_it_valid(entity_graph):
    collection = RDECollection(entity_graph["all"])
    assert collection.validate_data() is True
    assert collection._valid_data is True


def test_collection_validation_accepts_materialized_object_references(entity_graph):
    graph = entity_graph
    graph["historical_record"].has_observations = [graph["observation"]]
    graph["observation"].historical_record = graph["historical_record"]
    graph["observation"].has_geometries = [graph["geometry"]]
    graph["observation"].part_of_point_of_interest = graph["point_of_interest"]
    graph["map"].layers = [graph["layer"]]
    graph["layer"].map = graph["map"]

    assert RDECollection(graph["all"]).validate_data() is True


def test_collection_validation_reports_global_duplicate_ids(entity_graph):
    duplicate = copy.deepcopy(entity_graph["geometry"])
    collection = RDECollection(entity_graph["all"] + [duplicate])
    with pytest.raises(ValueError, match="Duplicate UUIDs found"):
        collection.validate_data()


@pytest.mark.parametrize(
    ("entity_name", "field_name", "duplicate_id", "message"),
    [
        ("historical_record", "has_observations", uid(3), "duplicate UUIDs in has_observations"),
        ("observation", "has_geometries", uid(4), "duplicate UUIDs in has_geometries"),
        ("map", "layers", uid(7), "duplicate UUIDs in layers"),
    ],
)
def test_collection_validation_reports_duplicate_array_references(
    entity_graph, entity_name, field_name, duplicate_id, message
):
    setattr(entity_graph[entity_name], field_name, [duplicate_id, duplicate_id])
    with pytest.raises(ValueError, match=message):
        RDECollection(entity_graph["all"]).validate_data()


@pytest.mark.parametrize(
    ("entity_name", "field_name", "missing_id", "message"),
    [
        ("historical_record", "dataset", uid(100), "references missing Dataset"),
        (
            "historical_record",
            "has_observations",
            [uid(101)],
            "references missing Observation",
        ),
        ("observation", "historical_record", uid(102), "references missing HistoricalRecord"),
        (
            "observation",
            "part_of_point_of_interest",
            uid(103),
            "references missing PointOfInterest",
        ),
        ("observation", "has_geometries", [uid(104)], "references missing Geometry"),
        ("layer", "map", uid(105), "references missing Map"),
        ("map", "layers", [uid(106)], "references missing Layer"),
    ],
)
def test_collection_validation_reports_stale_references(
    entity_graph, entity_name, field_name, missing_id, message
):
    setattr(entity_graph[entity_name], field_name, missing_id)
    with pytest.raises(ValueError, match=message):
        RDECollection(entity_graph["all"]).validate_data()


def test_collection_validation_exempts_external_area_and_layer_references(entity_graph):
    entity_graph["dataset"].has_areas = [uid(120)]
    entity_graph["geometry"].part_of_layer = uid(121)
    entity_graph["map"].areas = [uid(122)]
    assert RDECollection(entity_graph["all"]).validate_data() is True


def test_collection_validation_ignores_boolean_unresolved_poi_flag(entity_graph):
    entity_graph["observation"].part_of_point_of_interest = False
    without_poi = [
        item for item in entity_graph["all"] if item is not entity_graph["point_of_interest"]
    ]
    assert RDECollection(without_poi).validate_data() is True


def test_collection_validation_raw_mode_accepts_legacy_null_geometries(entity_graph):
    entity_graph["observation"].has_geometries = None

    with pytest.raises(ValueError, match="has_geometries is null"):
        RDECollection(entity_graph["all"]).validate_data()

    assert RDECollection(entity_graph["all"]).validate_data(mode="raw") is True


def test_collection_validation_can_allow_unresolved_poi_refs(entity_graph):
    entity_graph["observation"].part_of_point_of_interest = uid(500)
    without_poi = [
        item for item in entity_graph["all"] if item is not entity_graph["point_of_interest"]
    ]

    with pytest.raises(ValueError, match="references missing PointOfInterest"):
        RDECollection(without_poi).validate_data()

    assert RDECollection(without_poi).validate_data(allow_unresolved_poi=True) is True
