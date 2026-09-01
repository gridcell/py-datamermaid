"""Tests for :func:`datamermaid.get_projects` and the DataFrame conversion."""

from __future__ import annotations

import httpx
import pandas as pd
import pytest
import respx

import datamermaid
from conftest import PROJECTS_URL, page, projects, query_of
from datamermaid.projects import PROJECT_COLUMNS, PROJECT_STATUS_OPEN, get_projects
from datamermaid.utils import collapse_value, records_to_df


class TestRequestShape:
    @respx.mock
    def test_showall_is_sent_when_unauthenticated(self, client):
        route = respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1)))
        )

        get_projects(limit=1, client=client)

        assert query_of(route.calls.last.request)["showall"] == ["true"]

    @respx.mock
    def test_showall_is_omitted_when_authenticated(self, auth_client):
        route = respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1)))
        )

        get_projects(limit=1, client=auth_client)

        assert "showall" not in query_of(route.calls.last.request)

    @respx.mock
    def test_test_projects_are_filtered_out_by_default(self, client):
        route = respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1)))
        )

        get_projects(limit=1, client=client)

        assert query_of(route.calls.last.request)["status"] == [str(PROJECT_STATUS_OPEN)]

    @respx.mock
    def test_status_filter_is_dropped_when_including_test_projects(self, client):
        route = respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(1)))
        )

        get_projects(limit=1, include_test_projects=True, client=client)

        assert "status" not in query_of(route.calls.last.request)

    @respx.mock
    def test_uses_the_default_client_when_none_is_given(self, client):
        datamermaid.set_default_client(client)
        try:
            respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(projects(2))))
            assert len(datamermaid.get_projects(limit=2)) == 2
        finally:
            datamermaid.set_default_client(None)

    def test_invalid_limit_raises(self, client):
        with pytest.raises(ValueError):
            get_projects(limit=0, client=client)


class TestResult:
    @respx.mock
    def test_returns_a_dataframe_of_at_most_limit_rows(self, client):
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(5), count=5))
        )

        df = get_projects(limit=3, client=client)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3

    @respx.mock
    def test_includes_the_documented_columns(self, client):
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(2), count=2))
        )

        df = get_projects(client=client)

        for column in (
            "id",
            "name",
            "countries",
            "num_sites",
            "tags",
            "notes",
            "status",
            "created_on",
            "updated_on",
        ):
            assert column in df.columns
        assert any(column.startswith("data_policy") for column in df.columns)

    @respx.mock
    def test_columns_are_ordered_and_unknown_fields_dropped(self, client):
        record = projects(1)[0] | {"unexpected_field": "noise"}
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([record])))

        df = get_projects(client=client)

        assert "unexpected_field" not in df.columns
        assert list(df.columns) == [c for c in PROJECT_COLUMNS if c in df.columns]

    @respx.mock
    def test_list_columns_are_collapsed_to_strings(self, client):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(projects(1))))

        df = get_projects(client=client)

        assert df.loc[0, "countries"] == "Fiji"
        assert df.loc[0, "tags"] == "WCS"

    @respx.mock
    def test_empty_results_give_an_empty_frame_with_columns(self, client):
        respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page([])))

        df = get_projects(client=client)

        assert df.empty
        assert list(df.columns) == list(PROJECT_COLUMNS)

    @respx.mock
    def test_paginates_transparently_when_no_limit_is_given(self, client):
        page_two = PROJECTS_URL + "?limit=5000&offset=2"
        respx.get(PROJECTS_URL, params={"offset": "2"}).mock(
            return_value=httpx.Response(200, json=page(projects(2, 2), count=4))
        )
        respx.get(PROJECTS_URL).mock(
            return_value=httpx.Response(200, json=page(projects(2), next_url=page_two, count=4))
        )

        df = get_projects(client=client)

        assert len(df) == 4
        assert list(df["id"]) == [f"project-{i}" for i in range(4)]


class TestCollapseValue:
    def test_id_name_objects_collapse_to_names(self):
        value = [{"id": "a", "name": "WCS"}, {"id": "b", "name": "WWF"}]
        assert collapse_value(value) == "WCS, WWF"

    def test_objects_without_a_name_fall_back_to_id(self):
        assert collapse_value([{"id": "a"}]) == "a"

    def test_scalar_lists_are_joined(self):
        assert collapse_value(["Fiji", "Tonga"]) == "Fiji, Tonga"

    def test_empty_list_becomes_an_empty_string(self):
        assert collapse_value([]) == ""

    @pytest.mark.parametrize("value", ["Fiji", 3, None])
    def test_non_lists_pass_through(self, value):
        assert collapse_value(value) is value


class TestRecordsToDf:
    def test_missing_requested_columns_are_skipped(self):
        df = records_to_df([{"id": "a"}], columns=("id", "name"))

        assert list(df.columns) == ["id"]

    def test_no_column_selection_keeps_everything(self):
        df = records_to_df([{"b": 1, "a": 2}])

        assert set(df.columns) == {"a", "b"}

    def test_index_is_reset_after_pagination(self):
        df = records_to_df([{"id": "a"}, {"id": "b"}])

        assert list(df.index) == [0, 1]
