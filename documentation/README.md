# Time Atlas Python Documentation

This directory contains the Sphinx documentation for the Time Atlas Python package.

## Building the Documentation

### Prerequisites

Install the documentation requirements:

```bash
pip install -r requirements.txt
```

### Build HTML Documentation

On Linux/macOS:

```bash
make html
```

On Windows:

```bash
make.bat html
```

The built documentation will be available in `build/html/index.html`.

### Other Build Formats

Sphinx supports multiple output formats:

```bash
# PDF (requires LaTeX)
make latexpdf

# ePub
make epub

# Plain text
make text

# Man pages
make man
```

### Clean Build

To remove all built files:

```bash
make clean
```

## Documentation Structure

```
documentation/
├── source/
│   ├── _static/          # Static files (CSS, images, etc.)
│   ├── _templates/       # Custom templates
│   ├── api/              # API reference documentation
│   │   ├── rdemodel.rst  # RDE Model documentation
│   │   ├── timeatlas.rst # TimeAtlas client documentation
│   │   └── enums.rst     # Enumerations documentation
│   ├── conf.py           # Sphinx configuration
│   ├── index.rst         # Main documentation index
│   ├── getting_started.rst  # Getting started guide
│   ├── data_model.rst    # Data model overview
│   ├── examples.rst      # Usage examples
│   └── api.rst           # API reference index
├── build/                # Generated documentation (gitignored)
├── Makefile              # Build script for Unix
├── make.bat              # Build script for Windows
├── requirements.txt      # Documentation dependencies
└── README.md             # This file
```

## Viewing the Documentation

After building, open `build/html/index.html` in your web browser:

```bash
# On macOS
open build/html/index.html

# On Linux
xdg-open build/html/index.html

# On Windows
start build/html/index.html
```

## Auto-building During Development

For automatic rebuilding during development:

```bash
pip install sphinx-autobuild
sphinx-autobuild source build/html
```

Then navigate to http://localhost:8000 in your browser.

## Publishing to ReadTheDocs

To publish this documentation on ReadTheDocs:

1. Create a `.readthedocs.yaml` file in the repository root
2. Connect your GitHub repository to ReadTheDocs
3. ReadTheDocs will automatically build and host the documentation

Example `.readthedocs.yaml`:

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.11"

sphinx:
  configuration: documentation/source/conf.py

python:
  install:
    - requirements: documentation/requirements.txt
    - method: pip
      path: .
```

## Contributing

When adding new modules or features:

1. Add docstrings following Google or NumPy style
2. Create or update `.rst` files in `source/api/`
3. Add the new page to the appropriate `toctree` directive
4. Build and verify the documentation locally
