"""Tests for the MERMAID import (write) workflow.

Everything is respx-mocked, so no request ever leaves the machine.  The write
path gets particular attention on two points: the exact bytes and form fields
that go up, and the guards that must fire *before* any request is made.
"""

from __future__ import annotations

import json
import logging

import httpx
import pandas as pd
import pytest
import respx

import datamermaid
from conftest import (
    collect_records,
    collectrecords_url,
    edit_url,
    ingest_schema_url,
    ingest_url,
    multipart_fields,
    page,
    project_url,
    schema_field,
    template_url,
)
from datamermaid.exceptions import AuthenticationError, MermaidAPIError
from datamermaid.import_ import (
    METHOD_ENDPOINTS,
    import_bulk_edit,
    import_bulk_submit,
    import_bulk_validate,
    import_check_options,
    import_get_template_and_options,
    import_project_data,
)

PROJECT = "abc-123"
OTHER_PROJECT = "def-456"

TEMPLATE_CSV = "Site *,Management *,Reef slope,Sample unit notes\n"

SCHEMA = [
    schema_field("Site *", required=True, help_text="Name of the site"),
    schema_field("Management *", required=True),
    schema_field(
        "Reef slope",
        required=False,
        help_text="Slope of the reef",
        choices=["crest", "flat", "slope", "wall"],
    ),
    schema_field("Sample unit notes", required=False, choices=[]),
]


def mock_template(method: str = "fishbelt", *, body: str = TEMPLATE_CSV):
    return respx.get(template_url(method)).mock(return_value=httpx.Response(200, text=body))


def mock_options(method: str = "fishbelt", *, project: str = PROJECT, payload=None):
    return respx.get(ingest_schema_url(project, method)).mock(
        return_value=httpx.Response(200, json=SCHEMA if payload is None else payload)
    )


def fetch_options(client, method: str = "fishbelt") -> dict:
    """Fetch the options for a method with both endpoints mocked."""
    mock_template(method)
    mock_options(method)
    return import_get_template_and_options(PROJECT, method, client=client)[1]


class TestTemplateAndOptions:
    @respx.mock
    def test_the_template_comes_from_the_shared_csv_endpoint(self, auth_client):
        template_route = mock_template()
        mock_options()

        template, _ = import_get_template_and_options(PROJECT, "fishbelt", client=auth_client)

        assert template_route.called
        assert template_route.calls.last.request.url.path == "/v1/ingest_schema_csv/fishbelt/"
        assert list(template.columns) == [
            "Site *",
            "Management *",
            "Reef slope",
            "Sample unit notes",
        ]
        assert template.empty

    @respx.mock
    def test_the_options_come_from_the_project_ingest_schema(self, auth_client):
        mock_template()
        options_route = mock_options()

        import_get_template_and_options(PROJECT, "fishbelt", client=auth_client)

        assert options_route.calls.last.request.url.path == (
            f"/v1/projects/{PROJECT}/collectrecords/ingest_schema/fishbelt/"
        )

    @respx.mock
    def test_options_are_keyed_by_label_without_label_or_name(self, auth_client):
        options = fetch_options(auth_client)

        assert list(options) == ["Site *", "Management *", "Reef slope", "Sample unit notes"]
        assert "label" not in options["Site *"]
        assert "name" not in options["Site *"]
        assert options["Site *"]["required"] is True
        assert options["Site *"]["help_text"] == "Name of the site"

    @respx.mock
    def test_choices_are_flattened_to_strings(self, auth_client):
        options = fetch_options(auth_client)

        assert options["Reef slope"]["choices"] == ["crest", "flat", "slope", "wall"]

    @respx.mock
    def test_empty_choices_are_dropped(self, auth_client):
        options = fetch_options(auth_client)

        # No choices means "any value is allowed", which is not the same as an
        # empty list of allowed values.
        assert "choices" not in options["Sample unit notes"]
        assert "choices" not in options["Site *"]

    @respx.mock
    def test_choices_given_as_bare_strings_are_accepted(self, auth_client):
        mock_template()
        mock_options(
            payload=[
                {
                    "name": "reef_slope",
                    "label": "Reef slope",
                    "required": False,
                    "help_text": "",
                    "choices": ["crest", "wall"],
                }
            ]
        )

        _, options = import_get_template_and_options(PROJECT, "fishbelt", client=auth_client)

        assert options["Reef slope"]["choices"] == ["crest", "wall"]

    @respx.mock
    def test_bleaching_is_spelled_bleachingqc_on_the_wire(self, auth_client):
        template_route = mock_template("bleachingqc")
        options_route = mock_options("bleachingqc")

        import_get_template_and_options(PROJECT, "bleaching", client=auth_client)

        assert template_route.called
        assert options_route.called

    @respx.mock
    def test_the_template_is_fetched_with_a_token_when_one_is_available(self, auth_client):
        template_route = mock_template()
        mock_options()

        import_get_template_and_options(PROJECT, "fishbelt", client=auth_client)

        assert template_route.calls.last.request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_the_template_is_fetched_anonymously_when_no_token_can_be_found(self, client):
        template_route = mock_template()
        options_route = mock_options()

        with pytest.raises(AuthenticationError):
            import_get_template_and_options(PROJECT, "fishbelt", client=client)

        # The template endpoint is public, so it is still tried; the options
        # are project data and need a login, so that is where it stops.
        assert "Authorization" not in template_route.calls.last.request.headers
        assert not options_route.called

    def test_an_invalid_method_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_template()
            with pytest.raises(ValueError, match="`method` must be one of"):
                import_get_template_and_options(PROJECT, "fish", client=auth_client)
            assert not route.called

    def test_several_projects_raise_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_template()
            with pytest.raises(ValueError, match="one project at a time"):
                import_get_template_and_options(
                    [PROJECT, OTHER_PROJECT], "fishbelt", client=auth_client
                )
            assert not route.called

    def test_no_project_and_no_default_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_template()
            with pytest.raises(ValueError, match="no default project set"):
                import_get_template_and_options(client=auth_client)
            assert not route.called


@pytest.fixture
def options() -> dict:
    """Field options as :func:`import_get_template_and_options` returns them."""
    return {
        "Site *": {"required": True, "help_text": "", "choices": ["Nasue", "Namena"]},
        "Reef slope": {"required": False, "help_text": "", "choices": ["crest", "flat", "wall"]},
        "Sample unit notes": {"required": False, "help_text": ""},
        "Count *": {"required": True, "help_text": ""},
    }


class TestCheckOptions:
    def test_matching_values_are_reported_as_matches(self, options):
        data = pd.DataFrame({"Reef slope": ["crest", "wall"]})

        report = import_check_options(data, options, "Reef slope")

        assert list(report.columns) == ["data_value", "closest_choice", "match"]
        assert list(report["match"]) == [True, True]
        assert list(report["closest_choice"]) == ["crest", "wall"]

    def test_matching_is_case_insensitive_but_keeps_the_original_value(self, options):
        data = pd.DataFrame({"Reef slope": ["Crest"]})

        report = import_check_options(data, options, "Reef slope")

        assert report.loc[0, "data_value"] == "Crest"
        assert report.loc[0, "closest_choice"] == "crest"
        assert bool(report.loc[0, "match"]) is True

    def test_a_near_miss_reports_the_closest_choice(self, options):
        data = pd.DataFrame({"Reef slope": ["wal"]})

        report = import_check_options(data, options, "Reef slope")

        assert report.loc[0, "closest_choice"] == "wall"
        assert bool(report.loc[0, "match"]) is False

    def test_non_matches_come_first(self, options):
        data = pd.DataFrame({"Reef slope": ["crest", "wal", "flat"]})

        report = import_check_options(data, options, "Reef slope")

        assert list(report["data_value"]) == ["wal", "crest", "flat"]
        assert list(report["match"]) == [False, True, True]

    def test_repeated_values_are_reported_once(self, options):
        data = pd.DataFrame({"Reef slope": ["crest", "crest", "wal"]})

        report = import_check_options(data, options, "Reef slope")

        assert list(report["data_value"]) == ["wal", "crest"]

    def test_a_tie_goes_to_the_choice_mermaid_listed_first(self):
        # "toss" is one edit from both "tess" and "ross"; mermaidr's stable
        # sort keeps the first, so this one does too.
        options = {"F": {"required": False, "choices": ["tess", "ross"]}}
        data = pd.DataFrame({"F": ["toss"]})

        report = import_check_options(data, options, "F")

        assert report.loc[0, "closest_choice"] == "tess"

    def test_missing_values_are_left_out_of_the_report(self, options):
        data = pd.DataFrame({"Reef slope": ["crest", None]})

        report = import_check_options(data, options, "Reef slope")

        assert list(report["data_value"]) == ["crest"]

    def test_a_required_field_with_missing_values_reports_nothing_and_warns(self, options, caplog):
        data = pd.DataFrame({"Site *": ["Nasue", None]})

        with caplog.at_level(logging.WARNING, logger="datamermaid"):
            report = import_check_options(data, options, "Site *")

        assert report.empty
        assert list(report.columns) == ["data_value", "closest_choice", "match"]
        assert "required" in caplog.text

    def test_an_optional_field_that_is_entirely_missing_is_not_checked(self, options, caplog):
        data = pd.DataFrame({"Reef slope": [None, None]})

        with caplog.at_level(logging.INFO, logger="datamermaid"):
            report = import_check_options(data, options, "Reef slope")

        assert report.empty
        assert "missing" in caplog.text

    def test_a_field_without_choices_accepts_anything(self, options, caplog):
        data = pd.DataFrame({"Count *": [1, 2]})

        with caplog.at_level(logging.INFO, logger="datamermaid"):
            report = import_check_options(data, options, "Count *")

        assert report.empty
        assert "Any value is allowed" in caplog.text

    def test_non_string_values_are_compared_as_text(self, options):
        options = {"F": {"required": False, "choices": ["5", "10"]}}
        data = pd.DataFrame({"F": [5, 7]})

        report = import_check_options(data, options, "F")

        assert dict(zip(report["data_value"], report["match"], strict=True)) == {
            "5": True,
            "7": False,
        }

    def test_an_unknown_field_raises_naming_the_options(self, options):
        with pytest.raises(ValueError, match="does not exist in `options`") as excinfo:
            import_check_options(pd.DataFrame(), options, "Nope")

        assert "Reef slope" in str(excinfo.value)

    def test_template_is_not_a_field(self, options):
        with pytest.raises(ValueError, match="not a field to check"):
            import_check_options(pd.DataFrame(), options, "Template")

    def test_a_field_missing_from_the_data_raises(self, options):
        with pytest.raises(ValueError, match="does not exist in `data`"):
            import_check_options(pd.DataFrame({"Other": [1]}), options, "Reef slope")

    def test_options_without_required_raise(self):
        options = {"F": {"choices": ["a"]}}

        with pytest.raises(ValueError, match="`required` is missing"):
            import_check_options(pd.DataFrame({"F": ["a"]}), options, "F")


RECORDS = pd.DataFrame(
    {
        "Site *": ["Nasue", "Namena"],
        "Reef slope": ["crest", None],
        "Count *": [3, 4],
    }
)

#: What ``RECORDS`` must look like on the wire: missing values as empty fields,
#: not the string "NaN", since MERMAID ingests the literal text of each cell.
RECORDS_CSV = "Site *,Reef slope,Count *\nNasue,crest,3\nNamena,,4\n"


def mock_ingest(project: str = PROJECT, *, status: int = 200, json=None, text: str | None = None):
    kwargs = {"text": text} if text is not None else {"json": json if json is not None else {}}
    return respx.post(ingest_url(project)).mock(return_value=httpx.Response(status, **kwargs))


class TestImportProjectData:
    @respx.mock
    def test_records_are_posted_to_the_project_ingest_endpoint(self, auth_client):
        route = mock_ingest()

        import_project_data(RECORDS, PROJECT, "fishbelt", client=auth_client)

        assert route.called
        request = route.calls.last.request
        assert request.url.path == f"/v1/projects/{PROJECT}/collectrecords/ingest/"
        assert request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_the_csv_is_uploaded_with_missing_values_as_empty_fields(self, auth_client):
        route = mock_ingest()

        import_project_data(RECORDS, PROJECT, client=auth_client)

        fields = multipart_fields(route.calls.last.request)
        assert fields["file"].replace("\r\n", "\n") == RECORDS_CSV

    @respx.mock
    def test_the_protocol_is_sent_alongside_the_file(self, auth_client):
        route = mock_ingest()

        import_project_data(RECORDS, PROJECT, "benthicpit", client=auth_client)

        assert multipart_fields(route.calls.last.request)["protocol"] == "benthicpit"

    @respx.mock
    def test_bleaching_is_sent_as_bleachingqc(self, auth_client):
        route = mock_ingest()

        import_project_data(RECORDS, PROJECT, "bleaching", client=auth_client)

        assert multipart_fields(route.calls.last.request)["protocol"] == "bleachingqc"

    @respx.mock
    def test_it_dry_runs_by_default(self, auth_client):
        route = mock_ingest()

        import_project_data(RECORDS, PROJECT, client=auth_client)

        assert multipart_fields(route.calls.last.request)["dryrun"] == "true"

    @respx.mock
    def test_dryrun_false_omits_the_flag_so_records_are_saved(self, auth_client):
        route = mock_ingest()

        import_project_data(RECORDS, PROJECT, dryrun=False, client=auth_client)

        assert "dryrun" not in multipart_fields(route.calls.last.request)

    @respx.mock
    def test_a_successful_dry_run_returns_nothing_and_says_what_to_do_next(
        self, auth_client, caplog
    ):
        mock_ingest()

        with caplog.at_level(logging.INFO, logger="datamermaid"):
            result = import_project_data(RECORDS, PROJECT, client=auth_client)

        assert result is None
        assert "dryrun=False" in caplog.text

    @respx.mock
    def test_a_successful_import_returns_nothing(self, auth_client, caplog):
        mock_ingest()

        with caplog.at_level(logging.INFO, logger="datamermaid"):
            result = import_project_data(RECORDS, PROJECT, dryrun=False, client=auth_client)

        assert result is None
        assert "imported successfully" in caplog.text

    @respx.mock
    def test_a_csv_file_can_be_imported_instead_of_a_frame(self, auth_client, tmp_path):
        path = tmp_path / "records.csv"
        RECORDS.to_csv(path, index=False, na_rep="")
        route = mock_ingest()

        import_project_data(path, PROJECT, client=auth_client)

        fields = multipart_fields(route.calls.last.request)
        assert fields["file"].replace("\r\n", "\n") == RECORDS_CSV

    @respx.mock
    def test_whole_numbers_beside_a_blank_keep_their_integer_spelling(self, auth_client):
        route = mock_ingest()

        import_project_data(
            pd.DataFrame({"Count *": [3, None], "Depth *": [1.5, None]}),
            PROJECT,
            client=auth_client,
        )

        fields = multipart_fields(route.calls.last.request)
        assert fields["file"].replace("\r\n", "\n") == "Count *,Depth *\n3,1.5\n,\n"

    @respx.mock
    def test_a_csv_file_is_uploaded_without_reinterpreting_its_values(self, auth_client, tmp_path):
        path = tmp_path / "records.csv"
        path.write_text("Site *,Count *\nNA,007\n")
        route = mock_ingest()

        import_project_data(path, PROJECT, client=auth_client)

        fields = multipart_fields(route.calls.last.request)
        assert fields["file"].replace("\r\n", "\n") == "Site *,Count *\nNA,007\n"

    @respx.mock
    def test_the_default_project_is_used_when_none_is_given(self, auth_client):
        datamermaid.set_default_project(PROJECT)
        route = mock_ingest()

        import_project_data(RECORDS, client=auth_client)

        assert route.called


class TestImportSafety:
    """Nothing may reach the API without an explicit, non-default argument."""

    def test_clearexisting_with_a_dry_run_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_ingest()
            with pytest.raises(ValueError, match="contradict each other"):
                import_project_data(RECORDS, PROJECT, clearexisting=True, client=auth_client)
            assert not route.called

    def test_clearexisting_without_confirmation_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_ingest()
            with pytest.raises(ValueError, match="clearexisting_confirm=True"):
                import_project_data(
                    RECORDS, PROJECT, dryrun=False, clearexisting=True, client=auth_client
                )
            assert not route.called

    @respx.mock
    def test_a_confirmed_clearexisting_is_sent(self, auth_client):
        route = mock_ingest()

        import_project_data(
            RECORDS,
            PROJECT,
            dryrun=False,
            clearexisting=True,
            clearexisting_confirm=True,
            client=auth_client,
        )

        fields = multipart_fields(route.calls.last.request)
        assert fields["clearexisting"] == "true"
        assert "dryrun" not in fields

    def test_an_invalid_method_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_ingest()
            with pytest.raises(ValueError, match="`method` must be one of"):
                import_project_data(RECORDS, PROJECT, "fish", client=auth_client)
            assert not route.called

    def test_several_projects_raise_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_ingest()
            with pytest.raises(ValueError, match="one project at a time"):
                import_project_data(RECORDS, [PROJECT, OTHER_PROJECT], client=auth_client)
            assert not route.called

    @pytest.mark.parametrize("data", [{"a": 1}, ["a"], 3, None])
    def test_unusable_data_raises_before_any_request(self, auth_client, data):
        with respx.mock:
            route = mock_ingest()
            with pytest.raises(ValueError, match="DataFrame or the path"):
                import_project_data(data, PROJECT, client=auth_client)
            assert not route.called

    def test_a_missing_file_raises_before_any_request(self, auth_client, tmp_path):
        with respx.mock:
            route = mock_ingest()
            with pytest.raises(ValueError, match="DataFrame or the path"):
                import_project_data(str(tmp_path / "nope.csv"), PROJECT, client=auth_client)
            assert not route.called

    def test_no_token_raises_before_any_request(self, client):
        with respx.mock:
            route = mock_ingest()
            with pytest.raises(AuthenticationError, match="authenticate"):
                import_project_data(RECORDS, PROJECT, client=client)
            assert not route.called


class TestImportErrors:
    @respx.mock
    def test_row_problems_come_back_as_a_frame_with_a_warning(self, auth_client, caplog):
        mock_ingest(
            status=400,
            json=[
                {
                    "$row_number": 2,
                    "data": {"Site *": {"status": "error", "message": "Site not found"}},
                },
                {
                    "$row_number": 3,
                    "data": {"Site *": {"status": "ok"}},
                },
            ],
        )

        with caplog.at_level(logging.WARNING, logger="datamermaid"):
            problems = import_project_data(RECORDS, PROJECT, client=auth_client)

        assert isinstance(problems, pd.DataFrame)
        # The API counts the header as row 1; the report counts data rows.
        assert list(problems["row_number"]) == [1, 2]
        assert problems.columns[0] == "row_number"
        assert "Site not found" in problems.loc[0, "data"]
        assert "problems" in caplog.text

    @respx.mock
    def test_missing_required_fields_raise(self, auth_client):
        mock_ingest(status=400, text="Missing required fields: Site *")

        with pytest.raises(MermaidAPIError, match="Missing required fields"):
            import_project_data(RECORDS, PROJECT, client=auth_client)

    @respx.mock
    def test_an_unknown_project_raises_naming_it(self, auth_client):
        mock_ingest(status=404, text='{"detail": "Not Found"}')

        with pytest.raises(MermaidAPIError, match="is not a valid project ID") as excinfo:
            import_project_data(RECORDS, PROJECT, client=auth_client)

        assert PROJECT in str(excinfo.value)

    @respx.mock
    def test_a_permission_problem_surfaces_the_api_detail(self, auth_client):
        mock_ingest(
            status=400,
            json={"detail": "You do not have permission to perform this action."},
        )

        with pytest.raises(MermaidAPIError, match="do not have permission"):
            import_project_data(RECORDS, PROJECT, client=auth_client)

    @respx.mock
    def test_a_timeout_suggests_splitting_the_data(self, auth_client):
        mock_ingest(status=504, text="Gateway Timeout")

        with pytest.raises(MermaidAPIError, match="Split it up") as excinfo:
            import_project_data(RECORDS, PROJECT, client=auth_client)

        assert excinfo.value.status_code == 504

    @respx.mock
    def test_a_rejected_token_raises_an_authentication_error(self, auth_client):
        mock_ingest(status=401)

        with pytest.raises(AuthenticationError):
            import_project_data(RECORDS, PROJECT, client=auth_client)

    @respx.mock
    def test_an_unrecognised_error_body_raises(self, auth_client):
        mock_ingest(status=500, text="Internal Server Error")

        with pytest.raises(MermaidAPIError, match="Failed to import data"):
            import_project_data(RECORDS, PROJECT, client=auth_client)


def mock_collectrecords(*statuses, project: str = PROJECT):
    return respx.get(collectrecords_url(project)).mock(
        return_value=httpx.Response(200, json=page(collect_records(*statuses)))
    )


def mock_action(action: str, payload, *, project: str = PROJECT, status: int = 200):
    return respx.post(collectrecords_url(project, action)).mock(
        return_value=httpx.Response(status, json=payload)
    )


def counts(summary: pd.DataFrame) -> dict[str, int]:
    return dict(zip(summary["status"], summary["n"], strict=True))


class TestBulkValidate:
    @respx.mock
    def test_records_are_validated_in_batches_of_three(self, auth_client):
        mock_collectrecords(None, None, None, None)
        route = mock_action(
            "validate",
            {f"record-{i}": {"status": "ok"} for i in range(3)},
        )

        import_bulk_validate(PROJECT, client=auth_client)

        assert route.call_count == 2
        assert route.calls[0].request.url.path == f"/v1/projects/{PROJECT}/collectrecords/validate/"
        assert json.loads(route.calls[0].request.content) == {
            "ids": ["record-0", "record-1", "record-2"]
        }
        assert json.loads(route.calls[1].request.content) == {"ids": ["record-3"]}

    @respx.mock
    def test_the_statuses_are_summarised(self, auth_client):
        mock_collectrecords(None, None, None)
        mock_action(
            "validate",
            {
                "record-0": {"status": "ok"},
                "record-1": {"status": "warning"},
                "record-2": {"status": "error"},
            },
        )

        summary = import_bulk_validate(PROJECT, client=auth_client)

        assert list(summary.columns) == ["status", "n"]
        assert counts(summary) == {"error": 1, "warning": 1, "ok": 1}

    @respx.mock
    def test_statuses_that_did_not_occur_are_reported_as_zero(self, auth_client):
        mock_collectrecords(None)
        mock_action("validate", {"record-0": {"status": "ok"}})

        summary = import_bulk_validate(PROJECT, client=auth_client)

        assert counts(summary) == {"error": 0, "warning": 0, "ok": 1}

    @respx.mock
    def test_a_project_with_nothing_to_validate_makes_no_write_request(self, auth_client, caplog):
        respx.get(collectrecords_url(PROJECT)).mock(return_value=httpx.Response(200, json=page([])))
        route = mock_action("validate", {})

        with caplog.at_level(logging.INFO, logger="datamermaid"):
            summary = import_bulk_validate(PROJECT, client=auth_client)

        assert not route.called
        assert counts(summary) == {"error": 0, "warning": 0, "ok": 0}
        assert "No records in Collecting to validate." in caplog.text

    @respx.mock
    def test_a_failed_validation_request_raises(self, auth_client):
        mock_collectrecords(None)
        mock_action("validate", {}, status=500)

        with pytest.raises(MermaidAPIError):
            import_bulk_validate(PROJECT, client=auth_client)

    @respx.mock
    def test_a_body_that_is_not_json_counts_as_a_failure(self, auth_client):
        mock_collectrecords(None)
        respx.post(collectrecords_url(PROJECT, "validate")).mock(
            return_value=httpx.Response(200, text="")
        )

        summary = import_bulk_validate(PROJECT, client=auth_client)

        assert counts(summary) == {"error": 0, "warning": 0, "ok": 0, "not_ok": 1}

    def test_no_token_raises_before_any_request(self, client):
        with respx.mock:
            route = mock_collectrecords(None)
            with pytest.raises(AuthenticationError, match="authenticate"):
                import_bulk_validate(PROJECT, client=client)
            assert not route.called


class TestBulkSubmit:
    def test_it_refuses_without_confirmation(self, auth_client):
        with respx.mock:
            route = mock_collectrecords("ok")
            with pytest.raises(ValueError, match="confirm=True"):
                import_bulk_submit(PROJECT, client=auth_client)
            assert not route.called

    @respx.mock
    def test_only_cleanly_validated_records_are_submitted_one_at_a_time(self, auth_client):
        mock_collectrecords("ok", "warning", "error", "ok", None)
        route = mock_action("submit", {"record-0": {"status": "ok"}})

        import_bulk_submit(PROJECT, confirm=True, client=auth_client)

        submitted = [json.loads(call.request.content)["ids"] for call in route.calls]
        assert submitted == [["record-0"], ["record-3"]]

    @respx.mock
    def test_a_non_ok_status_is_counted_as_a_failure(self, auth_client):
        mock_collectrecords("ok")
        mock_action("submit", {"record-0": {"status": "error"}})

        summary = import_bulk_submit(PROJECT, confirm=True, client=auth_client)

        assert counts(summary) == {"ok": 0, "not_ok": 1}

    @respx.mock
    def test_a_failed_submit_request_is_counted_rather_than_raised(self, auth_client):
        mock_collectrecords("ok", "ok")
        respx.post(collectrecords_url(PROJECT, "submit")).mock(
            side_effect=[
                httpx.Response(200, json={"record-0": {"status": "ok"}}),
                httpx.Response(500, json={}),
            ]
        )

        summary = import_bulk_submit(PROJECT, confirm=True, client=auth_client)

        assert counts(summary) == {"ok": 1, "not_ok": 1}

    @respx.mock
    def test_nothing_valid_to_submit_makes_no_write_request(self, auth_client, caplog):
        mock_collectrecords("error", "warning")
        route = mock_action("submit", {})

        with caplog.at_level(logging.INFO, logger="datamermaid"):
            summary = import_bulk_submit(PROJECT, confirm=True, client=auth_client)

        assert not route.called
        assert counts(summary) == {"ok": 0, "not_ok": 0}
        assert "import_bulk_validate()" in caplog.text


SUBMITTED_URL = project_url(PROJECT, METHOD_ENDPOINTS["fishbelt"])


def mock_submitted(*record_ids: str):
    records = [{"id": record_id} for record_id in record_ids]
    return respx.get(SUBMITTED_URL).mock(return_value=httpx.Response(200, json=page(records)))


class TestBulkEdit:
    def test_it_refuses_without_confirmation(self, auth_client):
        with respx.mock:
            route = mock_submitted("su-1")
            with pytest.raises(ValueError, match="confirm=True"):
                import_bulk_edit(PROJECT, "fishbelt", client=auth_client)
            assert not route.called

    @pytest.mark.parametrize("method", [None, "fish", "all", ["fishbelt"]])
    def test_an_invalid_method_raises_before_any_request(self, auth_client, method):
        with respx.mock:
            route = mock_submitted("su-1")
            with pytest.raises(ValueError, match="`method` must be one of"):
                import_bulk_edit(PROJECT, method, confirm=True, client=auth_client)
            assert not route.called

    @respx.mock
    def test_each_submitted_record_is_put_back_to_collecting(self, auth_client):
        mock_submitted("su-1", "su-2")
        first = respx.put(edit_url(PROJECT, METHOD_ENDPOINTS["fishbelt"], "su-1")).mock(
            return_value=httpx.Response(200, json={"id": "new-1"})
        )
        second = respx.put(edit_url(PROJECT, METHOD_ENDPOINTS["fishbelt"], "su-2")).mock(
            return_value=httpx.Response(200, json={"id": "new-2"})
        )
        respx.get(collectrecords_url(PROJECT)).mock(
            return_value=httpx.Response(200, json=page([{"id": "new-1"}, {"id": "new-2"}]))
        )

        summary = import_bulk_edit(PROJECT, "fishbelt", confirm=True, client=auth_client)

        assert first.called and second.called
        assert counts(summary) == {"ok": 2, "not_ok": 0}

    @respx.mock
    def test_a_record_that_did_not_reach_collecting_counts_as_a_failure(self, auth_client):
        mock_submitted("su-1", "su-2")
        respx.put(edit_url(PROJECT, METHOD_ENDPOINTS["fishbelt"], "su-1")).mock(
            return_value=httpx.Response(200, json={"id": "new-1"})
        )
        respx.put(edit_url(PROJECT, METHOD_ENDPOINTS["fishbelt"], "su-2")).mock(
            return_value=httpx.Response(500, json={})
        )
        respx.get(collectrecords_url(PROJECT)).mock(
            return_value=httpx.Response(200, json=page([{"id": "new-1"}]))
        )

        summary = import_bulk_edit(PROJECT, "fishbelt", confirm=True, client=auth_client)

        assert counts(summary) == {"ok": 1, "not_ok": 1}

    @respx.mock
    def test_the_method_chooses_the_endpoint(self, auth_client):
        endpoint = METHOD_ENDPOINTS["bleaching"]
        route = respx.get(project_url(PROJECT, endpoint)).mock(
            return_value=httpx.Response(200, json=page([]))
        )

        import_bulk_edit(PROJECT, "bleaching", confirm=True, client=auth_client)

        assert route.called

    @respx.mock
    def test_nothing_submitted_makes_no_write_request(self, auth_client, caplog):
        mock_submitted()
        route = respx.put(edit_url(PROJECT, METHOD_ENDPOINTS["fishbelt"], "su-1")).mock(
            return_value=httpx.Response(200, json={"id": "new-1"})
        )

        with caplog.at_level(logging.INFO, logger="datamermaid"):
            summary = import_bulk_edit(PROJECT, "fishbelt", confirm=True, client=auth_client)

        assert not route.called
        assert counts(summary) == {"ok": 0, "not_ok": 0}
        assert "No submitted records to edit." in caplog.text
