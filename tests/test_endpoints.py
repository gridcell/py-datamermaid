"""Tests for the global, unauthenticated endpoints."""

from __future__ import annotations

import warnings

import httpx
import pandas as pd
import pytest
import respx

import datamermaid
from conftest import (
    choices_payload,
    global_url,
    labelmappings,
    managements,
    page,
    query_of,
    sites,
)
from datamermaid.client import DEFAULT_PAGE_SIZE
from datamermaid.endpoints import (
    CLASSIFICATION_PROVIDERS,
    KNOWN_ENDPOINTS,
    REFERENCE_ENDPOINTS,
    countries,
    get_choices,
    get_classification_labelmappings,
    get_endpoint,
    get_managements,
    get_reference,
    get_sites,
    get_summary_sampleevents,
)
from datamermaid.exceptions import MermaidAPIError, MermaidError
from datamermaid.project_endpoints import MANAGEMENT_COLUMNS, PROJECT_COLUMN, SITE_COLUMNS

SITES_URL = global_url("sites")
CHOICES_URL = global_url("choices")
LABELMAPPINGS_URL = global_url("classification/labelmappings")

LABELMAPPING_COLUMNS = [
    "id",
    "benthic_attribute",
    "growth_form",
    "provider_id",
    "provider_label",
    "provider",
]


class TestGetEndpoint:
    @respx.mock
    def test_requests_the_endpoint_at_the_api_root(self, client):
        route = respx.get(global_url("fishsizes")).mock(
            return_value=httpx.Response(200, json=page([{"id": "1", "name": "5"}]))
        )

        df = get_endpoint("fishsizes", client=client)

        assert route.called
        assert list(df["name"]) == ["5"]

    @respx.mock
    def test_no_token_is_resolved_for_a_public_endpoint(self, client, write_cached_token):
        """These endpoints are public, so a saved login is never looked up or sent."""
        write_cached_token()
        route = respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=page(sites(1))))

        get_endpoint("sites", client=client)

        assert "Authorization" not in route.calls.last.request.headers

    @respx.mock
    def test_limit_is_sent_and_honoured(self, client):
        route = respx.get(SITES_URL).mock(
            return_value=httpx.Response(200, json=page(sites(5), count=5))
        )

        df = get_endpoint("sites", limit=2, client=client)

        assert len(df) == 2
        assert query_of(route.calls.last.request)["limit"] == ["2"]

    @respx.mock
    def test_paginates_when_no_limit_is_given(self, client):
        page_two = SITES_URL + "?limit=5000&offset=2"
        respx.get(SITES_URL, params={"offset": "2"}).mock(
            return_value=httpx.Response(200, json=page(sites(1, start=2), count=3))
        )
        respx.get(SITES_URL).mock(
            return_value=httpx.Response(200, json=page(sites(2), next_url=page_two, count=3))
        )

        df = get_endpoint("sites", client=client)

        assert list(df["id"]) == ["site-0", "site-1", "site-2"]

    @respx.mock
    def test_filters_become_query_parameters_and_none_is_dropped(self, client):
        route = respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=page([])))

        get_endpoint("sites", country="Fiji", reef_zone=None, client=client)

        query = query_of(route.calls.last.request)
        assert query["country"] == ["Fiji"]
        assert "reef_zone" not in query

    @respx.mock
    def test_columns_select_and_order(self, client):
        respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=page(sites(1))))

        df = get_endpoint("sites", columns=("name", "id", "missing"), client=client)

        assert list(df.columns) == ["name", "id"]

    @respx.mock
    def test_unknown_endpoint_warns_but_is_still_requested(self, client):
        route = respx.get(global_url("somethingelse")).mock(
            return_value=httpx.Response(200, json=page([{"id": "x"}]))
        )

        with pytest.warns(UserWarning, match="not a known MERMAID endpoint"):
            df = get_endpoint("somethingelse", client=client)

        assert route.called
        assert list(df["id"]) == ["x"]

    @respx.mock
    def test_known_endpoints_do_not_warn(self, client):
        respx.get(global_url("projecttags")).mock(return_value=httpx.Response(200, json=page([])))

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            get_endpoint("projecttags", client=client)

    @respx.mock
    def test_surrounding_slashes_are_tolerated(self, client):
        route = respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=page([])))

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            get_endpoint("/sites/", client=client)

        assert route.called

    def test_empty_endpoint_raises(self, client):
        with pytest.raises(ValueError, match="must not be empty"):
            get_endpoint("", client=client)

    def test_invalid_limit_raises_before_any_request(self, client):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(SITES_URL)
            with pytest.raises(ValueError):
                get_endpoint("sites", limit=0, client=client)
            assert not route.called

    @respx.mock
    def test_http_errors_are_raised(self, client):
        respx.get(SITES_URL).mock(return_value=httpx.Response(500))

        with pytest.raises(MermaidAPIError) as excinfo:
            get_endpoint("sites", client=client)

        assert excinfo.value.status_code == 500

    @respx.mock
    def test_uses_the_default_client_when_none_is_given(self, client):
        datamermaid.set_default_client(client)
        try:
            respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=page(sites(2))))
            assert len(datamermaid.get_endpoint("sites")) == 2
        finally:
            datamermaid.set_default_client(None)

    def test_reference_and_named_endpoints_are_known(self):
        assert set(REFERENCE_ENDPOINTS) <= KNOWN_ENDPOINTS
        assert {"sites", "managements", "summarysampleevents", "choices"} <= KNOWN_ENDPOINTS


class TestNamedGetters:
    @respx.mock
    def test_get_sites(self, client):
        route = respx.get(SITES_URL).mock(
            return_value=httpx.Response(200, json=page(sites(3), count=3))
        )

        df = get_sites(limit=2, client=client)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert query_of(route.calls.last.request)["limit"] == ["2"]
        # The global endpoint carries each site's project; keep it, and keep the
        # layout identical to get_project_sites().
        expected = [PROJECT_COLUMN, *(c for c in SITE_COLUMNS if c in sites(1)[0])]
        assert list(df.columns) == expected
        assert list(df[PROJECT_COLUMN]) == ["project-from-payload"] * 2

    @respx.mock
    def test_get_managements(self, client):
        route = respx.get(global_url("managements")).mock(
            return_value=httpx.Response(200, json=page(managements(3), count=3))
        )

        df = get_managements(limit=2, client=client)

        assert len(df) == 2
        assert query_of(route.calls.last.request)["limit"] == ["2"]
        expected = [PROJECT_COLUMN, *(c for c in MANAGEMENT_COLUMNS if c in managements(1)[0])]
        assert list(df.columns) == expected
        assert list(df["parties"]) == ["community", "community"]

    @respx.mock
    def test_get_summary_sampleevents(self, client):
        events = [
            {"project_id": "p1", "site_name": "Site 1", "sample_date": "2020-01-01", "depth": 5},
            {"project_id": "p1", "site_name": "Site 2", "sample_date": "2020-01-02", "depth": 7},
            {"project_id": "p2", "site_name": "Site 3", "sample_date": "2020-01-03", "depth": 9},
        ]
        route = respx.get(global_url("summarysampleevents")).mock(
            return_value=httpx.Response(200, json=page(events, count=3))
        )

        df = get_summary_sampleevents(limit=1, client=client)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert query_of(route.calls.last.request)["limit"] == ["1"]
        assert list(df.columns) == list(events[0])

    @respx.mock
    @pytest.mark.parametrize("name", ["get_sites", "get_managements", "get_summary_sampleevents"])
    def test_fetch_everything_by_default(self, client, name):
        endpoint = {"get_summary_sampleevents": "summarysampleevents"}.get(name, name[4:])
        route = respx.get(global_url(endpoint)).mock(
            return_value=httpx.Response(200, json=page([]))
        )

        df = getattr(datamermaid, name)(client=client)

        assert df.empty
        assert query_of(route.calls.last.request)["limit"] == [str(DEFAULT_PAGE_SIZE)]

    @respx.mock
    def test_empty_sites_keep_the_documented_columns(self, client):
        respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=page([])))

        df = get_sites(client=client)

        assert df.empty
        assert list(df.columns) == [PROJECT_COLUMN, *SITE_COLUMNS]


class TestGetReference:
    @respx.mock
    @pytest.mark.parametrize("reference", REFERENCE_ENDPOINTS)
    def test_accepts_every_documented_reference(self, client, reference):
        route = respx.get(global_url(reference)).mock(
            return_value=httpx.Response(200, json=page([{"id": "1", "name": "Acanthuridae"}]))
        )

        df = get_reference(reference, client=client)

        assert route.called
        assert list(df["name"]) == ["Acanthuridae"]

    @respx.mock
    @pytest.mark.parametrize("reference", ["invertattributes", "invertspecies"])
    def test_invertebrate_tables_are_requested_at_the_api_root(self, client, reference):
        route = respx.get(global_url(reference)).mock(
            return_value=httpx.Response(200, json=page([{"id": "1", "name": "Diadema"}]))
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            df = get_reference(reference, client=client)

        assert route.called
        assert list(df["name"]) == ["Diadema"]
        # They are known endpoints, so nothing warns about a possible typo.
        assert [str(warning.message) for warning in caught] == []

    @pytest.mark.parametrize("reference", ["invertattributes", "invertspecies"])
    def test_invertebrate_tables_are_documented_and_known(self, reference):
        assert reference in REFERENCE_ENDPOINTS
        assert reference in KNOWN_ENDPOINTS

    @respx.mock
    def test_limit_is_honoured(self, client):
        route = respx.get(global_url("fishspecies")).mock(
            return_value=httpx.Response(
                200, json=page([{"id": str(i), "name": f"sp {i}"} for i in range(4)], count=4)
            )
        )

        df = get_reference("fishspecies", limit=3, client=client)

        assert len(df) == 3
        assert query_of(route.calls.last.request)["limit"] == ["3"]

    @respx.mock
    def test_every_field_is_kept(self, client):
        record = {"id": "1", "name": "Acanthurus", "family": "f1", "regions": ["r1", "r2"]}
        respx.get(global_url("fishgenera")).mock(
            return_value=httpx.Response(200, json=page([record]))
        )

        df = get_reference("fishgenera", client=client)

        assert list(df.columns) == ["id", "name", "family", "regions"]
        assert df.loc[0, "regions"] == "r1, r2"

    @pytest.mark.parametrize("reference", ["fishes", "sites", "", None, ["fishfamilies"]])
    def test_other_references_raise_listing_the_options(self, client, reference):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__regex=r".*")
            with pytest.raises(ValueError) as excinfo:
                get_reference(reference, client=client)
            assert not route.called

        message = str(excinfo.value)
        assert "`reference` must be one of" in message
        for option in REFERENCE_ENDPOINTS:
            assert f'"{option}"' in message

    def test_reference_names_are_case_sensitive(self, client):
        with pytest.raises(ValueError, match="FishFamilies"):
            get_reference("FishFamilies", client=client)


class TestGetClassificationLabelmappings:
    @respx.mock
    def test_returns_a_frame_of_mappings(self, client):
        route = respx.get(LABELMAPPINGS_URL).mock(
            return_value=httpx.Response(200, json=page(labelmappings(3)))
        )

        df = get_classification_labelmappings(client=client)

        assert route.called
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == LABELMAPPING_COLUMNS
        assert list(df["provider_label"]) == ["Label 0", "Label 1", "Label 2"]

    @respx.mock
    def test_the_endpoint_is_known_so_nothing_warns(self, client):
        """``classification/labelmappings`` sits below the root but is not a typo."""
        respx.get(LABELMAPPINGS_URL).mock(
            return_value=httpx.Response(200, json=page(labelmappings(1)))
        )

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            get_classification_labelmappings(client=client)

        assert "classification/labelmappings" in KNOWN_ENDPOINTS

    @respx.mock
    def test_no_provider_filter_is_sent_by_default(self, client):
        route = respx.get(LABELMAPPINGS_URL).mock(
            return_value=httpx.Response(200, json=page(labelmappings(1)))
        )

        get_classification_labelmappings(client=client)

        query = query_of(route.calls.last.request)
        assert "provider" not in query
        assert query["limit"] == [str(DEFAULT_PAGE_SIZE)]

    @respx.mock
    @pytest.mark.parametrize("provider", CLASSIFICATION_PROVIDERS)
    def test_provider_is_sent_as_a_query_parameter(self, client, provider):
        route = respx.get(LABELMAPPINGS_URL).mock(
            return_value=httpx.Response(200, json=page(labelmappings(2, provider=provider)))
        )

        df = get_classification_labelmappings(provider, client=client)

        assert query_of(route.calls.last.request)["provider"] == [provider]
        assert set(df["provider"]) == {provider}

    @respx.mock
    def test_limit_is_sent_and_honoured(self, client):
        route = respx.get(LABELMAPPINGS_URL).mock(
            return_value=httpx.Response(200, json=page(labelmappings(5), count=5))
        )

        df = get_classification_labelmappings(limit=2, client=client)

        assert len(df) == 2
        assert query_of(route.calls.last.request)["limit"] == ["2"]

    @pytest.mark.parametrize("provider", ["coralnet", "Coralnet", "reefcloud", "", ["CoralNet"], 1])
    def test_other_providers_raise_listing_the_options(self, client, provider):
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url__regex=r".*")
            with pytest.raises(ValueError) as excinfo:
                get_classification_labelmappings(provider, client=client)
            assert not route.called

        message = str(excinfo.value)
        assert "`provider` must be None or one of" in message
        for option in CLASSIFICATION_PROVIDERS:
            assert f'"{option}"' in message

    @respx.mock
    def test_an_api_error_raises(self, client):
        respx.get(LABELMAPPINGS_URL).mock(return_value=httpx.Response(500, text="boom"))

        with pytest.raises(MermaidAPIError):
            get_classification_labelmappings(client=client)


class TestGetChoices:
    @respx.mock
    def test_returns_a_frame_per_vocabulary(self, client):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=choices_payload()))

        choices = get_choices(client=client)

        assert isinstance(choices, dict)
        assert list(choices) == ["countries", "reeftypes", "empty"]
        assert all(isinstance(frame, pd.DataFrame) for frame in choices.values())
        assert list(choices["countries"]["name"]) == ["Fiji", "Indonesia", "Australia"]
        assert list(choices["countries"].columns) == ["id", "name", "updated_on"]

    @respx.mock
    def test_list_fields_inside_a_vocabulary_are_collapsed(self, client):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=choices_payload()))

        reeftypes = get_choices(client=client)["reeftypes"]

        assert list(reeftypes["regions"]) == ["r1, r2", ""]

    @respx.mock
    def test_an_empty_vocabulary_is_an_empty_frame(self, client):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=choices_payload()))

        assert get_choices(client=client)["empty"].empty

    @respx.mock
    def test_a_missing_data_key_is_an_empty_frame(self, client):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=[{"name": "bare"}]))

        assert get_choices(client=client)["bare"].empty

    @respx.mock
    def test_an_empty_payload_gives_an_empty_dict(self, client):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=[]))

        assert get_choices(client=client) == {}

    @respx.mock
    def test_no_pagination_beyond_the_single_response(self, client):
        """The bare-list payload has no ``next``; exactly one request is made."""
        route = respx.get(CHOICES_URL).mock(
            return_value=httpx.Response(200, json=choices_payload())
        )

        get_choices(client=client)

        assert route.call_count == 1
        request = route.calls.last.request
        assert "Authorization" not in request.headers
        # Not a paginated endpoint, so no page size is requested either.
        assert "limit" not in query_of(request)

    @respx.mock
    def test_a_paginated_envelope_is_also_understood(self, client):
        """Defensive: if the API ever wraps choices in the usual envelope."""
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=page(choices_payload())))

        assert list(get_choices(client=client)) == ["countries", "reeftypes", "empty"]

    @respx.mock
    @pytest.mark.parametrize("payload", [[{"data": []}], ["countries"], [None]])
    def test_a_malformed_vocabulary_raises(self, client, payload):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=payload))

        with pytest.raises(MermaidError, match="Unexpected `choices/` payload"):
            get_choices(client=client)

    @respx.mock
    def test_exported_from_the_package_root(self, client):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=choices_payload()))

        assert "reeftypes" in datamermaid.get_choices(client=client)


class TestCountries:
    @respx.mock
    def test_returns_sorted_country_names(self, client):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=choices_payload()))

        assert countries(client=client) == ["Australia", "Fiji", "Indonesia"]

    @respx.mock
    def test_missing_names_are_skipped(self, client):
        payload = [{"name": "countries", "data": [{"id": "1", "name": "Fiji"}, {"id": "2"}]}]
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=payload))

        assert countries(client=client) == ["Fiji"]

    @respx.mock
    def test_raises_when_the_vocabulary_is_absent(self, client):
        payload = [{"name": "reeftypes", "data": [{"id": "1", "name": "fringing"}]}]
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=payload))

        with pytest.raises(MermaidError, match="no `countries` vocabulary") as excinfo:
            countries(client=client)

        assert "reeftypes" in str(excinfo.value)

    @respx.mock
    def test_raises_when_the_vocabulary_has_no_names(self, client):
        payload = [{"name": "countries", "data": [{"id": "1"}]}]
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=payload))

        with pytest.raises(MermaidError, match="no `countries` vocabulary"):
            countries(client=client)

    @respx.mock
    def test_exported_from_the_package_root(self, client):
        respx.get(CHOICES_URL).mock(return_value=httpx.Response(200, json=choices_payload()))

        assert datamermaid.countries(client=client)[0] == "Australia"


class TestExports:
    @pytest.mark.parametrize(
        "name",
        [
            "CLASSIFICATION_PROVIDERS",
            "KNOWN_ENDPOINTS",
            "REFERENCE_ENDPOINTS",
            "countries",
            "get_choices",
            "get_classification_labelmappings",
            "get_endpoint",
            "get_managements",
            "get_reference",
            "get_sites",
            "get_summary_sampleevents",
            "search_projects",
        ],
    )
    def test_public_names_are_exported(self, name):
        assert name in datamermaid.__all__
        assert hasattr(datamermaid, name)
