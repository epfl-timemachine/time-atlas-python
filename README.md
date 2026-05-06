# Time Atlas Python Client

Python client library for interacting with the TimeAtlas API.

## Overview

Time Atlas is a comprehensive platform for managing and analyzing historical geospatial data. This Python client provides a convenient interface for accessing TimeAtlas API endpoints and working with Research Data Entities (RDEs).

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

- **Entity Caching**: Built-in caching mechanism for improved performance
- **Type Safety**: Comprehensive type hints and dataclass-based models
- **Geospatial Integration**: Native support for Shapely geometries

## Requirements

- Python 3.10 or higher
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
pytest
```

### Code formatting

```bash
black timeatlas/
```

## Documentation

For detailed documentation on the TimeAtlas API and data model, please refer to the official TimeAtlas documentation.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions:
- GitHub Issues: https://github.com/epfl-timemachine/time-atlas-python/issues
- Documentation: https://github.com/epfl-timemachine/time-atlas-python#readme
