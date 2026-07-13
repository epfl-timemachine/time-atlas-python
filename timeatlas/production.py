from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .RDEModel import RDETimeRange, UUIDManager


def csv_seed(row: pd.Series, cols: Sequence[str], suffix: str = "") -> str:
    """Return the legacy CSV-serialized UUID seed for selected row columns."""
    buf = io.StringIO()
    row[list(cols)].to_csv(buf, index=False, header=False)
    return buf.getvalue() + suffix


def find_layer_uuid(layer_fp: str | Path, slug_part: str) -> str:
    """Return the unique layer UUID whose slug contains *slug_part*."""
    with open(layer_fp, encoding="utf-8") as f:
        layers = json.load(f)["rde_objects"]
    matches = [(layer["slug"], layer["id"]) for layer in layers if slug_part in layer["slug"]]
    if len(matches) != 1:
        raise ValueError(
            f'Expected exactly 1 layer matching "{slug_part}", found {len(matches)}: {matches}'
        )
    return matches[0][1]


def find_latest_file(prefix: str | Path, ext: str) -> str:
    """Return the lexically latest recursive match for ``<prefix>*.<ext>``."""
    prefix = str(prefix)
    name = prefix.split("/")[-1]
    path_prefix = prefix[: -len(name)] or "."
    matches = list(Path(path_prefix).rglob(f"{name}*.{ext}"))
    if not matches:
        raise FileNotFoundError(f'No file matching "{name}*.{ext}" under {path_prefix}')
    return str(max(matches, key=lambda path: (path.name, str(path))))


def clean_metadata(raw: dict) -> dict:
    """Normalize metadata values for JSON/RDE output."""
    cleaned = {}
    for key, value in raw.items():
        if isinstance(value, (list, tuple, np.ndarray, pd.Series)):
            value_list = value.tolist() if isinstance(value, (np.ndarray, pd.Series)) else list(value)
            cleaned[key] = value_list
        elif pd.isna(value) if not isinstance(value, (list, np.ndarray)) else False:
            cleaned[key] = None
        elif str(value).lower() == "nan":
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned


def get_area_uuids(area_locs: Sequence[str | Path]) -> list[str]:
    """Read the first RDE UUID from each area ingestion file."""
    area_uuids = []
    for loc in area_locs:
        with open(Path(loc), encoding="utf-8") as f:
            area_uuids.append(json.load(f)["rde_objects"][0]["id"])
    return area_uuids


_COMPACT_DATE_FMT = "%Y%m%d"


def datetime_from_int(date_val: int | str, match_to_end: bool = False) -> str:
    """Convert an integer/string date (YYYYMMDD or YYYY) to ISO-8601."""
    date_val = str(date_val)
    if len(date_val) in (3, 7):
        date_val = "0" + date_val
    if len(date_val) == 8:
        date = datetime.strptime(date_val, _COMPACT_DATE_FMT)
        if match_to_end:
            date = date.replace(hour=23, minute=59, second=59)
        return date.isoformat()
    if len(date_val) == 4:
        suffix = "1231" if match_to_end else "0101"
        return datetime_from_int(date_val + suffix, match_to_end)
    raise ValueError(f"Invalid date value: {date_val}")


def normalize_to_epsg4326(
    gdf,
    source_crs: str | None = None,
    allow_override: bool = False,
):
    """Return a GeoDataFrame-like object normalized to EPSG:4326.

    The helper uses the GeoDataFrame protocol instead of importing geopandas,
    keeping geopandas optional for the TimeAtlas library itself.
    """
    if source_crs is not None and (getattr(gdf, "crs", None) is None or allow_override):
        gdf = gdf.set_crs(source_crs, allow_override=allow_override)
    if getattr(gdf, "crs", None) is None:
        raise ValueError("GeoDataFrame has no CRS; pass source_crs before normalizing")
    return gdf.to_crs("EPSG:4326")


@dataclass(frozen=True)
class ProductionContext:
    """Convenience bundle for a dataset production configuration."""

    config_path: Path
    config: dict[str, Any]
    uuid_manager: "UUIDManager"
    dataset_slug: str
    dataset_id: str
    time_range: "RDETimeRange"

    @classmethod
    def from_config(cls, config_path: str | Path) -> "ProductionContext":
        """Load a dataproduction config and derive common production values."""
        from .RDEModel import RDETimeRange, UUIDManager

        config_path = Path(config_path)
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        uuid_manager = UUIDManager(config["UUID_NAMESPACE"])
        dataset_slug = config["DATASET_CONFIGURATION"]["slug"]
        dataset_id = uuid_manager._generate_uuid(dataset_slug)
        time_range = RDETimeRange(
            datetime_from_int(config["TIMERANGE_MINIMUM"]),
            datetime_from_int(config["TIMERANGE_MAXIMUM"], match_to_end=True),
        )
        return cls(
            config_path=config_path,
            config=config,
            uuid_manager=uuid_manager,
            dataset_slug=dataset_slug,
            dataset_id=dataset_id,
            time_range=time_range,
        )


__all__ = [
    "ProductionContext",
    "clean_metadata",
    "csv_seed",
    "datetime_from_int",
    "find_latest_file",
    "find_layer_uuid",
    "get_area_uuids",
    "normalize_to_epsg4326",
]
