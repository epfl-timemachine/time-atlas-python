"""Offline Presentation API 2/3 adapters for the normalized source inventory.

Supported manifests have one embedded image painting per canvas and one
advertised ImageService2/3. Original manifest boundaries and canvas order are
preserved. Complex compositions and ranges fail explicitly instead of being
flattened. Source HR annotations are never copied to the new dataset.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from .SourceInventory import SourceInventoryError, _http_url, _join_key, _positive_int, _text


def _list(value) -> list:
    return value if isinstance(value, list) else [] if value is None else [value]


def _term(value) -> str:
    return re.split(r"[/#:]", _text(value))[-1]


def _id(value: Mapping, kind: str) -> str:
    identifier = value.get("id", value.get("@id"))
    if not isinstance(identifier, str) or not identifier.strip():
        raise SourceInventoryError(f"{kind} is missing its identifier")
    return identifier


def _type(value: Mapping) -> str:
    return _term(value.get("type", value.get("@type")))


def _labels(value, *, fallback: str = "") -> dict[str, list[str]]:
    """Translate P2 string/value labels and P3 language maps without loss."""
    if value is None or value == "" or value == [] or value == {}:
        return {"none": [fallback]} if fallback else {}
    labels: dict[str, list[str]] = {}
    if isinstance(value, str):
        return {"none": [value]}
    if isinstance(value, list):
        for part in value:
            for language, entries in _labels(part).items():
                labels.setdefault(language, []).extend(entries)
    elif isinstance(value, Mapping) and "@value" in value:
        text = value["@value"]
        if not isinstance(text, str) or not text.strip():
            raise SourceInventoryError("A source label contains an invalid value")
        labels[_text(value.get("@language")) or "none"] = [text]
    elif isinstance(value, Mapping):
        for language, entries in value.items():
            entries = _list(entries)
            if not entries or not all(isinstance(entry, str) and entry.strip() for entry in entries):
                raise SourceInventoryError("A source label contains an invalid language map")
            labels[str(language)] = entries.copy()
    else:
        raise SourceInventoryError("Unsupported source label representation")
    return labels


def _display(labels: Mapping) -> str:
    # Insertion order follows the supplied JSON. The full language map remains
    # available for output, while a scalar value supports explicit HR joins.
    return next((entry for entries in labels.values() for entry in entries), "")


def _rights(manifest: Mapping, version: int) -> dict:
    result = {}
    rights = manifest.get("rights") if version == 3 else manifest.get("license")
    if rights:
        values = _list(rights)
        if len(values) != 1:
            raise SourceInventoryError("Multiple source license statements are not supported")
        result["rights"] = _http_url(values[0], "Source rights URI")
    statement = manifest.get("requiredStatement") if version == 3 else manifest.get("attribution")
    if statement:
        if version == 3:
            if not isinstance(statement, Mapping) or not statement.get("label") or not statement.get("value"):
                raise SourceInventoryError("Invalid source requiredStatement")
            result["requiredStatement"] = {"label": _labels(statement["label"]),
                                           "value": _labels(statement["value"])}
        else:
            result["requiredStatement"] = {"label": {"en": ["Attribution"]}, "value": _labels(statement)}
    return result


def _image_service(body: Mapping) -> tuple[str, str, str]:
    services = _list(body.get("service"))
    if len(services) != 1 or not isinstance(services[0], Mapping):
        raise SourceInventoryError("Each source image must advertise exactly one ImageService2/3")
    service = services[0]
    service_url = _http_url(_id(service, "Image service"), "Image service URL")
    if service_url.split("?", 1)[0].endswith("/info.json"):
        raise SourceInventoryError("An image service ID must identify its root, not /info.json")
    service_type = _type(service)
    profiles = _list(service.get("profile"))
    profile_candidates = [profile for profile in profiles if isinstance(profile, str)]
    if len(profile_candidates) != 1:
        raise SourceInventoryError("An image service must advertise one supported compliance profile")
    profile = profile_candidates[0]
    version_two = re.fullmatch(r"https?://iiif\.io/api/image/2/(level[012])\.json", profile)
    if service_type in {"", "Image"}:
        contexts = _list(service.get("@context"))
        if version_two or any(re.fullmatch(r"https?://iiif\.io/api/image/2/context\.json", str(context)) for context in contexts):
            service_type = "ImageService2"
        elif any(re.fullmatch(r"https?://iiif\.io/api/image/3/context\.json", str(context)) for context in contexts):
            service_type = "ImageService3"
    if service_type not in {"ImageService2", "ImageService3"}:
        raise SourceInventoryError("Only advertised ImageService2 and ImageService3 are supported")
    if service_type == "ImageService2" and version_two:
        profile = version_two[1]
    elif service_type == "ImageService3" and version_two:
        raise SourceInventoryError("Image service type and profile declare conflicting API versions")
    if profile not in {"level0", "level1", "level2"}:
        raise SourceInventoryError("Only level0, level1 and level2 image service profiles are supported")
    return service_url, service_type, profile


def _painting(canvas: Mapping, version: int, canvas_id: str) -> Mapping:
    if version == 3:
        annotations = []
        pages = canvas.get("items")
        if not isinstance(pages, list) or not pages:
            raise SourceInventoryError(f"Canvas {canvas_id!r} has no embedded annotation pages")
        for page in pages:
            if not isinstance(page, Mapping) or _type(page) != "AnnotationPage" or not isinstance(page.get("items"), list):
                raise SourceInventoryError("Referenced or malformed AnnotationPages are unsupported; supply embedded pages")
            annotations.extend(page["items"])
    else:
        annotations = canvas.get("images")
        if not isinstance(annotations, list):
            raise SourceInventoryError(f"Canvas {canvas_id!r} has no image annotations")
    paintings = []
    for annotation in annotations:
        if not isinstance(annotation, Mapping):
            raise SourceInventoryError("Invalid source annotation")
        motivations = {_term(value) for value in _list(annotation.get("motivation"))}
        if "painting" in motivations:
            paintings.append(annotation)
    if len(paintings) != 1:
        raise SourceInventoryError(f"Canvas {canvas_id!r} must have exactly one painting annotation")
    annotation = paintings[0]
    if _type(annotation) != "Annotation":
        raise SourceInventoryError("The painting resource is not an Annotation")
    targets = _list(annotation.get("target" if version == 3 else "on"))
    if len(targets) != 1:
        raise SourceInventoryError("Painting annotations must target exactly one complete canvas")
    target = targets[0]
    if isinstance(target, Mapping):
        if target.get("selector") or target.get("source") or _type(target) not in {"", "Canvas"}:
            raise SourceInventoryError("Partial-canvas and SpecificResource painting targets are unsupported")
        target = _id(target, "Painting target")
    if target != canvas_id:
        raise SourceInventoryError("Painting annotations must target their complete canvas; regions are unsupported")
    bodies = _list(annotation.get("body" if version == 3 else "resource"))
    if len(bodies) != 1 or not isinstance(bodies[0], Mapping) or _type(bodies[0]) != "Image":
        raise SourceInventoryError("Only one Image painting body is supported; Choice and composite content are unsupported")
    return bodies[0]


def normalize_source_manifests(manifests, config: Mapping) -> list[dict]:
    """Normalize local JSON paths or loaded P2/P3 Manifest objects.

    Host code downloads ``config.manifestUrls`` before calling this function.
    ``recordLink.imageJoinField`` is one of canvas_id, canvas_label, image_url,
    or image_service_url. Existing grouping/ordering and image-service settings
    are ignored: the manifest itself supplies that information.
    """
    if isinstance(manifests, (str, Path, Mapping)):
        manifests = [manifests]
    else:
        manifests = list(manifests)
    if not manifests:
        raise SourceInventoryError("Provide at least one source manifest")
    record_link = config.get("recordLink", {})
    join_field = record_link.get("imageJoinField")
    if join_field not in {"canvas_id", "canvas_label", "image_url", "image_service_url"}:
        raise SourceInventoryError("Choose a manifest join field: canvas_id, canvas_label, image_url or image_service_url")
    normalization = record_link.get("normalization", "exact")
    inventory, seen_manifests = [], set()
    for manifest_position, source in enumerate(manifests, start=1):
        if isinstance(source, (str, Path)):
            try:
                manifest = json.loads(Path(source).read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as error:
                raise SourceInventoryError(f"Cannot read source manifest {str(source)!r}: {error}") from error
        else:
            manifest = source
        if not isinstance(manifest, Mapping) or _type(manifest) != "Manifest":
            raise SourceInventoryError("Expected a IIIF Manifest, not a Collection or another document")
        manifest_id = _id(manifest, "Manifest")
        if manifest_id in seen_manifests:
            raise SourceInventoryError(f"Duplicate source manifest: {manifest_id}")
        seen_manifests.add(manifest_id)
        if manifest.get("structures"):
            raise SourceInventoryError("Source manifests with nonempty ranges/structures are not supported yet")
        if manifest.get("type") == "Manifest":
            version = 3
            canvases = manifest.get("items")
        elif _term(manifest.get("@type")) == "Manifest":
            version = 2
            sequences = manifest.get("sequences")
            if not isinstance(sequences, list) or len(sequences) != 1 or not isinstance(sequences[0], Mapping):
                raise SourceInventoryError("Presentation 2 manifests must contain exactly one embedded sequence")
            canvases = sequences[0].get("canvases")
        else:
            raise SourceInventoryError("Only Presentation API 2 and 3 manifests are supported")
        if not isinstance(canvases, list) or not canvases:
            raise SourceInventoryError("A source manifest must contain at least one embedded canvas")
        manifest_labels = _labels(manifest.get("label"), fallback=manifest_id)
        manifest_metadata = _rights(manifest, version)
        seen_canvases = set()
        for canvas_position, canvas in enumerate(canvases, start=1):
            if not isinstance(canvas, Mapping) or _type(canvas) != "Canvas":
                raise SourceInventoryError("Only embedded Canvas resources are supported")
            canvas_id = _id(canvas, "Canvas")
            if canvas_id in seen_canvases:
                raise SourceInventoryError(f"Duplicate canvas identifier in manifest: {canvas_id}")
            seen_canvases.add(canvas_id)
            try:
                body = _painting(canvas, version, canvas_id)
                image_url = _http_url(_id(body, "Image body"), "Image body URL")
                width = _positive_int(body.get("width"), "Image width")
                height = _positive_int(body.get("height"), "Image height")
                if (_positive_int(canvas.get("width"), "Canvas width"),
                    _positive_int(canvas.get("height"), "Canvas height")) != (width, height):
                    raise SourceInventoryError("Differing image/canvas dimensions require a composition adapter and are unsupported")
                media_type = _text(body.get("format"))
                if not re.fullmatch(r"image/[a-zA-Z0-9.+-]+", media_type):
                    raise SourceInventoryError("The image body must specify its image MIME format")
                service_url, service_type, service_profile = _image_service(body)
                original_canvas_labels = _labels(canvas.get("label"))
                canvas_labels = original_canvas_labels or {"none": [f"Page {canvas_position}"]}
                row = {
                    "manifest_key": manifest_id, "manifest_id": manifest_id,
                    "manifest_label": _display(manifest_labels), "manifest_labels": manifest_labels,
                    "manifest_position": manifest_position, "source_manifest_metadata": manifest_metadata,
                    "canvas_key": canvas_id, "canvas_id": canvas_id,
                    "canvas_label": _display(canvas_labels), "canvas_labels": canvas_labels,
                    "canvas_position": canvas_position, "image_url": image_url,
                    "image_service_url": service_url, "image_service_type": service_type,
                    "image_service_profile": service_profile, "width": width, "height": height,
                    "media_type": media_type, "source_row": len(inventory) + 1,
                }
                join_value = _display(original_canvas_labels) if join_field == "canvas_label" else row[join_field]
                row["image_join_key"] = _join_key(join_value, normalization)
                inventory.append(row)
            except SourceInventoryError as error:
                raise SourceInventoryError(f"Manifest {manifest_id!r}, canvas {canvas_id!r}: {error}", error.report) from error
    return inventory
