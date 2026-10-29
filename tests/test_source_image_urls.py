import hashlib
import json

import pytest

from timeatlas import (
    SourceInventoryError, UUIDManager, plan_source_image_urls, normalize_source_image_urls,
    link_source_records, build_source_collection,
)


@pytest.fixture
def config():
    return {"enabled": True, "inputType": "image-urls", "grouping": {"mode": "single"},
            "ordering": {"mode": "inventory"}, "recordLink": {"recordKeyField": "id", "recordImageField": "page",
              "imageJoinField": "image_filename", "normalization": "page-number", "missing": "error"}}


def image_url(number=174, *, version=3, format="jpg", directory="book"):
    size = "max" if version == 3 else "full"
    return f"https://images.test/iiif/{version}/{directory}%2F{number}.tif/full/{size}/0/default.{format}"


def snapshot(url, *, version=3, profile="level2", **extra):
    item = plan_source_image_urls([url])[0]
    info = {"@context": f"http://iiif.io/api/image/{version}/context.json", "protocol": "http://iiif.io/api/image",
            "width": 800, "height": 1200}
    if version == 3:
        info.update({"id": item["image_service_url"], "type": "ImageService3", "profile": profile})
    else:
        info.update({"@id": item["image_service_url"], "profile": [f"http://iiif.io/api/image/2/{profile}.json"]})
    info.update(extra)
    return {"serviceUrl": item["image_service_url"], "infoUrl": item["info_url"], "finalUrl": item["info_url"], "info": info}


def test_plan_preserves_url_encoding_query_and_text_order(tmp_path):
    url = image_url(174) + "?key=a%2Fb"
    path = tmp_path / "images.txt"
    path.write_text("\ufeff" + url + "\n\n" + image_url(1) + "\n", encoding="utf-8")
    plan = plan_source_image_urls(path)
    assert plan[0] == {"image_url": url,
                       "image_service_url": "https://images.test/iiif/3/book%2F174.tif?key=a%2Fb",
                       "info_url": "https://images.test/iiif/3/book%2F174.tif/info.json?key=a%2Fb",
                       "source_position": 1, "request_format": "jpg"}
    assert plan[1]["source_position"] == 2


def test_typo_is_never_repaired_in_plan_or_input(tmp_path):
    url = image_url().replace("book%2F174", "book%2F/174")
    path = tmp_path / "images.txt"
    path.write_text(url + "\n")
    plan = plan_source_image_urls(path)
    assert "%2F/174" in plan[0]["info_url"]
    assert plan[0]["image_url"] == url and path.read_text() == url + "\n"


def test_info_dimensions_and_requested_jpeg_mime_not_underlying_tiff(config):
    url = image_url()
    result = normalize_source_image_urls([url], [snapshot(url)], config)
    row = result[0]
    assert row["width"] == 800 and row["height"] == 1200
    assert row["media_type"] == "image/jpeg"
    assert row["image_identifier"] == "book/174.tif"
    assert row["image_filename"] == "174.tif"
    assert row["image_directory"] == "/iiif/3/book"
    assert row["canvas_label"] == "Page 1" and row["image_join_key"] == "174"
    assert row["image_url"] == url
    assert row["image_service_type"] == "ImageService3" and row["image_service_profile"] == "level2"


def test_mixed_service_versions_and_profiles_are_not_overridden_by_ui(config):
    urls = [image_url(1, version=2), image_url(2)]
    snapshots = [snapshot(urls[0], version=2, profile="level1"), snapshot(urls[1], profile="level2")]
    config["imageService"] = {"version": "2", "profile": "level0"}
    rows = normalize_source_image_urls(urls, snapshots, config)
    assert [(row["image_service_type"], row["image_service_profile"]) for row in rows] == [
        ("ImageService2", "level1"), ("ImageService3", "level2")]


def test_image_api_21_max_size_and_legacy_image_type(config):
    url = image_url(174, version=2).replace("/full/full/", "/full/max/")
    item = snapshot(url, version=2)
    item["info"]["@type"] = "iiif:Image"
    row = normalize_source_image_urls([url], [item], config)[0]
    assert row["image_service_type"] == "ImageService2"
    assert (row["width"], row["height"]) == (800, 1200)


def test_grouping_natural_order_labels_and_hr_join_use_derived_fields(config):
    urls = [image_url(10), image_url(2), image_url(1, directory="postcard")]
    config.update({"grouping": {"mode": "field", "field": "image_directory"},
                   "ordering": {"mode": "natural"}, "columns": {"label": "image_filename"}})
    rows = normalize_source_image_urls(urls, [snapshot(url) for url in urls], config)
    assert [row["image_filename"] for row in rows] == ["2.tif", "10.tif", "1.tif"]
    assert [row["canvas_position"] for row in rows] == [1, 2, 1]
    assert rows[0]["canvas_label"] == "2.tif"
    manager = UUIDManager("https://test.example/url-only")
    hr_id = UUIDManager.generate_uuid(manager.namespace, "record")
    links, report = link_source_records(rows, [{"id": "a", "page": 2.0}], config, {"a": hr_id})
    collection, counts = build_source_collection(rows, uuid_manager=manager, collection_key="url-only",
                                                  collection_label="Source", links=links)
    assert counts["manifest_count"] == 2 and report["linked_record_count"] == 1
    assert collection.items[0].items[0].annotations[0].hr_id == hr_id


def test_numeric_default_uses_input_position_and_ids_survive_reordering(config):
    urls = [image_url(10), image_url(2)]
    config["ordering"] = {"mode": "numeric"}
    first = normalize_source_image_urls(urls, [snapshot(url) for url in urls], config)
    second = normalize_source_image_urls(urls[::-1], [snapshot(url) for url in urls], config)
    assert [row["image_url"] for row in first] == urls
    manager = UUIDManager("https://test.example/url-stability")
    def ids(rows):
        collection, _ = build_source_collection(rows, uuid_manager=manager, collection_key="stable",
                                                 collection_label="Source", allow_unlinked=True)
        return {page.image_url: page.id for page in collection.items[0].items}
    assert ids(first) == ids(second)


@pytest.mark.parametrize("change,message", [
    (lambda s: s["info"].update(id="https://other.test/unrelated"), "does not match"),
    (lambda s: s.update(serviceUrl="https://images.test/wrong"), "planned service"),
    (lambda s: s["info"].update(width=0), "positive integer"),
    (lambda s: s["info"].update(maxArea=100), "service limits"),
    (lambda s: s["info"].update(maxWidth=1000), "service limits"),
    (lambda s: s["info"].update(maxHeight=1200), "requires maxWidth"),
    (lambda s: s["info"].update(type="ImageService4"), "ImageService2"),
])
def test_invalid_or_limiting_info_fails(config, change, message):
    url = image_url()
    item = snapshot(url)
    change(item)
    with pytest.raises(SourceInventoryError, match=message):
        normalize_source_image_urls([url], [item], config)


def test_full_image_with_nonlimiting_constraints_and_v2_nested_limits(config):
    url = image_url()
    result = normalize_source_image_urls([url], [snapshot(url, maxWidth=1200, maxArea=960000)], config)
    assert result[0]["height"] == 1200
    url2 = image_url(version=2)
    item = snapshot(url2, version=2)
    item["info"]["profile"].append({"maxArea": 100})
    with pytest.raises(SourceInventoryError, match="service limits"):
        normalize_source_image_urls([url2], [item], config)


def test_redirected_and_percent_equivalent_service_id_allowed_but_slash_typo_rejected(config):
    url = image_url()
    item = snapshot(url)
    item["info"]["id"] = item["serviceUrl"].replace("%2F", "%2f")
    result = normalize_source_image_urls([url], [item], config)
    assert result[0]["image_service_url"] == item["info"]["id"]
    assert result[0]["image_url"] == url
    item["info"]["id"] = "https://cdn.test/iiif/book%2F174.tif"
    item["finalUrl"] = item["info"]["id"] + "/info.json"
    assert normalize_source_image_urls([url], [item], config)[0]["image_service_url"].startswith("https://cdn.test")
    typo = url.replace("book%2F174", "book%2F/174")
    wrong = snapshot(typo)
    wrong["info"]["id"] = wrong["info"]["id"].replace("%2F/", "%2F")
    with pytest.raises(SourceInventoryError, match="does not match"):
        normalize_source_image_urls([typo], [wrong], config)


def test_requested_format_needs_advertised_support_and_yields_its_own_mime(config):
    url = image_url(format="webp")
    with pytest.raises(SourceInventoryError, match="does not advertise"):
        normalize_source_image_urls([url], [snapshot(url)], config)
    result = normalize_source_image_urls([url], [snapshot(url, extraFormats=["webp"])], config)
    assert result[0]["media_type"] == "image/webp"
    png = image_url(format="png")
    assert normalize_source_image_urls([png], [snapshot(png)], config)[0]["media_type"] == "image/png"


def test_snapshot_paths_and_checksums(config, tmp_path):
    url = image_url()
    item = snapshot(url)
    raw = json.dumps(item.pop("info")).encode()
    file = tmp_path / "info.json"
    file.write_bytes(raw)
    item.update(path=str(file), sha256=hashlib.sha256(raw).hexdigest())
    assert normalize_source_image_urls([url], [item], config)[0]["source_info_sha256"] == item["sha256"]
    item["sha256"] = "0" * 64
    with pytest.raises(SourceInventoryError, match="checksum"):
        normalize_source_image_urls([url], [item], config)


@pytest.mark.parametrize("replacement", ["full/300,/0/default.jpg", "square/max/0/default.jpg",
                                         "full/max/90/default.jpg", "full/max/0/gray.jpg"])
def test_transformed_image_requests_fail_at_planning(replacement):
    url = image_url().replace("full/max/0/default.jpg", replacement)
    with pytest.raises(SourceInventoryError, match="Only full"):
        plan_source_image_urls([url])


def test_missing_duplicate_snapshots_and_urls_rejected(config):
    url = image_url()
    with pytest.raises(SourceInventoryError, match="Missing info"):
        normalize_source_image_urls([url], [], config)
    with pytest.raises(SourceInventoryError, match="Duplicate info"):
        normalize_source_image_urls([url], [snapshot(url), snapshot(url)], config)
    with pytest.raises(SourceInventoryError, match="Duplicate image"):
        plan_source_image_urls([url, url])


def test_size_syntax_must_match_detected_image_api_version(config):
    url = image_url().replace("/max/", "/full/")
    with pytest.raises(SourceInventoryError, match="size syntax"):
        normalize_source_image_urls([url], [snapshot(url)], config)


def test_url_and_text_size_limits():
    with pytest.raises(SourceInventoryError, match="10000"):
        plan_source_image_urls([image_url(number) for number in range(10001)])
    with pytest.raises(SourceInventoryError, match="2 MiB"):
        plan_source_image_urls(["https://example.test/" + "a" * (2 * 1024 * 1024)])


def test_multiline_url_text_preserves_nonempty_line_order():
    urls = [image_url(2), image_url(1)]
    plan = plan_source_image_urls(urls[0] + "\n\n" + urls[1] + "\n")
    assert [row["image_url"] for row in plan] == urls
    assert [row["source_position"] for row in plan] == [1, 2]


@pytest.mark.parametrize("urls,message", [
    ([], "image URL list is empty"),
    ([image_url(), None], "Every image URL must be a string"),
    ([image_url(format="bmp")], "Image URL 1: Unsupported requested image format"),
])
def test_invalid_url_lists_fail_before_metadata_download(urls, message):
    with pytest.raises(SourceInventoryError, match=message):
        plan_source_image_urls(urls)


@pytest.mark.parametrize("kind,message", [
    ("missing", "Cannot read the UTF-8 image URL list"),
    ("invalid-utf8", "Cannot read the UTF-8 image URL list"),
    ("oversized", "2 MiB"),
])
def test_unreadable_or_oversized_url_files_are_reported(tmp_path, kind, message):
    path = tmp_path / "images.txt"
    if kind == "invalid-utf8":
        path.write_bytes(b"\xff")
    elif kind == "oversized":
        path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(SourceInventoryError, match=message):
        plan_source_image_urls(path)


@pytest.mark.parametrize("item", [None, {}, {"infoUrl": 42}])
def test_snapshot_requires_requested_info_url(config, item):
    with pytest.raises(SourceInventoryError, match="Each info snapshot must identify"):
        normalize_source_image_urls([image_url()], [item], config)


@pytest.mark.parametrize("kind,message", [
    ("missing-path", "Cannot read an info.json snapshot"),
    ("missing-file", "Cannot read an info.json snapshot"),
    ("invalid-json", "Cannot read an info.json snapshot"),
    ("invalid-utf8", "Cannot read an info.json snapshot"),
    ("not-object", "must contain a JSON object"),
])
def test_bad_metadata_snapshots_keep_image_position_in_errors(config, tmp_path, kind, message):
    url = image_url()
    item = snapshot(url)
    if kind == "not-object":
        item["info"] = []
    else:
        del item["info"]
        if kind != "missing-path":
            path = tmp_path / "info.json"
            item["path"] = str(path)
            if kind == "invalid-json":
                path.write_text("{broken")
            elif kind == "invalid-utf8":
                path.write_bytes(b"\xff")
    with pytest.raises(SourceInventoryError) as error:
        normalize_source_image_urls([url], [item], config)
    assert str(error.value).startswith("Image URL 1: ")
    assert message in str(error.value)


@pytest.mark.parametrize("change,message", [
    (lambda s: s["info"].update(id=s["serviceUrl"] + "#fragment"), "must not contain fragments"),
    (lambda s: s.update(finalUrl="https://cdn.test/metadata"), "must end in /info.json"),
    (lambda s: s["info"].update(protocol="https://other.test/protocol"), "different protocol"),
    (lambda s: s["info"].update(extraFormats="webp"), "invalid format declaration"),
    (lambda s: s["info"].update(extraFormats=[1]), "invalid format declaration"),
    (lambda s: s.update(finalUrl="https://images.test:invalid/book/info.json"), "invalid port"),
    (lambda s: (s["info"].update(id="https://images.test/"), s.update(finalUrl="https://images.test//info.json")), "no identifier basename"),
])
def test_invalid_service_metadata_has_specific_errors(config, change, message):
    url = image_url()
    item = snapshot(url)
    change(item)
    with pytest.raises(SourceInventoryError, match=message):
        normalize_source_image_urls([url], [item], config)


def test_unredirected_snapshot_and_explicit_order_field_preserve_config(config):
    import copy

    urls = [image_url(2), image_url(1)]
    snapshots = [snapshot(url) for url in urls]
    for item in snapshots:
        item.pop("finalUrl")
    config["ordering"] = {"mode": "numeric", "field": "source_position"}
    config["recordLink"].pop("imageJoinField")
    original = copy.deepcopy(config)
    rows = normalize_source_image_urls(urls, snapshots, config)
    assert [row["image_url"] for row in rows] == urls
    assert [row["image_join_key"] for row in rows] == ["2", "1"]
    assert config == original


@pytest.mark.parametrize("settings", [
    {"columns": {"label": "unknown"}},
    {"grouping": {"mode": "field", "field": "unknown"}},
    {"grouping": {"mode": "field", "field": "image_directory", "labelField": "unknown"}},
    {"ordering": {"mode": "natural", "field": "unknown"}},
    {"recordLink": {"imageJoinField": "unknown"}},
])
def test_url_list_mappings_reject_unavailable_columns(config, settings):
    config.update(settings)
    url = image_url()
    with pytest.raises(SourceInventoryError, match="documented derived field"):
        normalize_source_image_urls([url], [snapshot(url)], config)
