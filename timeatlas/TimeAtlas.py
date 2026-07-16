import json
import os
import pickle
import shapely
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable
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
        resp.raise_for_status()
        data = resp.json()
        for dataset in data['items']:
            if dataset['slug'] == slug:
                ds = Dataset.constructor_from_json_obj(dataset)
                self.entity_cache[ds.id] = ds
                return ds
        raise ValueError(f'Dataset with slug {slug} not found')

    def generate_all_hr_from_dataset(self, dataset: Dataset) -> list[HistoricalRecord]:
        hr_jsons = self.get_all_results_from_endpoint('hr/search?query=&dataset_slug=' + dataset.slug, per_page=1000)
        hrs = [HistoricalRecord.constructor_from_json_obj(hr_json) for hr_json in hr_jsons]
        self.entity_cache.update({hr.id: hr for hr in hrs})
        return hrs

    # Waring: very slow. Waiting on a better API endpoint to retrieve all obs for a dataset
    def generate_obs_from_list_of_hr(self, hr_list: list[HistoricalRecord]) -> list[Observation]:
        obs_uuids = set()
        for hr in hr_list:
            for obs_ref in hr.has_observations:
                match obs_ref:
                    case str():
                        obs_uuids.add(obs_ref)
                    case Observation():
                        obs_uuids.add(obs_ref.id)
        obs_list = []
        # for obs_uuid in tqdm(obs_uuids, desc='Fetching observations'):
        for obs_uuid in obs_uuids:
            obs_list.append(self.get_single_rde_object('obs', obs_uuid))
        return obs_list
    
    def generate_geoms_from_list_of_obs(self, obs_list: list[Observation    ]) -> list[Geometry]:
        geom_uuids = set()
        for obs in obs_list:
            for geom_ref in obs.has_geometries:
                match geom_ref:
                    case str():
                        geom_uuids.add(geom_ref)
                    case Geometry():
                        geom_uuids.add(geom_ref.id)
        geom_list = []
        # for geom_uuid in tqdm(geom_uuids, desc='Fetching geometries'):
        for geom_uuid in geom_uuids:
            geom_list.append(self.get_single_rde_object('geometries', geom_uuid))
        return geom_list


    def generate_pois_from_list_of_obs(self, obs_list: list[Observation]) -> list[PointOfInterest]:
        poi_uuids = set()
        for obs in obs_list:
            poi_ref = obs.part_of_point_of_interest
            match poi_ref:
                case str():
                    poi_uuids.add(poi_ref)
                case PointOfInterest():
                    poi_uuids.add(poi_ref.id)
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


class RDEEnvelopeWriter:
    """Write TimeAtlas RDE ingestion envelopes.

    The writer accepts either concrete RDE model instances or already-serialized
    dictionaries.  It can write a regular envelope, stream an iterable directly
    to disk, or split a large iterable into several envelopes by estimated JSON
    byte size.
    """

    def __init__(
        self,
        output_dir: str | os.PathLike = '.',
        overwrite: bool = True,
        indent: int | None = 1,
    ):
        self.output_dir = Path(output_dir)
        self.overwrite = overwrite
        self.indent = indent

    @staticmethod
    def serialize_object(obj: RDE | dict) -> dict:
        """Return a JSON-compatible dictionary for one RDE object."""
        if isinstance(obj, dict):
            raw = obj
        elif hasattr(obj, 'to_dict'):
            raw = obj.to_dict()
        else:
            raise TypeError(f'Unsupported RDE envelope object type: {type(obj)}')
        return json.loads(json.dumps(raw, cls=_ShapelyEncoder, ensure_ascii=False))

    @staticmethod
    def normalize_type_in_file(rde_type: str | Iterable[str]) -> list[str]:
        """Normalize an RDE type label or labels to the envelope list form."""
        if isinstance(rde_type, str):
            return [rde_type]
        return list(rde_type)

    def _target_path(self, filename: str | os.PathLike) -> Path:
        path = Path(filename)
        if path.suffix != '.json':
            path = path.with_suffix('.json')
        if not path.is_absolute():
            path = self.output_dir / path
        return path

    def _creation_time(self, creation_time: str | None = None) -> str:
        return creation_time if creation_time is not None else datetime.now().isoformat()

    def _envelope(
        self,
        objects: list[dict],
        name: str,
        rde_type: str | Iterable[str],
        creation_time: str | None = None,
        related_dataset_slugs: list[str] | None = None,
    ) -> dict:
        envelope = {
            'name': name,
            'type_in_file': self.normalize_type_in_file(rde_type),
            'creation_time': self._creation_time(creation_time),
        }
        if related_dataset_slugs is not None:
            envelope['related_dataset_slugs'] = related_dataset_slugs
        envelope['rde_objects'] = objects
        return envelope

    def write(
        self,
        filename: str | os.PathLike,
        objects: Iterable[RDE | dict],
        name: str | None,
        rde_type: str | Iterable[str],
        *,
        overwrite: bool | None = None,
        creation_time: str | None = None,
        skip_if_unchanged: bool = False,
        related_dataset_slugs: list[str] | None = None,
    ) -> Path:
        """Write one RDE envelope and return its path.

        When ``skip_if_unchanged`` is enabled, the destination file is left
        untouched if its existing ``rde_objects`` payload is identical to the
        payload about to be written.
        """
        path = self._target_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        should_overwrite = self.overwrite if overwrite is None else overwrite
        serialized = [self.serialize_object(obj) for obj in objects]

        if not should_overwrite and path.exists() and skip_if_unchanged:
            with path.open('r', encoding='utf-8') as f:
                existing = json.load(f)
            if existing.get('rde_objects') == serialized:
                return path

        if path.exists() and not should_overwrite and not skip_if_unchanged:
            raise FileExistsError(f'{path} already exists')

        envelope_name = name if name is not None else path.stem
        envelope = self._envelope(serialized, envelope_name, rde_type, creation_time, related_dataset_slugs)
        with path.open('w', encoding='utf-8') as f:
            json.dump(envelope, f, indent=self.indent, ensure_ascii=False)
        return path

    def write_stream(
        self,
        filename: str | os.PathLike,
        objects: Iterable[RDE | dict],
        name: str | None,
        rde_type: str | Iterable[str],
        *,
        overwrite: bool | None = None,
        creation_time: str | None = None,
        related_dataset_slugs: list[str] | None = None,
    ) -> Path:
        """Write one RDE envelope while consuming ``objects`` incrementally."""
        path = self._target_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        should_overwrite = self.overwrite if overwrite is None else overwrite
        if path.exists() and not should_overwrite:
            raise FileExistsError(f'{path} already exists')

        envelope_name = name if name is not None else path.stem
        type_in_file = self.normalize_type_in_file(rde_type)
        with path.open('w', encoding='utf-8') as f:
            f.write('{\n')
            f.write(f' "name": {json.dumps(envelope_name, ensure_ascii=False)},\n')
            f.write(f' "type_in_file": {json.dumps(type_in_file, ensure_ascii=False)},\n')
            f.write(
                f' "creation_time": {json.dumps(self._creation_time(creation_time), ensure_ascii=False)},\n'
            )
            if related_dataset_slugs is not None:
                f.write(
                    f' "related_dataset_slugs": {json.dumps(related_dataset_slugs, ensure_ascii=False)},\n'
                )
            f.write(' "rde_objects": [')
            first = True
            for obj in objects:
                if first:
                    f.write('\n')
                    first = False
                else:
                    f.write(',\n')
                f.write(json.dumps(self.serialize_object(obj), ensure_ascii=False, cls=_ShapelyEncoder))
            if not first:
                f.write('\n')
            f.write(' ]\n}')
        return path

    def write_batches_by_size(
        self,
        filename_prefix: str,
        objects: Iterable[RDE | dict],
        name_prefix: str | None,
        rde_type: str | Iterable[str],
        max_size_bytes: int,
        *,
        start_index: int = 1,
        overwrite: bool | None = None,
        creation_time: str | None = None,
        related_dataset_slugs: list[str] | None = None,
    ) -> list[Path]:
        """Write several envelopes, flushing each batch near ``max_size_bytes``.

        The byte size is estimated from the serialized JSON payload plus the
        envelope overhead.  Objects larger than the threshold are still written,
        one per file.
        """
        if max_size_bytes <= 0:
            raise ValueError('max_size_bytes must be greater than 0')

        paths: list[Path] = []
        batch: list[dict] = []
        batch_bytes = 0
        index = start_index

        def batch_filename(batch_index: int) -> str:
            return f'{filename_prefix}_{batch_index}'

        def batch_name(batch_index: int) -> str:
            prefix = name_prefix if name_prefix is not None else filename_prefix
            return f'{prefix}_{batch_index}'

        def envelope_overhead_size(batch_index: int) -> int:
            envelope = self._envelope([], batch_name(batch_index), rde_type, creation_time, related_dataset_slugs)
            return len(json.dumps(envelope, ensure_ascii=False, cls=_ShapelyEncoder).encode('utf-8'))

        overhead = envelope_overhead_size(index)

        def flush() -> None:
            nonlocal batch, batch_bytes, index, overhead
            if not batch:
                return
            paths.append(
                self.write(
                    batch_filename(index),
                    batch,
                    batch_name(index),
                    rde_type,
                    overwrite=overwrite,
                    creation_time=creation_time,
                    related_dataset_slugs=related_dataset_slugs,
                )
            )
            batch = []
            batch_bytes = 0
            index += 1
            overhead = envelope_overhead_size(index)

        for obj in objects:
            serialized = self.serialize_object(obj)
            serialized_size = len(json.dumps(serialized, ensure_ascii=False).encode('utf-8')) + 2
            if batch and overhead + batch_bytes + serialized_size > max_size_bytes:
                flush()
            batch.append(serialized)
            batch_bytes += serialized_size

        flush()
        return paths


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

    _DATASET_TIED_TYPES: frozenset[type] = frozenset({HistoricalRecord, Observation, Dataset})
    """RDE types whose output files carry a ``related_dataset_slugs`` header field."""

    _POI_NAMESPACE = uuid.uuid5(
        uuid.NAMESPACE_URL,
        'https://timemachine.epfl.ch/operational/pois/',
    )
    """Shared namespace used for coordinate-derived Point of Interest UUIDs."""

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

    def save_rde_to_files(self, output_dir: str, overwrite: bool = False, rde_types: list[type] | None = None, dataset_slug: str | None = None) -> None:
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
            dataset_slug: When provided, dataset-tied output files
                        (``dataset.json``, ``historical_records.json``,
                        ``observations.json``) will include a
                        ``related_dataset_slugs`` header field set to
                        ``[dataset_slug]``. When omitted and the collection contains
                        exactly one dataset slug, that slug is inferred automatically.

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

        inferred_dataset_slugs = sorted({
            rde.slug
            for rde in self.rdes
            if isinstance(rde, Dataset) and rde.slug
        })
        related_dataset_slugs = (
            [dataset_slug]
            if dataset_slug is not None
            else inferred_dataset_slugs
            if len(inferred_dataset_slugs) == 1
            else None
        )

        for cls, rde_group in groups.items():
            filename, type_label = self._FILE_MAP[cls]
            filepath = os.path.join(output_dir, f'{filename}.json')

            # Only add related_dataset_slugs for dataset-tied file types
            slugs = related_dataset_slugs if cls in self._DATASET_TIED_TYPES else None

            # Produce fully-decoded dicts (Shapely geometries → GeoJSON) so the
            # result is directly comparable to what was previously saved on disk.
            serialized = [RDEEnvelopeWriter.serialize_object(rde) for rde in rde_group]

            if not overwrite and os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                same_objects = existing.get('rde_objects') == serialized
                same_related_slugs = (
                    cls not in self._DATASET_TIED_TYPES
                    or existing.get('related_dataset_slugs') == slugs
                )
                if same_objects and same_related_slugs:
                    continue

            RDEEnvelopeWriter(output_dir, overwrite=True).write(
                filename,
                serialized,
                filename,
                type_label,
                overwrite=True,
                related_dataset_slugs=slugs,
            )

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

    def aggregate_observations_into_points_of_interest(
        self,
        coordinate_precision: int = 5,
    ) -> list[PointOfInterest]:
        """Aggregate collection observations into coordinate-based Points of Interest.

        Every :class:`Observation` whose ``part_of_point_of_interest`` value is not
        explicitly ``False`` participates in the aggregation.  Coordinates are
        rounded to *coordinate_precision* decimal places and observations at the
        same rounded longitude/latitude are assigned the same deterministic UUID.
        The UUID algorithm and namespace match the legacy ``merge_obs.py`` data
        production utility.

        The operation mutates the collection: observation references are replaced
        by the generated UUID strings and the corresponding
        :class:`PointOfInterest` entities are added to ``rdes``.  Existing PoIs with
        a generated UUID are reused so their height information is preserved.  PoIs
        referenced by participating observations under an obsolete UUID are
        removed, while unrelated PoIs are left untouched.  Observations explicitly
        marked ``False`` or lacking a geometry receive a ``None`` PoI reference.

        Args:
            coordinate_precision: Number of decimal places used to aggregate
                coordinates.  Five decimal places is the legacy default and gives
                sub-metre grouping precision.

        Returns:
            The generated or reused Points of Interest, ordered by rounded
            longitude and latitude.

        Raises:
            ValueError: If *coordinate_precision* is negative or a participating
                observation has a non-point geometry.
        """
        if coordinate_precision < 0:
            raise ValueError('coordinate_precision must be greater than or equal to 0')

        observations = [rde for rde in self.rdes if isinstance(rde, Observation)]
        grouped_observations: dict[tuple[float, float], list[Observation]] = {}
        replaced_poi_ids: set[str] = set()

        for observation in observations:
            poi_reference = observation.part_of_point_of_interest
            if isinstance(poi_reference, PointOfInterest):
                replaced_poi_ids.add(poi_reference.id)
            elif isinstance(poi_reference, str):
                replaced_poi_ids.add(poi_reference)

            if poi_reference is False or observation.geometry is None:
                observation.part_of_point_of_interest = None
                continue
            if not isinstance(observation.geometry, shapely.geometry.Point):
                raise ValueError(
                    f'Observation {observation.id} must have a Point geometry to aggregate into a PoI'
                )
            if observation.geometry.is_empty:
                observation.part_of_point_of_interest = None
                continue

            coordinates = (
                round(float(observation.geometry.x), coordinate_precision),
                round(float(observation.geometry.y), coordinate_precision),
            )
            grouped_observations.setdefault(coordinates, []).append(observation)

        existing_pois = {
            rde.id: rde for rde in self.rdes if isinstance(rde, PointOfInterest)
        }
        generated_pois: list[PointOfInterest] = []

        for (longitude, latitude), grouped in sorted(grouped_observations.items()):
            poi_id = str(
                uuid.uuid5(
                    self._POI_NAMESPACE,
                    f'poi_{longitude}_{latitude}',
                )
            )
            poi = existing_pois.get(poi_id)
            if poi is None:
                poi = PointOfInterest(
                    id=poi_id,
                    geometry=shapely.geometry.Point(longitude, latitude),
                    height=HeightInfo(),
                )
            generated_pois.append(poi)
            for observation in grouped:
                observation.part_of_point_of_interest = poi_id

        generated_ids = {poi.id for poi in generated_pois}
        self.rdes = [
            rde
            for rde in self.rdes
            if not (
                isinstance(rde, PointOfInterest)
                and rde.id in replaced_poi_ids
                and rde.id not in generated_ids
            )
        ]
        current_poi_ids = {
            rde.id for rde in self.rdes if isinstance(rde, PointOfInterest)
        }
        self.rdes.extend(poi for poi in generated_pois if poi.id not in current_poi_ids)
        self._valid_data = False
        return generated_pois

    def consolidate_data(self, coordinate_precision: int = 5) -> list[PointOfInterest]:
        """Produce PoIs and update observation references in this collection.

        This backward-compatible entry point delegates to
        :meth:`aggregate_observations_into_points_of_interest`.
        """
        return self.aggregate_observations_into_points_of_interest(coordinate_precision)

    def validate_data(
        self,
        mode: str = 'strict',
        *,
        allow_null_has_geometries: bool = False,
        allow_unresolved_poi: bool = False,
    ) -> bool:
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

        ``mode='strict'`` keeps the default validation rules. ``mode='raw'`` is
        intended for legacy/raw producers and enables both
        ``allow_null_has_geometries`` and ``allow_unresolved_poi``.

        Sets :attr:`_valid_data` to ``True`` when all checks pass.  Any failure
        raises a :exc:`ValueError` listing every detected problem.

        Returns:
            ``True`` when the collection passes all checks.

        Raises:
            ValueError: If one or more validation checks fail.  The exception
                message lists every individual problem found.
        """
        if mode not in {'strict', 'raw'}:
            raise ValueError("mode must be either 'strict' or 'raw'")
        if mode == 'raw':
            allow_null_has_geometries = True
            allow_unresolved_poi = True

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
                    if rde.has_geometries is None:
                        if allow_null_has_geometries:
                            continue
                        errors.append(
                            f'Observation {rde.id}: has_geometries is null'
                        )
                        continue
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
                    if (
                        poi_id
                        and poi_id not in uuid_index
                        and allow_unresolved_poi
                    ):
                        poi_id = None
                    if poi_id and poi_id not in uuid_index:
                        errors.append(
                            f'Observation {rde.id}: references missing PointOfInterest {poi_id}'
                        )
                    if rde.has_geometries is None:
                        continue
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
