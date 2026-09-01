"""Tests for project id coercion, the default project, and project endpoints."""

from __future__ import annotations

import os

import httpx
import pandas as pd
import pytest
import respx

import datamermaid
from conftest import managements, page, project_url, query_of, sites
from datamermaid.auth import TOKEN_ENV_VAR
from datamermaid.exceptions import AuthenticationError, MermaidError
from datamermaid.project_endpoints import (
    DEFAULT_PROJECT_ENV_VAR,
    MANAGEMENT_COLUMNS,
    SITE_COLUMNS,
    as_project_ids,
    get_default_project,
    get_project_endpoint,
    get_project_managements,
    get_project_sites,
    set_default_project,
)


class TestAsProjectIds:
    def test_a_single_id(self):
        assert as_project_ids("p1") == ["p1"]

    def test_surrounding_whitespace_is_trimmed(self):
        assert as_project_ids(" p1 ") == ["p1"]

    def test_a_list_of_ids(self):
        assert as_project_ids(["p1", "p2"]) == ["p1", "p2"]

    def test_a_tuple_of_ids(self):
        assert as_project_ids(("p1", "p2")) == ["p1", "p2"]

    def test_a_project_record(self):
        assert as_project_ids({"id": "p1", "name": "Project 1"}) == ["p1"]

    def test_a_list_of_project_records(self):
        assert as_project_ids([{"id": "p1"}, {"id": "p2"}]) == ["p1", "p2"]

    def test_a_data_frame_of_projects(self):
        df = pd.DataFrame({"id": ["p1", "p2"], "name": ["One", "Two"]})

        assert as_project_ids(df) == ["p1", "p2"]

    def test_a_series_of_ids(self):
        assert as_project_ids(pd.Series(["p1", "p2"])) == ["p1", "p2"]

    def test_a_project_row(self):
        """Taking a row's `id` beats iterating it, which would read every field."""
        df = pd.DataFrame({"id": ["p1"], "name": ["Kubulau"]})

        assert as_project_ids(df.iloc[0]) == ["p1"]

    def test_an_id_column(self):
        df = pd.DataFrame({"id": ["p1", "p2"], "name": ["One", "Two"]})

        assert as_project_ids(df["id"]) == ["p1", "p2"]

    def test_the_output_of_get_projects(self, client):
        with respx.mock:
            from conftest import PROJECTS_URL, projects

            respx.get(PROJECTS_URL).mock(
                return_value=httpx.Response(200, json=page(projects(2), count=2))
            )
            df = datamermaid.get_projects(client=client)

        assert as_project_ids(df) == ["project-0", "project-1"]

    def test_duplicates_are_dropped_in_order(self):
        assert as_project_ids(["p2", "p1", "p2"]) == ["p2", "p1"]

    def test_missing_ids_in_a_frame_are_skipped(self):
        df = pd.DataFrame({"id": ["p1", None]})

        assert as_project_ids(df) == ["p1"]

    def test_a_frame_without_an_id_column_raises(self):
        df = pd.DataFrame({"name": ["One"]})

        with pytest.raises(ValueError, match="no `id` column"):
            as_project_ids(df)

    def test_an_empty_frame_raises(self):
        with pytest.raises(ValueError, match="no project id"):
            as_project_ids(pd.DataFrame(columns=["id"]))

    def test_a_record_without_an_id_raises(self):
        with pytest.raises(ValueError, match="no `id` key"):
            as_project_ids({"name": "One"})

    @pytest.mark.parametrize("value", [[], "", "   ", [None]])
    def test_empty_inputs_raise(self, value):
        with pytest.raises(ValueError, match="no project id"):
            as_project_ids(value)

    @pytest.mark.parametrize("value", [None, 3, b"p1", 4.5])
    def test_unsupported_types_raise(self, value):
        with pytest.raises(ValueError, match="`project` must be"):
            as_project_ids(value)


class TestDefaultProject:
    def test_unset_by_default(self):
        assert get_default_project() is None

    def test_round_trips(self):
        set_default_project("p1")

        assert get_default_project() == ["p1"]

    def test_accepts_every_project_shape(self):
        set_default_project(pd.DataFrame({"id": ["p1", "p2"]}))

        assert get_default_project() == ["p1", "p2"]

    def test_is_exported_to_the_environment(self):
        set_default_project(["p1", "p2"])

        assert os.environ[DEFAULT_PROJECT_ENV_VAR] == "p1,p2"

    def test_can_be_cleared(self):
        set_default_project("p1")
        set_default_project(None)

        assert get_default_project() is None
        assert DEFAULT_PROJECT_ENV_VAR not in os.environ

    def test_falls_back_to_the_environment(self, monkeypatch):
        monkeypatch.setenv(DEFAULT_PROJECT_ENV_VAR, " p1 , p2 ")

        assert get_default_project() == ["p1", "p2"]

    def test_an_empty_environment_variable_is_ignored(self, monkeypatch):
        monkeypatch.setenv(DEFAULT_PROJECT_ENV_VAR, "  ")

        assert get_default_project() is None

    def test_a_set_default_wins_over_the_environment(self, monkeypatch):
        monkeypatch.setenv(DEFAULT_PROJECT_ENV_VAR, "from-env")
        set_default_project("from-call")

        assert get_default_project() == ["from-call"]

    def test_an_invalid_default_raises(self):
        with pytest.raises(ValueError):
            set_default_project(pd.DataFrame({"name": ["One"]}))

    @respx.mock
    def test_project_functions_use_the_default(self, auth_client):
        set_default_project("p1")
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        df = get_project_sites(client=auth_client)

        assert route.called
        assert list(df["project"]) == ["p1"]

    @respx.mock
    def test_the_environment_default_is_used(self, monkeypatch, auth_client):
        monkeypatch.setenv(DEFAULT_PROJECT_ENV_VAR, "p9")
        route = respx.get(project_url("p9", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        get_project_sites(client=auth_client)

        assert route.called

    def test_an_unset_default_raises_a_clear_error(self, auth_client):
        with respx.mock:
            route = respx.get(project_url("p1", "sites")).mock(
                return_value=httpx.Response(200, json=page([]))
            )
            with pytest.raises(ValueError, match="no default project set"):
                get_project_sites(client=auth_client)
            assert not route.called

    def test_the_error_names_how_to_set_a_default(self, auth_client):
        with pytest.raises(ValueError) as excinfo:
            get_project_sites(client=auth_client)

        message = str(excinfo.value)
        assert "set_default_project" in message
        assert DEFAULT_PROJECT_ENV_VAR in message


class TestRequestShape:
    @respx.mock
    def test_sites_hits_the_project_sites_endpoint(self, auth_client):
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(2)))
        )

        get_project_sites("p1", client=auth_client)

        request = route.calls.last.request
        assert request.url.path == "/v1/projects/p1/sites/"
        assert request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_managements_hits_the_project_managements_endpoint(self, auth_client):
        route = respx.get(project_url("p1", "managements")).mock(
            return_value=httpx.Response(200, json=page(managements(2)))
        )

        get_project_managements("p1", client=auth_client)

        request = route.calls.last.request
        assert request.url.path == "/v1/projects/p1/managements/"
        assert request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_limit_is_forwarded_per_project(self, auth_client):
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(3), count=3))
        )

        df = get_project_sites("p1", limit=2, client=auth_client)

        assert query_of(route.calls.last.request)["limit"] == ["2"]
        assert len(df) == 2

    def test_an_invalid_limit_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = respx.get(project_url("p1", "sites")).mock(
                return_value=httpx.Response(200, json=page([]))
            )
            with pytest.raises(ValueError, match="positive integer"):
                get_project_sites("p1", limit=0, client=auth_client)
            assert not route.called

    @respx.mock
    def test_extra_filters_become_query_parameters(self, auth_client):
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        get_project_endpoint("p1", "sites", client=auth_client, country="Fiji", reef_type=None)

        query = query_of(route.calls.last.request)
        assert query["country"] == ["Fiji"]
        assert "reef_type" not in query

    @respx.mock
    def test_a_token_builds_an_authenticated_client(self):
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        get_project_sites("p1", token="from-token")

        assert route.calls.last.request.headers["Authorization"] == "Bearer from-token"

    def test_client_and_token_are_mutually_exclusive(self, auth_client):
        with pytest.raises(ValueError, match="not both"):
            get_project_sites("p1", client=auth_client, token="t")

    @respx.mock
    def test_the_default_client_is_used_when_none_is_given(self, auth_client):
        datamermaid.set_default_client(auth_client)
        try:
            respx.get(project_url("p1", "sites")).mock(
                return_value=httpx.Response(200, json=page(sites(2)))
            )
            assert len(get_project_sites("p1")) == 2
        finally:
            datamermaid.set_default_client(None)

    @respx.mock
    def test_pagination_is_followed(self, auth_client):
        url = project_url("p1", "sites")
        respx.get(url, params={"offset": "2"}).mock(
            return_value=httpx.Response(200, json=page(sites(2, 2), count=4))
        )
        respx.get(url).mock(
            return_value=httpx.Response(
                200, json=page(sites(2), next_url=url + "?limit=5000&offset=2", count=4)
            )
        )

        df = get_project_sites("p1", client=auth_client)

        assert list(df["id"]) == [f"site-{i}" for i in range(4)]


class TestAuthentication:
    def test_no_resolvable_token_raises_without_requesting(self, client):
        with respx.mock:
            route = respx.get(project_url("p1", "sites")).mock(
                return_value=httpx.Response(200, json=page(sites(1)))
            )
            with pytest.raises(AuthenticationError) as excinfo:
                get_project_sites("p1", client=client)
            assert not route.called

        assert isinstance(excinfo.value, MermaidError)
        message = str(excinfo.value)
        assert "datamermaid.authenticate()" in message
        assert TOKEN_ENV_VAR in message

    def test_the_generic_getter_also_requires_a_token(self, client):
        with pytest.raises(AuthenticationError):
            get_project_endpoint("p1", "beltfishes/obstransectbeltfishes", client=client)

    @respx.mock
    def test_the_environment_token_is_used(self, monkeypatch):
        """A signed-in user needs no `token=`; the client resolves it."""
        monkeypatch.setenv(TOKEN_ENV_VAR, "env-token")
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        assert len(get_project_sites("p1")) == 1
        assert route.calls.last.request.headers["Authorization"] == "Bearer env-token"

    @respx.mock
    def test_the_cached_token_is_used(self, write_cached_token):
        write_cached_token("cached-token")
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        get_project_sites("p1")

        assert route.calls.last.request.headers["Authorization"] == "Bearer cached-token"

    @respx.mock
    def test_a_rejected_cached_token_is_discarded(self, write_cached_token, token_cache_path):
        write_cached_token("cached-token")
        respx.get(project_url("p1", "sites")).mock(return_value=httpx.Response(401))

        with pytest.raises(AuthenticationError, match="authenticate"):
            get_project_sites("p1")

        assert not token_cache_path.exists()

    @respx.mock
    def test_an_explicit_token_wins_over_the_environment(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV_VAR, "env-token")
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        get_project_sites("p1", token="explicit-token")

        assert route.calls.last.request.headers["Authorization"] == "Bearer explicit-token"

    def test_client_and_token_together_are_rejected(self, auth_client):
        with pytest.raises(ValueError, match="not both"):
            get_project_sites("p1", client=auth_client, token="t")


class TestResult:
    @respx.mock
    def test_sites_are_returned_with_the_documented_columns(self, auth_client):
        respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(2)))
        )

        df = get_project_sites("p1", client=auth_client)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert list(df.columns) == ["project"] + [c for c in SITE_COLUMNS if c in set(df.columns)]

    @respx.mock
    def test_managements_are_returned_with_the_documented_columns(self, auth_client):
        respx.get(project_url("p1", "managements")).mock(
            return_value=httpx.Response(200, json=page(managements(1)))
        )

        df = get_project_managements("p1", client=auth_client)

        assert df.columns[0] == "project"
        assert list(df.columns) == ["project"] + [
            c for c in MANAGEMENT_COLUMNS if c in set(df.columns)
        ]
        assert df.loc[0, "parties"] == "community"

    @respx.mock
    def test_the_project_column_holds_the_requested_id(self, auth_client):
        # The payload carries its own `project` field; the requested id wins.
        respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(2)))
        )

        df = get_project_sites("p1", client=auth_client)

        assert list(df["project"]) == ["p1", "p1"]
        assert (df["project"] != "project-from-payload").all()

    @respx.mock
    def test_multiple_projects_are_concatenated_and_labelled(self, auth_client):
        first = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(2), count=2))
        )
        second = respx.get(project_url("p2", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1, 2), count=1))
        )

        df = get_project_sites(["p1", "p2"], client=auth_client)

        assert first.call_count == 1
        assert second.call_count == 1
        assert len(df) == 3
        assert list(df["project"]) == ["p1", "p1", "p2"]
        assert list(df["id"]) == ["site-0", "site-1", "site-2"]
        assert list(df.index) == [0, 1, 2]

    @respx.mock
    def test_a_frame_of_projects_queries_each_one(self, auth_client):
        first = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )
        second = respx.get(project_url("p2", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1, 1)))
        )

        df = get_project_sites(
            pd.DataFrame({"id": ["p1", "p2"], "name": ["One", "Two"]}), client=auth_client
        )

        assert first.called and second.called
        assert list(df["project"]) == ["p1", "p2"]

    @respx.mock
    def test_a_duplicated_project_is_requested_once(self, auth_client):
        route = respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        df = get_project_sites(["p1", "p1"], client=auth_client)

        assert route.call_count == 1
        assert len(df) == 1

    @respx.mock
    def test_an_empty_result_keeps_the_columns(self, auth_client):
        respx.get(project_url("p1", "sites")).mock(return_value=httpx.Response(200, json=page([])))

        df = get_project_sites("p1", client=auth_client)

        assert df.empty
        assert list(df.columns) == ["project", *SITE_COLUMNS]

    @respx.mock
    def test_projects_without_records_do_not_add_rows(self, auth_client):
        respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )
        respx.get(project_url("p2", "sites")).mock(return_value=httpx.Response(200, json=page([])))

        df = get_project_sites(["p1", "p2"], client=auth_client)

        assert list(df["project"]) == ["p1"]

    @respx.mock
    def test_the_generic_getter_keeps_every_column_by_default(self, auth_client):
        respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(200, json=page(sites(1)))
        )

        df = get_project_endpoint("p1", "sites", client=auth_client)

        assert df.columns[0] == "project"
        assert {"id", "name", "country", "reef_zone"} <= set(df.columns)

    @respx.mock
    def test_differing_field_subsets_keep_the_documented_column_order(self, auth_client):
        # p2 omits `reef_type`, so concatenating orders columns by first
        # appearance unless the result is put back into SITE_COLUMNS order.
        respx.get(project_url("p1", "sites")).mock(
            return_value=httpx.Response(
                200, json=page([{"id": "site-0", "name": "Site 0", "reef_type": "fringing"}])
            )
        )
        respx.get(project_url("p2", "sites")).mock(
            return_value=httpx.Response(
                200, json=page([{"id": "site-1", "name": "Site 1", "country": "Fiji"}])
            )
        )

        df = get_project_sites(["p1", "p2"], client=auth_client)

        assert list(df.columns) == ["project", "id", "name", "country", "reef_type"]
        assert pd.isna(df.loc[0, "country"])


class TestProjectIdValidation:
    @pytest.mark.parametrize("value", ["../../danger", "p1/sites", "/p1"])
    def test_an_id_containing_a_slash_raises(self, value):
        with pytest.raises(ValueError, match="cannot contain"):
            as_project_ids(value)

    def test_a_traversing_id_makes_no_request(self, auth_client):
        with respx.mock:
            route = respx.get(url__regex=r".*").mock(
                return_value=httpx.Response(200, json=page([]))
            )
            with pytest.raises(ValueError, match="cannot contain"):
                get_project_endpoint("../../danger", "sites", client=auth_client)
            assert not route.called

    def test_an_empty_token_raises_before_requesting(self):
        with respx.mock:
            route = respx.get(project_url("p1", "sites")).mock(
                return_value=httpx.Response(200, json=page(sites(1)))
            )
            with pytest.raises(AuthenticationError):
                get_project_sites("p1", token="")
            assert not route.called

    def test_a_traversing_default_from_the_environment_raises(self, monkeypatch, auth_client):
        monkeypatch.setenv(DEFAULT_PROJECT_ENV_VAR, "../../danger")

        with pytest.raises(ValueError, match="cannot contain"):
            get_project_sites(client=auth_client)
