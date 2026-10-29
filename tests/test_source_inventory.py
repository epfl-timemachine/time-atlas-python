import json
import uuid

import pytest

from timeatlas import (
    UUIDManager, Page, MultiLingualValue, SourceInventoryError,
    normalize_source_inventory, image_service_from_request, link_source_records,
    build_source_collection, write_source_collection, write_source_inventory,
)


@pytest.fixture
def config():
    return {
        "enabled": True, "inputType": "inventory",
        "columns": {"imageKey": "filename", "imageUrl": "url", "width": "width",
                    "height": "height", "mediaType": "media_type"},
        "imageService": {"version": "3", "profile": "level2"},
        "grouping": {"mode": "single"},
        "ordering": {"mode": "natural", "field": "filename"},
        "recordLink": {"recordKeyField": "id", "recordImageField": "page", "imageJoinField": "filename",
                       "normalization": "page-number", "missing": "error"},
    }


def source_row(number, **extra):
    return {"filename": f"/{number}.jpg", "width": "800", "height": "1200",
            "media_type": "image/jpeg",
            "url": f"https://external.test/iiif/3/book%2Fpages%2F/{number}.jpg/full/max/0/default.jpg",
            **extra}


def uuid_for(number):
    return str(uuid.UUID(int=number))


def test_inventory_preserves_encoded_external_urls_and_natural_order(config):
    rows = [source_row(10), source_row(2)]
    result = normalize_source_inventory(rows, config)
    assert [row["canvas_key"] for row in result] == ["/2.jpg", "/10.jpg"]
    assert [row["canvas_position"] for row in result] == [1, 2]
    assert result[0]["image_service_url"] == "https://external.test/iiif/3/book%2Fpages%2F/2.jpg"
    assert result[0]["image_url"] == rows[1]["url"]
    assert result[0]["canvas_label"] == "Page 1"
    assert result[0]["image_join_key"] == "2"


def test_service_url_inference_preserves_query_encoding():
    url = "https://external.test/iiif/2/a%2fb/full/full/0/default.jpg?key=a%2Fb"
    assert image_service_from_request(url) == "https://external.test/iiif/2/a%2fb?key=a%2Fb"
    with pytest.raises(SourceInventoryError, match="complete IIIF"):
        image_service_from_request("https://external.test/image.jpg")


@pytest.mark.parametrize("field,value", [("width", "0"), ("height", "1.5"), ("width", "nan"),
                                        ("url", "javascript:bad"), ("media_type", "image/png")])
def test_inventory_rejects_invalid_metadata(config, field, value):
    with pytest.raises(SourceInventoryError):
        normalize_source_inventory([source_row(1, **{field: value})], config)


def test_duplicate_images_rejected_but_repeat_across_manifests_supported(config):
    with pytest.raises(SourceInventoryError, match="Duplicate canvas"):
        normalize_source_inventory([source_row(1), source_row(1)], config)
    config["grouping"] = {"mode": "field", "field": "volume"}
    result = normalize_source_inventory([source_row(1, volume="a"), source_row(1, volume="b")], config)
    assert len(result) == 2


def test_grouping_mode_switch_ignores_inactive_label_settings(config):
    rows = [source_row(1, volume="a", title="Volume A"),
            source_row(2, volume="b", title="Volume B")]
    config["grouping"] = {"mode": "field", "field": "volume", "labelField": "title",
                          "label": "Old single-manifest label"}
    grouped = normalize_source_inventory(rows, config)
    assert [row["manifest_label"] for row in grouped] == ["Volume A", "Volume B"]

    # Switching to single leaves field/labelField values in the UI state.
    config["grouping"]["mode"] = "single"
    single = normalize_source_inventory(rows, config)
    assert {row["manifest_key"] for row in single} == {"source"}
    assert {row["manifest_label"] for row in single} == {"Old single-manifest label"}
    del config["grouping"]["label"]
    assert {row["manifest_label"] for row in normalize_source_inventory(rows, config)} == {""}

    # Per-image naming also ignores field and single-manifest label settings.
    config["grouping"]["mode"] = "per-image"
    config["grouping"]["label"] = "Old single-manifest label"
    separate = normalize_source_inventory(rows, config)
    assert [row["manifest_label"] for row in separate] == ["/1.jpg", "/2.jpg"]

    # A field group without its own label column uses the group key.
    config["grouping"]["mode"] = "field"
    del config["grouping"]["labelField"]
    assert [row["manifest_label"] for row in normalize_source_inventory(rows, config)] == ["a", "b"]


def test_multiple_hr_links_use_one_canvas(config):
    inventory = normalize_source_inventory([source_row(174), source_row(175)], config)
    records = [{"id": "a", "page": 174.0}, {"id": "b", "page": "174"}]
    links, report = link_source_records(inventory, records, config, {"a": uuid_for(1), "b": uuid_for(2)})
    collection, built = build_source_collection(
        inventory, uuid_manager=UUIDManager("https://test.example/dataset"),
        collection_key="book", collection_label="Book", links=links,
    )
    assert len(collection.items) == 1
    assert len(collection.items[0].items) == 2
    assert len(collection.items[0].items[0].annotations) == 2
    assert report["linked_record_count"] == 2
    assert report["unlinked_images"] == ["/175.jpg"]
    assert built["link_count"] == 2
    assert collection.items[0].label.values == {"none": ["Book"]}


def test_record_array_references_link_multiple_pages_and_shared_hrs(config):
    inventory = normalize_source_inventory([source_row(1), source_row(2)], config)
    records = [{"id": "a", "page": [1, 2, 2]}, {"id": "b", "page": 2}]
    links, report = link_source_records(inventory, records, config,
                                        {"a": uuid_for(1), "b": uuid_for(1)})
    collection, counts = build_source_collection(
        inventory, uuid_manager=UUIDManager("https://test.example/shared"),
        collection_key="book", collection_label="Book", links=links,
    )
    assert [len(page.annotations) for page in collection.items[0].items] == [1, 1]
    assert counts["link_count"] == 2
    assert report["linked_record_count"] == 2


def test_csv_reference_strings_are_not_split(config):
    inventory = normalize_source_inventory([source_row(1), source_row(2)], config)
    with pytest.raises(SourceInventoryError) as error:
        link_source_records(inventory, [{"id": "a", "page": "1,2"}], config, {"a": uuid_for(1)})
    assert error.value.report["invalid_references"]


def test_missing_links_require_explicit_policy_and_preserve_diagnostics(config):
    inventory = normalize_source_inventory([source_row(174)], config)
    records = [{"id": "a", "page": ""}, {"id": "b", "page": 999}]
    with pytest.raises(SourceInventoryError) as error:
        link_source_records(inventory, records, config, {})
    assert error.value.report["missing_references"] == ["a"]
    assert error.value.report["unmatched_references"] == [{"record_key": "b", "value": "999"}]
    config["recordLink"]["missing"] = "allow-unlinked"
    links, report = link_source_records(inventory, records, config, {})
    assert links == [] and report["linked_record_count"] == 0


def test_ambiguous_page_numbers_never_silently_link(config):
    config["grouping"] = {"mode": "field", "field": "volume"}
    config["recordLink"]["missing"] = "allow-unlinked"
    inventory = normalize_source_inventory([source_row(1, volume="a"), source_row(1, volume="b")], config)
    with pytest.raises(SourceInventoryError) as error:
        link_source_records(inventory, [{"id": "a", "page": 1}], config, {"a": uuid_for(1)})
    assert error.value.report["ambiguous_references"] == [{"record_key": "a", "value": "1"}]


def test_ids_stable_when_rows_reordered_and_an_earlier_page_added(config):
    manager = UUIDManager("https://test.example/stable")
    def generate(rows):
        inventory = normalize_source_inventory(rows, config)
        return build_source_collection(inventory, uuid_manager=manager, collection_key="stable",
                                       collection_label="Book", allow_unlinked=True)[0]
    first = generate([source_row(10), source_row(2)])
    second = generate([source_row(1), source_row(2), source_row(10)])
    assert first.id == second.id
    assert first.items[0].id == second.items[0].id
    assert {page.object_ref: page.id for page in first.items[0].items} == {
        page.object_ref: page.id for page in second.items[0].items if page.object_ref != "/1.jpg"}


@pytest.mark.parametrize("version", ["2", "3"])
def test_external_images_and_thumbnails_use_original_host_and_service_metadata(config, version):
    config["imageService"] = {"version": version, "profile": "level1"}
    manager = UUIDManager("https://test.example/external")
    inventory = normalize_source_inventory([source_row(1)], config)
    collection, _ = build_source_collection(inventory, uuid_manager=manager, collection_key="book",
                                            collection_label="Book", allow_unlinked=True)
    manifest = collection.items[0].to_iiif(manager, "https://internal.test")
    body = manifest["items"][0]["items"][0]["items"][0]["body"]
    service = body["service"][0]
    assert body["id"] == source_row(1)["url"]
    assert service.get("id", service.get("@id")) == inventory[0]["image_service_url"]
    assert service.get("type", service.get("@type")) == "ImageService" + version
    assert service["profile"] == ("level1" if version == "3" else "http://iiif.io/api/image/2/level1.json")
    assert manifest["thumbnail"][0]["id"] == body["id"]
    assert collection.to_iiif("https://internal.test")["items"][0]["thumbnail"][0]["id"] == body["id"]


def test_csv_and_json_inputs_and_separate_output_paths(config, tmp_path):
    rows = [source_row(1)]
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"rows": rows}))
    inventory = normalize_source_inventory(raw, config)
    manager = UUIDManager("https://test.example/write")
    collection, _ = build_source_collection(inventory, uuid_manager=manager, collection_key="book",
                                            collection_label="Book", allow_unlinked=True)
    files = write_source_collection(collection, uuid_manager=manager, output_dir=tmp_path / "output")
    assert {path.parent.name for path in files} == {"manifests", "collections"}
    assert all(path.name == json.loads(path.read_text())["id"] + ".json" for path in files)
    path = write_source_inventory(inventory, tmp_path / "job" / "source-inventory.csv")
    assert path.exists() and "image_service_url" in path.read_text()


def test_explicit_service_url_and_image_mime_are_retained(config):
    config["columns"]["serviceUrl"] = "service"
    row = source_row(1, service="https://different.test/iiif/a%2Fb",
                     url="https://cdn.test/page.png", media_type="image/png")
    result = normalize_source_inventory([row], config)[0]
    assert result["image_service_url"] == row["service"]
    assert result["image_url"] == row["url"]
    assert result["media_type"] == "image/png"


def test_bare_external_page_does_not_invent_image_service():
    page = Page(id=uuid_for(1), label=MultiLingualValue({"en": ["Page"]}), format="image/png",
                range_idx=1, width=5, height=6, object_ref="key", image_url="https://cdn.test/page.png")
    assert "service" not in page.image_body("https://internal.test")
    assert page.to_dict()["image_url"] == "https://cdn.test/page.png"


def test_service_capabilities_must_be_explicit(config):
    del config["imageService"]
    with pytest.raises(SourceInventoryError, match="Image API version"):
        normalize_source_inventory([source_row(1)], config)
