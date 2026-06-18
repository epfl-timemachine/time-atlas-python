import importlib
import pickle
import uuid

import pytest
from shapely.geometry import Point, Polygon

from timeatlas import (
    Dataset,
    DatasetConfiguration,
    Geometry,
    HeightInfo,
    HistoricalRecord,
    MultiLingualValue,
    Observation,
    ParadataValues,
    PointOfInterest,
    RDETimeRange,
    TimeAtlas,
)


timeatlas_module = importlib.import_module("timeatlas.TimeAtlas")


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self._data = data
        self.status_code = status_code
        self.raise_calls = 0

    def json(self):
        return self._data

    def raise_for_status(self):
        self.raise_calls += 1
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def client():
    value = object.__new__(TimeAtlas)
    value.api_url = "https://api.example.test/v1"
    value.entity_cache = {}
    value.default_save_cache_filepath = "rde_entity_cache.pkl"
    return value


def test_client_initialization_normalizes_url_and_checks_health(monkeypatch, tmp_path):
    health = FakeResponse()
    monkeypatch.setattr(timeatlas_module.requests, "get", lambda url: health)
    monkeypatch.setattr(TimeAtlas, "default_save_cache_filepath", str(tmp_path / "missing.pkl"))

    client = TimeAtlas("https://api.example.test/v1/")

    assert client.api_url == "https://api.example.test/v1"
    assert client.entity_cache == {}


def test_client_initialization_loads_existing_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.pkl"
    cache_path.write_bytes(pickle.dumps({"cached": "value"}))
    monkeypatch.setattr(timeatlas_module.requests, "get", lambda url: FakeResponse())
    monkeypatch.setattr(TimeAtlas, "default_save_cache_filepath", str(cache_path))

    assert TimeAtlas("https://api.example.test/v1").entity_cache == {"cached": "value"}


def test_client_initialization_rejects_bad_url_before_network(monkeypatch):
    called = False

    def get(_):
        nonlocal called
        called = True

    monkeypatch.setattr(timeatlas_module.requests, "get", get)
    with pytest.raises(ValueError, match="must end with /v1"):
        TimeAtlas("https://api.example.test")
    assert called is False


def test_client_initialization_reports_unhealthy_api(monkeypatch, tmp_path):
    monkeypatch.setattr(
        timeatlas_module.requests, "get", lambda url: FakeResponse(status_code=503)
    )
    monkeypatch.setattr(TimeAtlas, "default_save_cache_filepath", str(tmp_path / "cache.pkl"))

    with pytest.raises(ConnectionError, match="Status code: 503"):
        TimeAtlas("https://api.example.test/v1")


def test_save_entity_cache_uses_explicit_and_default_paths(client, tmp_path):
    client.entity_cache = {"key": "value"}
    explicit = tmp_path / "explicit.pkl"
    default = tmp_path / "default.pkl"
    client.default_save_cache_filepath = str(default)

    client.save_entity_cache_to_file(str(explicit))
    client.save_entity_cache_to_file()

    assert pickle.loads(explicit.read_bytes()) == client.entity_cache
    assert pickle.loads(default.read_bytes()) == client.entity_cache


def test_get_single_rde_object_uses_cache_and_deserializes_response(
    client, monkeypatch, sample_object
):
    raw = sample_object("dataset.json")
    response = FakeResponse(raw)
    calls = []

    def get(url):
        calls.append(url)
        return response

    monkeypatch.setattr(timeatlas_module.requests, "get", get)
    result = client.get_single_rde_object("datasets", raw["id"])
    cached = client.get_single_rde_object("datasets", raw["id"])

    assert result is cached
    assert result.slug == raw["slug"]
    assert calls == [f"{client.api_url}/datasets/{raw['id']}"]
    assert response.raise_calls == 1


def test_get_single_rde_object_handles_geojson_rde_type(client, monkeypatch):
    raw = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0, 0]},
        "properties": {"id": uid(1), "rde_type": "geometry"},
    }
    monkeypatch.setattr(timeatlas_module.requests, "get", lambda url: FakeResponse(raw))

    result = client.get_single_rde_object("geometries", uid(1))

    assert isinstance(result, Geometry)
    assert result.geometry.equals(Point(0, 0))


def test_get_single_rde_object_rejects_unknown_type(client, monkeypatch):
    monkeypatch.setattr(
        timeatlas_module.requests,
        "get",
        lambda url: FakeResponse({"id": uid(2), "rde_type": "unknown"}),
    )
    with pytest.raises(ValueError, match="Unknown RDE type"):
        client.get_single_rde_object("unknown", uid(2))


def test_get_all_results_from_endpoint_follows_pagination(client, monkeypatch):
    responses = [
        FakeResponse({"items": [{"id": 1}], "next": "page-2"}),
        FakeResponse({"items": [{"id": 2}], "next": None}),
    ]
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)

    monkeypatch.setattr(timeatlas_module.requests, "get", get)

    assert client.get_all_results_from_endpoint("hr", per_page=25) == [{"id": 1}, {"id": 2}]
    assert [call[1]["params"]["page"] for call in calls] == [1, 2]
    assert all(call[1]["params"]["per_page"] == 25 for call in calls)
    assert all(call[1]["headers"] == {"Accept": "application/json"} for call in calls)


def test_get_dataset_delegates_to_single_object(client, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(client, "get_single_rde_object", lambda endpoint, value: sentinel)
    assert client.get_dataset(uid(3)) is sentinel


def test_get_dataset_by_slug_caches_match_and_reports_missing(
    client, monkeypatch, sample_object
):
    raw = sample_object("dataset.json")
    response = FakeResponse({"items": [raw]})
    monkeypatch.setattr(timeatlas_module.requests, "get", lambda *args, **kwargs: response)

    dataset = client.get_dataset_by_slug(raw["slug"])

    assert client.entity_cache[dataset.id] is dataset
    assert response.raise_calls == 1
    with pytest.raises(ValueError, match="not found"):
        client.get_dataset_by_slug("missing")


def test_generate_all_historical_records_populates_cache(client, monkeypatch):
    dataset = Dataset(
        id=uid(10),
        slug="demo",
        name=MultiLingualValue(),
        time_range=RDETimeRange("1900-01-01", "1900-12-31"),
        configuration=DatasetConfiguration(),
    )
    raw = {
        "id": uid(11),
        "dataset": dataset.id,
        "start_time": "1900-01-01",
        "end_time": "1900-12-31",
        "paradata": "m",
        "has_observations": [],
    }
    endpoints = []

    def get_all(endpoint, per_page):
        endpoints.append((endpoint, per_page))
        return [raw]

    monkeypatch.setattr(client, "get_all_results_from_endpoint", get_all)
    records = client.generate_all_hr_from_dataset(dataset)

    assert records[0].id == uid(11)
    assert client.entity_cache[uid(11)] is records[0]
    assert endpoints == [("hr/search?query=&dataset_slug=demo", 1000)]


def test_reference_generation_methods_deduplicate_ids(client, monkeypatch):
    observation_object = Observation(
        id=uid(21),
        historical_record=uid(20),
        geometry=Point(0, 0),
        has_geometries=[],
    )
    records = [
        HistoricalRecord(
            id=uid(20),
            dataset=uid(19),
            time_range=RDETimeRange("1900-01-01", "1900-12-31"),
            paradata=ParadataValues.MANUAL,
            has_observations=[observation_object.id, observation_object],
        )
    ]
    geometry_object = Geometry(
        id=uid(22), geometry=Polygon([(0, 0), (1, 0), (0, 1), (0, 0)])
    )
    point_object = PointOfInterest(
        id=uid(23), geometry=Point(0, 0), height=HeightInfo()
    )
    observations = [
        Observation(
            id=uid(24),
            historical_record=uid(20),
            geometry=Point(0, 0),
            has_geometries=[geometry_object.id, geometry_object],
            part_of_point_of_interest=point_object,
        )
    ]
    calls = []
    objects = {
        observation_object.id: observation_object,
        geometry_object.id: geometry_object,
        point_object.id: point_object,
    }

    def get_single(endpoint, value):
        calls.append((endpoint, value))
        return objects[value]

    monkeypatch.setattr(client, "get_single_rde_object", get_single)

    assert client.generate_obs_from_list_of_hr(records) == [observation_object]
    assert client.generate_geoms_from_list_of_obs(observations) == [geometry_object]
    assert client.generate_pois_from_list_of_obs(observations) == [point_object]
    assert set(calls) == {
        ("obs", observation_object.id),
        ("geometries", geometry_object.id),
        ("poi", point_object.id),
    }


def test_materialize_all_rde_actualizes_references(client, monkeypatch, entity_graph):
    dataset = entity_graph["dataset"]
    record = entity_graph["historical_record"]
    observation = entity_graph["observation"]
    geometry = entity_graph["geometry"]
    point = entity_graph["point_of_interest"]
    client.entity_cache = {
        record.id: record,
        observation.id: observation,
        geometry.id: geometry,
        point.id: point,
    }
    monkeypatch.setattr(client, "generate_all_hr_from_dataset", lambda value: [record])
    monkeypatch.setattr(client, "generate_obs_from_list_of_hr", lambda value: [observation])
    monkeypatch.setattr(client, "generate_geoms_from_list_of_obs", lambda value: [geometry])
    monkeypatch.setattr(client, "generate_pois_from_list_of_obs", lambda value: [point])

    result = client.materialize_all_rde_from_dataset_obj(dataset)

    assert result == [record, observation, geometry, point]
    assert record.has_observations == [observation]
    assert observation.has_geometries == [geometry]
    assert observation.part_of_point_of_interest is point


def test_materialize_by_slug_delegates(client, monkeypatch):
    dataset = object()
    monkeypatch.setattr(client, "get_dataset_by_slug", lambda slug: dataset)
    monkeypatch.setattr(
        client, "materialize_all_rde_from_dataset_obj", lambda value: ["materialized"]
    )
    assert client.materialize_all_rde_from_dataset_slug("demo") == ["materialized"]


def test_historical_record_list_to_dataframe(entity_graph):
    record = entity_graph["historical_record"]
    dataframe = TimeAtlas.hr_list_to_dataframe([record])

    assert dataframe.loc[0, "id"] == record.id
    assert dataframe.loc[0, "obj"] is record
    assert dataframe.loc[0, "rde_type"] == "historical_record"
