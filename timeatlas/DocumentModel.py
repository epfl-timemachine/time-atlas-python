from __future__ import annotations # for forward references in type hints, used in the Collection class for items attribute
from .RDEModel import UUIDEntity, MultiLingualValue, UUIDManager
from dataclasses import dataclass
from typing import Optional, OrderedDict
from enum import Enum
from urllib.parse import quote_plus
from pandas.core.indexes.multi import MultiIndex
import pandas as pd
from PIL import Image

def int_tuple_list_to_svg_string(tpl: list[tuple[int,int]]) -> str:
    """Convert a list of integer coordinate tuples to an SVG path string.
    
    Args:
        tpl: List of (x, y) coordinate tuples defining a closed polygon path.
        
    Returns:
        SVG string with a closed path element.
        
    Example:
        >>> int_tuple_list_to_svg_string([(270, 1900), (1530, 1900), (1530, 1610)])
        "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'><g><path d='M270,1900 L1530,1900 L1530,1610 L270,1900' /></g></svg>"
        
    Note:
        Understanding the SVG path command: https://developer.mozilla.org/en-US/docs/Web/SVG/Tutorial/Paths
    """
    # example: "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'><g><path d='M270.000000,1900.000000 L1530.000000,1900.000000 L1530.000000,1610.000000 L1315.000000,1300.000000 L1200.000000,986.000000 L904.000000,661.000000 L600.000000,986.000000 L500.000000,1300.000000 L270,1630 L270.000000,1900.000000' /></g></svg>"
    svg_preample = "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'><g>"
    path_preample = f"<path d='M{tpl[0][0]},{tpl[0][1]}"
    path_body = ' '.join([f'L{v[0]},{v[1]}' for v in tpl[1:]])
    path_body += f' L{tpl[0][0]},{tpl[0][1]}'
    return svg_preample + path_preample + path_body + "' /></g></svg>"

def multiindex_to_nested_dict(df: pd.DataFrame) -> OrderedDict:
    """Convert a DataFrame with MultiIndex to a nested OrderedDict.
    
    Recursively processes each level of the MultiIndex to create a hierarchical
    dictionary structure, with the final level containing canvas_id values.
    
    Args:
        df: DataFrame with MultiIndex to convert.
        
    Returns:
        Nested OrderedDict representing the MultiIndex hierarchy.
        
    Note:
        Source: https://gist.github.com/dcragusa/1235704accde2152faa37113cafa95c0 (simplified)
    """
    if isinstance(df.index, MultiIndex):
        return OrderedDict((k, multiindex_to_nested_dict(df.loc[k])) for k in df.index.remove_unused_levels().levels[0])
    else:
        d = OrderedDict()
        for idx in df.index:
            d[idx] = df.loc[idx, 'canvas_id']
        return d

def ordered_dict_to_iiif_toc_structure(d: OrderedDict, lan:str, val:str, range_id_pref:str) -> dict:
    '''
    This function returns the IIIF ToC structure from the ordered dict.
    the ordered dict should be in the format "{"lvl1_label": {"lvl2_label": ...  {"lvln_label": [canvas_id1, canvas_id2,...,canvas_idn] }...}}.
    Accepts multiple leveld dict.
    '''
    res = {
        "id": range_id_pref,
        "type": "Range",
        "label": {lan: [val]},
        "items": None
    }
    itms = []
    for i, (k,v) in enumerate(d.items()):
        if isinstance(v, OrderedDict):
            itms.append(ordered_dict_to_iiif_toc_structure(v, lan, k, f'{range_id_pref}/{i+1}'))
        else:
            itms.append({
                "id": f'{range_id_pref}/{i+1}',
                "type": "Range",
                "label": {lan: [k]},
                "items": [{"id": canvas_id, "type": "Canvas"} for canvas_id in v]
            })
    res["items"] = itms
    return res

def url_encoded_iiif_image_url(prefix_url: str, path:str) -> str:
    """Generate a URL-encoded IIIF image URL.
    
    Args:
        prefix_url: The base URL prefix for the IIIF image service.
        path: The image path to be URL-encoded.
        
    Returns:
        Complete IIIF image URL with URL-encoded path.
    """
    return f"{prefix_url}/{quote_plus(path)}"


class FileReference(UUIDEntity):
    """Reference to a file resource with a unique identifier.
    
    Attributes:
        path_name: Path to the referenced file.
    """
    path_name: str

    def get_image_metadata(self) -> dict:
        """Extract image metadata using PIL.
        
        Returns:
            Dictionary with 'width', 'height', and 'format' keys.
            
        Raises:
            IOError: If the file cannot be opened or read.
            ValueError: If the file is not a valid image.
        """
        with Image.open(self.path_name) as img:
            # Get MIME type from PIL format
            format_map = {
                'JPEG': 'image/jpeg',
                'PNG': 'image/png',
                'GIF': 'image/gif',
                'TIFF': 'image/tiff',
                'BMP': 'image/bmp',
                'WEBP': 'image/webp'
            }
            mime_type = format_map.get(img.format, f'image/{img.format.lower()}' if img.format else 'image/unknown')
            
            return {
                'width': img.width,
                'height': img.height,
                'format': mime_type
            }

    def generate_page_from_file_reference(self, uuid_manager: UUIDManager, label: MultiLingualValue, range_idx: int) -> 'Page':
        """Generate a Page object from the file reference.
        
        Extracts image metadata using PIL and creates a Page object.
        
        Args:
            uuid_manager: Manager for generating unique identifiers.
            label: Multi-language label for the page.
            range_idx: Index position within a range or sequence.
        
        Returns:
            Page object with the file reference as its object_ref.
            
        Raises:
            IOError: If the image file cannot be opened.
            ValueError: If the file is not a valid image.
        """
        metadata = self.get_image_metadata()
        
        return Page(
            id=uuid_manager._generate_uuid(f'file_ref_page/{self.id}'),
            label=label,
            format=metadata['format'],
            range_idx=range_idx,
            height=metadata['height'],
            width=metadata['width'],
            object_ref=self
        )

    def get_model_metadata(self) -> dict:
        """Extract 3D model metadata based on file extension.
        
        Returns:
            Dictionary with 'format' key containing the MIME type.
            
        Note:
            3D models don't have standardized metadata extraction like images,
            so format is determined from file extension.
        """
        import os
        extension = os.path.splitext(self.path_name)[1].lower()
        
        format_map = {
            '.gltf': 'model/gltf+json',
            '.glb': 'model/gltf-binary',
            '.obj': 'model/obj',
            '.stl': 'model/stl',
            '.fbx': 'model/fbx',
            '.dae': 'model/vnd.collada+xml',
            '.ply': 'model/ply',
            '.3ds': 'model/3ds',
            '.usdz': 'model/vnd.usdz+zip',
            '.las': 'application/vnd.las',
            '.laz': 'application/vnd.las'
        }
        
        mime_type = format_map.get(extension, f'model/{extension[1:]}' if extension else 'model/unknown')
        
        return mime_type

    def generate_model_from_file_reference(self, uuid_manager: UUIDManager, label: MultiLingualValue) -> 'Model':
        """Generate a Model object from the file reference.
        
        Extracts model format from file extension and creates a Model object.
        
        Args:
            uuid_manager: Manager for generating unique identifiers.
            label: Multi-language label for the model.
        
        Returns:
            Model object with the file reference as its object_ref.
        """
        metadata = self.get_model_metadata()
        
        return Model(
            id=uuid_manager._generate_uuid(f'file_ref_model/{self.id}'),
            label=label,
            format=self.get_model_metadata(),
            object_ref=self
        )
    


class SelectorType(Enum):
    """Enumeration of Web Annotation selector types for targeting regions.
    
    Attributes:
        POINT: Point selector for single coordinate (x, y).
        SVG: SVG path selector for complex polygon regions.
        XYWH: Rectangle selector defined by x, y, width, height.
    """
    POINT = 'PointSelector'
    SVG = 'SvgSelector'
    XYWH = 'SquareSelector'


class Selector():
    """Web Annotation selector for targeting specific regions in a resource.
    
    Supports three selector types: POINT (single coordinate), SVG (polygon path),
    and XYWH (rectangular region).
    
    Attributes:
        type: The selector type (POINT, SVG, or XYWH).
        value: Coordinate data - tuple[int,int] for POINT, list[tuple[int,int]] for SVG,
               tuple[int,int,int,int] for XYWH.
        source: The resource URI being targeted.
        
    Raises:
        ValueError: If value format doesn't match the selector type requirements.
    """
    def __init__(self, tpe:SelectorType, value: (tuple[int,int] | list[tuple[int,int]] | tuple[int,int,int,int]), source:str):
        self.type = tpe
        self.value = value
        self.source = source
        if self.type is SelectorType.POINT and len(self.value) != 2:
            raise ValueError('Point selector should have 2 values')
        if self.type is SelectorType.XYWH and len(self.value) != 4:
            raise ValueError('XYWH selector should have 4 values')
        if self.type is SelectorType.SVG and type(self.value) != list:
            raise ValueError('SVG selector should be a list of number')

    def generate_selector_template(self) -> dict:
        """Generate Web Annotation selector JSON structure.
        
        Returns:
            Dictionary or string representing the selector in Web Annotation format.
            For POINT and SVG types, returns a SpecificResource dict.
            For XYWH, returns a Media Fragment URI string.
            
        Raises:
            ValueError: If selector type is not recognized.
        """
        match self.type:
            case SelectorType.POINT:
                return {
                    "type": "SpecificResource",
                    "source": self.source,
                    "selector": {
                        "type": self.type.value,
                        "x": self.value[0],
                        "y": self.value[1]
                    }
                }
            case SelectorType.SVG:
                return {    
                    "type": "SpecificResource",
                    "source": self.source,
                    "selector": {
                    "type": self.type.value,
                    "value": int_tuple_list_to_svg_string(self.value)
                    }
                }
            case SelectorType.XYWH:
                return f'{self.source}#xywh={self.value[0]},{self.value[1]},{self.value[2]},{self.value[3]}'
            case _:
                raise ValueError('Selector type not recognized:', sel.type)

@dataclass
class Annotation(UUIDEntity):
    """Web Annotation for commenting on or linking resources.
    
    Represents a W3C Web Annotation with optional text content, historical record
    reference, spatial selector, and external resource links.
    
    Attributes:
        lang: Language code for the annotation value (e.g., 'en', 'fr').
        value: HTML text content of the annotation.
        hr_id: Historical record identifier reference.
        selector: Optional Selector for targeting a specific region.
        external_resource: URI of an external linked resource.
        
    Raises:
        ValueError: If language/value pairs are incomplete, or if required fields are missing.
    """
    lang: Optional[str] = None
    value: Optional[str] = None
    hr_id: Optional[object] = None
    selector: Optional[Selector] = None
    external_resource: Optional[str] = None

    def __post_init__(self):
        if self.lang and not self.value:
            raise ValueError('Language provided without value for annotation:', self.id)
        if self.value and not self.lang:
            raise ValueError('Value provided without language for annotation:', self.id)
        if self.selector and not self.value:
            raise ValueError('Selector provided without value for annotation:', self.id)
        if not self.selector and not self.value and not self.lang and not self.hr_id:
            raise ValueError('Annotation should have at least a value, a language, a selector or an hr_id:', self.id)

    def to_iiif(self, uuid_manager: UUIDManager, canvas_id:str, canvas_type: str = "Canvas") -> dict:
        """Convert annotation to IIIF Presentation API format.
        
        Args:
            uuid_manager: Manager for generating unique identifiers.
            canvas_id: The canvas or resource ID being annotated.
            canvas_type: Type of the target resource (default: "Canvas").
            
        Returns:
            Dictionary containing IIIF annotation in Presentation API format.
        """
        annotation_array = []
        target_array = [
            {
                "type": canvas_type,
                "id": canvas_id
            } if not self.selector else self.selector.generate_selector_template()
        ]
        if self.value and self.lang:
            annotation_array.append({
                "type": "TextualBody",
                "language": self.lang,
                "format": "text/html",
                "value": self.value
            })
        if self.hr_id:
            annotation_array.append(
                {
                  "type": "rde:HistoricalRecord",
                  "id": self.hr_id
                }
            )
        if self.external_resource:
            target_array.append(
                {
                  "type": "ExternalResource",
                  "id": self.external_resource
                }
            )
        return {
            "id": uuid_manager._generate_uuid(f'{canvas_id}/annotation/{self.id}/1'),
            "type": "Annotation",
            "motivation": "commenting",
            "body": annotation_array,
            "target": target_array
        }

@dataclass
class Page(UUIDEntity):
    """Represents a page or canvas in an IIIF document.
    
    A page contains an image or other visual resource with dimensions, format,
    and optional annotations.
    
    Attributes:
        label: Multi-language label for the page.
        format: MIME type of the resource (e.g., 'image/jpeg').
        range_idx: Index position within a range or sequence.
        height: Height of the resource in pixels.
        width: Width of the resource in pixels.
        object_ref: Path or reference to the image file.
        annotations: Optional list of annotations on this page.
    """
    label: MultiLingualValue
    format: str
    range_idx: int
    height: int
    width: int
    object_ref: str | FileReference
    annotations: Optional[list[Annotation]] = None

    def to_iiif(self, uuid_manager: UUIDManager, url_prefix: str) -> dict:
        """Convert page to IIIF Presentation API Canvas format.
        
        Args:
            uuid_manager: Manager for generating unique identifiers.
            url_prefix: Base URL prefix for the IIIF image service.
            
        Returns:
            Dictionary containing IIIF Canvas in Presentation API v3 format.
            
        Raises:
            ValueError: If object_ref is a FileReference ().
        """
        # it is here that the annotation is generated, should be in page_obj.
        # todo: make the annotation and page id modular, and not hardcoded to 1 (cf. webannotation model, for multiple annotations per page)
        if isinstance(self.object_ref, FileReference):
            raise ValueError('Cannot generate IIIF manifest for a page with a file object reference, only string path is supported')
        
        url_encoded = url_encoded_iiif_image_url(url_prefix, self.object_ref)
        page_id = getattr(self, 'id', None)
        if isinstance(page_id, tuple) or isinstance(page_id, list):
            # we're in the case were there is an external resource in the id.
            page_id = page_id[0]
        
        annot_page_idx = page_id+f"/{self.range_idx:04d}-image"
        obj = {
            "id": page_id,
            "type": "Canvas",
            "label": self.label.values,
            "height": self.height,
            "width": self.width,
            "items": [
                {
                    "id": uuid_manager._generate_uuid(page_id+'/1'), 
                    "type": "AnnotationPage",
                    "items": [
                        {
                        "id": uuid_manager._generate_uuid(annot_page_idx),
                        "type": "Annotation",
                        "motivation": "painting",
                        "body": {
                            "id": f"{url_encoded}/full/max/0/default.jpg",
                            "type": "Image",
                            "format": self.format,
                            "height": self.height,
                            "width": self.width,
                            "service": [
                            {
                                "id": url_encoded,
                                "type": "ImageService3",
                                "profile": "level2"
                            }
                            ]
                        },
                        "target": page_id
                        }
                    ]
                }
            ]
        }
        if self.annotations:
            obj['annotations'] = {
                "id": uuid_manager._generate_uuid(f'{page_id}/annotation/{self.id}'),
                "type": "AnnotationPage",
                "items": [
                    annotation.to_iiif(uuid_manager, page_id) for annotation in self.annotations
                ]
            }
        return obj
    

@dataclass
class Model(UUIDEntity):
    """Represents a 3D model resource in IIIF.
    
    Attributes:
        label: Multi-language label for the model.
        format: MIME type of the 3D model (e.g., 'model/gltf-binary').
        object_ref: Path or reference to the 3D model file.
    """
    label: MultiLingualValue
    format: str
    object_ref: str | FileReference

    def to_iiif(self, uuid_manager: UUIDManager) -> dict:
        """Convert 3D model to IIIF Presentation API Scene format.
        
        Args:
            uuid_manager: Manager for generating unique identifiers.
            
        Returns:
            Dictionary containing IIIF Scene in Presentation API v4 format.
            
        Raises:
            ValueError: If object_ref is a FileReference (only string paths supported).
        """
        if object_ref := self.object_ref:
            if isinstance(object_ref, FileReference):
                raise ValueError('Cannot generate IIIF manifest for a model with a file object reference, only string path is supported')
        scene_id = self.id
        return {
            "id": scene_id,
            "type": "Scene",
            "label": self.label.values,
            "items": [
                {
                    "id": uuid_manager._generate_uuid(f"{scene_id}/page/p1/1"),
                    "type": "AnnotationPage",
                    "items": [
                        {
                            "id": uuid_manager._generate_uuid(f"{scene_id}/annotation/a1/1"),
                            "type": "Annotation",
                            "motivation": ["painting"],
                            "body": {
                                "id": self.object_ref,
                                "type": "Model",
                                "format": self.format
                            },
                            "target": scene_id
                        }
                    ]
                }
            ]
        }
    
@dataclass
class Document(UUIDEntity):
    """Represents an IIIF Manifest containing pages or 3D models.
    
    A document is the primary unit for presenting a sequence of canvases/scenes
    with optional navigational structures.
    
    Attributes:
        label: Multi-language label for the document.
        items: List of pages (2D images) or models (3D scenes).
        structures: Optional hierarchical structure (table of contents/ranges).
    """
    label: MultiLingualValue
    items: list[Page | Model]
    structures: Optional[dict] = None

    def to_iiif(self, uuid_manager: UUIDManager, label: dict[str, list[str]], url_prefix: str, presentation_version:str = '3') -> dict:
        """Convert document to IIIF Presentation API Manifest format.
        
        Args:
            uuid_manager: Manager for generating unique identifiers.
            label: Multi-language label dictionary.
            url_prefix: Base URL prefix for the IIIF image service.
            presentation_version: IIIF Presentation API version ('3' or '4').
            
        Returns:
            Dictionary containing complete IIIF Manifest.
        """
        first_page = self.items[0]
        man =  {
            "@context": f"http://iiif.io/api/presentation/{presentation_version}/context.json",
            "id": self.id,
            "type": "Manifest",
            "label": label,
            "thumbnail": [{
                "id": f"{url_encoded_iiif_image_url(url_prefix, first_page.object_ref)}/full/300,/0/default.jpg",
                "type": "Image"
            }
        ],
            "items": [p.to_iiif(uuid_manager, url_prefix) if isinstance(p, Page) else p.to_iiif(uuid_manager) for p in self.items]
        }
        if self.structures:
            man['structures'] = [self.structures]
        return man
    
    def to_iiif_manifest_item(self, url_prefix: str, with_thumbnail: bool = True) -> dict:
        """Convert document to a simplified IIIF Manifest reference.
        
        Useful for including in Collection items arrays.
        
        Args:
            url_prefix: Base URL prefix for the IIIF image service.
            with_thumbnail: Whether to include thumbnail information.
            
        Returns:
            Dictionary with basic manifest metadata (id, type, label, optional thumbnail).
        """
        first_page = self.items[0]
        return {
            "id": self.id,
            "type": "Manifest",
            "label": self.label.values,
            "thumbnail": [{
                "id": f"{url_encoded_iiif_image_url(url_prefix, first_page.object_ref)}/full/300,/0/default.jpg",
                "type": "Image"
            }] if with_thumbnail else [],
        }

@dataclass
class Collection(UUIDEntity):
    """Represents an IIIF Collection containing documents or sub-collections.
    
    Collections provide hierarchical organization of IIIF Manifests and other
    collections for browsing and discovery.
    
    Attributes:
        label: Multi-language label for the collection.
        items: List of documents (manifests) or nested collections.
        presentation_version: IIIF Presentation API version for the collection (default: '3').
    """
    label: MultiLingualValue
    items: list[Document | Collection]

    def to_iiif(self, uuid:str, url_prefix: str, with_thumbnails:bool=True, presentation_version:str = '3') -> dict:
        """Convert collection to IIIF Presentation API Collection format.
        
        Args:
            uuid: Unique identifier for the collection.
            url_prefix: Base URL prefix for the IIIF image service.
            with_thumbnails: Whether to include thumbnails for items.
            
        Returns:
            Dictionary containing IIIF Collection in Presentation API v3 format.
        """
        return {
            "@context": f"http://iiif.io/api/presentation/{presentation_version}/context.json",
            "id": uuid,
            "type": "Collection",
            "label": self.label.values,
            "items": [item.to_iiif_manifest_item(url_prefix, with_thumbnails) for item in self.items] ,
            "total": len(self.items),
            "metadata": [],
        }
