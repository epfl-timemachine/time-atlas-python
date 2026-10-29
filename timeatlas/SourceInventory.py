"""Normalize external IIIF image inventories and join them to Historical Records.

The configuration is the ingest assistant's ``ModelingSourceConfig`` (camelCase).
This module is deliberately offline: it neither downloads nor publishes images.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .DocumentModel import Annotation, Collection, Document, Page
from .RDEModel import MultiLingualValue, UUIDManager


class SourceInventoryError(ValueError):
    """Invalid source metadata or links; ``report`` contains actionable details."""

    def __init__(self, message: str, report: dict | None = None):
        super().__init__(message)
        self.report = report or {}


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def read_source_rows(rows: str | Path | Iterable[Mapping]) -> list[dict]:
    """Read UTF-8 CSV, a JSON array (or ``{"rows": [...]}``), or row mappings."""
    if isinstance(rows, (str, Path)):
        path = Path(rows)
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                result = list(csv.DictReader(stream))
        elif path.suffix.lower() == ".json":
            result = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(result, dict):
                result = result.get("rows")
        else:
            raise SourceInventoryError("Source inventories must be CSV or JSON")
    elif hasattr(rows, "to_dict") and not isinstance(rows, Mapping):
        result = rows.to_dict("records")
    else:
        result = list(rows)
    if not isinstance(result, list) or not all(isinstance(row, Mapping) for row in result):
        raise SourceInventoryError("Expected a list of inventory rows")
    return [dict(row) for row in result]


def _positive_int(value, field: str) -> int:
    try:
        number = Decimal(_text(value))
        if not number.is_finite() or number <= 0 or number != number.to_integral_value():
            raise InvalidOperation
        return int(number)
    except (InvalidOperation, ValueError):
        raise SourceInventoryError(f"{field} must be a positive integer") from None


def _http_url(value, field: str) -> str:
    # Inspect the URL without decoding or rebuilding it: IIIF identifiers often
    # contain encoded slashes and must retain their exact spelling.
    url = _text(value)
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        valid = False
    if not valid or any(char.isspace() for char in url):
        raise SourceInventoryError(f"{field} must be an absolute HTTP(S) URL")
    return url


def image_service_from_request(image_url: str) -> str:
    """Remove a full IIIF request's region/size/rotation/quality.format suffix.

    Encoded identifiers and query strings are retained. This function requires
    an Image API request URL; a bare JPEG URL cannot identify an IIIF service.
    """
    image_url = _http_url(image_url, "image URL")
    parsed = urlsplit(image_url)
    if parsed.fragment:
        raise SourceInventoryError("An image request URL must not contain a fragment")
    parts = parsed.path.rsplit("/", 4)
    if len(parts) != 5 or not parts[0] or "." not in parts[-1]:
        raise SourceInventoryError("Provide a service URL or a complete IIIF Image API request URL")
    _, region, size, rotation, quality_format = parts
    number = r"\d+(?:\.\d+)?"
    if not (region in {"full", "square"} or re.fullmatch(rf"(?:pct:)?{number},{number},{number},{number}", region)):
        raise SourceInventoryError("Cannot identify the IIIF region; provide a service URL")
    if not (size in {"full", "max"} or re.fullmatch(rf"\^?(?:pct:{number}|!?\d*,\d*)", size)):
        raise SourceInventoryError("Cannot identify the IIIF size; provide a service URL")
    if not re.fullmatch(rf"!?{number}", rotation) or not re.fullmatch(r"[A-Za-z]+\.[A-Za-z0-9]+", quality_format):
        raise SourceInventoryError("Cannot identify the IIIF image request; provide a service URL")
    suffix = "/" + "/".join(parts[1:])
    before_query = image_url.split("?", 1)[0]
    query = image_url[len(before_query):]
    return before_query[:-len(suffix)] + query


def _join_key(value, normalization: str) -> str:
    text = _text(value)
    if not text:
        return ""
    if normalization == "exact":
        return text
    if normalization != "page-number":
        raise SourceInventoryError(f"Unknown join normalization: {normalization}")
    # /00174.jpg and numeric 174.0 deliberately match; arbitrary filenames do
    # not silently become page numbers merely because they contain digits.
    if text.startswith(("http://", "https://")):
        # Decode only the join key, never the stored image/service URL. A
        # complete Image API request is first reduced to its identifier.
        try:
            text = image_service_from_request(text)
        except SourceInventoryError:
            pass
        text = unquote(urlsplit(text).path)
    basename = text.rsplit("/", 1)[-1]
    basename = re.sub(r"^(?:pg\.?|p\.|page)\s*", "", basename, flags=re.I)
    basename = re.sub(r"\.(?:jpe?g|png|tiff?|webp|gif)$", "", basename, flags=re.I)
    try:
        value = Decimal(basename)
        if not value.is_finite() or value < 0 or value != value.to_integral_value():
            raise InvalidOperation
        return str(int(value))
    except InvalidOperation:
        raise SourceInventoryError(f"Not a page number: {text!r}") from None


def _natural_key(value) -> tuple:
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r"(\d+)", _text(value)))


def normalize_source_inventory(rows, config: Mapping) -> list[dict]:
    """Validate mapped CSV/JSON data and return one canonical row per canvas.

    Required column mappings: imageKey, imageUrl, width, height, mediaType.
    Grouping is single, field, or per-image. Ordering is inventory, natural,
    or numeric. Image API version/profile must be explicitly configured.
    IDs are derived later from manifest_key/canvas_key, never row positions.
    """
    source_rows = read_source_rows(rows)
    if not source_rows:
        raise SourceInventoryError("The source inventory is empty")
    columns = config.get("columns", {})
    required = ("imageKey", "imageUrl", "width", "height", "mediaType")
    if any(not columns.get(name) for name in required):
        raise SourceInventoryError("Map imageKey, imageUrl, width, height and mediaType columns")
    service = config.get("imageService", {})
    if service.get("version") not in {"2", "3"} or service.get("profile") not in {"level0", "level1", "level2"}:
        raise SourceInventoryError("Specify the Image API version (2 or 3) and service profile")
    grouping = config.get("grouping", {})
    mode = grouping.get("mode")
    if mode not in {"single", "field", "per-image"}:
        raise SourceInventoryError("Specify manifest grouping: single, field or per-image")
    if mode == "field" and not grouping.get("field"):
        raise SourceInventoryError("Choose the manifest grouping field")
    ordering = config.get("ordering", {"mode": "inventory"})
    if ordering.get("mode") not in {"inventory", "natural", "numeric"}:
        raise SourceInventoryError("Unknown image ordering mode")
    record_link = config.get("recordLink", {})
    normalization = record_link.get("normalization", "exact")
    image_join_field = record_link.get("imageJoinField") or columns["imageKey"]
    inventory, seen, group_labels = [], set(), {}
    for index, row in enumerate(source_rows, start=1):
        def value(name):
            return row.get(columns.get(name, ""))

        canvas_key = _text(value("imageKey"))
        if not canvas_key:
            raise SourceInventoryError(f"Inventory row {index}: missing image key")
        manifest_key = (_text(row.get(grouping["field"])) if mode == "field"
                        else canvas_key if mode == "per-image" else "source")
        if not manifest_key:
            raise SourceInventoryError(f"Inventory row {index}: missing manifest group")
        identity = (manifest_key, canvas_key)
        if identity in seen:
            raise SourceInventoryError(f"Duplicate canvas key in manifest: {identity}")
        seen.add(identity)
        # Inactive UI settings remain in the configuration after a mode switch.
        # Only the current mode's label settings may affect the result.
        if mode == "field":
            manifest_label = _text(row.get(grouping.get("labelField", ""))) or manifest_key
        elif mode == "single":
            manifest_label = _text(grouping.get("label"))
        else:
            manifest_label = canvas_key
        if manifest_key in group_labels and group_labels[manifest_key] != manifest_label:
            raise SourceInventoryError(f"Conflicting labels for manifest {manifest_key!r}")
        group_labels[manifest_key] = manifest_label
        image_url = _http_url(value("imageUrl"), f"Inventory row {index} image URL")
        service_url = (_http_url(value("serviceUrl"), "Image service URL")
                       if _text(value("serviceUrl")) else image_service_from_request(image_url))
        if urlsplit(service_url).path.endswith("/info.json"):
            raise SourceInventoryError("Use the image service root, without /info.json")
        media_type = _text(value("mediaType")).lower()
        if not re.fullmatch(r"image/[a-z0-9.+-]+", media_type):
            raise SourceInventoryError(f"Inventory row {index}: mediaType must be an image MIME type")
        # The format describes the delivered painting image, not a source TIFF.
        extension = urlsplit(image_url).path.rsplit(".", 1)[-1].lower()
        known_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                       "tif": "image/tiff", "tiff": "image/tiff", "webp": "image/webp", "gif": "image/gif"}
        if extension in known_types and known_types[extension] != media_type:
            raise SourceInventoryError(f"Inventory row {index}: mediaType disagrees with the image request format")
        order_value = row.get(ordering.get("field") or columns["imageKey"])
        if ordering["mode"] == "numeric":
            try:
                sort_key = Decimal(_text(order_value))
                if not sort_key.is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                raise SourceInventoryError(f"Inventory row {index}: ordering value must be numeric") from None
        elif ordering["mode"] == "natural":
            sort_key = _natural_key(order_value)
        else:
            sort_key = index
        inventory.append({
            "manifest_key": manifest_key, "manifest_label": manifest_label,
            "canvas_key": canvas_key, "canvas_label": _text(value("label")),
            "image_url": image_url, "image_service_url": service_url,
            "image_service_type": "ImageService" + service["version"],
            "image_service_profile": service["profile"],
            "width": _positive_int(value("width"), f"Inventory row {index} width"),
            "height": _positive_int(value("height"), f"Inventory row {index} height"),
            "media_type": media_type, "image_join_key": _join_key(row.get(image_join_field), normalization),
            "source_row": index, "_sort_key": sort_key,
        })
    inventory.sort(key=lambda row: (_natural_key(row["manifest_key"]), row["_sort_key"], row["canvas_key"]))
    positions = defaultdict(int)
    for row in inventory:
        positions[row["manifest_key"]] += 1
        row["canvas_position"] = positions[row["manifest_key"]]
        row["canvas_label"] = row["canvas_label"] or f"Page {row['canvas_position']}"
        del row["_sort_key"]
    return inventory


def link_source_records(inventory: list[dict], records, config: Mapping,
                        hr_ids_by_record_key: Mapping) -> tuple[list[dict], dict]:
    """Join source records to actual generated HR UUIDs, without guessing links.

    ``hr_ids_by_record_key`` maps stable source record keys to the exact UUIDs
    used by the production script. Values may be one UUID or a list of UUIDs.
    A JSON array in the record image field links one record to several canvases;
    CSV strings are never split implicitly. Missing source references are fatal
    unless missing='allow-unlinked'.
    Unannotated source images are allowed: blank book pages are legitimate.
    """
    settings = config.get("recordLink", {})
    if not settings.get("recordKeyField") or not settings.get("recordImageField"):
        raise SourceInventoryError("Choose the stable record key and record image reference fields")
    if settings.get("missing") not in {"error", "allow-unlinked"}:
        raise SourceInventoryError("Specify the missing-link policy")
    images = defaultdict(list)
    for row in inventory:
        if row["image_join_key"]:
            images[row["image_join_key"]].append(row)
    id_lookup = {_text(key): value for key, value in hr_ids_by_record_key.items()}
    report = {"record_count": 0, "linked_record_count": 0, "missing_references": [],
              "unmatched_references": [], "ambiguous_references": [], "invalid_references": [],
              "missing_hr_ids": [], "duplicate_record_keys": [], "unlinked_images": []}
    links, seen_records = [], set()
    for row in read_source_rows(records):
        report["record_count"] += 1
        record_key = _text(row.get(settings["recordKeyField"]))
        if not record_key or record_key in seen_records:
            report["duplicate_record_keys"].append(record_key)
            continue
        seen_records.add(record_key)
        raw = row.get(settings["recordImageField"])
        references = raw if isinstance(raw, (list, tuple)) else [raw]
        if not references:
            references = [None]
        matched_images, seen_image_keys = [], set()
        for reference in references:
            try:
                image_key = _join_key(reference, settings.get("normalization", "exact"))
            except SourceInventoryError:
                report["invalid_references"].append({"record_key": record_key, "value": _text(reference)})
                continue
            if image_key in seen_image_keys:
                continue
            seen_image_keys.add(image_key)
            if not image_key:
                report["missing_references"].append(record_key)
                continue
            matches = images.get(image_key, [])
            if not matches:
                report["unmatched_references"].append({"record_key": record_key, "value": _text(reference)})
                continue
            if len(matches) != 1:
                report["ambiguous_references"].append({"record_key": record_key, "value": _text(reference)})
                continue
            matched_images.append(matches[0])
        if not matched_images:
            continue
        hr_ids = id_lookup.get(record_key)
        if isinstance(hr_ids, str):
            hr_ids = [hr_ids]
        if not hr_ids or not all(UUIDManager.is_valid_uuid(value) for value in hr_ids):
            report["missing_hr_ids"].append(record_key)
            continue
        links.extend({"manifest_key": image["manifest_key"], "canvas_key": image["canvas_key"],
                      "hr_id": hr_id} for image in matched_images for hr_id in hr_ids)
        report["linked_record_count"] += 1
    linked_images = {(link["manifest_key"], link["canvas_key"]) for link in links}
    report["unlinked_images"] = [row["canvas_key"] for row in inventory
                                  if (row["manifest_key"], row["canvas_key"]) not in linked_images]
    report["link_count"] = len(links)
    # Ambiguity and broken record identities are errors even when missing links
    # have been explicitly allowed: they cannot be resolved by dropping a row.
    fatal = any(report[key] for key in ("ambiguous_references", "invalid_references", "missing_hr_ids", "duplicate_record_keys"))
    missing = report["missing_references"] or report["unmatched_references"]
    if fatal or (missing and settings["missing"] != "allow-unlinked"):
        raise SourceInventoryError("Source links are incomplete or ambiguous; inspect the link report", report)
    return links, report


def _label(value, fallback: str = "") -> MultiLingualValue:
    if isinstance(value, MultiLingualValue):
        return value
    if isinstance(value, Mapping):
        return MultiLingualValue({key: item if isinstance(item, list) else [str(item)]
                                 for key, item in value.items()})
    return MultiLingualValue({"none": [_text(value) or fallback]})


def build_source_collection(inventory: list[dict], *, uuid_manager: UUIDManager,
                            collection_key: str, collection_label,
                            links: Iterable[Mapping] = (), allow_unlinked: bool = False) -> tuple[Collection, dict]:
    """Build stable Collection/Document/Page/Annotation objects from normalized rows."""
    if not inventory or not _text(collection_key):
        raise SourceInventoryError("A nonempty source inventory and stable collection key are required")
    page_lookup, documents = {}, {}
    label = _label(collection_label, collection_key)
    for row in inventory:
        manifest_key, canvas_key = row["manifest_key"], row["canvas_key"]
        key = (manifest_key, canvas_key)
        if key in page_lookup:
            raise SourceInventoryError(f"Duplicate canvas key in manifest: {key}")
        if manifest_key not in documents:
            documents[manifest_key] = Document(
                id=(uuid_manager, json.dumps([collection_key, manifest_key])),
                label=_label(row.get("manifest_labels") or row["manifest_label"]) if row.get("manifest_labels") or row["manifest_label"] else label,
                items=[],
                presentation_metadata=row.get("source_manifest_metadata"),
            )
        page = Page(
            id=(uuid_manager, json.dumps([collection_key, manifest_key, canvas_key])),
            label=_label(row.get("canvas_labels") or row["canvas_label"]), format=row["media_type"],
            range_idx=int(row["canvas_position"]), height=int(row["height"]), width=int(row["width"]),
            object_ref=canvas_key, image_url=row["image_url"],
            image_service_url=row["image_service_url"], image_service_type=row["image_service_type"],
            image_service_profile=row["image_service_profile"], annotations=[],
        )
        page_lookup[key] = page
        documents[manifest_key].items.append(page)
    seen_links = set()
    for link in links:
        key = (link["manifest_key"], link["canvas_key"])
        hr_id = link["hr_id"]
        if key not in page_lookup or not UUIDManager.is_valid_uuid(hr_id):
            raise SourceInventoryError(f"Invalid source link: {link}")
        if (*key, hr_id) in seen_links:
            continue
        seen_links.add((*key, hr_id))
        page = page_lookup[key]
        page.annotations.append(Annotation(id=(uuid_manager, json.dumps([page.id, hr_id])), hr_id=hr_id))
    if not seen_links and not allow_unlinked:
        raise SourceInventoryError("No Historical Record links; explicitly allow unlinked sources to continue")
    for document in documents.values():
        document.items.sort(key=lambda page: (page.range_idx, page.id))
        for page in document.items:
            page.annotations.sort(key=lambda annotation: annotation.id)
    collection = Collection(id=(uuid_manager, collection_key), label=label, items=list(documents.values()))
    return collection, {"manifest_count": len(documents), "image_count": len(page_lookup),
                        "link_count": len(seen_links),
                        "linked_hr_count": len({link[2] for link in seen_links}),
                        "unlinked_image_count": sum(not page.annotations for page in page_lookup.values()),
                        "collection_id": collection.id}


def write_source_collection(collection: Collection, *, uuid_manager: UUIDManager,
                            output_dir: str | Path) -> list[Path]:
    """Write IIIF under ``output_dir/iiif/{collections,manifests}/<uuid>.json``.

    ``output_dir`` is the dataset directory, e.g. /output/rde/datasets/<slug>.
    This does not create metadata sidecars inside the import output directory.
    """
    root = Path(output_dir) / "iiif"
    paths = []
    for directory, objects in (("manifests", collection.items), ("collections", [collection])):
        destination = root / directory
        destination.mkdir(parents=True, exist_ok=True)
        for obj in objects:
            if not isinstance(obj, (Document, Collection)):
                raise SourceInventoryError("Expected a Document or Collection")
            path = destination / f"{obj.id}.json"
            payload = obj.to_iiif(uuid_manager, "") if isinstance(obj, Document) else obj.to_iiif("")
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            paths.append(path)
    return paths


def write_source_inventory(inventory: list[dict], path: str | Path) -> Path:
    """Save the canonical inventory CSV, normally under /job for review."""
    if not inventory:
        raise SourceInventoryError("Cannot write an empty source inventory")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inventory[0]))
        writer.writeheader()
        writer.writerows({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                          for key, value in row.items()} for row in inventory)
    return path


def normalize_source_manifests(manifests, config: Mapping) -> list[dict]:
    """Normalize local Presentation 2/3 manifests; download URLs on the host first.

    See :mod:`timeatlas.SourceManifests` for the supported manifest profile.
    """
    from .SourceManifests import normalize_source_manifests as normalize
    return normalize(manifests, config)


def plan_source_image_urls(urls_or_txt_path) -> list[dict]:
    """Derive info.json requests from a URL list, without fetching them."""
    from .SourceImageURLs import plan_source_image_urls as plan
    return plan(urls_or_txt_path)


def normalize_source_image_urls(urls_or_txt_path, info_snapshots, config: Mapping) -> list[dict]:
    """Normalize a URL list plus host-fetched Image API metadata snapshots."""
    from .SourceImageURLs import normalize_source_image_urls as normalize
    return normalize(urls_or_txt_path, info_snapshots, config)
