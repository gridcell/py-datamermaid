"""Tests for the generated-report endpoint (``get_gfcr_report``).

The mocked response is built here rather than checked in: ``openpyxl`` writes a
small workbook to bytes, ``zipfile`` wraps it in the archive MERMAID answers
with, and respx serves that.  So the fixture stays legible, and the test says
exactly what the function is expected to unpack.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile

import httpx
import openpyxl
import pandas as pd
import pytest
import respx

import datamermaid
from conftest import global_url
from datamermaid.exceptions import AuthenticationError, MermaidAPIError, MermaidError
from datamermaid.reports import get_gfcr_report

PROJECT = "abc-123"
OTHER_PROJECT = "def-456"

REPORTS_URL = global_url("reports")

#: The workbook every test serves unless it needs something else: two sheets,
#: a header row and two data rows each.
SHEETS = {
    "F1": [["indicator", "value"], ["coral cover", 42], ["fish biomass", 7]],
    "F2": [["site", "year"], ["Reef A", 2021], ["Reef B", 2022]],
}


def workbook_bytes(sheets: dict[str, list[list]] | None = None) -> bytes:
    """Write ``{sheet_name: rows}`` to an in-memory xlsx and return its bytes."""
    book = openpyxl.Workbook()
    book.remove(book.active)  # the default "Sheet"
    for name, rows in (SHEETS if sheets is None else sheets).items():
        sheet = book.create_sheet(title=name)
        for row in rows:
            sheet.append(row)

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def zip_bytes(files: dict[str, bytes]) -> bytes:
    """Pack ``{filename: content}`` into a ZIP archive and return its bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def mock_report(content: bytes | None = None, *, status: int = 200) -> respx.Route:
    """Answer the reports endpoint with an archive holding one workbook."""
    if content is None:
        content = zip_bytes({"gfcr_report.xlsx": workbook_bytes()})
    return respx.post(REPORTS_URL).mock(return_value=httpx.Response(status, content=content))


def body_of(request) -> dict:
    """Parse the JSON body of a captured request."""
    return json.loads(request.read())


class TestRequestShape:
    @respx.mock
    def test_posts_to_the_reports_endpoint(self, auth_client):
        route = mock_report()

        get_gfcr_report(PROJECT, client=auth_client)

        assert route.called
        assert route.calls.last.request.method == "POST"
        assert route.calls.last.request.url.path == "/v1/reports/"

    @respx.mock
    def test_sends_the_report_type_and_project(self, auth_client):
        route = mock_report()

        get_gfcr_report(PROJECT, client=auth_client)

        assert body_of(route.calls.last.request) == {
            "report_type": "gfcr",
            "project_ids": [PROJECT],
            "background": "false",
        }

    @respx.mock
    def test_several_projects_go_in_one_request(self, auth_client):
        route = mock_report()

        get_gfcr_report([PROJECT, OTHER_PROJECT], client=auth_client)

        assert len(route.calls) == 1
        assert body_of(route.calls.last.request)["project_ids"] == [PROJECT, OTHER_PROJECT]

    @respx.mock
    def test_a_frame_of_projects_is_accepted(self, auth_client):
        route = mock_report()
        projects = pd.DataFrame({"id": [PROJECT, OTHER_PROJECT], "name": ["A", "B"]})

        get_gfcr_report(projects, client=auth_client)

        assert body_of(route.calls.last.request)["project_ids"] == [PROJECT, OTHER_PROJECT]

    @respx.mock
    def test_duplicate_projects_are_dropped(self, auth_client):
        route = mock_report()

        get_gfcr_report([PROJECT, OTHER_PROJECT, PROJECT], client=auth_client)

        assert body_of(route.calls.last.request)["project_ids"] == [PROJECT, OTHER_PROJECT]

    @respx.mock
    def test_sends_the_bearer_token(self, auth_client):
        route = mock_report()

        get_gfcr_report(PROJECT, client=auth_client)

        assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_does_not_ask_for_json_back(self, auth_client):
        """The body is an archive, which the JSON default would not satisfy."""
        route = mock_report()

        get_gfcr_report(PROJECT, client=auth_client)

        assert route.calls.last.request.headers["Accept"] == "*/*"

    @respx.mock
    def test_a_token_argument_is_used(self):
        route = mock_report()

        get_gfcr_report(PROJECT, token="passed-token")

        assert route.calls.last.request.headers["Authorization"] == "Bearer passed-token"

    @respx.mock
    def test_the_environment_token_is_used(self, client, monkeypatch):
        monkeypatch.setenv(datamermaid.TOKEN_ENV_VAR, "env-token")
        route = mock_report()

        get_gfcr_report(PROJECT, client=client)

        assert route.calls.last.request.headers["Authorization"] == "Bearer env-token"

    @respx.mock
    def test_uses_the_default_client_when_none_is_given(self, auth_client):
        datamermaid.set_default_client(auth_client)
        try:
            route = mock_report()
            datamermaid.get_gfcr_report(PROJECT)
        finally:
            datamermaid.set_default_client(None)

        assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_the_default_project_is_used(self, auth_client):
        route = mock_report()
        datamermaid.set_default_project([PROJECT, OTHER_PROJECT])

        get_gfcr_report(client=auth_client)

        assert body_of(route.calls.last.request)["project_ids"] == [PROJECT, OTHER_PROJECT]


class TestReturnedData:
    @respx.mock
    def test_returns_one_frame_per_sheet(self, auth_client):
        mock_report()

        report = get_gfcr_report(PROJECT, client=auth_client)

        assert list(report) == ["F1", "F2"]
        assert all(isinstance(frame, pd.DataFrame) for frame in report.values())

    @respx.mock
    def test_the_first_row_is_the_header(self, auth_client):
        mock_report()

        report = get_gfcr_report(PROJECT, client=auth_client)

        assert list(report["F1"].columns) == ["indicator", "value"]
        assert list(report["F2"].columns) == ["site", "year"]

    @respx.mock
    def test_cell_values_survive(self, auth_client):
        mock_report()

        report = get_gfcr_report(PROJECT, client=auth_client)

        assert list(report["F1"]["indicator"]) == ["coral cover", "fish biomass"]
        assert list(report["F1"]["value"]) == [42, 7]
        assert list(report["F2"]["year"]) == [2021, 2022]

    @respx.mock
    def test_an_empty_sheet_gives_an_empty_frame(self, auth_client):
        mock_report(zip_bytes({"r.xlsx": workbook_bytes({"F1": [], "F2": [["a"], [1]]})}))

        report = get_gfcr_report(PROJECT, client=auth_client)

        assert report["F1"].empty
        assert list(report["F2"]["a"]) == [1]

    @respx.mock
    def test_the_archive_may_hold_other_files_alongside_the_workbook(self, auth_client):
        mock_report(zip_bytes({"README.txt": b"generated by MERMAID", "r.xlsx": workbook_bytes()}))

        report = get_gfcr_report(PROJECT, client=auth_client)

        assert list(report) == ["F1", "F2"]


class TestSave:
    @respx.mock
    def test_writes_the_workbook(self, auth_client, tmp_path):
        expected = workbook_bytes()
        mock_report(zip_bytes({"gfcr_report.xlsx": expected}))
        destination = tmp_path / "gfcr.xlsx"

        get_gfcr_report(PROJECT, destination, client=auth_client)

        assert destination.read_bytes() == expected

    @respx.mock
    def test_the_saved_file_is_a_readable_workbook(self, auth_client, tmp_path):
        mock_report()
        destination = tmp_path / "gfcr.xlsx"

        get_gfcr_report(PROJECT, save=str(destination), client=auth_client)

        assert list(pd.read_excel(destination, sheet_name=None)) == ["F1", "F2"]

    @respx.mock
    def test_the_frames_are_returned_as_well(self, auth_client, tmp_path):
        mock_report()

        report = get_gfcr_report(PROJECT, tmp_path / "gfcr.xlsx", client=auth_client)

        assert list(report) == ["F1", "F2"]

    @respx.mock
    def test_xls_is_accepted_too(self, auth_client, tmp_path):
        mock_report()
        destination = tmp_path / "gfcr.XLS"

        get_gfcr_report(PROJECT, destination, client=auth_client)

        assert destination.exists()

    @respx.mock
    def test_nothing_is_written_when_save_is_omitted(self, auth_client, tmp_path):
        mock_report()

        get_gfcr_report(PROJECT, client=auth_client)

        assert list(tmp_path.iterdir()) == []

    @respx.mock
    @pytest.mark.parametrize("name", ["gfcr.csv", "gfcr", "gfcr.xlsx.zip", "gfcr.txt"])
    def test_a_non_excel_extension_raises_before_requesting(self, auth_client, name):
        route = mock_report()

        with pytest.raises(ValueError, match="`save`"):
            get_gfcr_report(PROJECT, name, client=auth_client)

        assert not route.called

    @respx.mock
    def test_a_missing_directory_raises_before_requesting(self, auth_client, tmp_path):
        route = mock_report()

        with pytest.raises(ValueError, match="does not exist"):
            get_gfcr_report(PROJECT, tmp_path / "nope" / "gfcr.xlsx", client=auth_client)

        assert not route.called

    @respx.mock
    def test_a_bare_filename_saves_beside_the_working_directory(
        self, auth_client, tmp_path, monkeypatch
    ):
        mock_report()
        monkeypatch.chdir(tmp_path)

        get_gfcr_report(PROJECT, "gfcr.xlsx", client=auth_client)

        assert (tmp_path / "gfcr.xlsx").exists()


class TestErrors:
    @respx.mock
    def test_no_project_and_no_default_raises_before_requesting(self, auth_client):
        route = mock_report()

        with pytest.raises(ValueError, match="No project given"):
            get_gfcr_report(client=auth_client)

        assert not route.called

    @respx.mock
    def test_a_missing_token_raises_before_requesting(self, client):
        route = mock_report()

        with pytest.raises(AuthenticationError, match="authenticate"):
            get_gfcr_report(PROJECT, client=client)

        assert not route.called

    @respx.mock
    def test_a_missing_openpyxl_raises_before_requesting(self, auth_client, monkeypatch):
        """``None`` in ``sys.modules`` is how the import machinery spells absent."""
        route = mock_report()
        monkeypatch.setitem(sys.modules, "openpyxl", None)

        with pytest.raises(ImportError, match=r"datamermaid\[excel\]"):
            get_gfcr_report(PROJECT, client=auth_client)

        assert not route.called

    @respx.mock
    def test_http_errors_surface_as_api_errors(self, auth_client):
        mock_report(b"nope", status=500)

        with pytest.raises(MermaidAPIError) as excinfo:
            get_gfcr_report(PROJECT, client=auth_client)

        assert excinfo.value.status_code == 500

    @respx.mock
    def test_a_rejected_token_raises_an_authentication_error(self, auth_client):
        mock_report(b"", status=401)

        with pytest.raises(AuthenticationError):
            get_gfcr_report(PROJECT, client=auth_client)

    @respx.mock
    def test_a_body_that_is_not_an_archive_raises(self, auth_client):
        mock_report(b'{"detail": "still generating"}')

        with pytest.raises(MermaidError, match="did not return a ZIP archive"):
            get_gfcr_report(PROJECT, client=auth_client)

    @respx.mock
    def test_an_empty_body_raises(self, auth_client):
        mock_report(b"")

        with pytest.raises(MermaidError, match="did not return a ZIP archive"):
            get_gfcr_report(PROJECT, client=auth_client)

    @respx.mock
    def test_an_archive_without_a_workbook_raises(self, auth_client):
        mock_report(zip_bytes({"report.csv": b"a,b\n1,2\n"}))

        with pytest.raises(MermaidError, match="found 0"):
            get_gfcr_report(PROJECT, client=auth_client)

    @respx.mock
    def test_an_empty_archive_raises(self, auth_client):
        mock_report(zip_bytes({}))

        with pytest.raises(MermaidError, match="found 0"):
            get_gfcr_report(PROJECT, client=auth_client)

    @respx.mock
    def test_an_archive_with_two_workbooks_raises(self, auth_client):
        mock_report(zip_bytes({"one.xlsx": workbook_bytes(), "two.xlsx": workbook_bytes()}))

        with pytest.raises(MermaidError, match="found 2"):
            get_gfcr_report(PROJECT, client=auth_client)

    @respx.mock
    def test_nothing_is_saved_when_the_response_is_malformed(self, auth_client, tmp_path):
        mock_report(b"not an archive")
        destination = tmp_path / "gfcr.xlsx"

        with pytest.raises(MermaidError):
            get_gfcr_report(PROJECT, destination, client=auth_client)

        assert not destination.exists()
