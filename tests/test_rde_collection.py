import copy
import importlib
import json
import uuid
import warnings
from datetime import datetime

import pytest
from shapely.geometry import Point, Polygon

from timeatlas import (
    Area,
    Dataset,
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


def test_collection_save_adds_dataset_slug_only_to_dataset_scoped_files(
    tmp_path, entity_graph
):
    collection = RDECollection(entity_graph["all"])
    collection.save_rde_to_files(str(tmp_path))

    for filename in (
        "dataset.json",
        "historical_records.json",
        "observations.json",
        "points_of_interest.json",
    ):
        assert json.loads((tmp_path / filename).read_text())["related_dataset_slugs"] == [
            "demo"
        ]
    for filename in ("geometries.json", "maps.json", "layers.json"):
        assert "related_dataset_slugs" not in json.loads(
            (tmp_path / filename).read_text()
        )


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


def test_collection_save_jsonl_matches_individual_envelopes(
    tmp_path, entity_graph, monkeypatch
):
    class FixedDateTime:
        @staticmethod
        def now():
            return datetime(2026, 7, 23, 12, 0, 0)

    monkeypatch.setattr(timeatlas_module, "datetime", FixedDateTime)
    collection = RDECollection(entity_graph["all"])
    individual_dir = tmp_path / "individual"
    collection.save_rde_to_files(str(individual_dir))

    package = collection.save_rde_to_jsonl(tmp_path / "package")
    lines = package.read_text(encoding="utf-8").splitlines()
    packaged_envelopes = [json.loads(line) for line in lines]
    individual_envelopes = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in individual_dir.glob("*.json")
    }

    assert package.name == "package.jsonl"
    assert len(lines) == len(individual_envelopes)
    assert {envelope["name"] for envelope in packaged_envelopes} == set(
        individual_envelopes
    )
    for envelope in packaged_envelopes:
        assert envelope == individual_envelopes[envelope["name"]]


def test_collection_save_jsonl_filters_types_and_checks_overwrite(
    tmp_path, entity_graph
):
    collection = RDECollection(entity_graph["all"])
    package = collection.save_rde_to_jsonl(
        tmp_path / "selected.jsonl",
        rde_types=[Dataset, Observation],
        dataset_slug="selected",
    )
    envelopes = [
        json.loads(line)
        for line in package.read_text(encoding="utf-8").splitlines()
    ]

    assert [envelope["name"] for envelope in envelopes] == [
        "observations",
        "dataset",
    ]
    assert all(
        envelope["related_dataset_slugs"] == ["selected"]
        for envelope in envelopes
    )
    with pytest.raises(FileExistsError):
        collection.save_rde_to_jsonl(package)
    assert collection.save_rde_to_jsonl(package, overwrite=True) == package


def test_collection_read_filters_types_before_deserialization(tmp_path, entity_graph):
    RDECollection(entity_graph["all"]).save_rde_to_files(str(tmp_path))

    restored = RDECollection.read_rde_from_files(
        str(tmp_path),
        rde_types=[Map, Observation],
    )

    assert {type(item) for item in restored.rdes} == {Map, Observation}
    assert {item.id for item in restored.rdes} == {
        entity_graph["map"].id,
        entity_graph["observation"].id,
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


def test_envelope_writer_validates_objects_sizes_and_existing_files(tmp_path):
    writer = RDEEnvelopeWriter(tmp_path)
    path = writer.write("existing", [{"id": uid(1)}], None, "dataset")

    assert writer.write(
        path, [{"id": uid(1)}], None, "dataset", overwrite=False, skip_if_unchanged=True
    ) == path
    with pytest.raises(FileExistsError):
        writer.write(path, [], None, "dataset", overwrite=False)
    with pytest.raises(FileExistsError):
        writer.write_stream(path, [], None, "dataset", overwrite=False)
    with pytest.raises(TypeError, match="Unsupported"):
        writer.serialize_object(object())
    with pytest.raises(ValueError, match="max_size_bytes"):
        writer.write_batches_by_size("batch", [], None, "dataset", 0)
    assert writer.write_batches_by_size("batch", [], None, "dataset", 100) == []


def test_envelope_writer_writes_jsonl_batches_by_size(tmp_path, entity_graph):
    writer = RDEEnvelopeWriter(tmp_path)
    objects = []
    for index in range(10):
        geom = copy.deepcopy(entity_graph["geometry"])
        geom.id = uid(300 + index)
        objects.append(geom)

    paths = writer.write_jsonl_batches_by_size(
        "iiif/manifests",
        objects,
        max_size_bytes=350,
        start_index=1,
    )

    assert len(paths) > 1
    assert paths[0].name == "manifests_1.jsonl"
    assert all(path.suffix == ".jsonl" for path in paths)
    for path in paths:
        assert path.stat().st_size <= 350
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        assert lines
        for line in lines:
            obj = json.loads(line)
            assert obj["geometry"]["type"] == "Polygon"


def test_envelope_writer_jsonl_validates_size_and_overwrite(tmp_path):
    writer = RDEEnvelopeWriter(tmp_path)
    with pytest.raises(ValueError, match="max_size_bytes"):
        writer.write_jsonl_batches_by_size("manifests", [{"id": uid(1)}], 0)

    writer.write_jsonl_batches_by_size("manifests", [{"id": uid(1)}], 100)
    with pytest.raises(FileExistsError):
        writer.write_jsonl_batches_by_size(
            "manifests",
            [{"id": uid(2)}],
            100,
            overwrite=False,
        )


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


def test_collection_aggregates_observations_and_replaces_obsolete_pois(entity_graph):
    first = entity_graph["observation"]
    obsolete_poi = entity_graph["point_of_interest"]
    first.part_of_point_of_interest = obsolete_poi
    same_location = copy.deepcopy(first)
    same_location.id = uid(30)
    same_location.geometry = Point(0.250004, 0.250004)
    another_location = copy.deepcopy(first)
    another_location.id = uid(31)
    another_location.geometry = Point(0.3, 0.4)
    unrelated_poi = copy.deepcopy(obsolete_poi)
    unrelated_poi.id = uid(32)
    collection = RDECollection(
        [first, same_location, another_location, obsolete_poi, unrelated_poi]
    )

    pois = collection.aggregate_observations_into_points_of_interest()

    expected_first_id = str(
        uuid.uuid5(RDECollection._POI_NAMESPACE, "poi_0.25_0.25")
    )
    assert [poi.id for poi in pois] == [
        expected_first_id,
        str(uuid.uuid5(RDECollection._POI_NAMESPACE, "poi_0.3_0.4")),
    ]
    assert first.part_of_point_of_interest == expected_first_id
    assert same_location.part_of_point_of_interest == expected_first_id
    assert another_location.part_of_point_of_interest == pois[1].id
    collection_poi_ids = {
        item.id for item in collection.rdes if type(item) is type(obsolete_poi)
    }
    assert obsolete_poi.id not in collection_poi_ids
    assert unrelated_poi.id in collection_poi_ids
    assert collection._valid_data is False


def test_collection_aggregation_reuses_generated_poi_and_is_idempotent(entity_graph):
    observation = entity_graph["observation"]
    poi = entity_graph["point_of_interest"]
    poi.id = str(uuid.uuid5(RDECollection._POI_NAMESPACE, "poi_0.25_0.25"))
    observation.part_of_point_of_interest = poi.id
    collection = RDECollection([observation, poi])

    assert collection.aggregate_observations_into_points_of_interest() == [poi]
    assert collection.aggregate_observations_into_points_of_interest() == [poi]
    assert poi.height.terrain == 10.0
    assert len([item for item in collection.rdes if type(item) is type(poi)]) == 1


def test_collection_aggregation_skips_non_participating_observations(entity_graph):
    disabled = copy.deepcopy(entity_graph["observation"])
    disabled.part_of_point_of_interest = False
    missing_geometry = copy.deepcopy(entity_graph["observation"])
    missing_geometry.id = uid(33)
    missing_geometry.geometry = None
    empty_geometry = copy.deepcopy(entity_graph["observation"])
    empty_geometry.id = uid(34)
    empty_geometry.geometry = Point()
    collection = RDECollection([disabled, missing_geometry, empty_geometry])

    assert collection.aggregate_observations_into_points_of_interest() == []
    assert all(
        observation.part_of_point_of_interest is None
        for observation in (disabled, missing_geometry, empty_geometry)
    )


def test_collection_aggregation_rejects_invalid_inputs(entity_graph):
    collection = RDECollection([entity_graph["observation"]])
    with pytest.raises(ValueError, match="coordinate_precision"):
        collection.aggregate_observations_into_points_of_interest(-1)

    entity_graph["observation"].geometry = entity_graph["geometry"].geometry
    with pytest.raises(ValueError, match="must have a Point geometry"):
        collection.aggregate_observations_into_points_of_interest()


def test_collection_validation_accepts_complete_graph_and_marks_it_valid(entity_graph):
    collection = RDECollection(entity_graph["all"])
    with pytest.warns(UserWarning, match="ad-hoc Area"):
        assert collection.validate_data() is True
    assert collection._valid_data is True
    area = next(item for item in collection.rdes if isinstance(item, Area))
    assert entity_graph["dataset"].has_areas == [area.id]
    assert area.geometry.equals(
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    )


def test_collection_produces_deterministic_padded_area_from_point_extent(entity_graph):
    collection = RDECollection(
        [entity_graph["dataset"], entity_graph["observation"]]
    )

    first = collection.produce_area_from_current_extent()
    second = collection.produce_area_from_current_extent()

    assert first is second
    assert first.geometry.geom_type == "Polygon"
    assert first.geometry.contains(entity_graph["observation"].geometry)
    assert len([item for item in collection.rdes if isinstance(item, Area)]) == 1
    assert entity_graph["dataset"].has_areas == [first.id]


def test_collection_extent_area_serializes_with_dataset_slug(tmp_path, entity_graph):
    collection = RDECollection(entity_graph["all"])
    with pytest.warns(UserWarning, match="ad-hoc Area"):
        collection.validate_data()
    collection.save_rde_to_files(str(tmp_path))

    area_envelope = json.loads((tmp_path / "areas.json").read_text())
    assert "related_dataset_slugs" not in area_envelope
    assert area_envelope["rde_objects"][0]["id"] == entity_graph["dataset"].has_areas[0]


def test_collection_extent_area_requires_spatial_data_and_valid_dataset(entity_graph):
    collection = RDECollection([entity_graph["dataset"]])
    with pytest.raises(ValueError, match="no observation or Geometry extent"):
        collection.produce_area_from_current_extent()
    with pytest.warns(UserWarning, match="ad-hoc Area"):
        with pytest.raises(ValueError, match="no observation or Geometry extent"):
            collection.validate_data()

    with pytest.raises(ValueError, match="must be present"):
        RDECollection([]).produce_area_from_current_extent(entity_graph["dataset"])
    with pytest.raises(ValueError, match="exactly one Dataset"):
        RDECollection([]).produce_area_from_current_extent()
    with pytest.raises(ValueError, match="padding"):
        collection.produce_area_from_current_extent(padding=0)


def test_collection_validation_warns_for_areas_missing_from_collection(entity_graph):
    entity_graph["dataset"].has_areas = [uid(120)]
    with pytest.warns(UserWarning, match="target backend"):
        assert RDECollection(entity_graph["all"]).validate_data() is True


def test_collection_validation_accepts_referenced_area_in_collection(entity_graph):
    area = Area(
        id=uid(120),
        slug="existing-area",
        name=entity_graph["dataset"].name,
        geometry=Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]),
    )
    entity_graph["dataset"].has_areas = [area.id]
    collection = RDECollection(entity_graph["all"] + [area])

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert collection.validate_data() is True
    assert [item for item in collection.rdes if isinstance(item, Area)] == [area]


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
