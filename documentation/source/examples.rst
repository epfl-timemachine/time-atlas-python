Examples
========

This page contains practical examples and recipes for common use cases.

Working with Historical Records
--------------------------------

Creating from DataFrame
^^^^^^^^^^^^^^^^^^^^^^^

You can create Historical Records directly from pandas DataFrames:

.. code-block:: python

   import pandas as pd
   from timeatlas import HistoricalRecord

   # Load data from CSV
   df = pd.read_csv('census_data.csv')

   # Create HRs from each row
   hrs = []
   for _, row in df.iterrows():
       hr = HistoricalRecord.constructor_from_dataframe_row(row)
       hrs.append(hr)

Serializing to JSON
^^^^^^^^^^^^^^^^^^^

Export Historical Records to JSON format:

.. code-block:: python

   import json
   from timeatlas import HistoricalRecord

   # Create or fetch an HR
   hr = HistoricalRecord(...)

   # Convert to dictionary
   hr_dict = hr.to_dict()

   # Save to JSON file
   with open('historical_record.json', 'w') as f:
       json.dump(hr_dict, f, indent=2)

Working with Observations
--------------------------

Creating Observations with Geometries
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from timeatlas import Observation, Geometry
   from shapely.geometry import Point, Polygon

   # Create a geometry for a building
   building_geom = Geometry(
       id='building-uuid',
       geometry=Polygon([
           (2.35, 48.85),
           (2.351, 48.85),
           (2.351, 48.851),
           (2.35, 48.851),
           (2.35, 48.85)
       ])
   )

   # Create an observation at the building's center
   obs = Observation(
       id='obs-uuid',
       historical_record='hr-uuid',
       geometry=Point(2.3505, 48.8505),
       has_geometries=[building_geom.id]
   )

Working with Datasets
---------------------

Creating a Dataset with Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from timeatlas import (
       Dataset, DatasetConfiguration, MetadataFieldConfig,
       MultiLingualValue, RDETimeRange, MetadataType
   )

   # Configure metadata fields
   name_field = MetadataFieldConfig(
       id='person_name',
       type=MetadataType.STRING,
       display_label=MultiLingualValue(values={
           'en': ['Person Name'],
           'fr': ['Nom de la Personne']
       }),
       indexable=True,
       short_display=True
   )

   # Create dataset configuration
   config = DatasetConfiguration(
       metadata_field_config=[name_field],
       main_label='person_name',
       display_thumbnail=True
   )

   # Create the dataset
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
       configuration=config
   )

Populating Dataset Members
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from timeatlas import Dataset, HistoricalRecord, Observation

   # Create dataset
   dataset = Dataset(...)

   # List of all RDE entities
   all_entities = [hr1, hr2, obs1, obs2, hr3]

   # Automatically populate hrs and obs lists
   dataset.instantiate_all_rde_members(all_entities)

   # Now dataset.hrs contains all HRs from this dataset
   # and dataset.obs contains all Observations

Working with Maps and Layers
-----------------------------

Creating a Map with Layers
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from timeatlas import (
       Map, Layer, LayerType, LayerConfiguration,
       LayerConfigurationService, MultiLingualValue,
       RDETimeRange, GeographicalExtent
   )

   # Create layer configuration
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

   # Create a raster layer
   layer = Layer(
       id='layer-uuid',
       slug='paris-1900-map',
       name=MultiLingualValue(values={'en': ['Paris Map 1900']}),
       description=MultiLingualValue(values={
           'en': ['Historical map of Paris from 1900']
       }),
       time_range=RDETimeRange('1900-01-01', '1900-12-31'),
       map='map-uuid',
       type=LayerType.RASTER,
       layer_configurations=[layer_config]
   )

   # Create the map
   map_entity = Map(
       id='map-uuid',
       slug='paris-1900',
       name=MultiLingualValue(values={'en': ['Paris 1900']}),
       time_range=RDETimeRange('1900-01-01', '1900-12-31'),
       layers=[layer.id]
   )

Working with Geospatial Data
-----------------------------

Creating Geometries from GeoJSON
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   import json
   from timeatlas import Geometry
   import shapely

   # Load GeoJSON
   with open('building.geojson', 'r') as f:
       geojson_data = json.load(f)

   # Create Geometry from GeoJSON Feature
   geometry = Geometry.constructor_from_json_obj(geojson_data)

   # Or create directly with Shapely
   geom_obj = shapely.from_geojson(json.dumps(geojson_data['geometry']))
   geometry2 = Geometry(
       id='geom-uuid',
       geometry=geom_obj
   )


Working with Areas
^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from timeatlas import Area, MultiLingualValue
   from shapely.geometry import Polygon

   # Define Paris city boundary (simplified)
   paris_boundary = Polygon([
       (2.22, 48.82),
       (2.47, 48.82),
       (2.47, 48.90),
       (2.22, 48.90),
       (2.22, 48.82)
   ])

   # Create area
   paris = Area(
       id='area-paris',
       slug='paris',
       name=MultiLingualValue(values={
           'en': ['Paris'],
           'fr': ['Paris']
       }),
       geometry=paris_boundary
   )

Client Usage Patterns
---------------------

Batch Fetching with Caching
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from timeatlas import TimeAtlas

   client = TimeAtlas(api_url='https://api.example.com/v1')

   # Fetch multiple entities
   uuids = ['uuid-1', 'uuid-2', 'uuid-3']
   hrs = []

   for uuid in uuids:
       hr = client.get_single_rde_object('historical-records', uuid)
       hrs.append(hr)

Error Handling
^^^^^^^^^^^^^^

.. code-block:: python

   from timeatlas import TimeAtlas
   import requests

   try:
       client = TimeAtlas(api_url='https://api.example.com/v1')
   except ConnectionError as e:
       print(f"Could not connect to API: {e}")
   except ValueError as e:
       print(f"Invalid API URL: {e}")

   try:
       entity = client.get_single_rde_object('datasets', 'invalid-uuid')
   except requests.HTTPError as e:
       print(f"API error: {e}")

For more detailed API documentation, see the :doc:`api` reference.
