import numpy as np
import pandas as pd

from .TAEnums import MetadataType
from .production import (
    clean_metadata,
    csv_seed,
    datetime_from_int,
    find_latest_file,
    find_layer_uuid,
    get_area_uuids,
)

def _seed(row: pd.Series, cols: list[str], suffix: str = '') -> str:
    """Replicate the CSV-seed produced by legacy make_uuid_from_row_selection."""
    return csv_seed(row, cols, suffix)

def _get_layer_uuid(layer_fp: str, slug_part: str) -> str:
    return find_layer_uuid(layer_fp, slug_part)

def _get_filepath_like(prefix: str, ext: str) -> str:
    return find_latest_file(prefix, ext)

def _clean_metadata(raw: dict) -> dict:
    """Replace NaN/ndarray values as the legacy produce_hr_obj wrapper did."""
    return clean_metadata(raw)


# helper function to infer the most likely Python type of a pandas Series, used for automatic metadata configuration generation from DataFrames.
def _get_likely_type(series: pd.Series):
    dtype = str(series.dtype)
    if dtype != 'object':
        return dtype
    for v in series.values:
        if v is None:
            continue
        try:
            if not pd.isna(v):
                return type(v)
        except (TypeError, ValueError):
            return type(v)
    return None

def _python_type_to_metadata_type(tpe) -> MetadataType:
    if tpe in (int,) or str(tpe).startswith('int'):
        return MetadataType.INTEGER
    if tpe == float or str(tpe).startswith('float'):
        return MetadataType.FLOAT
    if tpe in (list, np.ndarray):
        return MetadataType.LIST
    return MetadataType.STRING


def _get_area_uuids(area_locs: list[str]) -> list[str]:
    return get_area_uuids(area_locs)

def _datetime_from_int(date_val, match_to_end: bool = False) -> str:
    """Convert an integer/string date (YYYYMMDD or YYYY) to ISO-8601."""
    return datetime_from_int(date_val, match_to_end)
