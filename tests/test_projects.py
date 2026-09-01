"""Tests for the public project endpoints."""

from __future__ import annotations

import httpx
import respx

from datamermaid import get_projects, search_projects
from datamermaid.client import DEFAULT_BASE_URL, DEFAULT_PAGE_SIZE
from datamermaid.projects import _filter_projects, _is_test_project

PROJECTS_URL = DEFAULT_BASE_URL + "projects/"

PROJECTS = [
    {
        "id": "1",
        "name": "Kubulau Reefs",
        "countries": ["Fiji"],
        "tags": [{"name": "WCS Fiji"}],
        "status": 90,
    },
    {
        "id": "2",
        "name": "Karimunjawa",
        "countries": ["Indonesia"],
        "tags": [{"name": "WCS"}],
        "status": 90,
    },
    {"id": "3", "name": "Test project", "countries": ["Fiji"], "tags": [], "status": 80},
]


def page(results, next_url=None):
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


@respx.mock
def test_get_projects_asks_for_all_public_projects():
    route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(PROJECTS)))

    projects = get_projects()

    request = route.calls.last.request
    assert request.url.params["showall"] == "true"
    assert "authorization" not in request.headers
    assert [project["id"] for project in projects] == ["1", "2"]  # test project dropped


@respx.mock
def test_get_projects_can_include_test_projects():
    respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(PROJECTS)))

    assert len(get_projects(include_test_projects=True)) == 3


@respx.mock
def test_get_projects_limit_is_applied_after_filtering():
    respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(PROJECTS)))

    assert [project["id"] for project in get_projects(limit=1)] == ["1"]


@respx.mock
def test_search_projects_matches_name_country_and_tag():
    respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(PROJECTS)))

    assert [p["id"] for p in search_projects(name="kubulau")] == ["1"]
    assert [p["id"] for p in search_projects(country="indonesia")] == ["2"]
    assert [p["id"] for p in search_projects(tag="WCS")] == ["1", "2"]
    assert search_projects(name="Kubulau", country="Indonesia") == []


def test_filters_understand_comma_separated_fields():
    """Some MERMAID endpoints flatten ``countries``/``tags`` into strings."""
    flattened = [{"id": "9", "name": "Flat", "countries": "Fiji, Tonga", "tags": "WCS, TNC"}]

    assert _filter_projects(flattened, country="tonga") == flattened
    assert _filter_projects(flattened, tag="TNC") == flattened
    assert _filter_projects(flattened, country="Palau") == []


def test_filters_handle_missing_fields():
    sparse = [{"id": "9", "name": "Sparse"}]

    assert _filter_projects(sparse, name="sparse") == sparse
    assert _filter_projects(sparse, country="Fiji") == []
    assert _filter_projects(sparse, tag="WCS") == []


def test_test_projects_are_recognised_by_code_or_label():
    assert _is_test_project({"status": 80})
    assert _is_test_project({"status": "Test"})
    assert not _is_test_project({"status": 90})
    assert not _is_test_project({})


def test_filters_stringify_unexpected_field_types():
    odd = [{"id": "9", "name": "Odd", "tags": 42}]

    assert _filter_projects(odd, tag="42") == odd


@respx.mock
def test_get_projects_lets_the_api_apply_the_limit():
    route = respx.get(PROJECTS_URL).mock(
        return_value=httpx.Response(200, json=page(PROJECTS[:1], next_url=PROJECTS_URL + "?p=2"))
    )

    assert [project["id"] for project in get_projects(limit=1)] == ["1"]

    assert route.calls.last.request.url.params["limit"] == "1"
    assert route.call_count == 1  # no paging beyond what the limit needs


@respx.mock
def test_get_projects_keeps_paging_until_the_limit_is_filled():
    """Test projects are dropped locally, so a short page can be all filler."""
    route = respx.get(PROJECTS_URL).mock(
        side_effect=[
            httpx.Response(200, json=page([PROJECTS[2]], next_url=PROJECTS_URL + "?p=2")),
            httpx.Response(200, json=page([PROJECTS[0]])),
        ]
    )

    assert [project["id"] for project in get_projects(limit=1)] == ["1"]
    assert route.call_count == 2


@respx.mock
def test_search_projects_fetches_everything_before_limiting():
    route = respx.get(PROJECTS_URL).mock(return_value=httpx.Response(200, json=page(PROJECTS)))

    assert [project["id"] for project in search_projects(tag="WCS", limit=1)] == ["1"]

    assert route.calls.last.request.url.params["limit"] == str(DEFAULT_PAGE_SIZE)
