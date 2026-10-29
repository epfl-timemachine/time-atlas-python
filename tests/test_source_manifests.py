import copy
import json

import pytest

from timeatlas import (
    SourceInventoryError, UUIDManager, normalize_source_manifests,
    build_source_collection, link_source_records, write_source_inventory,
)


@pytest.fixture
def config():
    return {"enabled": True, "inputType": "manifest-url", "manifestUrls": ["https://source.test/manifest"],
            "recordLink": {"recordKeyField": "key", "recordImageField": "page",
                           "imageJoinField": "canvas_label", "normalization": "page-number", "missing": "error"}}


def manifest3(key="volume", pages=(4, 1, 174)):
    canvases = []
    for number in pages:
        canvas_id = f"https://source.test/{key}/canvas/{number}"
        service_id = f"https://images.test/iiif/3/book%2Fpages%2F{number}.jpg"
        body = {"id": service_id + "/full/max/0/default.jpg", "type": "Image",
                "width": 800, "height": 1000, "format": "image/jpeg",
                "service": [{"id": service_id, "type": "ImageService3", "profile": "level1"}]}
        canvases.append({"id": canvas_id, "type": "Canvas", "label": {"it": [f"pg. {number}"]},
                         "width": 800, "height": 1000,
                         "items": [{"id": canvas_id + "/page", "type": "AnnotationPage", "items": [
                             {"id": canvas_id + "/paint", "type": "Annotation", "motivation": "painting",
                              "body": [body], "target": canvas_id}]}],
                         "annotations": [{"type": "AnnotationPage", "items": [{"type": "Annotation", "body": [
                             {"type": "rde:HistoricalRecord", "id": "old-record-not-in-new-dataset"}]}]}]})
    return {"@context": "http://iiif.io/api/presentation/3/context.json", "type": "Manifest",
            "id": f"https://source.test/{key}/manifest", "label": {"en": ["Book"], "it": ["Libro"]},
            "rights": "https://creativecommons.org/publicdomain/mark/1.0/",
            "requiredStatement": {"label": {"en": ["Credit"]}, "value": {"en": ["Example Library"]}},
            "structures": [], "items": canvases}


def manifest2():
    manifest = manifest3(pages=(174,))
    canvas3 = manifest["items"][0]
    image3 = canvas3["items"][0]["items"][0]["body"][0]
    canvas_id = canvas3["id"]
    service_id = image3["service"][0]["id"]
    return {"@context": "http://iiif.io/api/presentation/2/context.json", "@type": "sc:Manifest",
            "@id": manifest["id"], "label": [{"@value": "Book", "@language": "en"}, {"@value": "Libro", "@language": "it"}],
            "license": manifest["rights"], "attribution": "Example Library",
            "sequences": [{"@id": manifest["id"] + "/sequence", "@type": "sc:Sequence", "canvases": [
                {"@id": canvas_id, "@type": "sc:Canvas", "label": "pg. 174", "width": 800, "height": 1000,
                 "images": [{"@id": canvas_id + "/painting", "@type": "oa:Annotation", "motivation": "sc:painting",
                             "on": canvas_id, "resource": {
                                 "@id": image3["id"].replace("/max/", "/full/"), "@type": "dctypes:Image",
                                 "width": 800, "height": 1000, "format": "image/jpeg",
                                 "service": {"@context": "http://iiif.io/api/image/2/context.json", "@id": service_id,
                                             "profile": ["http://iiif.io/api/image/2/level2.json", {"formats": ["png"]}]}}}]}]}]}


def first_painting(manifest):
    return manifest["items"][0]["items"][0]["items"][0]


def test_presentation3_retains_order_labels_metadata_and_exact_external_urls(config):
    source = manifest3()
    original = copy.deepcopy(source)
    result = normalize_source_manifests(source, config)
    assert [row["image_join_key"] for row in result] == ["4", "1", "174"]
    assert [row["canvas_position"] for row in result] == [1, 2, 3]
    assert result[0]["canvas_id"] == source["items"][0]["id"]
    assert result[0]["manifest_id"] == source["id"]
    assert result[0]["manifest_labels"] == source["label"]
    assert result[0]["canvas_labels"] == source["items"][0]["label"]
    assert result[0]["image_url"] == first_painting(source)["body"][0]["id"]
    assert result[0]["image_service_url"].endswith("book%2Fpages%2F4.jpg")
    assert result[0]["source_manifest_metadata"]["requiredStatement"] == source["requiredStatement"]
    assert source == original


def test_generation_preserves_original_order_and_labels_and_drops_old_hr_annotations(config):
    sources = [manifest3("z-volume"), manifest3("a-volume", pages=(22,))]
    for source in sources:
        source["structures"] = [{"id": source["id"] + "/contents", "type": "Range", "items": [
            {"id": canvas["id"], "type": "Canvas"} for canvas in reversed(source["items"])]}]
    inventory = normalize_source_manifests(sources, config)
    manager = UUIDManager("https://test.example/new-dataset")
    new_hr = UUIDManager.generate_uuid(manager.namespace, "new-record")
    links, report = link_source_records(inventory, [{"key": "record-1", "page": 174.0}], config,
                                        {"record-1": new_hr})
    collection, counts = build_source_collection(inventory, uuid_manager=manager, collection_key="new-dataset",
                                                 collection_label="Collection", links=links)
    assert [document.items[0].image_url for document in collection.items] == [
        first_painting(source)["body"][0]["id"] for source in sources]
    generated = collection.items[0].to_iiif(manager, "")
    assert [page["label"] for page in generated["items"]] == [page["label"] for page in sources[0]["items"]]
    assert generated["label"] == sources[0]["label"]
    assert generated["rights"] == sources[0]["rights"]
    assert generated["requiredStatement"] == sources[0]["requiredStatement"]
    assert not generated.get("structures")
    assert [row["manifest_position"] for row in inventory] == [1, 1, 1, 2]
    assert "old-record-not-in-new-dataset" not in json.dumps(generated)
    assert new_hr in json.dumps(generated)
    assert report["linked_record_count"] == 1 and counts["manifest_count"] == 2


def test_presentation2_sequence_image_service_and_attribution(config):
    result = normalize_source_manifests(manifest2(), config)
    assert result[0]["image_service_type"] == "ImageService2"
    assert result[0]["image_service_profile"] == "level2"
    assert result[0]["manifest_labels"] == {"en": ["Book"], "it": ["Libro"]}
    assert result[0]["source_manifest_metadata"]["requiredStatement"]["value"] == {"none": ["Example Library"]}
    manager = UUIDManager("https://test.example/p2")
    collection, _ = build_source_collection(result, uuid_manager=manager, collection_key="v2", collection_label="V2",
                                             allow_unlinked=True)
    service = collection.items[0].to_iiif(manager, "")["items"][0]["items"][0]["items"][0]["body"]["service"][0]
    assert service["type"] == "ImageService2"
    assert service["id"] == result[0]["image_service_url"]
    assert service["profile"] == "http://iiif.io/api/image/2/level2.json"


@pytest.mark.parametrize("field", ["canvas_id", "canvas_label", "image_url", "image_service_url"])
def test_manifest_join_fields_support_exact_matching(config, field):
    config["recordLink"].update({"imageJoinField": field, "normalization": "exact"})
    row = normalize_source_manifests(manifest3(), config)[0]
    assert row["image_join_key"] == row[field]


@pytest.mark.parametrize("field", ["canvas_id", "canvas_label", "image_url", "image_service_url"])
def test_manifest_page_number_joins_decode_only_match_key(config, field):
    config["recordLink"]["imageJoinField"] = field
    row = normalize_source_manifests(manifest3(), config)[0]
    assert row["image_join_key"] == "4"
    assert "%2F" in row["image_service_url"]


def test_missing_canvas_label_display_fallback_never_invents_join(config):
    source = manifest3(pages=(4,))
    del source["items"][0]["label"]
    row = normalize_source_manifests(source, config)[0]
    assert row["canvas_labels"] == {"none": ["Page 1"]}
    assert row["image_join_key"] == ""
    with pytest.raises(SourceInventoryError) as error:
        link_source_records([row], [{"key": "a", "page": 1}], config, {})
    assert error.value.report["unmatched_references"]


def test_local_json_paths_and_csv_language_maps(config, tmp_path):
    source = tmp_path / "downloaded-manifest.json"
    source.write_text(json.dumps(manifest3()))
    result = normalize_source_manifests([source], config)
    csv_path = write_source_inventory(result, tmp_path / "source-inventory.csv")
    import csv
    with csv_path.open() as stream:
        rows = list(csv.DictReader(stream))
    assert json.loads(rows[0]["manifest_labels"]) == result[0]["manifest_labels"]


@pytest.mark.parametrize("mutation,message", [
    (lambda m: m.update(type="Collection"), "Expected a IIIF Manifest"),
    (lambda m: m["items"].append(copy.deepcopy(m["items"][0])), "Duplicate canvas"),
    (lambda m: first_painting(m).update(target=m["items"][0]["id"] + "#xywh=0,0,1,1"), "complete canvas"),
    (lambda m: first_painting(m)["body"].append(copy.deepcopy(first_painting(m)["body"][0])), "one Image"),
    (lambda m: first_painting(m)["body"][0].update(type="Choice"), "Choice"),
    (lambda m: first_painting(m)["body"][0].pop("width"), "positive integer"),
    (lambda m: first_painting(m)["body"][0].pop("format"), "MIME format"),
    (lambda m: first_painting(m)["body"][0].pop("service"), "ImageService2/3"),
    (lambda m: m["items"][0].update(width=400), "Differing image/canvas dimensions"),
    (lambda m: m["items"][0]["items"][0].pop("items"), "embedded pages"),
    (lambda m: first_painting(m)["body"][0]["service"][0].update(type="ImageService4"), "ImageService2"),
])
def test_unsupported_or_incomplete_manifests_fail_explicitly(config, mutation, message):
    source = manifest3()
    mutation(source)
    with pytest.raises(SourceInventoryError, match=message):
        normalize_source_manifests(source, config)


def test_duplicate_manifest_and_multiple_v2_sequences_rejected(config):
    with pytest.raises(SourceInventoryError, match="Duplicate source manifest"):
        normalize_source_manifests([manifest3(), manifest3()], config)
    source = manifest2()
    source["sequences"].append(copy.deepcopy(source["sequences"][0]))
    with pytest.raises(SourceInventoryError, match="exactly one embedded sequence"):
        normalize_source_manifests(source, config)


def test_configured_inventory_settings_cannot_change_manifest_structure(config):
    config.update({"columns": {"imageKey": "stale"}, "grouping": {"mode": "per-image"},
                   "ordering": {"mode": "natural"}, "imageService": {"version": "2", "profile": "level0"}})
    result = normalize_source_manifests(manifest3(), config)
    assert len({row["manifest_key"] for row in result}) == 1
    assert [row["image_join_key"] for row in result] == ["4", "1", "174"]
    assert all(row["image_service_type"] == "ImageService3" and row["image_service_profile"] == "level1" for row in result)


@pytest.mark.parametrize("version", [2, 3])
def test_navigation_ranges_never_filter_duplicate_or_reorder_canvases(config, version):
    source = manifest3() if version == 3 else manifest2()
    if version == 3:
        first, _, last = source["items"]
        source["structures"] = [{"id": "https://source.test/contents", "type": "Range", "items": [
            {"id": last["id"], "type": "Canvas"},
            {"id": "https://source.test/chapter", "type": "Range", "items": [
                {"id": first["id"], "type": "Canvas"}, {"id": last["id"], "type": "Canvas"}]}]}]
        canvas_ids = [canvas["id"] for canvas in source["items"]]
    else:
        canvases = source["sequences"][0]["canvases"]
        second = copy.deepcopy(canvases[0])
        second["@id"] += "/second"
        second["images"][0]["on"] = second["@id"]
        canvases.append(second)
        source["structures"] = [{"@id": "https://source.test/contents", "@type": "sc:Range",
                                 "canvases": [second["@id"], second["@id"]]}]
        canvas_ids = [canvas["@id"] for canvas in canvases]
    original = copy.deepcopy(source)
    rows = normalize_source_manifests(source, config)
    assert [row["canvas_id"] for row in rows] == canvas_ids
    assert [row["canvas_position"] for row in rows] == list(range(1, len(canvas_ids) + 1))
    assert source == original
    manager = UUIDManager("https://test.example/navigation")
    collection, counts = build_source_collection(rows, uuid_manager=manager, collection_key="navigation",
                                                 collection_label="Navigation", allow_unlinked=True)
    generated = collection.items[0].to_iiif(manager, "")
    assert len(generated["items"]) == len(canvas_ids)
    assert not generated.get("structures")
    assert counts["manifest_count"] == 1


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("extension,expected", [
    ("jpg", "image/jpeg"), ("png", "image/png"), ("tif", "image/tiff"),
    ("gif", "image/gif"), ("webp", "image/webp"), ("jp2", "image/jp2"),
])
def test_delivered_image_format_overrides_archival_format(config, version, extension, expected):
    source = manifest3(pages=(4,)) if version == 3 else manifest2()
    body = first_painting(source)["body"][0] if version == 3 else source["sequences"][0]["canvases"][0]["images"][0]["resource"]
    id_key = "id" if version == 3 else "@id"
    service = body["service"][0] if version == 3 else body["service"]
    service[id_key] = service[id_key].removesuffix(".jpg") + ".tif"
    body[id_key] = service[id_key] + f"/full/{'max' if version == 3 else 'full'}/0/default.{extension}?download=1"
    body["format"] = "image/tiff" if expected != "image/tiff" else "image/jpeg"
    original = copy.deepcopy(source)
    rows = normalize_source_manifests(source, config)
    assert rows[0]["media_type"] == expected
    assert rows[0]["image_service_url"].endswith(".tif")
    assert rows[0]["image_url"] == body[id_key]
    assert source == original
    manager = UUIDManager("https://test.example/formats")
    collection, _ = build_source_collection(rows, uuid_manager=manager, collection_key="formats",
                                             collection_label="Formats", allow_unlinked=True)
    generated = first_painting(collection.items[0].to_iiif(manager, ""))["body"]
    assert generated["format"] == expected
    assert generated["id"] == body[id_key]


@pytest.mark.parametrize("image_url", [
    "https://images.test/download/scan.jpg",
    "https://images.test/iiif/3/scan/full/max/0/default.custom",
])
def test_non_iiif_or_unknown_format_urls_keep_declared_media_type(config, image_url):
    source = manifest3(pages=(4,))
    body = first_painting(source)["body"][0]
    body.update(id=image_url, format="image/tiff")
    assert normalize_source_manifests(source, config)[0]["media_type"] == "image/tiff"


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("identifier,canonical", [
    ("venice%2F%2Fcatastici%2F001.tif", "venice%2Fcatastici%2F001.tif"),
    ("venice%2f/%2Fcatastici%2f001.tif", "venice%2Fcatastici%2f001.tif"),
    ("venice//catastici/001.tif", "venice%2Fcatastici/001.tif"),
    ("venice/%2fcatastici/001.tif", "venice%2Fcatastici/001.tif"),
])
def test_manifest_path_style_image_pair_normalizes_only_duplicate_identifier_separators(config, version, identifier, canonical):
    source = manifest3(pages=(4,)) if version == 3 else manifest2()
    body = first_painting(source)["body"][0] if version == 3 else source["sequences"][0]["canvases"][0]["images"][0]["resource"]
    id_key = "id" if version == 3 else "@id"
    service = body["service"][0] if version == 3 else body["service"]
    prefix = f"HTTPS://Images.TEST/iiif/{version}/"
    query = "?token=opaque%2F%2F//&redirect=https://elsewhere.test/a//b"
    service[id_key] = prefix + identifier + query + "#service//fragment"
    body[id_key] = prefix + identifier + "/full/max/0/default.jpg" + query + "#image%2F%2Ffragment"
    original = copy.deepcopy(source)
    rows = normalize_source_manifests(source, config)
    assert rows[0]["image_service_url"] == prefix + canonical + query + "#service//fragment"
    assert rows[0]["image_url"] == prefix + canonical + "/full/max/0/default.jpg" + query + "#image%2F%2Ffragment"
    assert source == original


@pytest.mark.parametrize("identifier", [
    "venice%2fcatastici%2F001.tif",
    "venice/catastici/001.tif",
    "venice%2Fcatastici/001.tif",
    "venice%252F%252Fopaque%2F001.tif",
])
def test_valid_manifest_image_paths_are_preserved_byte_for_byte(config, identifier):
    source = manifest3(pages=(4,))
    body = first_painting(source)["body"][0]
    query = "?redirect=https://example.test/a//b&value=%2f%2F"
    body["service"][0]["id"] = "https://images.test/iiif/3/" + identifier + query
    body["id"] = "https://images.test/iiif/3/" + identifier + "/full/max/0/default.jpg" + query
    rows = normalize_source_manifests(source, config)
    assert rows[0]["image_url"] == body["id"]
    assert rows[0]["image_service_url"] == body["service"][0]["id"]


@pytest.mark.parametrize("image_url,service_url", [
    ("https://images.test/custom/book%2F%2F001.tif/full/max/0/default.jpg", "https://images.test/custom/book%2F%2F001.tif"),
    ("https://images.test/iiif/3/opaque%2F%2Fid/full/max/0/default.jpg", "https://images.test/iiif/3/opaque%2F%2Fid"),
    ("https://images.test/iiif/3/book%2F%2F001.tif/full/max/0/default.jpg", "https://other.test/iiif/3/book%2F%2F001.tif"),
    ("https://images.test/iiif/3/book%2F%2F001.tif/full/max/0/default.jpg", "https://images.test/iiif/3/other%2F%2F001.tif"),
    ("https://images.test/static/book%2F%2F001.jpg", "https://images.test/iiif/3/book%2F%2F001.tif"),
])
def test_unrecognized_or_unrelated_manifest_image_pair_is_not_rewritten(config, image_url, service_url):
    source = manifest3(pages=(4,))
    body = first_painting(source)["body"][0]
    body["id"] = image_url
    body["service"][0]["id"] = service_url
    rows = normalize_source_manifests(source, config)
    assert rows[0]["image_url"] == image_url
    assert rows[0]["image_service_url"] == service_url


def test_manifest_image_and_service_pair_can_have_one_canonical_identifier(config):
    source = manifest3(pages=(4,))
    body = first_painting(source)["body"][0]
    body["id"] = "https://images.test/iiif/3/book%2F%2F001.tif/full/max/0/default.jpg?download=1"
    body["service"][0]["id"] = "https://images.test/iiif/3/book%2F001.tif?info=1"
    row = normalize_source_manifests(source, config)[0]
    assert row["image_url"] == "https://images.test/iiif/3/book%2F001.tif/full/max/0/default.jpg?download=1"
    assert row["image_service_url"] == body["service"][0]["id"]
