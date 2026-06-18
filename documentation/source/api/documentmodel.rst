Document Model
==============

The document model provides classes for constructing IIIF Presentation API
resources from images, 3D models, annotations, and hierarchical collections.

File Resources
--------------

.. autoclass:: timeatlas.DocumentModel.FileReference
   :members:
   :undoc-members:
   :show-inheritance:

Selectors and Annotations
-------------------------

.. autoclass:: timeatlas.DocumentModel.SelectorType
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: timeatlas.DocumentModel.Selector
   :members:
   :undoc-members:
   :show-inheritance:
   :special-members: __init__

.. autoclass:: timeatlas.DocumentModel.Annotation
   :members:
   :undoc-members:
   :show-inheritance:

IIIF Resources
--------------

.. autoclass:: timeatlas.DocumentModel.Page
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: timeatlas.DocumentModel.Model
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: timeatlas.DocumentModel.Document
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: timeatlas.DocumentModel.Collection
   :members:
   :undoc-members:
   :show-inheritance:

Helper Functions
----------------

.. autofunction:: timeatlas.DocumentModel.int_tuple_list_to_svg_string

.. autofunction:: timeatlas.DocumentModel.multiindex_to_nested_dict

.. autofunction:: timeatlas.DocumentModel.ordered_dict_to_iiif_toc_structure

.. autofunction:: timeatlas.DocumentModel.url_encoded_iiif_image_url
