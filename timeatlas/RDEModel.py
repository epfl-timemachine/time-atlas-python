from dataclasses import dataclass, field
from shapely.geometry import Point, LineString, Polygon, MultiLineString, MultiPolygon
import shapely
import json
from typing import Optional, Self
from datetime import datetime
import pandas as pd
from .TAEnums import *

# Type aliases for improved code readability and type hints
type GeometryType = Point | LineString | Polygon | MultiLineString | MultiPolygon
"""Union type for all supported Shapely geometry types in the Time Atlas data model."""

type UUID = str
"""String representation of a Universal Unique Identifier (UUID)."""

type ObsReference = Observation | UUID
"""Reference to an Observation entity, either as an object or UUID string."""

type HRReference = HistoricalRecord | UUID
"""Reference to a HistoricalRecord entity, either as an object or UUID string."""

type DatasetReference = Dataset | UUID
"""Reference to a Dataset entity, either as an object or UUID string."""

type POIReference = PointOfInterest | UUID
"""Reference to a PointOfInterest entity, either as an object or UUID string."""

type GeometryReference = Geometry | UUID
"""Reference to a Geometry entity, either as an object or UUID string."""

type AreaReference = Area | UUID
"""Reference to an Area entity, either as an object or UUID string."""

type LayerReference = Layer | UUID
"""Reference to a Layer entity, either as an object or UUID string."""

type MapReference = Map | UUID
"""Reference to a Map entity, either as an object or UUID string."""

@dataclass
class UUIDEntity:
    """Base class for entities that have a unique identifier.
    
    All Research Data Entities (RDE) in the Time Atlas data model have a unique UUID
    generated from a UUIDv5 algorithm with a custom dataset-based namespace and a
    deterministic identifier from the data.
    
    Attributes:
        id: Universal unique identifier of the resource
    """
    id: UUID

    def get_ref(self) -> str:
        """Return the UUID reference of this entity.
        
        Returns:
            The UUID string of this entity
        """
        return self.id

    @classmethod
    def parse_uuid(cls, data_id: str) -> None:
        """Parse a UUID from various formats.
        
        In the API, unique IDs are often represented as URLs, but in the data model
        we keep only the UUID part. This method extracts the UUID from URL format.
        
        Args:
            data_id: The ID to parse, either as a UUID string or URL containing UUID
            
        Returns:
            The parsed UUID string
        """
        # in the API, the unique id is often represented as a URL, but in the data model we want to keep only the UUID part, so we parse it here.
        if data_id.startswith('http'):
            return data_id.split('/')[-1]
        return data_id

@dataclass
class RDE:
    """Base class for all Research Data Entities (RDE) in the Time Atlas data model.
    
    Provides common serialization and type handling methods for all RDE types.
    All RDE instances are related using numerical identifiers (UUIDs), which are
    transformed into URLs when ingested in the backend.
    """
    def to_dict(self, exclude_fields = {}) -> dict:
        """Convert the RDE instance to a dictionary representation.
        
        Handles proper serialization of nested RDE objects, enums, and special types
        like MultiLingualValue and RDETimeRange. Automatically adds the rde_type field
        for main RDE entities.
        
        Args:
            exclude_fields: Set of field names to exclude from the output dictionary
            
        Returns:
            Dictionary representation of the RDE instance
        """
        result = {}
        for field_name, field_value in self.__dict__.items():
            if field_name in exclude_fields:
                continue
            match field_value:
                case UUIDEntity():
                    result[field_name] = field_value.get_ref()
                case RDE():
                    # works for dataset configuration as well, as it inherits from RDE, but does not have rde_type field, so it will not be added in the final dict
                    result[field_name] = field_value.to_dict()
                case RDETimeRange():
                    result['start_time'] = field_value.start_time
                    result['end_time'] = field_value.end_time
                case HeightInfo():
                    result['terrain_height'] = field_value.terrain
                    result['building_height'] = field_value.building
                case list():
                    result[field_name] = [item.get_ref() if isinstance(item, RDE) else item for item in field_value]
                case Enum():
                    result[field_name] = field_value.value
                case MultiLingualValue():
                    result[field_name] = field_value.values
                case _:
                    result[field_name] = field_value

        # dataset configuration and other special cases have no rde_type field, only doing it for main RDE types
        rde_name = self.__class__.__name__.lower()
        if rde_name in CLASS_NAME_TO_RDE:
            result['rde_type'] = CLASS_NAME_TO_RDE[rde_name].value
        return result
    
    def get_type(self) -> Optional[RDEType]:
        """Get the RDE type enum value for this entity.
        
        Returns:
            The RDEType enum value or None if not a main RDE type
        """
        rde_name = self.__class__.__name__.lower()
        return CLASS_NAME_TO_RDE.get(rde_name).value
    
    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct an RDE instance from a JSON object.
        
        This method should be implemented in subclasses to handle specific
        deserialization logic for each RDE type.
        
        Args:
            json_obj: Dictionary containing the RDE data
            
        Returns:
            An instance of the RDE subclass
            
        Raises:
            NotImplementedError: If not implemented in subclass
        """
        raise NotImplementedError('This method should be implemented in subclasses')

@dataclass
class RDETimeRange:
    """Represents a temporal range for RDE entities.
    
    Datetime values formatted as ISO 8601 strings representing the range of time
    existence for an RDE, denoting the starting and ending points. Used by
    Historical Records, Datasets, Maps, and Layers.
    
    Attributes:
        start_time: ISO 8601 formatted datetime string for the start of existence
        end_time: ISO 8601 formatted datetime string for the end of existence
        
    Raises:
        ValueError: If datetime format is invalid
        AssertionError: If start_time is greater than end_time
    """
    start_time: str
    end_time: str

    def __post_init__(self):
        # Validate time format
        datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
        datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
        assert self.start_time <= self.end_time, "start_time must be less than or equal to end_time"

@dataclass
class MultiLingualValue:
    """Container for multilingual text values following IIIF format.
    
    Stores text that can be expressed in multiple languages, similar to the
    IIIF format for multilingual descriptions. Each language can have multiple
    values.
    
    Attributes:
        values: Dictionary mapping language codes (2-3 letters) to lists of text values
                Example: {"en": ["English text"], "fr": ["Texte français"]}
    """
    values: dict[str, list[str]]

@dataclass
class MetadataFieldConfig(RDE):
    """Configuration for a metadata field in a Historical Record.
    
    Describes how the frontend and/or backend should manipulate values recorded
    in the HR's metadata property. Each field configuration specifies display
    properties, data type, indexing behavior, and semantic tags.
    
    Attributes:
        id: The metadata field name as it appears in the HR metadata dictionary
        type: The data type of the metadata field (STRING, INTEGER, FLOAT, LIST, URL)
        display_label: Multilingual label to display next to the value in the frontend
        nullable: Whether the field may hold empty values
        indexable: Whether the field is indexed in the search engine for full-text search
        short_display: Whether this field should be displayed by default in card view
        hidden: Whether the field should not be displayed to normal users
        tag: Broad category for this field (PEOPLE, PLACE, LAND_USE) for facet search
        paradata: How the data was acquired/produced for this specific field
    """
    id: str
    type: Optional[MetadataType] = None
    display_label: MultiLingualValue = field(default_factory=MultiLingualValue)
    nullable: bool = field(default=True)
    indexable: bool = field(default=False)
    short_display: bool = field(default=False)
    hidden: bool = field(default=False)
    tag: Optional[MetadataTag] = None
    paradata: Optional[ParadataValues] = None

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a MetadataFieldConfig from a JSON object.
        
        Args:
            json_obj: Dictionary containing metadata field configuration data
            
        Returns:
            MetadataFieldConfig instance
        """
        return cls(
            id=json_obj['id'],
            type=METADATA_TYPE_TO_ENUM.get(json_obj['type'], MetadataType.STRING),
            display_label=MultiLingualValue(values=json_obj.get('display_label', {})),
            nullable=json_obj.get('nullable', True),
            indexable=json_obj.get('indexable', False),
            short_display=json_obj.get('short_display', False),
            hidden=json_obj.get('hidden', False),
            tag=METADATA_TAG_TO_ENUM.get(json_obj['tag'], None),
            paradata=PARADATA_VALUE_TO_ENUM.get(json_obj['paradata'], None)
        )

@dataclass
class FreeFormMetadata(RDE):
    """Free-form metadata field for Datasets and Maps.
    
    Holds arbitrary contextual information that relates to a Dataset or Map.
    Both the label and value are specified as multilingual entities since
    they are arbitrary and need localization support.
    
    Attributes:
        type: The metadata type (STRING, INTEGER, FLOAT, LIST, URL)
        label: Multilingual label for the metadata field
        value: Multilingual value for the metadata field
    """
    type: MetadataType
    label: MultiLingualValue
    value: MultiLingualValue

    def to_dict(self):
        """Convert to dictionary representation.
        
        Returns:
            Dictionary with type as string value and multilingual label/value
        """
        return {
            'type': self.type.value,
            'label': self.label.values,
            'value': self.value.values
        }
    
@dataclass
class DatasetConfiguration(RDE):
    """Operational configuration for a Dataset.
    
    Describes how the Historical Records in a dataset should be handled and
    served through the information system. Includes metadata field configurations
    and display settings for the frontend.
    
    Attributes:
        metadata_field_config: List of configurations for each metadata field in HRs
        main_label: Formatting string indicating which metadata to use for main label
        sub_label: Formatting string for potential sub-label display
        display_thumbnail: Whether HRs have thumbnails that should be displayed
        external_source: Whether source button should forward to external URL
    """
    metadata_field_config: list[MetadataFieldConfig] = field(default_factory=list)
    main_label: str = ''
    sub_label: str = ''
    display_thumbnail: bool = False
    external_source: bool = False

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a DatasetConfiguration from a JSON object.
        
        Args:
            json_obj: Dictionary containing dataset configuration data
            
        Returns:
            DatasetConfiguration instance
        """
        return cls(
            metadata_field_config=[MetadataFieldConfig.constructor_from_json_obj(v) for v in json_obj.get('metadata_field_config', [])],
            main_label=json_obj.get('dataset_config', {}).get('main_label', ''),
            sub_label=json_obj.get('dataset_config', {}).get('sub_label', ''),
            display_thumbnail=json_obj.get('dataset_config', {}).get('display_thumbnail', False),
            external_source=json_obj.get('dataset_config', {}).get('external_source', False)
        )
    
    def to_dict(self, exclude_fields={}):
        """Convert to dictionary representation.
        
        Args:
            exclude_fields: Set of field names to exclude
            
        Returns:
            Dictionary representation with serialized metadata field configs
        """
        self.metadata_field_config = [v.to_dict() for v in self.metadata_field_config] if self.metadata_field_config else []
        return super().to_dict(exclude_fields=exclude_fields)

@dataclass
class Dataset(RDE, UUIDEntity):
    """A homogeneous collection of information ingested in the Time Machine system.
    
    Represents the link between research data and its numerical expression and
    exploitation. Allows users to access meta/paradata on the dataset level.
    The entity is tied to operational configuration describing how the entities
    forming the dataset should be handled and served.
    
    Attributes:
        id: Universal unique identifier of the dataset
        slug: Ad-hoc label identifying the dataset (human-readable)
        name: Multilingual short title displayed as header in the frontend
        time_range: Temporal range of the dataset's existence
        creation_time: Timestamp indicating when this version was created
        version: Version label formatted as "X.Y.Z" (major.minor.patch)
        sources: List of IIIF manifest UUIDs used to produce the dataset
        has_areas: References to areas the dataset is related to
        configuration: Metadata configuration for HRs from this dataset
        metadata: List of free-form metadata fields for contextual information
        hrs: List of Historical Records in this dataset (processing only)
        obs: List of Observations in this dataset (processing only)
    """
    slug: str
    name: MultiLingualValue
    time_range: RDETimeRange
    creation_time: Optional[str] = None
    version: Optional[str] = None
    sources: list[str] = field(default_factory=list)
    has_areas: Optional[list[AreaReference]] = field(default_factory=list)
    configuration: DatasetConfiguration = field(default_factory=DatasetConfiguration)
    metadata: list[FreeFormMetadata] = field(default_factory=list)

    # fields that do not exist in the RDE data model, only there to make python processing easier: 
    hrs: list['HistoricalRecord'] = field(default_factory=list)
    obs: list['Observation'] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a Dataset from a JSON object.
        
        Args:
            json_obj: Dictionary containing dataset data
            
        Returns:
            Dataset instance
        """
        config_data = json_obj.get('configuration')
        configuration = DatasetConfiguration.constructor_from_json_obj(config_data) if config_data else None
        return cls(
            id=UUIDEntity.parse_uuid(json_obj['id']),
            slug=json_obj['slug'],
            name=MultiLingualValue(values=json_obj['name']),
            metadata = [FreeFormMetadata(type=METADATA_TYPE_TO_ENUM.get(m['type'], MetadataType.STRING),
                                         label=MultiLingualValue(values=m.get('label', {})),
                                         value=MultiLingualValue(values=m.get('value', {}))) for m in json_obj.get('metadata', [])],
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            configuration=configuration,
            creation_time=json_obj.get('creation_time', None),
            version=json_obj.get('version', None),
            sources=json_obj.get('sources', []),
            has_areas=json_obj.get('has_areas', [])
        )
    
    # override to exclude specific fields 
    def to_dict(self, exclude_fields = {'hrs', 'obs'}) -> dict:
        """Convert to dictionary representation.
        
        Args:
            exclude_fields: Fields to exclude (defaults to processing-only fields)
            
        Returns:
            Dictionary representation with serialized nested objects
        """
        self.configuration = self.configuration.to_dict() if self.configuration else None
        self.metadata = [v.to_dict() for v in self.metadata] if self.metadata else []
        return super().to_dict(exclude_fields=exclude_fields)

    def instantiate_all_rde_members(self, rde_list: list[RDE]) -> None:
        """Populate the hrs and obs lists from a list of RDE entities.
        
        Helper method for processing that adds all HRs and Observations belonging
        to this dataset to the internal lists.
        
        Args:
            rde_list: List of RDE entities to filter and add
        """
        for rde in rde_list:
            if hasattr(rde, "dataset") and RDEType.dataset == self.id:
                match rde:
                    case HistoricalRecord(): self.hrs.append(rde)
                    case Observation(): self.obs.append(rde)

@dataclass
class HistoricalRecord(RDE, UUIDEntity):
    """A single "atom" of knowledge from a historical document.
    
    An Historical Record represents a record of information about a place, location,
    or set of people found from a historical document. It is the source from which
    any information accessible through the Time Machine projects comes from.
    Examples: a census entry, a parcel listing row, a sentence from a research book,
    a photograph depicting an urban space.
    
    The granularity should be as precise as possible, with the source URL ideally
    being a IIIF annotation of the information from a document's scan.
    
    Attributes:
        id: Universal unique identifier of the historical record
        dataset: Reference to the dataset this HR belongs to
        time_range: Temporal range of the record's existence
        paradata: How the data was acquired (manual, semi-automatic, automatic)
        has_observations: List of observations documented in this historical source
        metadata: Dictionary of arbitrary key-value pairs storing all metadata
        rights_attribution: Optional rights and attribution information
    """
    dataset: DatasetReference
    time_range: RDETimeRange
    paradata: ParadataValues
    has_observations: list[ObsReference]
    metadata: dict = field(default_factory=dict)
    rights_attribution: Optional[str] = None

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a HistoricalRecord from a JSON object.
        
        Args:
            json_obj: Dictionary containing historical record data
            
        Returns:
            HistoricalRecord instance
        """
        return cls(
            id=UUIDEntity.parse_uuid(json_obj['id']),
            dataset=UUIDEntity.parse_uuid(json_obj['dataset']['id']),
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            paradata=json_obj.get('paradata', ''),
            type=json_obj.get('type', ''),
            has_observations=json_obj.get('has_observations', []),
            metadata=json_obj.get('metadata', {}),
            rights_attribution=json_obj.get('rights_attribution')
        )
    
    def actualize_observations_references(self, entity_list: dict[UUID, RDE]) -> None:
        """Replace observation UUID references with actual Observation objects.
        
        Args:
            entity_list: Dictionary mapping UUIDs to RDE instances
        """
        self.has_observations = [entity_list[obs_ref] if isinstance(obs_ref, str) and obs_ref in entity_list else obs_ref for obs_ref in self.has_observations]

    def to_dict(self, flatten_metadata:bool = False) -> dict:
        """Convert to dictionary representation.
        
        Args:
            flatten_metadata: If True, flatten metadata dict into top-level fields
            
        Returns:
            Dictionary representation with optional flattened metadata
        """
        result = super().to_dict()
        # HR specific serialization for documents
        result['has_observations'] = [obs.get_ref() if isinstance(obs, RDE) else obs for obs in self.has_observations]
        if flatten_metadata:
            for k,v in self.metadata.items():
                result[k] = v
            result.pop('metadata', None)
        return result

    @classmethod
    def constructor_from_dataframe_row(cls, row:pd.Series) -> Self:
        """Construct a HistoricalRecord from a pandas DataFrame row.
        
        Automatically extracts metadata fields from columns not used by core attributes.
        
        Args:
            row: pandas Series representing a row from a DataFrame
            
        Returns:
            HistoricalRecord instance
        """
        metadata_keys = set(row.index).difference({'uuid', 'dataset', 'start_time', 'end_time', 'paradata', 'type', 'has_observations', 'rights_attribution'})
        metadata = {k: row[k] for k in metadata_keys}
        return cls(
            id=UUIDEntity.parse_uuid(row['id']),
            dataset=UUIDEntity.parse_uuid(row['dataset']),
            time_range=RDETimeRange(row['start_time'], row['end_time']),
            paradata=row.get('paradata', ''),
            type=row.get('type', ''),
            has_observations=row.get('has_observations', []),
            metadata=metadata,
            rights_attribution=row.get('rights_attribution')
        )

@dataclass
class HeightInfo:
    """Elevation information for Points of Interest.
    
    Stores elevation data separated between terrain and building height,
    both expressed in meters. This information is typically referenced from
    Maptiler's Database and is used by the interface to correctly place
    POIs in 3D vision mode.
    
    Attributes:
        terrain: Height of the terrain in meters
        building: Height of the building in meters
    """
    terrain: Optional[float] = None
    building: Optional[float] = None

@dataclass
class PointOfInterest(RDE, UUIDEntity):
    """A point that has been observed by one or many observations.
    
    Points of Interest are what have been observed and relate to coordinate handles
    of observations to place on a map. They can be pointed to by multiple Observations
    from different datasets, acting as an aggregate by virtue of having observations
    located on the same exact coordinate space.
    
    Attributes:
        id: Universal unique identifier of the POI
        geometry: GPS coordinates of the POI as a Shapely Point
        height: Elevation information (terrain and building height) in meters
    """
    geometry: Point
    height: HeightInfo

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a PointOfInterest from a JSON object.
        
        Handles both standard JSON and GeoJSON Feature formats.
        
        Args:
            json_obj: Dictionary containing POI data
            
        Returns:
            PointOfInterest instance
        """
        geom = json_obj.get('geometry')
        json_obj = json_obj.get('properties', json_obj)  # in case the JSON object is a GeoJSON Feature object
        return cls(
            id=UUIDEntity.parse_uuid(json_obj['id']),
            geometry=(shapely.from_geojson(json.dumps(geom)) if geom else None),
            height=HeightInfo(
                terrain=json_obj.get('terrain_height'),
                building=json_obj.get('building_height')
            )
        )

@dataclass
class Observation(RDE, UUIDEntity):
    """The space-time representation of information recorded in a historical source.
    
    An Observation is tied to a single point of physical space represented by a
    single latitude and longitude. It can be a physical location (e.g., cadastral
    parcel) or an event (e.g., apprenticeship). It serves as a pivot entity linking
    Historical Records, Points of Interest, and Geometries.
    
    A single HR can hold multiple Observations (e.g., a postcard showing multiple
    identified landmarks, where each landmark gets a dedicated Observation).
    
    Attributes:
        id: Universal unique identifier of the observation
        historical_record: Reference to the HR that attests to this observation's existence
        geometry: GPS coordinates of the observation as a Shapely Point
        has_geometries: List of geometry entities tied to this observation
        part_of_point_of_interest: Optional reference to the associated POI
    """
    historical_record: HRReference
    geometry: Point
    has_geometries: list[GeometryReference] = field(default_factory=list)
    part_of_point_of_interest: Optional[POIReference] = None

    def actualize_references(self, entity_list: dict[UUID, RDE]) -> None:
        """Replace UUID references with actual RDE objects.
        
        Args:
            entity_list: Dictionary mapping UUIDs to RDE instances
        """
        self.has_geometries = [entity_list[geom_ref] if isinstance(geom_ref, str) and geom_ref in entity_list else geom_ref for geom_ref in self.has_geometries]
        self.part_of_point_of_interest = entity_list[self.part_of_point_of_interest] if isinstance(self.part_of_point_of_interest, str) and self.part_of_point_of_interest in entity_list else self.part_of_point_of_interest
        self.historical_record = entity_list[self.historical_record] if isinstance(self.historical_record, str) and self.historical_record in entity_list else self.historical_record

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct an Observation from a JSON object.
        
        Handles both standard JSON and GeoJSON Feature formats.
        
        Args:
            json_obj: Dictionary containing observation data
            
        Returns:
            Observation instance
        """
        geom = json_obj.get('geometry')
        json_obj = json_obj.get('properties', json_obj)  # in case the JSON object is a GeoJSON Feature object
        return cls(
            id=UUIDEntity.parse_uuid(json_obj['id']),
            historical_record=json_obj.get('documented_in')[0] if isinstance(json_obj.get('documented_in'), list) and len(json_obj.get('documented_in')) > 0 else None,
            geometry=shapely.from_geojson(json.dumps(geom)),
            has_geometries=json_obj.get('has_geometries', []),
            # height=HeightInfo(
            #     terrain=json_obj.get('height', {}).get('terrain'),
            #     building=json_obj.get('height', {}).get('building')
            # ),
            part_of_point_of_interest=json_obj.get('part_of_point_of_interest', None)
        )
    
@dataclass
class GeographicalExtent:
    """Bounding box representing the geographical extent of a map or layer.
    
    Stores the boundary coordinates in [min_x, min_y, max_x, max_y] format,
    representing the spatial limits of a geographical entity.
    
    Attributes:
        coordinates: List of four float values [min_x, min_y, max_x, max_y]
        
    Raises:
        AssertionError: If coordinates don't meet format requirements
    """
    coordinates: list[float]

    def __post_init__(self):
        assert len(self.coordinates) == 4, "Extent must have four coordinates: [min_x, min_y, max_x, max_y]"
        assert self.coordinates[0] < self.coordinates[2], "min_x must be less than max_x"
        assert self.coordinates[1] < self.coordinates[3], "min_y must be less than max_y"
        # note that the two asserts above would faile on map that are exactly on limits of the negative 
        # latitude (-0.0) or longitude (-0.0), it is unlikey we ingest map from such zones (and most GIS 
        # software specially avoid it: https://en.wikipedia.org/wiki/180th_meridian)

@dataclass
class Map(RDE, UUIDEntity):
    """A group of geographical layers stemming from a single historical map.
    
    Represents a historical map from which users can freely select layers to display
    in the interface. Each map contains one or more layers (raster or vector) that
    can be toggled on/off.
    
    Attributes:
        id: Universal unique identifier of the map
        name: Multilingual short title displayed as header in the frontend
        slug: Short string identifying the map (human-readable)
        time_range: Temporal range of the map's existence
        layers: List of layer entities derived from this map
        metadata: List of free-form metadata fields for contextual information
        thumbnail: IIIF protocol URL linking to an image thumbnail
        version: Version label formatted as "X.Y.Z" (major.minor.patch)
        areas: References to areas the map is related to (must have at least one)
    """
    name: MultiLingualValue
    slug: str
    time_range: RDETimeRange
    layers: list[LayerReference] = field(default_factory=list)
    metadata: list[FreeFormMetadata] = field(default_factory=list)
    thumbnail: Optional[str] = None
    version: Optional[str] = None
    areas: list[AreaReference] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a Map from a JSON object.
        
        Args:
            json_obj: Dictionary containing map data
            
        Returns:
            Map instance
        """
        return cls(
            id=UUIDEntity.parse_uuid(json_obj['id']),
            name=MultiLingualValue(values=json_obj['name']),
            slug=json_obj['slug'],
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            layers=json_obj.get('layers', []),
            metadata=[FreeFormMetadata(type=METADATA_TYPE_TO_ENUM.get(m['type'], MetadataType.STRING),
                                       label=MultiLingualValue(values=m.get('label', {})),
                                       value=MultiLingualValue(values=m.get('value', {}))) for m in json_obj.get('metadata', [])],
            thumbnail=json_obj.get('thumbnail'),
            extent=GeographicalExtent(json_obj.get('extent', [])),
            version=json_obj.get('version'),
            areas=json_obj.get('areas', [])
        )
    
    def to_dict(self, exclude_fields = {}) -> dict:
        """Convert to dictionary representation.
        
        Args:
            exclude_fields: Set of field names to exclude
            
        Returns:
            Dictionary representation with serialized nested objects
        """
        self.metadata = [v.to_dict() for v in self.metadata] if self.metadata else []
        self.layers = [layer.get_ref() if isinstance(layer, Layer) else layer['id'] if isinstance(layer, dict) and 'id' in layer else layer for layer in self.layers]
        return super().to_dict(exclude_fields=exclude_fields)
    
@dataclass
class LayerConfigurationService:
    """Service configuration for accessing a layer's tiles.
    
    Describes the URL and service type for accessing layer tiles from a geoserver.
    
    Attributes:
        url: URL on the geoserver that serves the tiles for the layer
        type: Short string of the tile type (MVT, MVTS, XYZ, etc.)
    """
    url: str
    type: str

@dataclass 
class LayerConfiguration(RDE, UUIDEntity):
    """Configuration describing how a layer is served and accessed.
    
    Defines the technical details for how the frontend can access and display
    a layer, including service endpoints, zoom levels, and spatial extent.
    
    Attributes:
        id: Universal unique identifier of the layer configuration
        service: Service configuration (URL and type) for accessing tiles
        min_zoom_level: Minimum zoom level available for display
        max_zoom_level: Maximum zoom level available for display
        extent: Optional bounding box boundary of the layer
    """
    service: LayerConfigurationService
    min_zoom_level: int
    max_zoom_level: int
    extent: Optional[GeographicalExtent] = None

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a LayerConfiguration from a JSON object.
        
        Args:
            json_obj: Dictionary containing layer configuration data
            
        Returns:
            LayerConfiguration instance
        """
        service_data = json_obj.get('service', {})
        service = LayerConfigurationService(
            url=service_data.get('url', ''),
            type=service_data.get('type', '')
        )
        return cls(
            id=UUIDEntity.parse_uuid(json_obj['id']),
            service=service,
            min_zoom_level=json_obj.get('min_zoom_level', 0),
            max_zoom_level=json_obj.get('max_zoom_level', 22),
            extent=GeographicalExtent(json_obj.get('extent', [])) if 'extent' in json_obj else None
        )
    
    def to_dict(self, exclude_fields={}):
        """Convert to dictionary representation.
        
        Args:
            exclude_fields: Set of field names to exclude
            
        Returns:
            Dictionary representation with serialized service and extent
        """
        self.service = {
            'url': self.service.url,
            'type': self.service.type
        }
        self.extent = self.extent.coordinates if self.extent else None
        return super().to_dict(exclude_fields)

@dataclass 
class Layer(RDE, UUIDEntity):
    """A synthetic derivation from a map (raster or vector).
    
    Represents an abstraction of objects that users can manipulate to display as a
    2D planar field in the interface. Can be either a vectorization of specific
    content from a map or the actual digital facsimile of the map.
    
    Attributes:
        id: Universal unique identifier of the layer
        slug: Short string identifying the layer
        name: Multilingual short title displayed in the frontend
        description: Brief multilingual description displayed in overlay choices
        time_range: Temporal range of the layer's existence
        map: Reference to the map this layer is part of
        type: Layer type (RASTER: image tiles, VECTOR: geometry entities)
        layer_configurations: List of configurations for accessing this layer
    """
    slug: str
    name: MultiLingualValue
    description: MultiLingualValue
    time_range: RDETimeRange
    map: MapReference
    type: LayerType
    layer_configurations: list[LayerConfiguration] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a Layer from a JSON object.
        
        Args:
            json_obj: Dictionary containing layer data
            
        Returns:
            Layer instance
        """
        return cls(
            id=UUIDEntity.parse_uuid(json_obj['id']),
            slug=json_obj['slug'],
            name=MultiLingualValue(values=json_obj['name']),
            description=MultiLingualValue(values=json_obj.get('description', {})),
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            map=UUIDEntity.parse_uuid(json_obj['map']['id']) if 'map' in json_obj and isinstance(json_obj['map'], dict) else None,
            type=LAYER_TYPE_TO_ENUM.get(json_obj.get('type', '').upper(), LayerType.RASTER),
            layer_configurations=[LayerConfiguration.constructor_from_json_obj(lc) for lc in json_obj.get('layer_configurations', [])]
        )
    
    def to_dict(self, exclude_fields={}):
        """Convert to dictionary representation.
        
        Args:
            exclude_fields: Set of field names to exclude
            
        Returns:
            Dictionary representation with serialized layer configurations
        """
        self.layer_configurations = [lc.to_dict() for lc in self.layer_configurations] if self.layer_configurations else []
        return super().to_dict()

@dataclass
class Geometry(RDE, UUIDEntity):
    """Mathematical representation of a physical location as GPS coordinates.
    
    Represents geographical areas tied to an Observation and Historical Record.
    Can represent parcels, buildings, streets, courtyards, parishes, or any arbitrary
    zone. Can also exist without being referenced by a record, existing only as part
    of a vector Layer.
    
    Attributes:
        id: Universal unique identifier of the geometry
        geometry: Shapely geometry object (Point, LineString, Polygon, Multi*)
        part_of_layer: Optional reference to the layer this geometry belongs to
        
    Raises:
        ValueError: If the geometry is not valid according to Shapely validation
    """
    geometry: GeometryType
    part_of_layer: Optional[LayerReference] = None

    def __post_init__(self):
        if isinstance(self.geometry, dict):
            self.geometry = shapely.from_geojson(json.dumps(self.geometry))
        if not self.geometry.is_valid:
            raise ValueError(f'Invalid geometry, because  {shapely.validation.explain_validity(self.geometry)}')

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct a Geometry from a JSON object.
        
        Handles GeoJSON Feature format where properties and geometry are separate.
        
        Args:
            json_obj: Dictionary containing geometry data (typically GeoJSON Feature)
            
        Returns:
            Geometry instance
        """
        # to note, the JSON object is a GeoJSON Feature object
        props = json_obj.get('properties', {})
        geometry = json_obj.get('geometry', {})
        return cls(
            id=UUIDEntity.parse_uuid(props.get('id', json_obj.get('id'))),
            part_of_layer=UUIDEntity.parse_uuid(props.get('part_of_layer')) if 'part_of_layer' in props else None,
            geometry=shapely.from_geojson(json.dumps(geometry)),
        )
    
    @classmethod
    def constructor_from_raw_geojson_line(cls, geojson_line: str, uuid: str, layer_uuid: str) -> Self:
        """Construct a Geometry from a raw GeoJSON line string.
        
        Used for processing GeoJSON line-delimited files.
        
        Args:
            geojson_line: String containing a single GeoJSON object
            uuid: UUID to assign to this geometry
            layer_uuid: UUID of the layer this geometry belongs to
            
        Returns:
            Geometry instance
        """
        json_obj = json.loads(geojson_line)
        return cls(
            id=UUIDEntity.parse_uuid(uuid),
            has_layer=UUIDEntity.parse_uuid(layer_uuid),
            geometry=shapely.from_geojson(json.dumps(json_obj.get('geometry', {}))),
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary representation.
        
        Returns:
            Dictionary representation with geometry as GeoJSON dict
        """
        result = super().to_dict()
        result['geometry'] = json.loads(shapely.to_geojson(self.geometry))
        return result

@dataclass
class Area(RDE, UUIDEntity):
    """The boundary of a specific geographical entity.
    
    Represents geographical boundaries of continents, countries, cities, or ad-hoc
    administrative zones. Used to index maps and datasets to curated areas in the
    Time Atlas, enabling spatial filtering and organization.
    
    Attributes:
        id: Universal unique identifier of the area
        slug: Short string identifying the area (human-readable)
        name: Multilingual name of the geographical entity
        geometry: Shapely geometry object representing the boundary (typically Polygon)
    """
    slug: str
    name: MultiLingualValue
    geometry: GeometryType

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        """Construct an Area from a JSON object.
        
        Args:
            json_obj: Dictionary containing area data
            
        Returns:
            Area instance
        """
        return cls(
            id=UUIDEntity.parse_uuid(json_obj['id']),
            name=MultiLingualValue(values=json_obj['name']),
            geometry=shapely.from_geojson(json.dumps(json_obj.get('geometry', {})))
        )
