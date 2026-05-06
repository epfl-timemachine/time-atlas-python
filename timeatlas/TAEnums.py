from enum import Enum

class LayerType(Enum):
    """Enumeration for layer types in the Time Atlas data model.
    
    A layer is a synthetic derivation from a map, either from vectorization of specific
    content or from the actual digital facsimile of the map. It represents objects that
    users can manipulate to display as a 2D planar field in the interface.
    
    Attributes:
        RASTER: Layer formed from an image stored through tiles in the geoserver
        VECTOR: Layer formed of Geometry entities that point to it via part_of_layer field
    """
    RASTER = 'raster'
    VECTOR = 'vector'

LAYER_TYPE_TO_ENUM = {
    "RASTER": LayerType.RASTER,
    "VECTOR": LayerType.VECTOR,
}
"""Mapping dictionary from string layer type names to LayerType enum values.

Used for parsing layer type strings from JSON/dict representations into enum values.
"""

class MetadataTag(Enum):
    """Enumeration for broad categorization of metadata fields.
    
    Tags indicate to the information system a broad category for metadata fields,
    which is useful for triggering specific facet searches in the interface.
    
    Attributes:
        PEOPLE: Metadata related to persons or human entities
        PLACE: Metadata related to locations or geographical places
        LAND_USE: Metadata related to land usage or professions/activities
    """
    PEOPLE = "PEOPLE"
    PLACE = "PLACE"
    LAND_USE = "LAND_USE"

METADATA_TAG_TO_ENUM = {
    "PEOPLE": MetadataTag.PEOPLE,
    "PLACE": MetadataTag.PLACE,
    "LAND_USE": MetadataTag.LAND_USE
}
"""Mapping dictionary from string metadata tag names to MetadataTag enum values.

Used for parsing metadata tag strings from JSON/dict representations into enum values.
"""

class MetadataType(Enum):
    """Enumeration for metadata field data types.
    
    Defines the possible data types for metadata fields in Historical Records,
    Datasets, and Maps. These types are used for proper parsing, validation,
    and display of metadata values.
    
    Attributes:
        STRING: String of unicode characters, stores text of arbitrary length
        INTEGER: Whole number, positive or negative
        FLOAT: Decimal numbers
        LIST: A list of values of a set type (composite type, e.g., LIST[FLOAT])
        URL: A URL string
    """
    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    LIST = "LIST"
    URL = "URL"

METADATA_TYPE_TO_ENUM = {
    "STRING": MetadataType.STRING,
    "INTEGER": MetadataType.INTEGER,
    "FLOAT": MetadataType.FLOAT,
    "LIST": MetadataType.LIST,
    "URL": MetadataType.URL
}
"""Mapping dictionary from string metadata type names to MetadataType enum values.

Used for parsing metadata type strings from JSON/dict representations into enum values.
"""

class ParadataValues(Enum):
    """Enumeration for paradata values indicating data acquisition methods.
    
    Paradata informs users how data was acquired from historical record sources.
    This metadata about the data production process is important for assessing
    reliability and understanding the data creation workflow.
    
    Attributes:
        MANUAL: Data acquired through manual transcription or entry (m)
        AUTOMATIC: Data acquired through purely automatic process without human involvement (a)
        SEMIAUTOMATIC: Data acquired through automatic process with manual correction/validation (sa)
        AI: Data acquired through artificial intelligence/machine learning (ai)
    """
    MANUAL = 'm'
    AUTOMATIC = 'a'
    SEMIAUTOMATIC = 'sa'
    AI = 'ai'

PARADATA_VALUE_TO_ENUM = {
    "m": ParadataValues.MANUAL,
    "a": ParadataValues.AUTOMATIC,
    "sa": ParadataValues.SEMIAUTOMATIC,
    "ai": ParadataValues.AI,
    "MANUAL": ParadataValues.MANUAL,
    "AUTOMATIC": ParadataValues.AUTOMATIC,
    "SEMIAUTOMATIC": ParadataValues.SEMIAUTOMATIC,
    "AI": ParadataValues.AI
}
"""Mapping dictionary from string paradata values to ParadataValues enum values.

Supports both short codes (m, a, sa, ai) and full names (MANUAL, AUTOMATIC, etc.)
for parsing paradata strings from JSON/dict representations into enum values.
"""

class RDEType(Enum):
    """Enumeration for Research Data Entity (RDE) types in the Time Atlas data model.
    
    The Time Atlas data model consists of eight main classes of RDE that are manipulated
    through both the frontend and backend of the time machine information system.
    
    Attributes:
        HR: Historical Record - source from which information comes, an "atom" of knowledge
        OBS: Observation - space-time representation of information from a historical source
        POI: Point of Interest - aggregate of observations at a specific coordinate
        GEOM: Geometry - mathematical representation of a physical location as GPS coordinates
        DATASET: Dataset - homogeneous collection of information ingested in the system
        MAP: Map - group of geographical layers from a single historical map
        LAYER: Layer - synthetic derivation from a map (raster or vector)
        LAYER_CONFIGURATION: Configuration describing how a layer is served/accessed
        AREA: Area - boundary of a geographical entity (continent, country, city, zone)
    """
    HR = 'historical_record'
    OBS = 'observation'
    POI = 'point_of_interest'
    GEOM = 'geometry'
    DATASET = 'dataset'
    MAP = 'map'
    LAYER = 'layer'
    LAYER_CONFIGURATION = 'layer_configuration'
    AREA = 'area'

CLASS_NAME_TO_RDE = {
    # the short version are left here for compatibility in certain previous version of the API/Data model, to be removed eventually
    'hr': RDEType.HR,
    'obs': RDEType.OBS,
    'poi': RDEType.POI,
    'historical_record': RDEType.HR, 
    'historicalrecord': RDEType.HR,
    'observation': RDEType.OBS,
    'point_of_interest': RDEType.POI,
    'pointofinterest': RDEType.POI,
    'geometry': RDEType.GEOM,
    'dataset': RDEType.DATASET,
    'map': RDEType.MAP,
    'layer': RDEType.LAYER,
    'layer_configuration': RDEType.LAYER_CONFIGURATION,
    'layerconfiguration': RDEType.LAYER_CONFIGURATION,
    'area': RDEType.AREA
}
"""Mapping dictionary from class name strings to RDEType enum values.

Supports multiple naming conventions for backward compatibility:
- Short codes (hr, obs, poi)
- Snake case (historical_record, point_of_interest)
- Single words (historicalrecord, pointofinterest, layerconfiguration)

Used for parsing RDE type strings from JSON/dict representations into enum values.
"""