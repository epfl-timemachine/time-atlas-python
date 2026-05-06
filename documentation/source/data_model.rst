Data Model
==========

The Time Atlas data model is built around Research Data Entities (RDEs), which represent 
different types of historical and geographical information. The model is designed to be 
simple and generic, with 8 core data classes that share similar attributes while allowing 
for heterogeneous and specific metadata from historical sources.

Overview
--------

The principle of this modeling is to highlight the most common characteristics of any set 
of data that can be visualized in the Time Atlas interface and generalize them into simple 
entity classes. At the same time, the model expects each entity to record as much 
heterogeneous and specific metadata as possible from the original historical source.

Core RDE Types
^^^^^^^^^^^^^^

The eight Research Data Entities (RDEs) are:

1. **Historical Record (HR)** - Atoms of knowledge from historical documents
2. **Observation (Obs)** - Space-time representations of information
3. **Point of Interest (PoI)** - Coordinates handle aggregating observations
4. **Geometry** - Mathematical representations of physical locations
5. **Dataset** - Collections of homogeneous information
6. **Map** - Groups of geographical layers from historical maps
7. **Layer** - Synthetic derivations from maps (raster or vector)
8. **Area** - Boundaries of geographical entities

Entity Relationships
^^^^^^^^^^^^^^^^^^^^

Instances of data are related using UUID identifiers. When ingested in the backend, these 
UUIDs are transformed into URLs. The relationship field names follow a systematic logic 
representing cardinality:

* **Exactly one (1)**: Singular RDE type name (e.g., ``dataset``, ``historical_record``, ``map``)
* **One or Zero (<2)**: ``part_of_<rde_type>`` (e.g., ``part_of_point_of_interest``, ``part_of_layer``)
* **Zero or Many**: ``has_<type_plural>`` (e.g., ``has_observations``, ``has_geometries``, ``has_areas``)
* **Obligatory Many (>0)**: RDE type name in plural (e.g., ``layers``, ``areas``)

Common RDE Attributes
^^^^^^^^^^^^^^^^^^^^^

Most RDEs share these common fields:

* ``id`` - Universal unique identifier (UUID v5)
* ``rde_type`` - Type of RDE (hr, obs, poi, geometry, dataset, map, layer, area)
* ``start_time`` / ``end_time`` - ISO 8601 datetime strings for temporal range (HR, Dataset, Map, Layer)

Base Classes
^^^^^^^^^^^^

All RDE entities inherit from common base classes:

.. code-block:: python

   from timeatlas import RDE, UUIDEntity

   # UUIDEntity provides unique identification
   # RDE provides common serialization methods

Research Data Entities
==================================

1. Historical Record (HR)
--------------------------

An Historical Record is the source from which any information accessible through the Time Atlas 
comes from. It is a single "atom" of knowledge - a record of information about a place, location, 
an event, or set of people found from a historical document.

**Purpose**: Documents information from historical sources with direct links to raw scans or 
transcriptions. Examples include census entries, parcel listings, academic research excerpts, 
or photographs depicting urban spaces.

**Granularity**: Should be as precise as possible - ideally a IIIF annotation of specific 
information from a document's scan.

**Key Attributes:**

* ``id`` - Universal unique identifier
* ``dataset`` - Reference to parent dataset (required)
* ``time_range`` - Temporal range of the record's existence
* ``paradata`` - How data was acquired: ``m`` (manual), ``sa`` (semi-automatic), or ``a`` (automatic)
* ``has_observations`` - List of observations documented in this source (can be empty)
* ``metadata`` - Dictionary of arbitrary key-value pairs storing all metadata
* ``rights_attribution`` - Optional rights and attribution information

**Example:**

.. code-block:: python

   from timeatlas import HistoricalRecord, RDETimeRange

   hr = HistoricalRecord(
       id='hr-uuid-1234',
       dataset='dataset-uuid',
       time_range=RDETimeRange(
           start_time='1900-01-01T00:00:00Z',
           end_time='1910-12-31T23:59:59Z'
       ),
       paradata='m',
       has_observations=['obs-1', 'obs-2'],
       metadata={
           'source': 'Census 1900',
           'location': 'Paris',
           'occupation': 'Baker'
       }
   )

**Relationship**: A single HR can reference multiple observations (or none). It must belong 
to exactly one dataset.

2. Observation (Obs)
--------------------

An Observation is the space-time representation of information recorded in a historical source. 
It is tied to a single point of physical space represented by latitude and longitude coordinates.

**Purpose**: Acts as a pivot entity linking Historical Records, Points of Interest, and Geometries. 
Can represent physical locations (example: cadastral parcels) or events (example: apprenticeships).

**Key Attributes:**

* ``id`` - Universal unique identifier
* ``historical_record`` - Reference to source HR (required - cannot be null)
* ``geometry`` - GPS coordinates as a Shapely Point
* ``has_geometries`` - List of associated geometry entities (optional)
* ``part_of_point_of_interest`` - Optional POI reference

**Example:**

.. code-block:: python

   from timeatlas import Observation
   from shapely.geometry import Point

   obs = Observation(
       id='obs-uuid',
       historical_record='hr-uuid',
       geometry=Point(2.3522, 48.8566),  # Paris coordinates
       has_geometries=['geom-1', 'geom-2'],
       part_of_point_of_interest='poi-uuid'
   )

**Relationship**: Each observation must reference exactly one HR. A single HR can have multiple 
observations (e.g., a postcard showing multiple identified landmarks). Not all observations have 
geometries or belong to a POI.

3. Point of Interest (PoI)
---------------------------

A Point of Interest is what has been observed by one or many observations, relating to coordinate 
handles placed on a map.

**Purpose**: Aggregates observations from single or multiple datasets located at the same exact 
coordinate space. Acts as the display point on the map interface.

**Key Attributes:**

* ``id`` - Universal unique identifier
* ``geometry`` - GPS coordinates as a Shapely Point
* ``height`` - Elevation information (terrain and building height in meters)

**Example:**

.. code-block:: python

   from timeatlas import PointOfInterest, HeightInfo
   from shapely.geometry import Point

   poi = PointOfInterest(
       id='poi-uuid',
       geometry=Point(2.3522, 48.8566),
       height=HeightInfo(terrain=35.0, building=20.0)
   )

**Relationship**: Can be pointed to by multiple observations from different datasets. Height 
information is typically sourced from Maptiler's database and used for 3D visualization.

4. Geometry
-----------

A Geometry entity is the mathematical representation of a physical location as GPS coordinates. 
It can represent parcels, buildings, streets, courtyards, administrative boundaries, ad-hoc zones,
or any geographical area.

**Purpose**: Provides detailed spatial boundaries for locations tied to observations and historical 
records. Can also exist independently as part of vector layers.

**Key Attributes:**

* ``id`` - Universal unique identifier
* ``geometry`` - Shapely geometry object (Point, LineString, Polygon, MultiLineString, MultiPolygon)
* ``part_of_layer`` - Optional reference to parent layer

**Example:**

.. code-block:: python

   from timeatlas import Geometry
   from shapely.geometry import Polygon

   geom = Geometry(
       id='geom-uuid',
       geometry=Polygon([
           (2.35, 48.85),
           (2.36, 48.85),
           (2.36, 48.86),
           (2.35, 48.86),
           (2.35, 48.85)
       ]),
       part_of_layer='layer-uuid'
   )

**Relationship**: Can be referenced by observations through ``has_geometries``. Can exist without 
being referenced by a record (as part of a vector layer only).

5. Dataset
----------

A Dataset represents a homogeneous collection of information ingested in the Time Machine system. 
It links research data to its numerical expression and exploitation.

**Purpose**: Groups related historical records and provides dataset-level metadata and configuration 
for how the data should be handled and displayed.

**Key Attributes:**

* ``id`` - Universal unique identifier
* ``slug`` - Human-readable identifier
* ``name`` - Multilingual short title
* ``time_range`` - Temporal range of dataset existence
* ``configuration`` - Metadata configuration for HRs in this dataset
* ``metadata`` - Free-form metadata fields
* ``version`` - Version label (X.Y.Z format)
* ``creation_time`` - Timestamp of version creation
* ``sources`` - List of IIIF manifest UUIDs
* ``has_areas`` - References to related areas

**Example:**

.. code-block:: python

   from timeatlas import Dataset, DatasetConfiguration, MultiLingualValue, RDETimeRange

   dataset = Dataset(
       id='dataset-uuid',
       slug='census-1900',
       name=MultiLingualValue(values={
           'en': ['Census 1900'],
           'fr': ['Recensement 1900']
       }),
       time_range=RDETimeRange(
           start_time='1900-01-01T00:00:00Z',
           end_time='1900-12-31T23:59:59Z'
       ),
       version='1.0.0',
       configuration=DatasetConfiguration(...)
   )

**Versioning**: Version format "X.Y.Z" where major changes (X) affect RDE structure, minor changes 
(Y) add fields/data, and patches (Z) fix small issues.

6. Map
------

A Map entity represents a group of geographical layers stemming from a single historical map which 
users can freely select to display in the interface.

**Purpose**: Organizes and groups layers derived from a single historical map source.

**Key Attributes:**

* ``id`` - Universal unique identifier
* ``slug`` - Human-readable identifier
* ``name`` - Multilingual short title
* ``time_range`` - Temporal range of map existence
* ``layers`` - List of layer UUIDs (required, must have at least one)
* ``metadata`` - Free-form metadata fields
* ``thumbnail`` - IIIF protocol URL for thumbnail image
* ``version`` - Version label (X.Y.Z format)
* ``areas`` - References to related areas (required, must have at least one)

**Example:**

.. code-block:: python

   from timeatlas import Map, MultiLingualValue, RDETimeRange

   map_entity = Map(
       id='map-uuid',
       slug='paris-1900',
       name=MultiLingualValue(values={'en': ['Paris Map 1900']}),
       time_range=RDETimeRange('1900-01-01', '1900-12-31'),
       layers=['layer-1', 'layer-2'],
       areas=['area-paris'],
       thumbnail='https://iiif.example.com/image.jpg'
   )

**Relationship**: Must be tied to at least one area. Contains one or more layers.

7. Layer
--------

A Layer is a synthetic derivation from a map, either from vectorization of specific content or 
the actual digital facsimile of the map. It represents objects users can manipulate to display 
as a 2D planar field.

**Purpose**: Provides the actual displayable content from maps, either as raster tiles or vector 
geometries.

**Types:**

* **RASTER**: Layer formed from an image stored through tiles in the geoserver
* **VECTOR**: Layer formed of Geometry entities pointing to it via ``part_of_layer``

**Key Attributes:**

* ``id`` - Universal unique identifier
* ``slug`` - Human-readable identifier
* ``name`` - Multilingual short title
* ``description`` - Brief multilingual description for overlay choices
* ``time_range`` - Temporal range of layer existence
* ``map`` - Reference to parent map (required)
* ``type`` - LayerType enum (RASTER or VECTOR)
* ``layer_configurations`` - List of configuration objects for accessing the layer

**Example:**

.. code-block:: python

   from timeatlas import Layer, LayerType, LayerConfiguration, MultiLingualValue, RDETimeRange

   layer = Layer(
       id='layer-uuid',
       slug='paris-buildings',
       name=MultiLingualValue(values={'en': ['Paris Buildings 1900']}),
       description=MultiLingualValue(values={'en': ['Vectorized buildings']}),
       time_range=RDETimeRange('1900-01-01', '1900-12-31'),
       map='map-uuid',
       type=LayerType.VECTOR,
       layer_configurations=[...]
   )

**Relationship**: Must belong to exactly one map. Contains one or more layer configurations 
describing how to access the layer data.

8. Area
-------

An Area represents the boundary of a specific geographical entity - continents, countries, cities, 
or ad-hoc administrative zones.

**Purpose**: Used to index maps and datasets to curated geographical areas in the Time Atlas, 
enabling spatial filtering and organization.

**Key Attributes:**

* ``id`` - Universal unique identifier
* ``slug`` - Human-readable identifier
* ``name`` - Multilingual name of the geographical entity
* ``geometry`` - Shapely geometry object representing the boundary (typically Polygon)

**Example:**

.. code-block:: python

   from timeatlas import Area, MultiLingualValue
   from shapely.geometry import Polygon

   paris = Area(
       id='area-paris',
       slug='paris',
       name=MultiLingualValue(values={
           'en': ['Paris'],
           'fr': ['Paris']
       }),
       geometry=Polygon([
           (2.22, 48.82),
           (2.47, 48.82),
           (2.47, 48.90),
           (2.22, 48.90),
           (2.22, 48.82)
       ])
   )

**Relationship**: Referenced by datasets via ``has_areas`` and by maps via ``areas``. Acts as 
a spatial index for content organization.

Configuration and Supporting Entities
======================================

Multilingual Values
-------------------

Text that can be expressed in multiple languages uses ``MultiLingualValue``, following 
the IIIF format for multilingual descriptions:

.. code-block:: python

   from timeatlas import MultiLingualValue

   name = MultiLingualValue(values={
       'en': ['English Name', 'Alternative English Name'],
       'fr': ['Nom Français'],
       'de': ['Deutscher Name'],
       'it': ['Nome Italiano']
   })

Each language code (2-3 letters) can have multiple values in a list.

Free-Form Metadata Fields
--------------------------

Both datasets and maps can have free-form metadata fields for contextual information. 
As they are arbitrary, both the label and value must be specified as multilingual entities:

.. code-block:: python

   from timeatlas import FreeFormMetadata, MetadataType, MultiLingualValue

   metadata_field = FreeFormMetadata(
       type=MetadataType.STRING,
       label=MultiLingualValue(values={
           'en': ['Original Source'],
           'fr': ['Source Originale']
       }),
       value=MultiLingualValue(values={
           'en': ['National Archives'],
           'fr': ['Archives Nationales']
       })
   )

Metadata Types
^^^^^^^^^^^^^^

Metadata fields can have the following types:

* ``STRING`` - Unicode text of arbitrary length
* ``INTEGER`` - Whole numbers (positive or negative)
* ``FLOAT`` - Decimal numbers
* ``URL`` - Web URLs
* ``LIST`` - Lists of values (can contain other types)

Dataset Configuration
---------------------

The Dataset Configuration describes how Historical Records in a dataset should be handled 
and served through the information system.

**Key Attributes:**

* ``metadata_field_config`` - List of configurations for each metadata field in HRs
* ``main_label`` - Formatting string for the main label display
* ``sub_label`` - Formatting string for sub-label display
* ``display_thumbnail`` - Whether HRs have thumbnails to display
* ``external_source`` - Whether source button forwards to external URL

**Example:**

.. code-block:: python

   from timeatlas import DatasetConfiguration, MetadataFieldConfig, MetadataType, MetadataTag, MultiLingualValue

   config = DatasetConfiguration(
       metadata_field_config=[
           MetadataFieldConfig(
               id='person_name',
               type=MetadataType.STRING,
               display_label=MultiLingualValue(values={
                   'en': ['Person Name'],
                   'fr': ['Nom de la Personne']
               }),
               indexable=True,
               short_display=True,
               nullable=False,
               hidden=False,
               tag=MetadataTag.PEOPLE
           ),
           MetadataFieldConfig(
               id='occupation',
               type=MetadataType.STRING,
               display_label=MultiLingualValue(values={
                   'en': ['Occupation'],
                   'fr': ['Profession']
               }),
               indexable=True,
               short_display=True,
               nullable=True,
               hidden=False
           ),
           MetadataFieldConfig(
            id='location',
            type=MetadataType.STRING,
            display_label=MultiLingualValue(values={
                'en': ['Location'],
                'fr': ['Lieu']
            }),
            indexable=True,
            short_display=True,
            nullable=True,
            hidden=False,
            tag=MetadataTag.PLACE
           )
       ],
       main_label='${person_name}',
       sub_label='${occupation} in ${location}',
       display_thumbnail=True,
       external_source=False
   )

Metadata Field Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each metadata field in Historical Records can be configured with:

* ``id`` - Field name as it appears in the HR metadata dictionary
* ``type`` - Data type (STRING, INTEGER, FLOAT, URL, LIST)
* ``display_label`` - Multilingual label for frontend display
* ``paradata`` - How the data was acquired (MANUAL, SEMI_AUTOMATIC, AUTOMATIC, AI)
* ``nullable`` - Whether the field can hold empty values
* ``indexable`` - Whether indexed for full-text search
* ``short_display`` - Whether displayed by default in card view
* ``hidden`` - Whether hidden from normal users
* ``tag`` - Broad category (PEOPLE, PLACE, LAND_USE) for facet search

Layer Configuration
-------------------

Layer Configuration describes how a layer is served and accessed by the frontend.

**Key Attributes:**

* ``service`` - Service configuration (URL and type)
* ``min_zoom_level`` - Minimum zoom level for display
* ``max_zoom_level`` - Maximum zoom level for display
* ``extent`` - Optional bounding box boundary

**Example:**

.. code-block:: python

   from timeatlas import LayerConfiguration, LayerConfigurationService, GeographicalExtent

   layer_config = LayerConfiguration(
       id='config-uuid',
       service=LayerConfigurationService(
           url='https://tiles.example.com/layer/{z}/{x}/{y}',
           type='XYZ'
       ),
       min_zoom_level=10,
       max_zoom_level=18,
       extent=GeographicalExtent([2.25, 48.81, 2.42, 48.90])
   )

Service Types
^^^^^^^^^^^^^

Layer services can use various tile formats:

* ``XYZ`` - Standard XYZ tile format
* ``MVT`` - Mapbox Vector Tiles
* ``WMTS`` - Web Map Tile Service
* And others depending on geoserver configuration

Geographical Extent
-------------------

Bounding boxes are represented using ``GeographicalExtent``:

.. code-block:: python

   from timeatlas import GeographicalExtent

   # Format: [min_x, min_y, max_x, max_y]
   extent = GeographicalExtent([2.25, 48.81, 2.42, 48.90])

The extent must have exactly four coordinates, and min values must be less than max values.

Time Ranges
-----------

Temporal information is represented using ``RDETimeRange`` with ISO 8601 formatted datetime strings:

.. code-block:: python

   from timeatlas import RDETimeRange

   time_range = RDETimeRange(
       start_time='1900-01-01T00:00:00Z',
       end_time='1910-12-31T23:59:59Z'
   )

   # Validation happens automatically
   # Raises ValueError if format is invalid
   # Raises AssertionError if start_time > end_time

Height Information
------------------

Elevation data for Points of Interest is stored in ``HeightInfo``:

.. code-block:: python

   from timeatlas import HeightInfo

   height = HeightInfo(
       terrain=35.0,    # Terrain height in meters
       building=20.0    # Building height in meters
   )

This information is typically sourced from Maptiler's database and used for 3D visualization.

Working with the Data Model
============================

Type Aliases
------------

The module defines several type aliases for improved code readability:

* ``UUID`` - String representation of a Universal Unique Identifier
* ``GeometryType`` - Union of Shapely geometry types (Point, LineString, Polygon, Multi*)
* ``ObsReference`` - Observation object or UUID string
* ``HRReference`` - HistoricalRecord object or UUID string
* ``DatasetReference`` - Dataset object or UUID string
* ``POIReference`` - PointOfInterest object or UUID string
* ``GeometryReference`` - Geometry object or UUID string
* ``AreaReference`` - Area object or UUID string
* ``LayerReference`` - Layer object or UUID string
* ``MapReference`` - Map object or UUID string

Serialization
-------------

All RDE entities can be serialized to/from dictionaries for JSON interchange:

.. code-block:: python

   from timeatlas import HistoricalRecord

   # Create an HR
   hr = HistoricalRecord(...)

   # Convert to dictionary (suitable for JSON)
   hr_dict = hr.to_dict()

   # Construct from dictionary/JSON
   hr_loaded = HistoricalRecord.constructor_from_json_obj(hr_dict)

   # For HRs, you can flatten metadata into top-level fields
   hr_dict_flat = hr.to_dict(flatten_metadata=True)

Creating from DataFrames
-------------------------

Historical Records can be created directly from pandas DataFrame rows:

.. code-block:: python

   import pandas as pd
   from timeatlas import HistoricalRecord

   # Load data
   df = pd.read_csv('census_data.csv')

   # Create HRs from rows
   hrs = []
   for _, row in df.iterrows():
       hr = HistoricalRecord.constructor_from_dataframe_row(row)
       hrs.append(hr)

Metadata columns not used by core attributes are automatically extracted into the 
``metadata`` dictionary.

Actualizing References
----------------------

When loading data, you often start with UUID strings that reference other entities. 
You can replace these strings with actual object references:

.. code-block:: python

   from timeatlas import Observation, HistoricalRecord, Geometry

   # Dictionary of all loaded entities by UUID
   entity_dict = {
       'hr-uuid': historical_record_obj,
       'geom-1': geometry1_obj,
       'geom-2': geometry2_obj,
       'poi-uuid': poi_obj
   }

   # Observation initially has UUID strings
   obs = Observation(
       id='obs-uuid',
       historical_record='hr-uuid',
       geometry=Point(2.35, 48.85),
       has_geometries=['geom-1', 'geom-2'],
       part_of_point_of_interest='poi-uuid'
   )

   # Replace UUID references with actual objects
   obs.actualize_references(entity_dict)

   # Now obs.historical_record is an HR object
   # obs.has_geometries contains Geometry objects
   # obs.part_of_point_of_interest is a PoI object

Similarly, Historical Records can actualize observation references:

.. code-block:: python

   hr.actualize_observations_references(entity_dict)

Summary
=======

The Time Atlas data model provides a flexible yet structured way to represent historical 
geospatial data. The eight RDE types work together to create a comprehensive system where:

* **Historical Records** document information from sources
* **Observations** link records to specific locations
* **Points of Interest** aggregate observations at coordinates
* **Geometries** provide detailed spatial boundaries
* **Datasets** organize and configure collections of records
* **Maps** group related geographical layers
* **Layers** provide displayable map content
* **Areas** enable spatial indexing and filtering

Each entity type has well-defined relationships with others, creating a rich interconnected 
data model that supports complex historical and geographical research while remaining 
accessible and maintainable.

For complete API documentation of all classes and methods, see the :doc:`api` reference.

