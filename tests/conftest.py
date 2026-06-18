import json
import uuid
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon

from timeatlas import (
    Dataset,
    DatasetConfiguration,
    Geometry,
    HeightInfo,
    HistoricalRecord,
    Layer,
    LayerType,
    Map,
    MultiLingualValue,
    Observation,
    ParadataValues,
    PointOfInterest,
    RDETimeRange,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "test" / "data"
FALLBACK_DATA = ROOT / "tests" / "fixtures" / "sample_rdes.json"


def uuid_str(value: int) -> str:
    return str(uuid.UUID(int=value))


def first_rde_object(path: Path) -> dict:
    """Read only the first object from a potentially very large RDE envelope."""
    marker = '"rde_objects"'
    decoder = json.JSONDecoder()
    buffer = ""
    found_array = False

    with path.open(encoding="utf-8") as stream:
        while chunk := stream.read(16_384):
            buffer += chunk
            if not found_array:
                marker_index = buffer.find(marker)
                if marker_index < 0:
                    buffer = buffer[-len(marker) :]
                    continue
                array_index = buffer.find("[", marker_index + len(marker))
                if array_index < 0:
                    continue
                buffer = buffer[array_index + 1 :]
                found_array = True

            candidate = buffer.lstrip()
            try:
                value, _ = decoder.raw_decode(candidate)
                return value
            except json.JSONDecodeError:
                continue

    raise ValueError(f"No RDE object found in {path}")


@pytest.fixture
def sample_object():
    fallback = json.loads(FALLBACK_DATA.read_text(encoding="utf-8"))

    def load(filename: str) -> dict:
        path = DATA_DIR / filename
        return first_rde_object(path) if path.exists() else fallback[filename]

    return load


@pytest.fixture
def entity_graph():
    dataset = Dataset(
        id=uuid_str(1),
        slug="demo",
        name=MultiLingualValue({"en": ["Demo"]}),
        time_range=RDETimeRange("1900-01-01T00:00:00", "1900-12-31T23:59:59"),
        configuration=DatasetConfiguration(),
    )
    historical_record = HistoricalRecord(
        id=uuid_str(2),
        dataset=dataset.id,
        time_range=RDETimeRange("1900-01-01T00:00:00", "1900-12-31T23:59:59"),
        paradata=ParadataValues.MANUAL,
        has_observations=[uuid_str(3)],
        metadata={"title": "Record"},
    )
    geometry = Geometry(
        id=uuid_str(4),
        geometry=Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]),
    )
    point_of_interest = PointOfInterest(
        id=uuid_str(5),
        geometry=Point(0.25, 0.25),
        height=HeightInfo(terrain=10.0, building=4.0),
    )
    observation = Observation(
        id=uuid_str(3),
        historical_record=historical_record.id,
        geometry=Point(0.25, 0.25),
        has_geometries=[geometry.id],
        part_of_point_of_interest=point_of_interest.id,
    )
    map_object = Map(
        id=uuid_str(6),
        name=MultiLingualValue({"en": ["Map"]}),
        slug="map",
        time_range=RDETimeRange("1900-01-01T00:00:00", "1900-12-31T23:59:59"),
        layers=[uuid_str(7)],
    )
    layer = Layer(
        id=uuid_str(7),
        slug="layer",
        name=MultiLingualValue({"en": ["Layer"]}),
        description=MultiLingualValue({"en": ["Description"]}),
        time_range=RDETimeRange("1900-01-01T00:00:00", "1900-12-31T23:59:59"),
        map=map_object.id,
        type=LayerType.VECTOR,
    )
    return {
        "dataset": dataset,
        "historical_record": historical_record,
        "observation": observation,
        "geometry": geometry,
        "point_of_interest": point_of_interest,
        "map": map_object,
        "layer": layer,
        "all": [
            dataset,
            historical_record,
            observation,
            geometry,
            point_of_interest,
            map_object,
            layer,
        ],
    }
