# Time Atlas Python Client

[![Tests](https://github.com/epfl-timemachine/time-atlas-python/actions/workflows/tests.yml/badge.svg)](https://github.com/epfl-timemachine/time-atlas-python/actions/workflows/tests.yml)
![Coverage threshold](https://img.shields.io/badge/coverage_threshold-95%25-brightgreen)

Python client library for interacting with the TimeAtlas API.

## Overview

The [Time Atlas](https://timeatlas.eu) is a comprehensive platform for managing and analyzing historical geospatial data. This Python client provides a convenient interface for accessing TimeAtlas API endpoints and working with Research Data Entities (RDEs).

## Installation

```bash
pip install time-atlas-python
```

## Quick Start

```python
from timeatlas import TimeAtlas

# Initialize the client
client = TimeAtlas(api_url='https://your-timeatlas-instance.com/v1')

# Fetch a single RDE object
entity = client.get_single_rde_object('historical-records', 'uuid-here')
```

## Features

- **RDE Support**: Work with multiple Research Data Entity types:
  - Historical Records (HR)
  - Observations (OBS)
  - Points of Interest (POI)
  - Geometries (GEOM)
  - Datasets
  - Maps
  - Layers
  - Areas
- **Type Safety**: Comprehensive type hints and dataclass-based models
- **Geospatial Integration**: Native support for Shapely geometries

## Producing Points of Interest from observations

`RDECollection` can aggregate every observation that needs a Point of Interest,
patch the observation references, and serialize the resulting PoIs alongside the
other dataset files:

```python
from timeatlas import RDECollection

collection = RDECollection(historical_records + observations + [dataset])
points_of_interest = collection.consolidate_data()
collection.save_rde_to_files("output/dataset-slug")
```

Observations at coordinates that match after rounding to five decimal places share
a deterministic PoI UUID. Set `part_of_point_of_interest=False` on observations
that should not produce a PoI.

## Dataset areas and spatial indexing

`RDECollection.validate_data()` ensures every dataset can participate in the
backend's by-area index. If a dataset has no area references, validation warns and
adds a deterministic ad-hoc `Area` covering the union extent of observation and
Geometry RDE geometries. That area is attached to the dataset and is subsequently
written to `areas.json`.

```python
collection.validate_data()  # may add an extent-derived Area
collection.save_rde_to_files("output/dataset-slug")
```

You can create it explicitly with
`collection.produce_area_from_current_extent()`. When a dataset already references
area UUIDs that are absent from the collection, validation warns that those areas
must already exist in the target backend.

## Uploading, importing, and publishing a collection

The import client runs the manual server workflow end to end. The collection must
pass local validation first; the client then serializes it, verifies every upload,
waits for packaging, checks the server validation report, queues the import, and
bulk-publishes its resources only after completion.

Before writing or uploading files, area UUIDs referenced by datasets but absent
from the collection are checked against `GET /areas/<uuid>` on the target API. The
workflow is interrupted if any referenced area exists neither locally nor online.

```python
from timeatlas import RDECollection, TimeAtlasImportClient

collection = RDECollection(historical_records + observations + points_of_interest + [dataset])
collection.validate_data()

client = TimeAtlasImportClient(
    "http://localhost:8000/v1",
    token="personal-access-token",
    team_id="team-uuid",
)
result = client.run_collection_workflow(collection, "output/dataset-slug")
print(result.import_data["uuid"], result.import_data["status"])
```

For local scripts, `TimeAtlasImportClient.from_credentials_file(...)` accepts a
file with `TOKEN=...` and `TEAM_ID=...` lines.

## Requirements

- Python 3.12 or higher
- requests >= 2.31.0
- pandas >= 2.0.0
- shapely >= 2.0.0

## Development

### Setting up development environment

```bash
# Clone the repository
git clone https://github.com/epfl-timemachine/time-atlas-python.git
cd time-atlas-python

# Install in development mode with dev dependencies
pip install -e ".[dev]"
```

### Running tests

```bash
python -m pytest
```

Run the complete suite with branch coverage:

```bash
python -m pytest \
  --cov=timeatlas \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=xml
```

The project enforces a minimum total coverage of 95%. The HTML report is written to
`htmlcov/index.html`, and the XML report is written to `coverage.xml`.

Tests use deterministic fixtures, mocked HTTP responses, temporary files, and representative
RDE samples from `test/data`; they do not require a running TimeAtlas API.

### Continuous integration

The [test workflow](https://github.com/epfl-timemachine/time-atlas-python/actions/workflows/tests.yml)
runs the suite with coverage on Python 3.12 and 3.13 for every push and pull request. Coverage
XML reports are uploaded as workflow artifacts for each supported Python version.

### Code formatting

```bash
black timeatlas/
```

## Documentation

Documentation is accessible through [epfl-timemachine.github.io/time-atlas-python](https://epfl-timemachine.github.io/time-atlas-python/)


### License

This program is provided as open source under the [GNU Affero General Public License](https://github.com/epfl-timemachine/time-atlas-python/blob/master/LICENSE) v3 or later.
