import pandas as pd
import json
import os
from datetime import datetime
import numpy as np
from pathlib import Path
from .TAEnums import MetadataType


def _seed(row: pd.Series, cols: list[str], suffix: str = '') -> str:
    """Replicate the CSV-seed produced by legacy make_uuid_from_row_selection."""
    buf = io.StringIO()
    row[cols].to_csv(buf, index=False, header=False)
    return buf.getvalue() + suffix

def _get_layer_uuid(layer_fp: str, slug_part: str) -> str:
    with open(layer_fp) as f:
        layers = json.load(f)['rde_objects']
    matches = [(v['slug'], v['id']) for v in layers if slug_part in v['slug']]
    if len(matches) != 1:
        raise ValueError(
            f'Expected exactly 1 layer matching "{slug_part}", found {len(matches)}: {matches}'
        )
    return matches[0][1]

def _get_filepath_like(prefix: str, ext: str) -> str:
    name = prefix.split('/')[-1]
    path_prefix = prefix[: -len(name)] or '.'
    return str(sorted(Path(path_prefix).rglob(f'{name}*.{ext}'))[-1])

def _clean_metadata(raw: dict) -> dict:
    """Replace NaN/ndarray values as the legacy produce_hr_obj wrapper did."""
    cleaned = {}
    for k, v in raw.items():
        if isinstance(v, (list, tuple, np.ndarray, pd.Series)):
            val_list = v.tolist() if isinstance(v, (np.ndarray, pd.Series)) else list(v)
            cleaned[k] = val_list
        elif pd.isna(v) if not isinstance(v, (list, np.ndarray)) else False:
            cleaned[k] = None
        elif str(v).lower() == 'nan':
            cleaned[k] = None
        else:
            cleaned[k] = v
    return cleaned


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
    return [
        json.load(open(os.path.join(loc)))['rde_objects'][0]['id']
        for loc in area_locs
    ]

_COMPACT_DATE_FMT = '%Y%m%d'

def _datetime_from_int(date_val, match_to_end: bool = False) -> str:
    """Convert an integer/string date (YYYYMMDD or YYYY) to ISO-8601."""
    date_val = str(date_val)
    if len(date_val) in (3, 7):
        date_val = '0' + date_val
    if len(date_val) == 8:
        date = datetime.strptime(date_val, _COMPACT_DATE_FMT)
        return (date.replace(hour=23, minute=59, second=59) if match_to_end else date).isoformat()
    if len(date_val) == 4:
        suffix = '1231' if match_to_end else '0101'
        return _datetime_from_int(date_val + suffix, match_to_end)
    raise ValueError(f'Invalid date value: {date_val}')