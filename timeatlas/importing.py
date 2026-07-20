"""Authenticated wrappers for the Time Atlas file-import workflow."""

from __future__ import annotations

import hashlib
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import requests


class ImportWorkflowError(RuntimeError):
    """Raised when an import cannot safely advance to its next phase."""


@dataclass
class ImportWorkflowResult:
    """The server artefacts produced by a completed import/publication run."""

    uploaded_files: list[dict]
    import_data: dict
    validation_report: dict
    events: list[dict] = field(default_factory=list)
    publications: list[dict] = field(default_factory=list)


class TimeAtlasImportClient:
    """Client for uploading, validating, importing, and publishing RDE files.

    ``api_url`` must point at the versioned API root, for example
    ``http://localhost:8000/v1``. Personal access tokens are sent as Bearer
    tokens and are never included in exceptions or returned workflow data.
    """

    FAILURE_STATUSES = frozenset(
        {
            "validation_failed",
            "failed",
            "cancelled",
            "cancelled_with_partial_import",
        }
    )
    COMPLETED_STATUSES = frozenset({"completed", "completed_with_indexing_errors"})
    _RESOURCE_ENDPOINTS = {
        "dataset": "datasets",
        "map": "maps",
        "area": "areas",
        "point_of_interest": "points-of-interest",
    }

    def __init__(
        self,
        api_url: str,
        token: str,
        team_id: str,
        *,
        timeout: float = 60,
        max_retries: int = 5,
        session: requests.Session | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        if not self.api_url.endswith("/v1"):
            raise ValueError("API URL must end with /v1")
        if not token:
            raise ValueError("token must not be empty")
        if not team_id:
            raise ValueError("team_id must not be empty")
        self.team_id = team_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        )

    @classmethod
    def from_credentials_file(
        cls, api_url: str, path: str | Path, **kwargs
    ) -> "TimeAtlasImportClient":
        """Build a client from a file containing ``TOKEN=`` and ``TEAM_ID=`` lines."""
        values = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
        missing = {"TOKEN", "TEAM_ID"} - values.keys()
        if missing:
            raise ValueError(f"Credential file is missing: {', '.join(sorted(missing))}")
        return cls(api_url, values["TOKEN"], values["TEAM_ID"], **kwargs)

    def _url(self, path: str) -> str:
        return f"{self.api_url}/teams/{self.team_id}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, expected: Iterable[int], **kwargs) -> dict:
        for attempt in range(self.max_retries + 1):
            response = self.session.request(
                method, self._url(path), timeout=self.timeout, **kwargs
            )
            if response.status_code != 429 or attempt == self.max_retries:
                break
            retry_after = getattr(response, "headers", {}).get("Retry-After")
            try:
                delay = max(float(retry_after), 0.1)
            except (TypeError, ValueError):
                delay = min(2**attempt, 30)
            time.sleep(delay)
        if response.status_code not in set(expected):
            detail = response.text[:1000]
            raise ImportWorkflowError(
                f"{method.upper()} {path} returned HTTP {response.status_code}: {detail}"
            )
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    @staticmethod
    def _data(payload: dict) -> dict:
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise ImportWorkflowError("The API response does not contain a data object")
        return data

    def upload_file(self, path: str | Path, virtual_folder_path: str | None = None) -> dict:
        """Upload one source file and verify its name, size, and SHA-256 checksum."""
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        form = {} if virtual_folder_path is None else {"virtual_folder_path": virtual_folder_path}
        with source.open("rb") as stream:
            payload = self._request(
                "post",
                "files",
                {201},
                data=form,
                files={"file": (source.name, stream, mime_type)},
            )
        uploaded = self._data(payload)
        expected_checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        mismatches = []
        if uploaded.get("original_filename") != source.name:
            mismatches.append("filename")
        if uploaded.get("size_bytes") != source.stat().st_size:
            mismatches.append("size")
        if uploaded.get("checksum_sha256") != expected_checksum:
            mismatches.append("checksum")
        if mismatches:
            raise ImportWorkflowError(
                f"Uploaded file {source.name} failed server verification: {', '.join(mismatches)}"
            )
        return uploaded

    def list_files(self, folder: str = "", per_page: int = 100) -> list[dict]:
        """List all team files, following the API's page links."""
        files: list[dict] = []
        page = 1
        while True:
            payload = self._request(
                "get",
                "files",
                {200},
                params={
                    "folder": folder,
                    "page": page,
                    "per_page": per_page,
                    "sort_by": "name",
                    "sort_dir": "asc",
                },
            )
            files.extend(payload.get("data", []))
            meta = payload.get("meta", {})
            if page >= meta.get("last_page", meta.get("current_page", page)):
                break
            page += 1
        return files

    def upload_files(
        self, paths: Iterable[str | Path], virtual_folder_path: str | None = None
    ) -> list[dict]:
        """Upload several files and confirm every returned UUID appears in the listing."""
        uploaded = [self.upload_file(path, virtual_folder_path) for path in paths]
        listed_ids = {item.get("uuid") for item in self.list_files(virtual_folder_path or "")}
        missing = [item.get("uuid") for item in uploaded if item.get("uuid") not in listed_ids]
        if missing:
            raise ImportWorkflowError(f"Uploaded files are absent from the team listing: {missing}")
        return uploaded

    def create_import(
        self,
        team_file_uuids: Iterable[str],
        *,
        import_type: str = "dataset",
        config: dict | None = None,
    ) -> dict:
        body = {
            "type": import_type,
            "team_file_uuids": list(team_file_uuids),
            "mode": "manual",
        }
        if config is not None:
            body["config"] = config
        return self._data(self._request("post", "imports", {202}, json=body))

    def get_import(self, import_id: str) -> dict:
        return self._data(self._request("get", f"imports/{import_id}", {200}))

    def list_events(
        self, import_id: str, *, cursor: int | None = None
    ) -> tuple[list[dict], int | None]:
        params = {} if cursor is None else {"cursor": cursor}
        payload = self._request("get", f"imports/{import_id}/events", {200}, params=params)
        events = payload.get("data", [])
        meta = payload.get("meta", {})
        next_cursor = meta.get("next_cursor")
        if next_cursor is None and events:
            last_id = events[-1].get("id")
            next_cursor = last_id + 1 if isinstance(last_id, int) else None
        return events, next_cursor

    def wait_for_import(
        self,
        import_id: str,
        success_statuses: Iterable[str],
        *,
        timeout: float = 1800,
        poll_interval: float = 2,
        on_event: Callable[[dict], None] | None = None,
    ) -> tuple[dict, list[dict]]:
        """Poll import status and events until a requested terminal phase is reached."""
        successes = set(success_statuses)
        deadline = time.monotonic() + timeout
        cursor = None
        collected: list[dict] = []
        while True:
            events, cursor = self.list_events(import_id, cursor=cursor)
            collected.extend(events)
            if on_event is not None:
                for event in events:
                    on_event(event)
            current = self.get_import(import_id)
            status = current.get("status")
            if status in successes:
                return current, collected
            if status in self.FAILURE_STATUSES:
                raise ImportWorkflowError(
                    f"Import {import_id} entered {status}: {current.get('errors', {})}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for import {import_id}; last status was {status}"
                )
            time.sleep(poll_interval)

    def validate_import(self, import_id: str) -> None:
        self._request("post", f"imports/{import_id}/validate", {202})

    def get_validation_report(self, import_id: str) -> dict:
        return self._data(
            self._request("get", f"imports/{import_id}/validation-report", {200})
        )

    def queue_import(self, import_id: str) -> None:
        self._request("post", f"imports/{import_id}/queue", {202})

    def publish_resource(
        self, resource_type: str, resource_id: str, visibility: str = "public"
    ) -> dict:
        endpoint = self._RESOURCE_ENDPOINTS.get(resource_type)
        if endpoint is None:
            raise ValueError(f"Unsupported publishable resource type: {resource_type}")
        payload = self._request(
            "post",
            f"{endpoint}/{resource_id}/publish",
            {200, 409},
            json={"visibility": visibility},
        )
        if "already published" in str(payload.get("message", "")).lower():
            return {
                "uuid": resource_id,
                "type": resource_type,
                "status": "published",
                "visibility": visibility,
            }
        if "data" not in payload:
            raise ImportWorkflowError(
                f"Could not publish {resource_type} {resource_id}: {payload}"
            )
        return self._data(payload)

    def publish_import_resource_type(
        self, import_id: str, resource_type: str, visibility: str = "public"
    ) -> dict:
        """Publish all imported resources of a type through the bulk import route."""
        return self._data(
            self._request(
                "post",
                f"imports/{import_id}/resources/publish",
                {200, 202},
                json={"type": resource_type, "visibility": visibility},
            )
        )

    def publish_resources(
        self,
        resource_type: str,
        resource_ids: Iterable[str],
        visibility: str = "public",
        *,
        max_workers: int = 8,
    ) -> list[dict]:
        """Publish resources through documented entity routes with bounded concurrency."""
        ids = list(resource_ids)
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than 0")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(
                executor.map(
                    lambda resource_id: self.publish_resource(
                        resource_type, resource_id, visibility
                    ),
                    ids,
                )
            )

    def run_collection_workflow(
        self,
        collection,
        output_dir: str | Path,
        *,
        visibility: str = "public",
        workflow_timeout: float = 1800,
        poll_interval: float = 2,
        publication_workers: int = 8,
        on_event: Callable[[dict], None] | None = None,
    ) -> ImportWorkflowResult:
        """Serialize a validated collection and run the complete publication workflow."""
        if not getattr(collection, "_valid_data", False):
            raise ValueError("RDECollection must pass validate_data() before upload")

        output = Path(output_dir)
        collection.save_rde_to_files(str(output), overwrite=True)
        present_types = {type(item) for item in collection.rdes}
        paths = [
            output / f"{filename}.json"
            for cls, (filename, _label) in collection._FILE_MAP.items()
            if cls in present_types
        ]
        uploaded = self.upload_files(paths)
        created = self.create_import(item["uuid"] for item in uploaded)
        import_id = created["uuid"]

        emitted_event_ids: set[int] = set()

        def emit_once(event: dict) -> None:
            event_id = event.get("id")
            if isinstance(event_id, int) and event_id in emitted_event_ids:
                return
            if isinstance(event_id, int):
                emitted_event_ids.add(event_id)
            if on_event is not None:
                on_event(event)

        _packaged, packaging_events = self.wait_for_import(
            import_id,
            {"packaged"},
            timeout=workflow_timeout,
            poll_interval=poll_interval,
            on_event=emit_once,
        )
        self.validate_import(import_id)
        _validated, validation_events = self.wait_for_import(
            import_id,
            {"validated"},
            timeout=workflow_timeout,
            poll_interval=poll_interval,
            on_event=emit_once,
        )
        report = self.get_validation_report(import_id)
        if report.get("status") != "passed" or report.get("failures"):
            raise ImportWorkflowError(f"Server validation did not pass: {report}")

        self.queue_import(import_id)
        completed, import_events = self.wait_for_import(
            import_id,
            self.COMPLETED_STATUSES,
            timeout=workflow_timeout,
            poll_interval=poll_interval,
            on_event=emit_once,
        )

        # The import-scoped endpoint publishes every imported entity of a type,
        # including dataset-level PoIs, without thousands of individual calls.
        resource_types = []
        for cls, resource_type in (
            (collection._class_for_name("PointOfInterest"), "point_of_interest"),
            (collection._class_for_name("Dataset"), "dataset"),
            (collection._class_for_name("Map"), "map"),
            (collection._class_for_name("Area"), "area"),
        ):
            if cls in present_types:
                resource_types.append(resource_type)
        publications = []
        for kind in resource_types:
            bulk_result = self.publish_import_resource_type(import_id, kind, visibility)
            publications.append(bulk_result)
            # Some API releases expose the import-scoped route but return only a
            # selection summary. In that case use the documented entity routes
            # to guarantee that publication state is actually updated.
            if bulk_result.get("status") != "published":
                model_name = {
                    "point_of_interest": "PointOfInterest",
                    "dataset": "Dataset",
                    "map": "Map",
                    "area": "Area",
                }[kind]
                ids = [
                    item.id
                    for item in collection.rdes
                    if type(item) is collection._class_for_name(model_name)
                ]
                publications.extend(
                    self.publish_resources(
                        kind,
                        ids,
                        visibility,
                        max_workers=publication_workers,
                    )
                )
        unique_events = {
            event.get("id", ("without-id", index)): event
            for index, event in enumerate(
                packaging_events + validation_events + import_events
            )
        }
        return ImportWorkflowResult(
            uploaded_files=uploaded,
            import_data=completed,
            validation_report=report,
            events=list(unique_events.values()),
            publications=publications,
        )
