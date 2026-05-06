Getting Started
===============

This guide will help you get started with the Time Atlas Python client library.

Installation
------------

Using pip
^^^^^^^^^

The recommended way to install Time Atlas Python is via pip:

.. code-block:: bash

   pip install time-atlas-python

From Source
^^^^^^^^^^^

You can also install from source:

.. code-block:: bash

   git clone https://github.com/viaccoz/time-atlas-python.git
   cd time-atlas-python
   pip install -e .

Prerequisites
-------------

Time Atlas Python requires:

* Python 3.10 or higher
* An active TimeAtlas API instance
* API credentials (if required by your instance)

Basic Usage
-----------

Initializing the Client
^^^^^^^^^^^^^^^^^^^^^^^

To start using the library, first import and initialize the TimeAtlas client:

.. code-block:: python

   from timeatlas import TimeAtlas

   # Initialize with your API URL
   client = TimeAtlas(api_url='https://your-timeatlas-instance.com/v1')

The client will automatically:

1. Validate the API connection
2. Load any existing entity cache from disk
3. Prepare for API requests

Fetching Entities
^^^^^^^^^^^^^^^^^

Fetch individual RDE entities by their endpoint and UUID:

.. code-block:: python

   # Fetch a historical record
   hr = client.get_single_rde_object('historical-records', 'uuid-of-record')

   # Fetch an observation
   obs = client.get_single_rde_object('observations', 'uuid-of-observation')

   # Fetch a dataset
   dataset = client.get_single_rde_object('datasets', 'uuid-of-dataset')

Next Steps
----------

* Explore the :doc:`data_model` to understand the RDE structure
* Check out :doc:`examples` for common usage patterns
* Review the complete :doc:`api` reference

Troubleshooting
---------------

Connection Issues
^^^^^^^^^^^^^^^^^

If you encounter connection errors:

1. Verify your API URL ends with ``/v1``
2. Check that the API is accessible from your network
3. Ensure the API health endpoint responds correctly

Import Errors
^^^^^^^^^^^^^

If you see import errors:

1. Verify you've installed all dependencies
2. Check your Python version (must be 3.10+)
3. Try reinstalling: ``pip install --upgrade time-atlas-python``
