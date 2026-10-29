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
    assert service["@type"] == "ImageService2"
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
    (lambda m: m.update(structures=[{"id": "range", "type": "Range"}]), "ranges/structures"),
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
