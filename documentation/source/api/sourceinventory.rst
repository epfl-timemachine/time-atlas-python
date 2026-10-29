External IIIF Source Inventories
===============================

``timeatlas.SourceInventory`` normalizes CSV/JSON metadata for images already
hosted by an external IIIF server. It uses the same camelCase source configuration
as the ingest assistant. It performs no network requests: the supplied metadata
and service capabilities are validated locally, not verified against a server.

It also exposes ``normalize_source_manifests`` for already downloaded IIIF
Presentation 2/3 manifests, using the same inventory and generation pipeline.
``plan_source_image_urls`` and ``normalize_source_image_urls`` support image URL
lists enriched from host-downloaded Image API information responses.

Configuration
-------------

An inventory has one row per canvas, a stable image identifier, a complete image
request URL, positive width/height, and the MIME type of the delivered image.
Optional columns provide the image service root and label. Do not supply a
``info.json`` URL as the service root. For example::

    config = {
        "enabled": True,
        "inputType": "inventory",
        "columns": {
            "imageKey": "filename", "imageUrl": "url",
            "width": "width", "height": "height", "mediaType": "media_type",
        },
        "imageService": {"version": "3", "profile": "level2"},
        "grouping": {"mode": "single", "label": "Volume I"},
        "ordering": {"mode": "natural", "field": "filename"},
        "recordLink": {
            "recordKeyField": "record_id", "recordImageField": "page_number",
            "imageJoinField": "filename", "normalization": "page-number",
            "missing": "error",
        },
    }

``grouping.mode`` also accepts ``field`` with ``field`` naming a column, or
``per-image``. ``grouping.labelField`` maps a document label column; conflicting
labels inside one manifest are rejected. ``ordering.mode`` also accepts
``inventory`` (input order) or ``numeric`` (a numeric ordering column).

``recordLink.normalization`` accepts ``exact`` or ``page-number``. The latter
matches numeric page values such as 174.0 to image filenames such as /174.jpg
and explicit page labels such as ``pg. 174``. Image request and service URLs
can also be matched by a numeric image-identifier basename; URL decoding applies
only to the join key and never changes the stored external URLs.
Page numbers repeated in different volumes are ambiguous: use a compound key
and an exact join instead. ``missing`` must explicitly be ``error`` or
``allow-unlinked``. Invalid or ambiguous links always fail.

Generation
----------

Pass actual generated Historical Record UUIDs, not independent UUID guesses::

    from timeatlas import (
        UUIDManager, normalize_source_inventory, link_source_records,
        build_source_collection, write_source_collection, write_source_inventory,
    )

    inventory = normalize_source_inventory("images.csv", config)
    # HRs have already been produced using the source record IDs.
    hr_ids_by_record_key = {row["record_id"]: hr.id for row, hr in produced_records}
    links, report = link_source_records(
        inventory, record_rows, config, hr_ids_by_record_key,
    )
    uuid_manager = UUIDManager("https://example.org/my-dataset")
    collection, counts = build_source_collection(
        inventory, uuid_manager=uuid_manager,
        collection_key="my-dataset", collection_label="My source collection",
        links=links,
    )
    write_source_collection(collection, uuid_manager=uuid_manager, output_dir=dataset_dir)
    write_source_inventory(inventory, "/job/source-inventory.csv")
    dataset.sources = [collection.id]

Catch ``SourceInventoryError`` and save its ``report`` when joins fail. Store
the inventory and link report outside import output. IIIF files are written
under the dataset's ``iiif/collections`` and ``iiif/manifests`` directories,
named using their UUIDs.

The normalized schema contains manifest_key, manifest_label, canvas_key,
canvas_label, canvas_position, image_url, image_service_url, image_service_type,
image_service_profile, width, height, media_type, image_join_key and source_row.
Manifest and canvas keys produce deterministic IDs independently of CSV order.
Multiple HR links create annotations without duplicating canvases. Blank pages
without annotations are retained.

A JSON array in a record's image-reference field links that record to multiple
canvases. CSV cell strings are not implicitly split. Different source record
keys may map to the same HR UUID when the production model deliberately merges
records, but each source record key itself must remain unique.

Downloaded manifest input
-------------------------

The application downloads configured ``manifestUrls`` on the host, saves source
snapshots and checksums, then passes local JSON paths or already loaded manifest
objects to the offline parser::

    from timeatlas.SourceInventory import normalize_source_manifests

    config = {
        "enabled": True,
        "inputType": "manifest-url",
        "manifestUrls": ["https://example.org/iiif/book/manifest"],
        "recordLink": {
            "recordKeyField": "record_id", "recordImageField": "page_number",
            "imageJoinField": "canvas_label", "normalization": "page-number",
            "missing": "error",
        },
    }
    inventory = normalize_source_manifests(
        ["/job/source-manifests/manifest-001.json"], config,
    )

Use the same ``link_source_records`` and ``build_source_collection`` calls as
for CSV input. Manifest grouping, image-service metadata and canvas order come
from each supplied manifest; inventory-mode settings do not override them.
Join fields are ``canvas_id``, ``canvas_label``, ``image_url`` and
``image_service_url``. A missing source canvas label receives a display fallback
but never a fabricated join key.

The normalized rows additionally contain original ``manifest_id``/``canvas_id``,
``manifest_position``, complete ``manifest_labels``/``canvas_labels`` language
maps, and optional ``source_manifest_metadata`` rights/requiredStatement fields.
The builder preserves these label maps and rights statements. Existing source
Historical Record annotations are excluded; only explicitly joined current
dataset HRs are annotated. New UUIDs depend on stable original manifest/canvas
identifiers and the destination dataset namespace.

Supported input is Presentation 3 embedded canvases/AnnotationPages or
Presentation 2 with one embedded sequence, one complete image painting per
canvas, matching image/canvas dimensions, required image width/height/MIME
metadata and one advertised ImageService2/3. Version 2 string/language labels
and attribution are translated to Presentation 3 language maps and
requiredStatement. Service profiles are normalized to their advertised
compliance level; the downloaded source snapshot retains any extra service
capability details. For a complete Image API request, a recognized output format
in the painting URL takes precedence over the declared image MIME type: a TIFF
service identifier requesting ``default.jpg`` produces ``image/jpeg``. Other
URLs retain their declared MIME type. Source snapshots are unchanged.

For matching image-request/service pairs with a file-style identifier below
``/iiif/2/`` or ``/iiif/3/``, duplicate identifier separators (literal ``/``,
encoded ``%2F`` or a mixture) collapse to one encoded separator. For example,
``venice%2F%2Fcatastici%2F001.tif`` becomes
``venice%2Fcatastici%2F001.tif`` consistently in the image and service URL.
This compatibility rule treats those identifiers as filesystem-style paths;
opaque identifiers and arbitrary URL prefixes are never rewritten. Valid single
separators, other escapes, host/scheme spelling, queries and fragments remain
unchanged. Original canvas objects remain available in the source snapshots for
authored record joins; normalized inventory URL fields contain the canonical
values. This rule does not alter the CSV-inventory or image-URL-list adapters.

Optional ``structures`` (navigation ranges/tables of contents) are accepted but
not copied. They can repeat, omit or reorder canvas references independently of
the page sequence. All pages follow the manifest's top-level ``items`` order
(or its single Presentation 2 sequence), once each, including pages absent from
the ranges. Each supplied manifest stays a separate volume; the collection
follows the supplied manifest order. Rebuilding the original navigation hierarchy
is outside this adapter's scope.

Unsupported input fails explicitly: Collections, multiple sequences,
referenced AnnotationPages, Choice/multiple painting bodies,
region or composite layouts, differing image/canvas dimensions and missing
required metadata. No remote image enrichment or source annotation copying
occurs in this adapter.

Image URL lists and information snapshots
----------------------------------------

Image URL input requires only a UTF-8 text file containing one complete IIIF
image request URL per nonempty line. The planner performs no network access and
preserves the original URL spelling, escaping and order::

    from timeatlas.SourceInventory import (
        plan_source_image_urls, normalize_source_image_urls,
    )

    plan = plan_source_image_urls("images.txt")
    # Host code downloads each unique plan row's info_url. Each snapshot is:
    snapshots = [{
        "serviceUrl": plan[0]["image_service_url"],
        "infoUrl": plan[0]["info_url"],
        "finalUrl": plan[0]["info_url"],  # actual final URL after redirects
        "path": "/job/source-image-info/info-0001.json",
        "sha256": "...SHA-256 of the downloaded file bytes...",
    }]
    config = {
        "enabled": True, "inputType": "image-urls",
        "grouping": {"mode": "single"},
        "ordering": {"mode": "natural", "field": "image_filename"},
        "recordLink": {
            "recordKeyField": "record_id", "recordImageField": "page_number",
            "imageJoinField": "image_filename", "normalization": "page-number",
            "missing": "error",
        },
    }
    inventory = normalize_source_image_urls("images.txt", snapshots, config)

The snapshot list contains one entry per unique requested info URL. Each plan
row contains image_url, image_service_url, info_url, source_position and
request_format. An already loaded ``info`` object can replace path/sha256 for
offline use. The normalizer verifies snapshot checksums when supplied and
requires the declared service identity to match the requested service or the
final downloaded metadata URL. Percent-encoding equivalence is accepted during
identity comparison; duplicate slashes and unrelated identifiers are not fixed.
The original image URL remains unchanged in generated painting bodies.

Dimensions and ImageService2/3 compliance levels come from the metadata; MIME
type comes from the actual requested format, not the source file extension or a
list of available formats. Requested formats must be supported by the advertised
compliance level or additional format declarations. Requests are limited to full
region, default quality, rotation 0 and Image API 2 ``full``/``max`` or Image API 3 ``max``
size. If maxWidth/maxHeight/maxArea reduce the available full size, normalization
fails instead of guessing scaled dimensions. Metadata and image pixel retrieval
are separate: the helpers never download or copy image pixels.

Grouping, ordering, labels and HR joins use these derived columns:

* ``image_url``: exact supplied request URL, also the stable canvas key.
* ``image_service_url``: validated service ID advertised by info.json.
* ``image_identifier``: decoded last service-URI component.
* ``image_filename``: basename of the decoded service path.
* ``image_directory``: parent of the decoded service path, including its prefix.
* ``source_position``: original 1-based input position.

Natural ordering defaults to image_filename; numeric ordering defaults to
source_position. ``columns.label`` optionally names one derived field; otherwise
labels use page numbers. The default HR join field is image_filename. Existing
inventory-mode image column mappings and manual service settings are ignored.
Text input is limited to 10,000 unique URLs and 2 MiB. Duplicate URLs, missing
snapshots, unsupported requests and unavailable metadata produce explicit errors.

External URL handling
---------------------

``Page`` supports explicit ``image_url``, ``image_service_url``,
``image_service_type``, ``image_service_profile`` and optional ``thumbnail_url``.
Explicit URLs are preserved without URL-decoding or re-encoding. Without an
explicit thumbnail, the original image request serves as the thumbnail; the
library does not invent a resize request that a remote server may not support.
Existing ``object_ref`` paths and a shared ``url_prefix`` keep their behavior.

Image API 2 services serialize using ``@id``/``@type`` and a version 2 profile
URI. Image API 3 uses ``id``/``type`` and its short profile name, as described in
the `IIIF Presentation API service specification
<https://iiif.io/api/presentation/3.0/#service>`_.

API
---

.. automodule:: timeatlas.SourceInventory
   :members:
