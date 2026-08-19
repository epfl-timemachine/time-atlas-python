import uuid
from collections import OrderedDict

import pandas as pd
import pytest
from PIL import Image

from timeatlas import (
    Annotation,
    Collection,
    Document,
    FileReference,
    Model,
    MultiLingualValue,
    Page,
    Selector,
    SelectorType,
    UUIDManager,
    int_tuple_list_to_svg_string,
    multiindex_to_nested_dict,
    ordered_dict_to_iiif_toc_structure,
    url_encoded_iiif_image_url,
)


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


@pytest.fixture
def manager():
    return UUIDManager("https://example.test/documents")


def test_svg_path_generation_closes_polygon_and_rejects_empty_input():
    svg = int_tuple_list_to_svg_string([(1, 2), (3, 4), (5, 6)])
    assert "M1,2L3,4 L5,6 L1,2" in svg
    assert svg.endswith("' /></g></svg>")
    with pytest.raises(ValueError, match="At least one coordinate"):
        int_tuple_list_to_svg_string([])


def test_multiindex_conversion_and_toc_generation():
    index = pd.MultiIndex.from_tuples(
        [("Volume I", "Page 1"), ("Volume I", "Page 2"), ("Volume II", "Page 1")]
    )
    dataframe = pd.DataFrame({"canvas_id": ["canvas-1", "canvas-2", "canvas-3"]}, index=index)

    nested = multiindex_to_nested_dict(dataframe)
    toc = ordered_dict_to_iiif_toc_structure(nested, "en", "Contents", "range")

    assert isinstance(nested, OrderedDict)
    assert nested["Volume I"]["Page 2"] == "canvas-2"
    assert toc["items"][0]["label"] == {"en": ["Volume I"]}
    assert toc["items"][0]["items"][1]["items"] == [{"id": "canvas-2", "type": "Canvas"}]


def test_toc_generation_supports_explicit_canvas_lists():
    toc = ordered_dict_to_iiif_toc_structure(
        OrderedDict([("Chapter", ["canvas-1", "canvas-2"])]), "en", "Book", "range"
    )
    assert [item["id"] for item in toc["items"][0]["items"]] == ["canvas-1", "canvas-2"]


def test_iiif_image_url_encodes_paths():
    assert (
        url_encoded_iiif_image_url("https://images.test", "folder/image name.jpg")
        == "https://images.test/folder%2Fimage+name.jpg"
    )


def test_file_reference_extracts_image_metadata_and_generates_page(tmp_path, manager):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (32, 24), color="red").save(image_path)
    reference = FileReference(id=uid(1), path_name=str(image_path))

    metadata = reference.get_image_metadata()
    page = reference.generate_page_from_file_reference(
        manager, MultiLingualValue({"en": ["Page"]}), range_idx=2
    )

    assert metadata == {"width": 32, "height": 24, "format": "image/png"}
    assert page.width == 32 and page.height == 24
    assert page.object_ref is reference
    assert page.range_idx == 2


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [
        ("model.gltf", "model/gltf+json"),
        ("model.glb", "model/gltf-binary"),
        ("model.obj", "model/obj"),
        ("model.stl", "model/stl"),
        ("model.fbx", "model/fbx"),
        ("model.dae", "model/vnd.collada+xml"),
        ("model.ply", "model/ply"),
        ("model.3ds", "model/3ds"),
        ("model.usdz", "model/vnd.usdz+zip"),
        ("model.las", "application/vnd.las"),
        ("model.laz", "application/vnd.las"),
        ("model.custom", "model/custom"),
        ("model", "model/unknown"),
    ],
)
def test_file_reference_detects_model_mime_types(filename, mime_type):
    assert FileReference(id=uid(2), path_name=filename).get_model_metadata() == mime_type


def test_file_reference_generates_model(manager):
    reference = FileReference(id=uid(3), path_name="building.glb")
    model = reference.generate_model_from_file_reference(
        manager, MultiLingualValue({"en": ["Building"]})
    )
    assert model.format == "model/gltf-binary"
    assert model.object_ref is reference


@pytest.mark.parametrize(
    ("selector_type", "value", "expected"),
    [
        (
            SelectorType.POINT,
            (10, 20),
            {
                "type": "SpecificResource",
                "source": "canvas",
                "selector": {"type": "PointSelector", "x": 10, "y": 20},
            },
        ),
        (SelectorType.XYWH, (1, 2, 3, 4), "canvas#xywh=1,2,3,4"),
    ],
)
def test_selector_templates(selector_type, value, expected):
    assert Selector(selector_type, value, "canvas").generate_selector_template() == expected


def test_svg_selector_template_contains_svg_path():
    template = Selector(SelectorType.SVG, [(0, 0), (1, 1), (2, 0)], "canvas").generate_selector_template()
    assert template["selector"]["type"] == "SvgSelector"
    assert "<path" in template["selector"]["value"]


def test_svg_selector_preserves_all_polygons():
    template = Selector(
        SelectorType.SVG,
        [[(0, 0), (1, 0), (1, 1)], [(10, 10), (11, 10), (11, 11)]],
        "canvas",
    ).generate_selector_template()
    svg = template["selector"]["value"]
    assert svg.count("<path") == 2
    assert "M0,0" in svg and "M10,10" in svg
    assert svg.count(" Z") == 2


@pytest.mark.parametrize(
    ("selector_type", "value", "message"),
    [
        (SelectorType.POINT, (1,), "Point selector"),
        (SelectorType.XYWH, (1, 2), "XYWH selector"),
        (SelectorType.SVG, (1, 2), "SVG selector"),
    ],
)
def test_selector_validation(selector_type, value, message):
    with pytest.raises(ValueError, match=message):
        Selector(selector_type, value, "canvas")


def test_selector_rejects_unknown_type():
    selector = Selector(SelectorType.POINT, (1, 2), "canvas")
    selector.type = object()
    with pytest.raises(ValueError, match="not recognized"):
        selector.generate_selector_template()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lang": "en"},
        {"value": "Text"},
        {
            "selector": Selector(SelectorType.POINT, (1, 2), "canvas"),
            "lang": "en",
        },
        {},
    ],
)
def test_annotation_validation(kwargs):
    with pytest.raises(ValueError):
        Annotation(id=uid(10), **kwargs)


def test_annotation_validates_uuid_before_rendering():
    with pytest.raises(ValueError, match="Invalid UUID"):
        Annotation(id="invalid", lang="en", value="Text")


def test_annotation_to_iiif_supports_text_hr_selector_and_external_resource(manager):
    annotation = Annotation(
        id=uid(11),
        lang="en",
        value="<p>Text</p>",
        hr_id=uid(12),
        selector=Selector(SelectorType.POINT, (4, 5), "canvas"),
        external_resource="https://example.test/context",
    )
    rendered = annotation.to_iiif(manager, "canvas")

    assert rendered["motivation"] == "commenting"
    assert rendered["body"][0]["language"] == "en"
    assert rendered["body"][1] == {"type": "rde:HistoricalRecord", "id": uid(12)}
    assert rendered["target"][0]["selector"]["x"] == 4
    assert rendered["target"][1]["type"] == "ExternalResource"


def test_annotation_can_contain_only_historical_record(manager):
    rendered = Annotation(id=uid(13), hr_id=uid(14)).to_iiif(manager, "canvas", "Scene")
    assert rendered["body"] == [{"type": "rde:HistoricalRecord", "id": uid(14)}]
    assert rendered["target"] == [{"type": "Scene", "id": "canvas"}]


def test_page_to_iiif_renders_painting_and_commenting_annotations(manager):
    annotation = Annotation(id=uid(20), lang="en", value="Note")
    page = Page(
        id=uid(21),
        label=MultiLingualValue({"en": ["Page"]}),
        format="image/jpeg",
        range_idx=1,
        height=100,
        width=200,
        object_ref="folder/page 1.jpg",
        annotations=[annotation],
    )
    rendered = page.to_iiif(manager, "https://images.test")

    assert rendered["type"] == "Canvas"
    assert rendered["items"][0]["items"][0]["body"]["service"][0]["type"] == "ImageService3"
    assert "folder%2Fpage+1.jpg" in rendered["items"][0]["items"][0]["body"]["id"]
    assert rendered["annotations"][0]["items"][0]["body"][0]["value"] == "Note"


def test_page_rejects_unpublished_file_reference(manager):
    page = Page(
        id=uid(22),
        label=MultiLingualValue(),
        format="image/png",
        range_idx=1,
        height=1,
        width=1,
        object_ref=FileReference(id=uid(23), path_name="local.png"),
    )
    with pytest.raises(ValueError, match="file object reference"):
        page.to_iiif(manager, "https://images.test")


def test_model_to_iiif_renders_scene_and_annotations(manager):
    annotation = Annotation(id=uid(30), hr_id=uid(31))
    model = Model(
        id=uid(32),
        label=MultiLingualValue({"en": ["Model"]}),
        format="model/gltf-binary",
        object_ref="https://models.test/model.glb",
        annotations=[annotation],
    )
    rendered = model.to_iiif(manager)

    assert rendered["type"] == "Scene"
    assert rendered["items"][0]["items"][0]["body"]["type"] == "Model"
    assert rendered["annotations"][0]["items"][0]["body"][0]["id"] == uid(31)


def test_model_rejects_file_reference(manager):
    model = Model(
        id=uid(33),
        label=MultiLingualValue(),
        format="model/gltf-binary",
        object_ref=FileReference(id=uid(34), path_name="local.glb"),
    )
    with pytest.raises(ValueError, match="file object reference"):
        model.to_iiif(manager)


def test_document_and_manifest_item_render_pages_models_and_structures(manager):
    page = Page(
        id=uid(40),
        label=MultiLingualValue({"en": ["Page"]}),
        format="image/png",
        range_idx=1,
        height=10,
        width=20,
        object_ref="page.png",
    )
    model = Model(
        id=uid(41),
        label=MultiLingualValue({"en": ["Model"]}),
        format="model/gltf+json",
        object_ref="model.gltf",
    )
    document = Document(
        id=uid(42),
        label=MultiLingualValue({"en": ["Document"]}),
        items=[page, model],
        structures={"id": "range", "type": "Range", "items": []},
    )

    manifest = document.to_iiif(manager, "https://images.test", presentation_version="4")
    item = document.to_iiif_manifest_item("https://images.test", with_thumbnail=False)

    assert manifest["@context"].endswith("/4/context.json")
    assert [entry["type"] for entry in manifest["items"]] == ["Canvas", "Scene"]
    assert manifest["structures"][0]["id"] == "range"
    assert item["thumbnail"] == []


def test_collection_supports_documents_and_nested_collections():
    page = Page(
        id=uid(50),
        label=MultiLingualValue(),
        format="image/png",
        range_idx=1,
        height=1,
        width=1,
        object_ref="page.png",
    )
    document = Document(id=uid(51), label=MultiLingualValue({"en": ["Doc"]}), items=[page])
    nested = Collection(id=uid(52), label=MultiLingualValue({"en": ["Nested"]}), items=[])
    collection = Collection(
        id=uid(53),
        label=MultiLingualValue({"en": ["Root"]}),
        items=[document, nested],
    )

    rendered = collection.to_iiif("https://images.test", with_thumbnails=False)

    assert rendered["total"] == 2
    assert rendered["items"][0]["type"] == "Manifest"
    assert rendered["items"][0]["thumbnail"] == []
    assert rendered["items"][1]["type"] == "Collection"
