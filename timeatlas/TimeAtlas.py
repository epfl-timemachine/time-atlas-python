import json
import os
import pickle
import shapely
from collections import Counter
from datetime import datetime
from .RDEModel import *
import requests
import pandas as pd

RDE_TYPE_TO_STATIC_CLASS_DEF = {
    RDEType.HR.value: HistoricalRecord,
    'hr': HistoricalRecord,
    RDEType.OBS.value: Observation,
    RDEType.POI.value: PointOfInterest,
    RDEType.GEOM.value: Geometry,
    RDEType.DATASET.value: Dataset,
    RDEType.MAP.value: Map,
    RDEType.LAYER.value: Layer,
    RDEType.AREA.value: Area
}

class TimeAtlas:

    entity_cache = {}
    default_save_cache_filepath = 'rde_entity_cache.pkl'

    def __init__(self, api_url: str):
        self.api_url = api_url
        # requests.get(f'{self.api_url}/status').raise_for_status()
        if api_url.endswith('/v1/'):
            # removing trailing slash as it makes the endpoint construction clearer.
            self.api_url = api_url[:-1]
        if not self.api_url.endswith('/v1'):
            raise ValueError('API URL must end with /v1')

        # test health of the API by querying the health endpoint
        resp = requests.get(f'{self.api_url}/health')
        if resp.status_code != 200:
            raise ConnectionError(f'Could not connect to TimeAtlas API at {self.api_url}. Status code: {resp.status_code}')
        if os.path.exists(self.default_save_cache_filepath):
            with open(self.default_save_cache_filepath, 'rb') as f:
                self.entity_cache = pickle.load(f)
        else:
            self.entity_cache = {}

    def save_entity_cache_to_file(self, filepath: str = None):
        if filepath is None:
            filepath = self.default_save_cache_filepath
        
        with open(filepath, 'wb') as f:
            pickle.dump(self.entity_cache, f)

    def get_single_rde_object(self, endpoint: str, uuid: str) -> RDE:
        if uuid in self.entity_cache:
            return self.entity_cache[uuid]
        resp = requests.get(f'{self.api_url}/{endpoint}/{uuid}')
        resp.raise_for_status()
        data = resp.json()
        rde_type = data.get('rde_type')
        if rde_type is None and 'properties' in data and 'rde_type' in data['properties']:
            # special cases for geometries, as they are GeoJSON Feature objects
            rde_type = data['properties']['rde_type']
        if rde_type not in RDE_TYPE_TO_STATIC_CLASS_DEF:
            raise ValueError(f'Unknown RDE type: {rde_type}')
        res = RDE_TYPE_TO_STATIC_CLASS_DEF[rde_type].constructor_from_json_obj(data)
        self.entity_cache[uuid] = res
        return res


    def get_all_results_from_endpoint(self, endpoint: str, per_page: int = 1000) -> list[dict]:
        # the TimeAtlas API paginates results, so we need to loop until we get all results. 1000 is the maximal amount per page. 
        results = []
        page = 1
        while True:
            resp = requests.get(f'{self.api_url}/{endpoint}', params={'page': page, 'per_page': per_page}, headers={'Accept': 'application/json'})
            resp.raise_for_status()
            data = resp.json()
            results.extend(data['items'])

            if 'next' not in data or data['next'] is None:
                break
            page += 1

        return results
    
    def get_dataset(self, dataset_uuid: str) -> Dataset:
        # resp = requests.get(f'{self.api_url}/datasets/{dataset_uuid}')
        return self.get_single_rde_object('datasets', dataset_uuid)

    def get_dataset_by_slug(self, slug: str) -> Dataset:
        resp = requests.get(f'{self.api_url}/datasets', headers={'Accept': 'application/json'})
        data = resp.json()
        for dataset in data['items']:
            if dataset['slug'] == slug:
                ds = Dataset.constructor_from_json_obj(dataset)
                self.entity_cache[dataset['uuid']] = ds
                return ds
        raise ValueError(f'Dataset with slug {slug} not found')

    def generate_all_hr_from_dataset(self, dataset: Dataset) -> list[HistoricalRecord]:
        hr_jsons = self.get_all_results_from_endpoint('hr/search?query=&dataset_slug=' + dataset.slug, per_page=1000)
        hrs = [HR.constructor_from_json_obj(hr_json) for hr_json in hr_jsons]
        self.entity_cache.update({hr.uuid: hr for hr in hrs})
        return hrs

    # Waring: very slow. Waiting on a better API endpoint to retrieve all obs for a dataset
    def generate_obs_from_list_of_hr(self, hr_list: list[HistoricalRecord]) -> list[Observation]:
        obs_uuids = set()
        for hr in hr_list:
            for obs_ref in hr.documents:
                match obs_ref:
                    case str():
                        obs_uuids.add(obs_ref)
                    case Observation():
                        obs_uuids.add(obs_ref.uuid)
        obs_list = []
        # for obs_uuid in tqdm(obs_uuids, desc='Fetching observations'):
        for obs_uuid in obs_uuids:
            obs_list.append(self.get_single_rde_object('obs', obs_uuid))
        return obs_list
    
    def generate_geoms_from_list_of_obs(self, obs_list: list[Observation    ]) -> list[Geometry]:
        geom_uuids = set()
        for obs in obs_list:
            for geom_ref in obs.has_geometry:
                match geom_ref:
                    case str():
                        geom_uuids.add(geom_ref)
                    case Geometry():
                        geom_uuids.add(geom_ref.uuid)
        geom_list = []
        # for geom_uuid in tqdm(geom_uuids, desc='Fetching geometries'):
        for geom_uuid in geom_uuids:
            geom_list.append(self.get_single_rde_object('geometries', geom_uuid))
        return geom_list


    def generate_pois_from_list_of_obs(self, obs_list: list[Observation]) -> list[PointOfInterest]:
        poi_uuids = set()
        for obs in obs_list:
            poi_ref = obs.has_handle
            match poi_ref:
                case str():
                    poi_uuids.add(poi_ref)
                case PointOfInterest():
                    poi_uuids.add(poi_ref.uuid)
        poi_list = []
        # for poi_uuid in tqdm(poi_uuids, desc='Fetching POIs'):
        for poi_uuid in poi_uuids:
            poi_list.append(self.get_single_rde_object('poi', poi_uuid))
        return poi_list
    
    def materialize_all_rde_from_dataset_obj(self, dataset: Dataset) -> list[RDE]:
        hrs = self.generate_all_hr_from_dataset(dataset)
        obs = self.generate_obs_from_list_of_hr(hrs)
        geoms = self.generate_geoms_from_list_of_obs(obs)
        pois = self.generate_pois_from_list_of_obs(obs)
        for o in obs: o.actualize_references(self.entity_cache)
        for h in hrs: h.actualize_observations_references(self.entity_cache)
        return hrs + obs + geoms + pois
    

    def materialize_all_rde_from_dataset_slug(self, dataset_slug: str) -> list[RDE]:
        ds = self.get_dataset_by_slug(dataset_slug)
        return self.materialize_all_rde_from_dataset_obj(ds)

    @staticmethod
    def hr_list_to_dataframe(hr_list: list[HistoricalRecord]) -> pd.DataFrame:    
        hr_dicts = []
        for hr in hr_list:
            hr_dict = hr.to_dict()
            hr_dict['obj'] = hr
            hr_dicts.append(hr_dict)
        return pd.DataFrame(hr_dicts)


class _ShapelyEncoder(json.JSONEncoder):
    """JSON encoder that transparently serializes Shapely geometry objects to GeoJSON dicts."""

    def default(self, obj):
        if isinstance(obj, shapely.geometry.base.BaseGeometry):
            return json.loads(shapely.to_geojson(obj))
        return super().default(obj)


class RDECollection:
    """A collection of Research Data Entities (RDE) ready for file-based serialization.

    Acts as the interface between in-memory RDE model objects and the serialization
    layer expected by the Time Atlas ingestion pipeline.  Entities are grouped by
    their concrete class and written to individual JSON files, each wrapped in the
    standard RDE envelope format used throughout the project::

        {
            "name": "<filename stem>",
            "type_in_file": ["<rde_type string>"],
            "creation_time": "<ISO-8601 timestamp>",
            "rde_objects": [ ... ]
        }

    Attributes:
        rdes: Flat list of all RDE instances held in this collection.
    """

    _FILE_MAP: dict[type, tuple[str, str]] = {
        HistoricalRecord: ('historical_records', RDEType.HR.value),
        Observation:      ('observations',       RDEType.OBS.value),
        PointOfInterest:  ('points_of_interest', RDEType.POI.value),
        Geometry:         ('geometries',         RDEType.GEOM.value),
        Dataset:          ('dataset',            RDEType.DATASET.value),
        Map:              ('maps',               RDEType.MAP.value),
        Layer:            ('layers',             RDEType.LAYER.value),
        Area:             ('areas',              RDEType.AREA.value),
    }
    """Mapping from RDE concrete class to (output filename stem, rde_type label)."""

    def __init__(self, rdes: list[RDE]):
        """Create an RDECollection.

        Args:
            rdes: List of RDE instances to include in this collection.
        """
        self.rdes = rdes
        self._valid_data: bool = False

    def add(self, rdes: list[RDE] | RDE) -> None:
        """Append one or more RDE instances to the collection.

        Args:
            rdes: A single RDE instance or a list of RDE instances to add.
        """
        if isinstance(rdes, list):
            self.rdes.extend(rdes)
        else:
            self.rdes.append(rdes)

    def save_rde_to_files(self, output_dir: str, overwrite: bool = False, rde_types: list[type] | None = None) -> None:
        """Serialize the collection's RDE entities to individual JSON files grouped by type.

        For each RDE class present in the collection, one ``.json`` file is written
        to *output_dir*.  The file name matches the keys in :attr:`_FILE_MAP`
        (e.g. ``historical_records.json``, ``observations.json``).

        Serialization relies on each entity's own ``to_dict()`` method.  Shapely
        geometry objects that appear in the resulting dicts (e.g. from
        :class:`~timeatlas.RDEModel.Observation` or
        :class:`~timeatlas.RDEModel.PointOfInterest`) are automatically converted
        to GeoJSON-compatible dicts during the JSON encoding step, so no manual
        geometry handling is required before calling this method.

        If a file already exists and *overwrite* is ``False``, the serialized
        ``rde_objects`` list is compared with the file's current content; the
        file is only rewritten when the content has actually changed.  This
        avoids spurious modification timestamps that would trigger unnecessary
        downstream reprocessing.

        Args:
            output_dir: Path to the directory where output files are written.
                        The directory (and any missing parents) is created
                        automatically if it does not yet exist.
            overwrite:  When ``True``, rewrite every output file unconditionally,
                        even if the content is unchanged.  Defaults to ``False``.
            rde_types:  Optional list of RDE classes to serialize (e.g.
                        ``[HistoricalRecord, Observation]``).  When ``None``
                        (the default), all types present in the collection are
                        written.

        Raises:
            OSError: If *output_dir* cannot be created or a file cannot be written.
        """
        os.makedirs(output_dir, exist_ok=True)

        allowed: set[type] = set(rde_types) if rde_types is not None else set(self._FILE_MAP.keys())

        # Group RDEs by concrete class, skipping unknown types and those not in the filter
        groups: dict[type, list[RDE]] = {}
        for rde in self.rdes:
            cls = type(rde)
            if cls in self._FILE_MAP and cls in allowed:
                groups.setdefault(cls, []).append(rde)

        for cls, rde_group in groups.items():
            filename, type_label = self._FILE_MAP[cls]
            filepath = os.path.join(output_dir, f'{filename}.json')

            # Produce fully-decoded dicts (Shapely geometries → GeoJSON) so the
            # result is directly comparable to what was previously saved on disk.
            serialized: list[dict] = json.loads(
                json.dumps([rde.to_dict() for rde in rde_group], cls=_ShapelyEncoder, ensure_ascii=False)
            )

            if not overwrite and os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                if existing.get('rde_objects') == serialized:
                    continue

            envelope = {
                'name': filename,
                'type_in_file': [type_label],
                'creation_time': datetime.now().isoformat(),
                'rde_objects': serialized,
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(envelope, f, indent=1, ensure_ascii=False)

    @classmethod
    def read_rde_from_files(cls, input_dir: str) -> 'RDECollection':
        """Deserialize RDE entities from JSON files produced by :meth:`save_rde_to_files`.

        Scans *input_dir* for ``.json`` files, reads each envelope, and reconstructs
        the appropriate RDE class instances using the ``rde_type`` label stored in
        the ``type_in_file`` envelope field.  The class is resolved once per file
        via :data:`RDE_TYPE_TO_STATIC_CLASS_DEF`, then each object in ``rde_objects``
        is passed to the matching class's ``constructor_from_json_obj`` classmethod.

        Files whose ``type_in_file`` value is absent or unrecognised are silently
        skipped, so partially-populated directories are handled gracefully.

        Args:
            input_dir: Path to the directory containing the serialized ``.json`` files.

        Returns:
            A new :class:`RDECollection` populated with all successfully deserialized
            RDE instances.

        Raises:
            FileNotFoundError: If *input_dir* does not exist.
            json.JSONDecodeError: If a file contains malformed JSON.
        """
        rdes: list[RDE] = []
        for entry in os.scandir(input_dir):
            if not (entry.is_file() and entry.name.endswith('.json')):
                continue
            with open(entry.path, 'r', encoding='utf-8') as f:
                envelope = json.load(f)
            for obj in envelope.get('rde_objects', []):
                rde_type = obj.get('rde_type')
                if rde_type is None and 'properties' in obj:
                    # GeoJSON Feature objects (e.g. Geometry) nest rde_type under properties
                    rde_type = obj['properties'].get('rde_type')
                rde_class = RDE_TYPE_TO_STATIC_CLASS_DEF.get(rde_type)
                if rde_class is None:
                    continue
                rdes.append(rde_class.constructor_from_json_obj(obj))
        return cls(rdes)

    def validate_data(self) -> bool:
        """Validate the internal consistency of all RDE entities in the collection.

        Performs three categories of checks:

        1. **Global UUID uniqueness** — every entity in the collection must have a
           distinct UUID.
        2. **Array-field UUID uniqueness** — within each entity, array fields that
           hold references to other RDEs must not contain duplicate UUIDs.  The
           affected fields are:

           * :attr:`~timeatlas.RDEModel.HistoricalRecord.has_observations`
           * :attr:`~timeatlas.RDEModel.Observation.has_geometries`
           * :attr:`~timeatlas.RDEModel.Map.layers`

        3. **No stale references** — whenever an entity references another entity
           by UUID, that target entity must also be present in the collection.
           The following reference fields are checked:

           * ``HistoricalRecord.dataset`` → :class:`~timeatlas.RDEModel.Dataset`
           * ``HistoricalRecord.has_observations`` → :class:`~timeatlas.RDEModel.Observation`
           * ``Observation.historical_record`` → :class:`~timeatlas.RDEModel.HistoricalRecord`
           * ``Observation.part_of_point_of_interest`` → :class:`~timeatlas.RDEModel.PointOfInterest`
           * ``Observation.has_geometries`` → :class:`~timeatlas.RDEModel.Geometry`
           * ``Layer.map`` → :class:`~timeatlas.RDEModel.Map`
           * ``Map.layers`` → :class:`~timeatlas.RDEModel.Layer`

           The following fields are intentionally **exempt** from stale-reference
           checking because they routinely point to entities outside the collection:

           * ``Geometry.part_of_layer``
           * ``Dataset.has_areas``
           * ``Map.areas``

        Sets :attr:`_valid_data` to ``True`` when all checks pass.  Any failure
        raises a :exc:`ValueError` listing every detected problem.

        Returns:
            ``True`` when the collection passes all checks.

        Raises:
            ValueError: If one or more validation checks fail.  The exception
                message lists every individual problem found.
        """
        self._valid_data = False
        errors: list[str] = []

        def resolve_ref(ref) -> str | None:
            """Return the UUID string from any RDE reference form.

            Handles resolved RDE objects (via ``get_ref()``), raw UUID strings,
            and unresolved flags (``None``, ``bool``) — returning ``None`` for
            the latter so callers can skip them with a simple truthiness check.
            """
            match ref:
                case UUIDEntity():
                    return ref.get_ref()
                case str():
                    return ref
                case _:
                    return None

        # Build a UUID → RDE index once for efficient stale-reference lookups.
        uuid_index: dict[str, RDE] = {rde.id: rde for rde in self.rdes}

        # ------------------------------------------------------------------
        # 1. Global UUID uniqueness across the whole collection
        # ------------------------------------------------------------------
        all_ids = [rde.id for rde in self.rdes]
        duplicate_ids = {uid for uid, count in Counter(all_ids).items() if count > 1}
        if duplicate_ids:
            errors.append(f'Duplicate UUIDs found in collection: {duplicate_ids}')

        # ------------------------------------------------------------------
        # 2. UUID uniqueness within per-RDE array fields
        # ------------------------------------------------------------------
        for rde in self.rdes:
            match rde:
                case HistoricalRecord():
                    refs = [resolve_ref(r) for r in rde.has_observations]
                    dups = {r for r, c in Counter(refs).items() if c > 1}
                    if dups:
                        errors.append(
                            f'HistoricalRecord {rde.id}: duplicate UUIDs in has_observations: {dups}'
                        )
                case Observation():
                    refs = [resolve_ref(r) for r in rde.has_geometries]
                    dups = {r for r, c in Counter(refs).items() if c > 1}
                    if dups:
                        errors.append(
                            f'Observation {rde.id}: duplicate UUIDs in has_geometries: {dups}'
                        )
                case Map():
                    refs = [resolve_ref(r) for r in rde.layers]
                    dups = {r for r, c in Counter(refs).items() if c > 1}
                    if dups:
                        errors.append(
                            f'Map {rde.id}: duplicate UUIDs in layers: {dups}'
                        )

        # ------------------------------------------------------------------
        # 3. Stale-reference checks
        # ------------------------------------------------------------------
        for rde in self.rdes:
            match rde:
                case HistoricalRecord():
                    ds_id = resolve_ref(rde.dataset)
                    if ds_id and ds_id not in uuid_index:
                        errors.append(
                            f'HistoricalRecord {rde.id}: references missing Dataset {ds_id}'
                        )
                    for ref in rde.has_observations:
                        obs_id = resolve_ref(ref)
                        if obs_id and obs_id not in uuid_index:
                            errors.append(
                                f'HistoricalRecord {rde.id}: references missing Observation {obs_id}'
                            )

                case Observation():
                    hr_id = resolve_ref(rde.historical_record)
                    if hr_id and hr_id not in uuid_index:
                        errors.append(
                            f'Observation {rde.id}: references missing HistoricalRecord {hr_id}'
                        )
                    # part_of_point_of_interest may be bool (unresolved flag) — resolve_ref returns None for it
                    poi_id = resolve_ref(rde.part_of_point_of_interest)
                    if poi_id and poi_id not in uuid_index:
                        errors.append(
                            f'Observation {rde.id}: references missing PointOfInterest {poi_id}'
                        )
                    for ref in rde.has_geometries:
                        geom_id = resolve_ref(ref)
                        if geom_id and geom_id not in uuid_index:
                            errors.append(
                                f'Observation {rde.id}: references missing Geometry {geom_id}'
                            )

                case Layer():
                    map_id = resolve_ref(rde.map)
                    if map_id and map_id not in uuid_index:
                        errors.append(
                            f'Layer {rde.id}: references missing Map {map_id}'
                        )

                case Map():
                    for ref in rde.layers:
                        layer_id = resolve_ref(ref)
                        if layer_id and layer_id not in uuid_index:
                            errors.append(
                                f'Map {rde.id}: references missing Layer {layer_id}'
                            )
                    # Map.areas → exempt from stale-reference check

                case _:
                    pass
                    # Dataset.has_areas → exempt from stale-reference check
                    # Geometry.part_of_layer → exempt from stale-reference check

        if errors:
            raise ValueError(
                f'RDECollection validation failed with {len(errors)} error(s):\n'
                + '\n'.join(f'  - {e}' for e in errors)
            )

        self._valid_data = True
        return True
