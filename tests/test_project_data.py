"""Tests for the endpoint mapping and the project data CSV endpoints."""

from __future__ import annotations

import httpx
import pandas as pd
import pytest
import respx

import datamermaid
from conftest import fixture_csv, project_csv_url, query_of
from datamermaid.exceptions import AuthenticationError, MermaidAPIError
from datamermaid.project_data import (
    DATA_LEVELS,
    METHODS,
    PROJECT_COLUMN,
    construct_endpoints,
    get_project_data,
)

PROJECT = "abc-123"
OTHER_PROJECT = "def-456"

#: ``(method, data)`` -> the path fragments the API expects, per mermaidr.
EXPECTED_ENDPOINTS = {
    ("fishbelt", "observations"): ["beltfishes/obstransectbeltfishes"],
    ("fishbelt", "sampleunits"): ["beltfishes/sampleunits"],
    ("fishbelt", "sampleevents"): ["beltfishes/sampleevents"],
    ("benthiclit", "observations"): ["benthiclits/obstransectbenthiclits"],
    ("benthiclit", "sampleunits"): ["benthiclits/sampleunits"],
    ("benthiclit", "sampleevents"): ["benthiclits/sampleevents"],
    ("benthicpit", "observations"): ["benthicpits/obstransectbenthicpits"],
    ("benthicpit", "sampleunits"): ["benthicpits/sampleunits"],
    ("benthicpit", "sampleevents"): ["benthicpits/sampleevents"],
    ("benthicpqt", "observations"): ["benthicpqts/obstransectbenthicpqts"],
    ("benthicpqt", "sampleunits"): ["benthicpqts/sampleunits"],
    ("benthicpqt", "sampleevents"): ["benthicpqts/sampleevents"],
    ("habitatcomplexity", "observations"): ["habitatcomplexities/obshabitatcomplexities"],
    ("habitatcomplexity", "sampleunits"): ["habitatcomplexities/sampleunits"],
    ("habitatcomplexity", "sampleevents"): ["habitatcomplexities/sampleevents"],
    ("bleaching", "observations"): [
        "bleachingqcs/obscoloniesbleacheds",
        "bleachingqcs/obsquadratbenthicpercents",
    ],
    ("bleaching", "sampleunits"): ["bleachingqcs/sampleunits"],
    ("bleaching", "sampleevents"): ["bleachingqcs/sampleevents"],
    ("macroinvertebrate", "observations"): ["beltinverts/obstransectbeltinverts"],
    ("macroinvertebrate", "sampleunits"): ["beltinverts/sampleunits"],
    ("macroinvertebrate", "sampleevents"): ["beltinverts/sampleevents"],
}

FISHBELT_SLUGS = {
    "observations": "obstransectbeltfishes",
    "sampleunits": "sampleunits",
    "sampleevents": "sampleevents",
}


def mock_fishbelt(data: str, project: str = PROJECT, *, body: str | None = None):
    """Mock one fishbelt CSV endpoint, answering with its fixture by default."""
    url = project_csv_url(project, "beltfishes", FISHBELT_SLUGS[data])
    csv = fixture_csv(f"fishbelt_{data}") if body is None else body
    return respx.get(url).mock(return_value=httpx.Response(200, text=csv))


class TestConstructEndpoints:
    @pytest.mark.parametrize(("method", "data"), sorted(EXPECTED_ENDPOINTS))
    def test_every_method_and_level_maps_to_its_endpoints(self, method, data):
        endpoints = construct_endpoints(method, data)

        assert endpoints == {method: {data: EXPECTED_ENDPOINTS[(method, data)]}}

    def test_bleaching_observations_span_two_endpoints(self):
        observations = construct_endpoints("bleaching", "observations")["bleaching"]["observations"]

        assert observations == [
            "bleachingqcs/obscoloniesbleacheds",
            "bleachingqcs/obsquadratbenthicpercents",
        ]

    def test_habitat_complexity_has_its_own_observation_slug(self):
        observations = construct_endpoints("habitatcomplexity", "observations")
        slug = observations["habitatcomplexity"]["observations"][0]

        assert slug == "habitatcomplexities/obshabitatcomplexities"

    def test_all_covers_every_method_and_level(self):
        endpoints = construct_endpoints("all", "all")

        assert list(endpoints) == list(METHODS)
        for method, levels in endpoints.items():
            assert list(levels) == list(DATA_LEVELS)
            for data, paths in levels.items():
                assert paths == EXPECTED_ENDPOINTS[(method, data)]

    def test_all_methods_for_one_level(self):
        endpoints = construct_endpoints("all", "sampleevents")

        assert list(endpoints) == list(METHODS)
        assert all(list(levels) == ["sampleevents"] for levels in endpoints.values())

    def test_all_levels_for_one_method(self):
        endpoints = construct_endpoints("fishbelt", "all")

        assert list(endpoints) == ["fishbelt"]
        assert list(endpoints["fishbelt"]) == list(DATA_LEVELS)

    def test_lists_are_accepted_and_returned_in_canonical_order(self):
        endpoints = construct_endpoints(["bleaching", "fishbelt"], ["sampleevents", "observations"])

        assert list(endpoints) == ["fishbelt", "bleaching"]
        assert list(endpoints["fishbelt"]) == ["observations", "sampleevents"]

    def test_duplicates_are_collapsed(self):
        assert construct_endpoints(["fishbelt", "fishbelt"], "observations") == construct_endpoints(
            "fishbelt", "observations"
        )

    def test_defaults_to_everything(self):
        assert construct_endpoints() == construct_endpoints("all", "all")

    @pytest.mark.parametrize("method", ["fish", "", "FISHBELT", "beltfishes", None, 3])
    def test_invalid_method_raises_naming_the_options(self, method):
        with pytest.raises(ValueError, match="`method`") as excinfo:
            construct_endpoints(method, "observations")

        message = str(excinfo.value)
        assert all(name in message for name in METHODS)

    @pytest.mark.parametrize("data", ["observation", "sample_units", "", None, 3])
    def test_invalid_data_raises_naming_the_options(self, data):
        with pytest.raises(ValueError, match="`data`") as excinfo:
            construct_endpoints("fishbelt", data)

        message = str(excinfo.value)
        assert all(name in message for name in DATA_LEVELS)

    def test_an_empty_list_raises(self):
        with pytest.raises(ValueError, match="`method`"):
            construct_endpoints([], "observations")


class TestRequestShape:
    @respx.mock
    @pytest.mark.parametrize("data", list(FISHBELT_SLUGS))
    def test_fetches_the_project_csv_endpoint(self, auth_client, data):
        route = mock_fishbelt(data)

        get_project_data(PROJECT, "fishbelt", data, client=auth_client)

        assert route.called
        path = route.calls.last.request.url.path
        assert path == f"/v1/projects/{PROJECT}/beltfishes/{FISHBELT_SLUGS[data]}/csv/"

    @respx.mock
    def test_sends_the_bearer_token(self, auth_client):
        route = mock_fishbelt("observations")

        get_project_data(PROJECT, client=auth_client)

        assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"

    @respx.mock
    def test_asks_for_csv(self, auth_client):
        route = mock_fishbelt("observations")

        get_project_data(PROJECT, client=auth_client)

        assert route.calls.last.request.headers["Accept"] == "text/csv"

    @respx.mock
    def test_no_pagination_parameters_are_sent(self, auth_client):
        route = mock_fishbelt("observations")

        get_project_data(PROJECT, limit=2, client=auth_client)

        assert query_of(route.calls.last.request) == {}

    @respx.mock
    def test_covariates_are_requested_when_asked_for(self, auth_client):
        route = mock_fishbelt("observations")

        get_project_data(PROJECT, covariates=True, client=auth_client)

        assert query_of(route.calls.last.request)["covariates"] == ["true"]

    @respx.mock
    def test_covariates_are_omitted_by_default(self, auth_client):
        route = mock_fishbelt("observations")

        get_project_data(PROJECT, client=auth_client)

        assert "covariates" not in query_of(route.calls.last.request)

    @respx.mock
    def test_uses_the_default_client_when_none_is_given(self, auth_client):
        datamermaid.set_default_client(auth_client)
        try:
            mock_fishbelt("observations")
            df = datamermaid.get_project_data(PROJECT)
        finally:
            datamermaid.set_default_client(None)

        assert len(df) == 5

    @respx.mock
    def test_a_token_argument_is_used(self, monkeypatch):
        route = mock_fishbelt("observations")

        get_project_data(PROJECT, token="passed-token")

        assert route.calls.last.request.headers["Authorization"] == "Bearer passed-token"

    @respx.mock
    def test_the_environment_token_is_used(self, client, monkeypatch):
        monkeypatch.setenv(datamermaid.TOKEN_ENV_VAR, "env-token")
        route = mock_fishbelt("observations")

        get_project_data(PROJECT, client=client)

        assert route.calls.last.request.headers["Authorization"] == "Bearer env-token"


class TestResult:
    @respx.mock
    def test_observations_are_parsed_from_csv(self, auth_client):
        mock_fishbelt("observations")

        df = get_project_data(PROJECT, "fishbelt", "observations", client=auth_client)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5
        assert df.loc[0, "fish_taxon"] == "Acanthurus nigricauda"
        assert df.loc[0, "count"] == 3
        assert df.loc[0, "biomass_kgha"] == pytest.approx(12.4419)

    @respx.mock
    def test_sample_units_are_parsed_from_csv(self, auth_client):
        mock_fishbelt("sampleunits")

        df = get_project_data(PROJECT, "fishbelt", "sampleunits", client=auth_client)

        assert len(df) == 3
        assert "biomass_kgha" in df.columns

    @respx.mock
    def test_sample_events_are_parsed_from_csv(self, auth_client):
        mock_fishbelt("sampleevents")

        df = get_project_data(PROJECT, "fishbelt", "sampleevents", client=auth_client)

        assert len(df) == 2
        assert list(df["site"]) == ["Nasue", "Namena"]

    @respx.mock
    def test_limit_truncates_the_rows(self, auth_client):
        mock_fishbelt("observations")

        df = get_project_data(PROJECT, limit=2, client=auth_client)

        assert len(df) == 2
        assert list(df.index) == [0, 1]

    @respx.mock
    def test_a_limit_beyond_the_data_returns_everything(self, auth_client):
        mock_fishbelt("observations")

        assert len(get_project_data(PROJECT, limit=500, client=auth_client)) == 5

    @respx.mock
    def test_an_empty_body_gives_an_empty_frame(self, auth_client):
        mock_fishbelt("observations", body="")

        df = get_project_data(PROJECT, client=auth_client)

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    @respx.mock
    def test_a_header_only_body_keeps_the_columns(self, auth_client):
        mock_fishbelt("observations", body="project,site,count\n")

        df = get_project_data(PROJECT, client=auth_client)

        assert df.empty
        assert list(df.columns) == ["project", "site", "count"]

    @respx.mock
    def test_all_levels_return_a_nested_dict(self, auth_client):
        for data in FISHBELT_SLUGS:
            mock_fishbelt(data)

        result = get_project_data(PROJECT, "fishbelt", "all", client=auth_client)

        assert list(result) == ["fishbelt"]
        assert list(result["fishbelt"]) == list(DATA_LEVELS)
        assert [len(df) for df in result["fishbelt"].values()] == [5, 3, 2]
        assert all(isinstance(df, pd.DataFrame) for df in result["fishbelt"].values())

    @respx.mock
    def test_a_single_element_list_still_returns_one_frame(self, auth_client):
        mock_fishbelt("observations")

        df = get_project_data(PROJECT, ["fishbelt"], ["observations"], client=auth_client)

        assert isinstance(df, pd.DataFrame)


class TestMultipleProjects:
    @respx.mock
    def test_rows_are_stacked_and_labelled_with_the_project(self, auth_client):
        first = mock_fishbelt("sampleevents", PROJECT)
        second = mock_fishbelt("sampleevents", OTHER_PROJECT)

        df = get_project_data([PROJECT, OTHER_PROJECT], data="sampleevents", client=auth_client)

        assert first.called and second.called
        assert len(df) == 4
        assert list(df[PROJECT_COLUMN]) == [PROJECT] * 2 + [OTHER_PROJECT] * 2
        assert df.columns[0] == PROJECT_COLUMN

    @respx.mock
    def test_a_single_project_gains_no_extra_column(self, auth_client):
        mock_fishbelt("sampleevents")

        df = get_project_data(PROJECT, data="sampleevents", client=auth_client)

        assert PROJECT_COLUMN not in df.columns

    @respx.mock
    def test_limit_applies_per_project(self, auth_client):
        mock_fishbelt("observations", PROJECT)
        mock_fishbelt("observations", OTHER_PROJECT)

        df = get_project_data([PROJECT, OTHER_PROJECT], limit=2, client=auth_client)

        assert len(df) == 4

    @respx.mock
    def test_a_projects_frame_can_be_passed_straight_through(self, auth_client):
        mock_fishbelt("sampleevents", PROJECT)
        mock_fishbelt("sampleevents", OTHER_PROJECT)
        projects = pd.DataFrame({"id": [PROJECT, OTHER_PROJECT], "name": ["a", "b"]})

        df = get_project_data(projects, data="sampleevents", client=auth_client)

        assert sorted(set(df[PROJECT_COLUMN])) == [PROJECT, OTHER_PROJECT]


class TestErrors:
    def test_an_invalid_method_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_fishbelt("observations")
            with pytest.raises(ValueError, match="`method`"):
                get_project_data(PROJECT, "fish", client=auth_client)
            assert not route.called

    def test_an_invalid_data_level_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_fishbelt("observations")
            with pytest.raises(ValueError, match="`data`"):
                get_project_data(PROJECT, "fishbelt", "observation", client=auth_client)
            assert not route.called

    def test_an_invalid_limit_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_fishbelt("observations")
            with pytest.raises(ValueError, match="positive integer"):
                get_project_data(PROJECT, limit=0, client=auth_client)
            assert not route.called

    def test_a_missing_project_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_fishbelt("observations")
            with pytest.raises(ValueError, match="no default project set"):
                get_project_data(client=auth_client)
            assert not route.called

    def test_an_invalid_project_raises_before_any_request(self, auth_client):
        with respx.mock:
            route = mock_fishbelt("observations")
            with pytest.raises(ValueError, match="cannot contain"):
                get_project_data("bad/id", client=auth_client)
            assert not route.called

    @pytest.mark.parametrize(
        "method",
        [
            "benthiclit",
            "benthicpit",
            "benthicpqt",
            "habitatcomplexity",
            "bleaching",
            "macroinvertebrate",
        ],
    )
    def test_other_methods_are_not_implemented_yet(self, auth_client, method):
        with respx.mock:
            route = mock_fishbelt("observations")
            with pytest.raises(NotImplementedError, match=method):
                get_project_data(PROJECT, method, client=auth_client)
            assert not route.called

    def test_no_token_raises_before_any_request(self, client):
        with respx.mock:
            route = mock_fishbelt("observations")
            with pytest.raises(AuthenticationError, match="authenticate"):
                get_project_data(PROJECT, client=client)
            assert not route.called

    @respx.mock
    def test_http_errors_surface_as_api_errors(self, auth_client):
        respx.get(project_csv_url(PROJECT, "beltfishes", "obstransectbeltfishes")).mock(
            return_value=httpx.Response(404)
        )

        with pytest.raises(MermaidAPIError) as excinfo:
            get_project_data(PROJECT, client=auth_client)

        assert excinfo.value.status_code == 404

    @respx.mock
    def test_a_rejected_token_raises_an_authentication_error(self, auth_client):
        respx.get(project_csv_url(PROJECT, "beltfishes", "obstransectbeltfishes")).mock(
            return_value=httpx.Response(401)
        )

        with pytest.raises(AuthenticationError):
            get_project_data(PROJECT, client=auth_client)


class TestDefaultProject:
    """The default project is shared with the other project endpoints."""

    @respx.mock
    def test_it_is_used_when_no_project_is_given(self, auth_client):
        datamermaid.set_default_project(PROJECT)
        route = mock_fishbelt("observations")

        df = get_project_data(client=auth_client)

        assert route.called
        assert not df.empty

    @respx.mock
    def test_an_explicit_project_wins(self, auth_client):
        datamermaid.set_default_project(OTHER_PROJECT)
        route = mock_fishbelt("observations")

        get_project_data(PROJECT, client=auth_client)

        assert route.calls.last.request.url.path.startswith(f"/v1/projects/{PROJECT}/")
