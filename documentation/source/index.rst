Time Atlas Python Documentation
================================

Welcome to the Time Atlas Python client library documentation!

Time Atlas is a comprehensive platform for managing and analyzing historical geospatial data. 
This Python client provides a convenient interface for accessing TimeAtlas API endpoints and 
working with Research Data Entities (RDEs).

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   getting_started
   data_model
   api
   examples

Quick Links
-----------

* :doc:`getting_started` - Installation and basic usage
* :doc:`data_model` - Understanding the RDE data model
* :doc:`api` - Complete API reference
* :doc:`examples` - Usage examples and recipes

Overview
--------

The Time Atlas Python library provides:

* **Time Atlas RDE data model**: Accurately represents the Research Data Entity types (Historical Records, 
  Observations, Points of Interest, Geometries, Datasets, Maps, Layers, and Areas)
* **Type Safety**: Comprehensive type hints and dataclass-based models for all RDEs

Installation
------------

Install the package via pip:

.. code-block:: bash

   pip install time-atlas-python

Quick Start
-----------

.. code-block:: python

   from timeatlas import TimeAtlas

   # Initialize the client
   client = TimeAtlas(api_url='https://your-timeatlas-instance.com/v1')

   # Fetch a single RDE object
   entity = client.get_single_rde_object('historical-records', 'uuid-here')

Requirements
------------

* Python 3.12 or higher
* requests >= 2.31.0
* pandas >= 2.0.0
* shapely >= 2.0.0
