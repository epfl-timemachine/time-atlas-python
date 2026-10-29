"""Offline IIIF Image API URL planning and info.json inventory normalization."""
from __future__ import annotations

import copy
import hashlib
import json
import posixpath
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .SourceInventory import (
    SourceInventoryError, _http_url, _positive_int, image_service_from_request,
    normalize_source_inventory,
)
from .SourceManifests import _image_service


MAX_IMAGE_URLS = 10_000
MAX_URL_TEXT_BYTES = 2 * 1024 * 1024
DERIVED_FIELDS = {"image_url", "image_service_url", "image_identifier",
                  "image_filename", "image_directory", "source_position"}
IMAGE_FORMATS = {"jpg": "image/jpeg", "png": "image/png", "tif": "image/tiff",
                 "gif": "image/gif", "webp": "image/webp", "jp2": "image/jp2"}


def _urls(source) -> list[str]:
    if isinstance(source, Path) or (isinstance(source, str) and not source.startswith(("http://", "https://"))):
        path = Path(source)
        try:
            if path.stat().st_size > MAX_URL_TEXT_BYTES:
                raise SourceInventoryError("The image URL list exceeds the 2 MiB limit")
            values = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError) as error:
            raise SourceInventoryError(f"Cannot read the UTF-8 image URL list: {error}") from error
    elif isinstance(source, str):
        values = source.splitlines()
    else:
        values = list(source)
    if not all(isinstance(value, str) for value in values):
        raise SourceInventoryError("Every image URL must be a string")
    if sum(len(value.encode("utf-8")) + 1 for value in values) > MAX_URL_TEXT_BYTES:
        raise SourceInventoryError("The image URL list exceeds the 2 MiB limit")
    urls = [value.strip() for value in values if value.strip()]
    if not urls:
        raise SourceInventoryError("The image URL list is empty")
    if len(urls) > MAX_IMAGE_URLS:
        raise SourceInventoryError(f"The image URL list exceeds the {MAX_IMAGE_URLS} URL limit")
    if len(set(urls)) != len(urls):
        raise SourceInventoryError("Duplicate image URLs are not allowed")
    return urls


def _append_info(service_url: str) -> str:
    before_query, marker, query = service_url.partition("?")
    return before_query + "/info.json" + (marker + query if marker else "")


def plan_source_image_urls(urls_or_txt_path) -> list[dict]:
    """Validate full-image requests and derive info URLs without network access.

    Output rows contain image_url, image_service_url (request-derived), info_url,
    source_position and request_format. Host code fetches one snapshot for each
    unique info_url. No URL spelling, identifiers or input files are repaired.
    """
    plan = []
    for position, image_url in enumerate(_urls(urls_or_txt_path), start=1):
        try:
            service_url = image_service_from_request(image_url)
            _, region, size, rotation, quality_format = urlsplit(image_url).path.rsplit("/", 4)
            quality, request_format = quality_format.rsplit(".", 1)
            if region != "full" or size not in {"full", "max"} or rotation != "0" or quality != "default":
                raise SourceInventoryError("Only full/full or full/max, rotation 0, default-quality image requests are supported")
            if request_format not in IMAGE_FORMATS:
                raise SourceInventoryError(f"Unsupported requested image format: {request_format}")
            plan.append({"image_url": image_url, "image_service_url": service_url,
                         "info_url": _append_info(service_url), "source_position": position,
                         "request_format": request_format})
        except SourceInventoryError as error:
            raise SourceInventoryError(f"Image URL {position}: {error}", error.report) from error
    return plan


def _identity(url: str) -> tuple:
    parsed = urlsplit(_http_url(url, "Image service URL"))
    if parsed.fragment:
        raise SourceInventoryError("Image service URLs must not contain fragments")
    # Decode only for identity comparison. Do not collapse slashes, dot segments
    # or unrelated identifiers, and do not rewrite either stored URL.
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise SourceInventoryError("Image service URL has an invalid port") from None
    return (parsed.scheme.lower(), parsed.hostname.lower(), port, parsed.username, parsed.password,
            unquote(parsed.path), parsed.query)


def _service_from_info_url(info_url: str) -> str:
    _http_url(info_url, "Image information URL")
    before_query, marker, query = info_url.partition("?")
    if not before_query.endswith("/info.json"):
        raise SourceInventoryError("The final image-information URL must end in /info.json")
    return before_query[:-len("/info.json")] + (marker + query if marker else "")


def _snapshot_info(snapshot: Mapping) -> dict:
    if "info" in snapshot:
        info = snapshot["info"]
    else:
        try:
            raw = Path(snapshot["path"]).read_bytes()
            if snapshot.get("sha256") and hashlib.sha256(raw).hexdigest() != snapshot["sha256"]:
                raise SourceInventoryError("The info.json snapshot checksum does not match")
            info = json.loads(raw.decode("utf-8-sig"))
        except (KeyError, OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SourceInventoryError(f"Cannot read an info.json snapshot: {error}") from error
    if not isinstance(info, dict):
        raise SourceInventoryError("An info.json snapshot must contain a JSON object")
    return info


def _validate_full_image(info: Mapping, service_type: str, profile: str, plan: Mapping) -> tuple[int, int]:
    width = _positive_int(info.get("width"), "Image information width")
    height = _positive_int(info.get("height"), "Image information height")
    size = urlsplit(plan["image_url"]).path.rsplit("/", 4)[2]
    supported_sizes = {"max"} if service_type == "ImageService3" else {"full", "max"}
    if size not in supported_sizes:
        raise SourceInventoryError(f"{service_type} does not support this full-image size syntax: {size!r}")
    protocol = info.get("protocol")
    if protocol is not None and protocol != "http://iiif.io/api/image":
        raise SourceInventoryError("The image information declares a different protocol")
    profile_objects = [entry for entry in info.get("profile", []) if isinstance(entry, Mapping)] if isinstance(info.get("profile"), list) else []
    constraints = [info, *profile_objects]
    limits = {name: min(_positive_int(item[name], name) for item in constraints if name in item)
              for name in ("maxWidth", "maxHeight", "maxArea") if any(name in item for item in constraints)}
    if "maxHeight" in limits and "maxWidth" not in limits:
        raise SourceInventoryError("Image maxHeight requires maxWidth")
    if "maxWidth" in limits and "maxHeight" not in limits:
        limits["maxHeight"] = limits["maxWidth"]
    if (width > limits.get("maxWidth", width) or height > limits.get("maxHeight", height)
            or width * height > limits.get("maxArea", width * height)):
        raise SourceInventoryError("Image service limits reduce or reject the full-size request; request dimensions cannot be inferred without a scaling adapter")
    supported_formats = {"jpg", "png"} if profile == "level2" else {"jpg"}
    declared = [info.get("extraFormats", [])] if service_type == "ImageService3" else [item.get("formats", []) for item in profile_objects]
    for formats in declared:
        if not isinstance(formats, list) or not all(isinstance(value, str) for value in formats):
            raise SourceInventoryError("Image information contains an invalid format declaration")
        supported_formats.update(formats)
    if plan["request_format"] not in supported_formats:
        raise SourceInventoryError(f"The image service does not advertise requested format {plan['request_format']!r}")
    return width, height


def normalize_source_image_urls(urls_or_txt_path, info_snapshots, config: Mapping) -> list[dict]:
    """Combine a URL list with host-fetched Image API 2/3 info snapshots offline.

    Snapshots are mappings with serviceUrl, infoUrl, finalUrl, path and sha256.
    For an already loaded response, ``info`` may replace path/sha256. Snapshot
    identity must match its planned image; unrelated service IDs fail. Grouping,
    ordering and HR joins use the six documented derived fields.
    """
    plan = plan_source_image_urls(urls_or_txt_path)
    snapshots = {}
    for snapshot in info_snapshots:
        if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("infoUrl"), str):
            raise SourceInventoryError("Each info snapshot must identify its requested infoUrl")
        info_url = snapshot["infoUrl"]
        if info_url in snapshots:
            raise SourceInventoryError(f"Duplicate info.json snapshot: {info_url}")
        snapshots[info_url] = snapshot
    rows, metadata_by_url = [], {}
    for item in plan:
        snapshot = snapshots.get(item["info_url"])
        if snapshot is None:
            raise SourceInventoryError(f"Missing info.json snapshot for image URL {item['source_position']}: {item['info_url']}")
        try:
            if snapshot.get("serviceUrl") != item["image_service_url"]:
                raise SourceInventoryError("The info.json snapshot does not match its planned service URL")
            info = _snapshot_info(snapshot)
            service_url, service_type, profile = _image_service({"service": info})
            identities = {_identity(item["image_service_url"])}
            if snapshot.get("finalUrl"):
                identities.add(_identity(_service_from_info_url(snapshot["finalUrl"])))
            if _identity(service_url) not in identities:
                raise SourceInventoryError("The info.json service ID does not match the requested or redirected image service")
            width, height = _validate_full_image(info, service_type, profile, item)
            # The last URI component is the Image API identifier; slashes
            # inside that identifier are percent-encoded by compliant servers.
            image_identifier = unquote(urlsplit(service_url).path.rsplit("/", 1)[-1])
            decoded_path = unquote(urlsplit(service_url).path)
            image_filename = posixpath.basename(decoded_path)
            image_directory = posixpath.dirname(decoded_path)
            if not image_filename:
                raise SourceInventoryError("The image service has no identifier basename")
            row = {"image_url": item["image_url"], "image_service_url": service_url,
                   "image_identifier": image_identifier, "image_filename": image_filename,
                   "image_directory": image_directory, "source_position": item["source_position"],
                   "width": width, "height": height, "media_type": IMAGE_FORMATS[item["request_format"]]}
            metadata_by_url[item["image_url"]] = {"image_service_type": service_type,
                                                  "image_service_profile": profile,
                                                  "source_info_url": item["info_url"],
                                                  "source_info_sha256": snapshot.get("sha256", "")}
            rows.append(row)
        except SourceInventoryError as error:
            raise SourceInventoryError(f"Image URL {item['source_position']}: {error}", error.report) from error

    inventory_config = copy.deepcopy(dict(config))
    label_field = inventory_config.get("columns", {}).get("label")
    grouping = inventory_config.get("grouping", {})
    ordering = inventory_config.setdefault("ordering", {"mode": "inventory"})
    record_link = inventory_config.setdefault("recordLink", {})
    record_link["imageJoinField"] = record_link.get("imageJoinField") or "image_filename"
    if not ordering.get("field"):
        ordering["field"] = "source_position" if ordering.get("mode") == "numeric" else "image_filename"
    used_fields = [label_field, record_link["imageJoinField"]]
    if grouping.get("mode") == "field":
        used_fields.extend([grouping.get("field"), grouping.get("labelField")])
    if ordering.get("mode") != "inventory":
        used_fields.append(ordering.get("field"))
    if any(field and field not in DERIVED_FIELDS for field in used_fields):
        raise SourceInventoryError("URL-list grouping, ordering, labels and joins must use a documented derived field")
    inventory_config["columns"] = {"imageKey": "image_url", "imageUrl": "image_url", "serviceUrl": "image_service_url",
                                    "width": "width", "height": "height", "mediaType": "media_type"}
    if label_field:
        inventory_config["columns"]["label"] = label_field
    # Shared grouping/ordering validation is reused. Each row's actual detected
    # service metadata replaces this temporary common value immediately below.
    first_metadata = metadata_by_url[rows[0]["image_url"]]
    inventory_config["imageService"] = {"version": first_metadata["image_service_type"][-1],
                                         "profile": first_metadata["image_service_profile"]}
    inventory = normalize_source_inventory(rows, inventory_config)
    derived_by_url = {row["image_url"]: row for row in rows}
    for row in inventory:
        row.update({key: derived_by_url[row["image_url"]][key] for key in DERIVED_FIELDS})
        row.update(metadata_by_url[row["image_url"]])
    return inventory
