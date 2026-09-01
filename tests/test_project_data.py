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
    OBSERVATION_KEYS,
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


#: One column per fixture, with the value its first row holds, so that a test
#: can tell the fixtures apart as well as count their rows.
FIRST_VALUES = {
    "fishbelt_observations": ("fish_taxon", "Acanthurus nigricauda"),
    "fishbelt_sampleunits": ("biomass_kgha", 14.3451),
    "fishbelt_sampleevents": ("site", "Nasue"),
    "benthiclit_observations": ("benthic_attribute", "Acropora"),
    "benthiclit_sampleunits": ("percent_cover_benthic_category_Hard coral", 12.8),
    "benthiclit_sampleevents": ("percent_cover_benthic_category_avg_Hard coral", 15.6),
    "benthicpit_observations": ("interval", 0.5),
    "benthicpit_sampleunits": ("percent_cover_benthic_category_Sand", 52.0),
    "benthicpit_sampleevents": ("percent_cover_benthic_category_avg_Hard coral", 41.0),
    "benthicpqt_observations": ("num_points", 42),
    "benthicpqt_sampleunits": ("num_points_per_quadrat", 100),
    "benthicpqt_sampleevents": ("percent_cover_benthic_category_avg_Sand", 57.0),
    "habitatcomplexity_observations": ("score", 3),
    "habitatcomplexity_sampleunits": ("score_avg", 3.5),
    "habitatcomplexity_sampleevents": ("score_avg_avg", 3.15),
    "macroinvertebrate_observations": ("benthic_attribute", "Diadema setosum"),
    "macroinvertebrate_sampleunits": ("density_ha", 500.0),
    "macroinvertebrate_sampleevents": ("density_ha_avg", 400.0),
    "bleaching_colonies_bleached": ("count_normal", 12),
    "bleaching_percent_cover": ("percent_hard", 45),
    "bleaching_sampleunits": ("percent_bleached", 11.11),
    "bleaching_sampleevents": ("count_total_avg", 23.0),
}


def endpoint_fixtures(method: str, data: str) -> list[tuple[str, str]]:
    """``(path, fixture name)`` for every endpoint one method and level covers.

    Bleaching observations span two endpoints, whose fixtures are named after
    the keys their frames come back under rather than after the level.
    """
    pairs = []
    for path in construct_endpoints(method, data)[method][data]:
        key = OBSERVATION_KEYS.get(path.rsplit("/", 1)[-1])
        pairs.append((path, f"{method}_{key or data}"))
    return pairs


def mock_endpoint(method: str, data: str, project: str = PROJECT, *, body: str | None = None):
    """Mock every CSV endpoint of one method and level; answers with fixtures."""
    routes = []
    for path, name in endpoint_fixtures(method, data):
        method_slug, data_slug = path.split("/")
        csv = fixture_csv(name) if body is None else body
        route = respx.get(project_csv_url(project, method_slug, data_slug))
        routes.append(route.mock(return_value=httpx.Response(200, text=csv)))
    return routes


def mock_fishbelt(data: str, project: str = PROJECT, *, body: str | None = None):
    """Mock one fishbelt CSV endpoint, answering with its fixture by default."""
    return mock_endpoint("fishbelt", data, project, body=body)[0]


def fixture_rows(name: str) -> int:
    """How many data rows a CSV fixture holds."""
    return len(fixture_csv(name).strip().splitlines()) - 1


def fixture_columns(name: str) -> list[str]:
    """The column headings of a CSV fixture."""
    return fixture_csv(name).splitlines()[0].split(",")


def assert_matches_fixture(frame: pd.DataFrame, fixture: str) -> None:
    """Check a frame against the fixture it was parsed from."""
    assert list(frame.columns) == fixture_columns(fixture)
    assert len(frame) == fixture_rows(fixture)

    column, expected = FIRST_VALUES[fixture]
    actual = frame.loc[0, column]
    if isinstance(expected, float):
        assert actual == pytest.approx(expected)
    else:
        assert actual == expected


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


class TestEveryMethod:
    """Every method fetches and parses its own CSV, at every level."""

    @respx.mock
    @pytest.mark.parametrize(("method", "data"), sorted(EXPECTED_ENDPOINTS))
    def test_it_fetches_and_parses_its_endpoints(self, auth_client, method, data):
        routes = mock_endpoint(method, data)

        result = get_project_data(PROJECT, method, data, client=auth_client)

        fixtures = endpoint_fixtures(method, data)
        expected = [f"/v1/projects/{PROJECT}/{path}/csv/" for path, _ in fixtures]
        assert [route.calls.last.request.url.path for route in routes] == expected
        if len(fixtures) == 1:
            assert isinstance(result, pd.DataFrame)
            frames = [result]
        else:
            assert list(result) == ["colonies_bleached", "percent_cover"]
            frames = list(result.values())
        for frame, (_, name) in zip(frames, fixtures, strict=True):
            assert_matches_fixture(frame, name)

    @respx.mock
    @pytest.mark.parametrize("method", METHODS)
    def test_an_empty_body_gives_an_empty_frame(self, auth_client, method):
        mock_endpoint(method, "observations", body="")

        result = get_project_data(PROJECT, method, "observations", client=auth_client)

        frames = [result] if isinstance(result, pd.DataFrame) else list(result.values())
        assert frames
        assert all(isinstance(frame, pd.DataFrame) and frame.empty for frame in frames)

    @respx.mock
    @pytest.mark.parametrize("method", METHODS)
    def test_a_header_only_body_keeps_the_columns(self, auth_client, method):
        mock_endpoint(method, "sampleevents", body="project,site,depth_avg\n")

        df = get_project_data(PROJECT, method, "sampleevents", client=auth_client)

        assert df.empty
        assert list(df.columns) == ["project", "site", "depth_avg"]

    @respx.mock
    def test_empty_bodies_stack_without_raising(self, auth_client):
        mock_endpoint("benthicpit", "observations", PROJECT, body="")
        mock_endpoint("benthicpit", "observations", OTHER_PROJECT, body="")

        df = get_project_data(
            [PROJECT, OTHER_PROJECT], "benthicpit", "observations", client=auth_client
        )

        assert df.empty


class TestBleachingObservations:
    """Bleaching observations span two endpoints and return two named frames."""

    @respx.mock
    def test_both_endpoints_are_fetched_and_named(self, auth_client):
        colonies, percents = mock_endpoint("bleaching", "observations")

        result = get_project_data(PROJECT, "bleaching", "observations", client=auth_client)

        assert colonies.called and percents.called
        assert list(result) == ["colonies_bleached", "percent_cover"]
        assert_matches_fixture(result["colonies_bleached"], "bleaching_colonies_bleached")
        assert_matches_fixture(result["percent_cover"], "bleaching_percent_cover")

    @respx.mock
    def test_the_other_levels_stay_single_frames(self, auth_client):
        for data in ("sampleunits", "sampleevents"):
            mock_endpoint("bleaching", data)

        units = get_project_data(PROJECT, "bleaching", "sampleunits", client=auth_client)
        events = get_project_data(PROJECT, "bleaching", "sampleevents", client=auth_client)

        assert isinstance(units, pd.DataFrame)
        assert isinstance(events, pd.DataFrame)

    @respx.mock
    def test_the_pair_sits_inside_the_nested_dict(self, auth_client):
        for data in DATA_LEVELS:
            mock_endpoint("bleaching", data)

        result = get_project_data(PROJECT, "bleaching", "all", client=auth_client)

        observations = result["bleaching"]["observations"]
        assert list(observations) == ["colonies_bleached", "percent_cover"]
        assert all(isinstance(frame, pd.DataFrame) for frame in observations.values())
        assert isinstance(result["bleaching"]["sampleunits"], pd.DataFrame)

    @respx.mock
    def test_limit_applies_to_each_endpoint(self, auth_client):
        mock_endpoint("bleaching", "observations")

        both = get_project_data(PROJECT, "bleaching", "observations", limit=2, client=auth_client)

        assert [len(frame) for frame in both.values()] == [2, 2]

    @respx.mock
    def test_both_frames_are_stacked_across_projects(self, auth_client):
        mock_endpoint("bleaching", "observations", PROJECT)
        mock_endpoint("bleaching", "observations", OTHER_PROJECT)

        result = get_project_data(
            [PROJECT, OTHER_PROJECT], "bleaching", "observations", client=auth_client
        )

        assert list(result) == ["colonies_bleached", "percent_cover"]
        for frame in result.values():
            assert frame.columns[0] == PROJECT_COLUMN
            assert list(frame[PROJECT_COLUMN]) == [PROJECT] * 3 + [OTHER_PROJECT] * 3


class TestAllMethodsAndLevels:
    @respx.mock
    def test_everything_is_fetched_and_nested_by_method_then_level(self, auth_client):
        routes = [route for pair in EXPECTED_ENDPOINTS for route in mock_endpoint(*pair)]

        result = get_project_data(PROJECT, "all", "all", client=auth_client)

        assert all(route.called for route in routes)
        assert list(result) == list(METHODS)
        for method, levels in result.items():
            assert list(levels) == list(DATA_LEVELS)
            for data, value in levels.items():
                fixtures = endpoint_fixtures(method, data)
                frames = [value] if isinstance(value, pd.DataFrame) else list(value.values())
                for frame, (_, name) in zip(frames, fixtures, strict=True):
                    assert_matches_fixture(frame, name)

    @respx.mock
    def test_every_method_at_one_level(self, auth_client):
        for method in METHODS:
            mock_endpoint(method, "sampleevents")

        result = get_project_data(PROJECT, "all", "sampleevents", client=auth_client)

        assert list(result) == list(METHODS)
        assert all(list(levels) == ["sampleevents"] for levels in result.values())
        assert all(isinstance(levels["sampleevents"], pd.DataFrame) for levels in result.values())

    @respx.mock
    def test_keys_keep_the_canonical_order_whatever_order_was_asked_for(self, auth_client):
        for method in ("bleaching", "fishbelt"):
            for data in ("sampleevents", "observations"):
                mock_endpoint(method, data)

        result = get_project_data(
            PROJECT,
            ["bleaching", "fishbelt"],
            ["sampleevents", "observations"],
            client=auth_client,
        )

        assert list(result) == ["fishbelt", "bleaching"]
        assert all(list(levels) == ["observations", "sampleevents"] for levels in result.values())


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
