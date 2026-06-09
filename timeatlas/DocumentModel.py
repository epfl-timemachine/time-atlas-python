from .RDEModel import UUIDEntity, MultiLingualValue, UUIDManager
from dataclasses import dataclass
from typing import Optional, OrderedDict
from enum import Enum
from urllib.parse import quote_plus
from pandas.core.indexes.multi import MultiIndex
import pandas as pd

def int_tuple_list_to_svg_string(tpl: list[tuple[int,int]]) -> str:
    # example: "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'><g><path d='M270.000000,1900.000000 L1530.000000,1900.000000 L1530.000000,1610.000000 L1315.000000,1300.000000 L1200.000000,986.000000 L904.000000,661.000000 L600.000000,986.000000 L500.000000,1300.000000 L270,1630 L270.000000,1900.000000' /></g></svg>"
    # understanding the svg path command: https://developer.mozilla.org/en-US/docs/Web/SVG/Tutorial/Paths
    svg_preample = "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'><g>"
    path_preample = f"<path d='M{tpl[0][0]},{tpl[0][1]}"
    path_body = ' '.join([f'L{v[0]},{v[1]}' for v in tpl[1:]])
    path_body += f' L{tpl[0][0]},{tpl[0][1]}'
    return svg_preample + path_preample + path_body + "' /></g></svg>"

# source: https://gist.github.com/dcragusa/1235704accde2152faa37113cafa95c0 then simplified for my use
def multiindex_to_nested_dict(df: pd.DataFrame) -> OrderedDict:
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
    return f"{prefix_url}/{quote_plus(path)}"

class SelectorType(Enum):
    POINT = 'PointSelector'
    SVG = 'SvgSelector'
    XYWH = 'SquareSelector'

class FileReference(UUIDEntity):
    path_name: str

class Selector():
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
            "id": uuid_manager.generate_uuid(f'{canvas_id}/annotation/{self.id}/1'),
            "type": "Annotation",
            "motivation": "commenting",
            "body": annotation_array,
            "target": target_array
        }

@dataclass
class Page(UUIDEntity):
    label: MultiLingualValue
    format: str
    range_idx: int
    height: int
    width: int
    object_ref: str | FileReference
    annotations: Optional[list[Annotation]] = None

    def to_iiif(self, uuid_manager: UUIDManager, url_prefix: str) -> dict:
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
            "label": self.label,
            "height": self.height,
            "width": self.width,
            "items": [
                {
                    "id": uuid_manager.generate_uuid(page_id+'/1'), 
                    "type": "AnnotationPage",
                    "items": [
                        {
                        "id": uuid_manager.generate_uuid(annot_page_idx),
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
                "id": uuid_manager.generate_uuid(f'{page_id}/annotation/{self.id}'),
                "type": "AnnotationPage",
                "items": [
                    annotation.to_iiif(uuid_manager, page_id) for annotation in self.annotations
                ]
            }
        return obj
    

@dataclass
class Model(UUIDEntity):
    label: MultiLingualValue
    format: str
    object_ref: str | FileReference

    def to_iiif(self, uuid_manager: UUIDManager,) -> dict: 
        if object_ref := self.object_ref:
            if isinstance(object_ref, FileReference):
                raise ValueError('Cannot generate IIIF manifest for a model with a file object reference, only string path is supported')
        scene_id = self.id
        return {
            "id": scene_id,
            "type": "Scene",
            "label": self.label,
            "items": [
                {
                    "id": uuid_manager.generate_uuid(f"{scene_id}/page/p1/1"),
                    "type": "AnnotationPage",
                    "items": [
                        {
                            "id": uuid_manager.generate_uuid(f"{scene_id}/annotation/a1/1"),
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
    label: MultiLingualValue
    items: list[Page | Model]
    structures: Optional[dict] = None

    def to_iiif(self, uuid_manager: UUIDManager, label: dict[str, list[str]], presentation_version:str = '3') -> dict:
        first_page = self.items[0]
        man =  {
            "@context": f"http://iiif.io/api/presentation/{presentation_version}/context.json",
            "id": self.id,
            "type": "Manifest",
            "label": label,
            "thumbnail": [{
                "id": f"{url_encoded_iiif_image_url(first_page.path)}/full/300,/0/default.jpg",
                "type": "Image"
            }
        ],
            "items": [p.to_iiif(uuid_manager) for p in self.items]
        }
        if self.structures:
            man['structures'] = [self.structures]
        return man
    
    def to_iiif_manifest_item(self, with_thumbnail: bool = True) -> dict:
        first_page = self.items[0]
        return {
            "id": self.id,
            "type": "Manifest",
            "label": self.label,
            "thumbnail": [{
                "id": f"{url_encoded_iiif_image_url(first_page.path)}/full/300,/0/default.jpg",
                "type": "Image"
            }] if with_thumbnail else [],
        }

@dataclass
class Collection(UUIDEntity):
    label: MultiLingualValue
    items: list[Document | 'Collection']

    def to_iiif(self, uuid:str, with_thumbnails:bool=True) -> dict:
        return {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": uuid,
            "type": "Collection",
            "label": self.label,
            "items": [item.to_iiif(uuid, with_thumbnails) for item in self.items] ,
            "total": len(self.items),
            "metadata": [],
        }
