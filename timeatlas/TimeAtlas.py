import os
from .RDEModel import *
import requests
import pickle
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
                    case Obs():
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
