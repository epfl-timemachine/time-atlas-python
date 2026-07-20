import hashlib
import json
from pathlib import Path

import pytest

from timeatlas import ImportWorkflowError, RDECollection, TimeAtlasImportClient


class Response:
    def __init__(self, status, payload=None, text=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.content = self.text.encode()
        self.headers = headers or {}

    def json(self):
        return self._payload


class Session:
    def __init__(self, responses=()):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def client(responses=()):
    return TimeAtlasImportClient(
        "https://example.test/v1", "secret", "team", session=Session(responses)
    )


def test_client_configuration_and_credentials_file(tmp_path):
    credentials = tmp_path / "credentials.txt"
    credentials.write_text("# local\nTOKEN='abc'\nTEAM_ID=xyz\n")
    session = Session()
    value = TimeAtlasImportClient.from_credentials_file(
        "https://example.test/v1/", credentials, session=session
    )

    assert value.api_url == "https://example.test/v1"
    assert value.team_id == "xyz"
    assert session.headers["Authorization"] == "Bearer abc"
    (tmp_path / "empty").write_text("")
    with pytest.raises(ValueError, match="missing"):
        TimeAtlasImportClient.from_credentials_file(
            "https://example.test/v1", tmp_path / "empty", session=session
        )


def test_client_rejects_invalid_configuration(tmp_path):
    (tmp_path / "empty").write_text("")
    with pytest.raises(ValueError, match="end with /v1"):
        TimeAtlasImportClient("https://example.test", "token", "team")
    with pytest.raises(ValueError, match="token"):
        TimeAtlasImportClient("https://example.test/v1", "", "team")
    with pytest.raises(ValueError, match="team_id"):
        TimeAtlasImportClient("https://example.test/v1", "token", "")


def test_request_checks_status_and_unwraps_data():
    value = client([Response(200, {"data": {"value": 1}}), Response(422, text="bad")])
    assert value._data(value._request("get", "files", {200}))["value"] == 1
    with pytest.raises(ImportWorkflowError, match="HTTP 422: bad"):
        value._request("post", "imports", {202})
    with pytest.raises(ImportWorkflowError, match="data object"):
        value._data({"data": []})


def test_request_retries_throttled_responses(monkeypatch):
    value = client(
        [
            Response(429, {"message": "slow"}, headers={"Retry-After": "0"}),
            Response(200, {"data": {"ok": True}}),
        ]
    )
    monkeypatch.setattr("timeatlas.importing.time.sleep", lambda _: None)
    assert value._request("get", "files", {200})["data"]["ok"] is True


def test_area_exists_online_uses_non_team_endpoint():
    value = client([Response(200, {"id": "area"}), Response(404, {"message": "missing"})])

    assert value.area_exists_online("present") is True
    assert value.area_exists_online("missing") is False
    assert value.session.calls[0][1] == "https://example.test/v1/areas/present"
    assert "/teams/" not in value.session.calls[0][1]

    value = client([Response(500, {"message": "broken"})])
    with pytest.raises(ImportWorkflowError, match="GET areas/id returned HTTP 500"):
        value.area_exists_online("id")


def test_area_preflight_skips_uploaded_areas_and_accepts_online_refs(entity_graph):
    collection = RDECollection(entity_graph["all"])
    collection.validate_data()
    value = client()
    value.ensure_area_references_available(collection)
    assert value.session.calls == []

    external_id = "00000000-0000-0000-0000-000000000120"
    entity_graph["dataset"].has_areas = [external_id]
    external_collection = RDECollection(entity_graph["all"])
    value = client([Response(200, {"id": external_id})])
    value.ensure_area_references_available(external_collection)
    assert value.session.calls[0][1].endswith(f"/areas/{external_id}")


def test_collection_workflow_interrupts_before_upload_for_missing_online_area(
    monkeypatch, tmp_path, entity_graph
):
    missing_id = "00000000-0000-0000-0000-000000000120"
    entity_graph["dataset"].has_areas = [missing_id]
    collection = RDECollection(entity_graph["all"])
    with pytest.warns(UserWarning, match="target backend"):
        collection.validate_data()
    value = client([Response(404, {"message": "missing"})])
    upload_attempted = False

    def upload_files(_paths):
        nonlocal upload_attempted
        upload_attempted = True

    monkeypatch.setattr(value, "upload_files", upload_files)
    with pytest.raises(ImportWorkflowError, match="Upload interrupted"):
        value.run_collection_workflow(collection, tmp_path)

    assert upload_attempted is False
    assert list(tmp_path.iterdir()) == []


def test_upload_file_builds_multipart_and_verifies_response(tmp_path):
    source = tmp_path / "dataset.json"
    source.write_text('{"ok": true}')
    metadata = {
        "uuid": "file-id",
        "original_filename": source.name,
        "size_bytes": source.stat().st_size,
        "checksum_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    value = client([Response(201, {"data": metadata})])

    assert value.upload_file(source, "folder") == metadata
    method, url, kwargs = value.session.calls[0]
    assert method == "post"
    assert url.endswith("/teams/team/files")
    assert kwargs["data"] == {"virtual_folder_path": "folder"}
    assert kwargs["files"]["file"][0] == "dataset.json"

    bad = dict(metadata, checksum_sha256="bad")
    with pytest.raises(ImportWorkflowError, match="checksum"):
        client([Response(201, {"data": bad})]).upload_file(source)
    with pytest.raises(FileNotFoundError):
        value.upload_file(tmp_path / "missing.json")


def test_list_and_upload_files_verify_server_listing(monkeypatch, tmp_path):
    value = client(
        [
            Response(200, {"data": [{"uuid": "one"}], "meta": {"last_page": 2}}),
            Response(200, {"data": [{"uuid": "two"}], "meta": {"last_page": 2}}),
        ]
    )
    assert [item["uuid"] for item in value.list_files()] == ["one", "two"]
    assert [call[2]["params"]["page"] for call in value.session.calls] == [1, 2]

    monkeypatch.setattr(value, "upload_file", lambda path, folder: {"uuid": Path(path).stem})
    monkeypatch.setattr(value, "list_files", lambda folder: [{"uuid": "one"}])
    assert value.upload_files(["one.json"]) == [{"uuid": "one"}]
    with pytest.raises(ImportWorkflowError, match="absent"):
        value.upload_files(["two.json"])


def test_import_endpoint_wrappers():
    responses = [
        Response(202, {"data": {"uuid": "import"}}),
        Response(200, {"data": {"uuid": "import", "status": "packaged"}}),
        Response(200, {"data": [{"id": 3}], "meta": {"next_cursor": 3}}),
        Response(202, {"data": {}}),
        Response(200, {"data": {"status": "passed"}}),
        Response(202, {"data": {}}),
        Response(200, {"data": {"status": "published"}}),
        Response(200, {"data": {"status": "published"}}),
    ]
    value = client(responses)
    assert value.create_import(["file"], config={"x": 1})["uuid"] == "import"
    assert value.get_import("import")["status"] == "packaged"
    assert value.list_events("import") == ([{"id": 3}], 3)
    value.validate_import("import")
    assert value.get_validation_report("import")["status"] == "passed"
    value.queue_import("import")
    assert value.publish_resource("dataset", "dataset")["status"] == "published"
    assert value.publish_import_resource_type("import", "dataset")["status"] == "published"
    with pytest.raises(ValueError, match="Unsupported"):
        value.publish_resource("observation", "x")


def test_publish_resource_treats_already_published_as_success():
    value = client([Response(409, {"message": "Resource is already published."})])
    assert value.publish_resource("dataset", "id") == {
        "uuid": "id",
        "type": "dataset",
        "status": "published",
        "visibility": "public",
    }

    value = client([Response(409, {"message": "Different conflict"})])
    with pytest.raises(ImportWorkflowError, match="Could not publish"):
        value.publish_resource("dataset", "id")


def test_publish_resources_uses_bounded_worker_pool(monkeypatch):
    value = client()
    monkeypatch.setattr(
        value,
        "publish_resource",
        lambda kind, identifier, visibility: {"type": kind, "uuid": identifier},
    )
    assert value.publish_resources("dataset", ["one", "two"], max_workers=2) == [
        {"type": "dataset", "uuid": "one"},
        {"type": "dataset", "uuid": "two"},
    ]
    with pytest.raises(ValueError, match="max_workers"):
        value.publish_resources("dataset", [], max_workers=0)


def test_wait_for_import_collects_events_and_handles_failure(monkeypatch):
    value = client()
    states = iter([{"status": "packaging"}, {"status": "packaged"}])
    event_pages = iter([([{"id": 1}], 1), ([{"id": 2}], 2)])
    monkeypatch.setattr(value, "get_import", lambda _: next(states))
    monkeypatch.setattr(value, "list_events", lambda *args, **kwargs: next(event_pages))
    seen = []
    current, events = value.wait_for_import(
        "import", {"packaged"}, poll_interval=0, on_event=seen.append
    )
    assert current["status"] == "packaged"
    assert events == seen == [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(value, "list_events", lambda *args, **kwargs: ([], None))
    monkeypatch.setattr(value, "get_import", lambda _: {"status": "failed", "errors": {"x": 1}})
    with pytest.raises(ImportWorkflowError, match="entered failed"):
        value.wait_for_import("import", {"completed"}, poll_interval=0)


def test_collection_workflow_requires_validation_and_runs_all_phases(
    monkeypatch, tmp_path, entity_graph
):
    collection = RDECollection(entity_graph["all"])
    value = client()
    with pytest.raises(ValueError, match="validate_data"):
        value.run_collection_workflow(collection, tmp_path)

    collection.validate_data()
    monkeypatch.setattr(value, "upload_files", lambda paths: [{"uuid": "file"}])
    created_import_types = []
    monkeypatch.setattr(
        value,
        "create_import",
        lambda ids, import_type: created_import_types.append(import_type)
        or {"uuid": "import"},
    )
    waits = iter(
        [
            ({"status": "packaged"}, [{"id": 1}]),
            ({"status": "validated"}, [{"id": 2}]),
            ({"status": "completed"}, [{"id": 3}]),
        ]
    )
    monkeypatch.setattr(value, "wait_for_import", lambda *args, **kwargs: next(waits))
    monkeypatch.setattr(value, "validate_import", lambda _: None)
    monkeypatch.setattr(
        value, "get_validation_report", lambda _: {"status": "passed", "failures": []}
    )
    monkeypatch.setattr(value, "queue_import", lambda _: None)
    published = []
    monkeypatch.setattr(
        value,
        "publish_import_resource_type",
        lambda import_id, kind, visibility: published.append(kind) or {"type": kind},
    )
    individually_published = []
    monkeypatch.setattr(
        value,
        "publish_resources",
        lambda kind, ids, visibility, max_workers: individually_published.append(
            (kind, list(ids))
        )
        or [],
    )

    result = value.run_collection_workflow(collection, tmp_path, poll_interval=0)

    assert result.import_data["status"] == "completed"
    assert created_import_types == ["full"]
    assert result.events == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert published == ["area", "point_of_interest", "dataset", "map"]
    assert [item[0] for item in individually_published] == [
        "area",
        "point_of_interest",
        "dataset",
        "map",
    ]


def test_collection_workflow_stops_on_failed_report(monkeypatch, tmp_path, entity_graph):
    collection = RDECollection(entity_graph["all"])
    collection.validate_data()
    value = client()
    monkeypatch.setattr(value, "upload_files", lambda paths: [{"uuid": "file"}])
    monkeypatch.setattr(
        value, "create_import", lambda ids, import_type: {"uuid": "import"}
    )
    monkeypatch.setattr(value, "wait_for_import", lambda *args, **kwargs: ({}, []))
    monkeypatch.setattr(value, "validate_import", lambda _: None)
    monkeypatch.setattr(
        value,
        "get_validation_report",
        lambda _: {"status": "failed", "failures": [{"message": "bad"}]},
    )
    with pytest.raises(ImportWorkflowError, match="did not pass"):
        value.run_collection_workflow(collection, tmp_path)
