TimeAtlas Client
================

.. automodule:: timeatlas.TimeAtlas
   :members:
   :undoc-members:
   :show-inheritance:

Main Client Class
-----------------

.. autoclass:: timeatlas.TimeAtlas.TimeAtlas
   :members:
   :undoc-members:
   :show-inheritance:
   :special-members: __init__

Usage Examples
--------------

Basic Usage
^^^^^^^^^^^

.. code-block:: python

    from timeatlas import TimeAtlas

    # Initialize the client
    client = TimeAtlas(api_url='https://your-timeatlas-instance.com/v1')

    # Fetch a single RDE object
    entity = client.get_single_rde_object('historical-records', 'uuid-here')

    # Save entity cache to file
    client.save_entity_cache_to_file('my_cache.pkl')

Working with Cached Entities
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The TimeAtlas client maintains an internal cache of fetched entities for improved
performance. The cache is automatically saved to disk and loaded on subsequent
client initializations.

.. code-block:: python

    # Cache is automatically loaded from default file on initialization
    client = TimeAtlas(api_url='https://api.example.com/v1')

    # Save cache to custom location
    client.save_entity_cache_to_file('custom_cache.pkl')
