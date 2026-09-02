"""The README quickstart, run against a mocked MERMAID API.

This script walks the same path as the README -- sign in, find projects, pull
project data, pull reference data -- but every request is answered by an
in-process ``httpx.MockTransport`` rather than the real API, so it runs
offline, needs no account, and ``tests/test_docs.py`` executes it to make sure
the documented calls keep working.

Run it with::

    python examples/quickstart.py

To talk to the real API instead, drop the ``MermaidClient(transport=...)`` and
call ``datamermaid.authenticate()`` first; everything else stays the same.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

try:
    import httpx

    import datamermaid
    from datamermaid import MermaidClient
except ImportError as exc:  # explain what to install, instead of a deep traceback
    import sys

    # `python -P` and PYTHONSAFEPATH=1 keep this directory off sys.path, and the
    # helper below lives in it; without this the handler would fail in its turn.
    sys.path.insert(0, str(Path(__file__).parent))
    from _preflight import missing_dependency

    raise missing_dependency(exc) from None

# Survey CSVs are the fixtures the test suite uses, which are trimmed copies of
# real MERMAID responses.
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

PROJECTS = [
    {
        "id": "00673bec-0000-4000-8000-000000000001",
        "name": "WCS Fiji Reef Monitoring",
        "countries": ["Fiji"],
        "num_sites": 12,
        "tags": [{"id": "t1", "name": "WCS Fiji"}],
        "notes": "",
        "status": 90,
        "data_policy_beltfish": "public summary",
        "created_on": "2020-01-01T00:00:00Z",
        "updated_on": "2021-01-01T00:00:00Z",
    },
    {
        "id": "00673bec-0000-4000-8000-000000000002",
        "name": "Sulawesi Community Reefs",
        "countries": ["Indonesia"],
        "num_sites": 4,
        "tags": [{"id": "t2", "name": "Community"}],
        "notes": "",
        "status": 90,
        "data_policy_beltfish": "private",
        "created_on": "2020-06-01T00:00:00Z",
        "updated_on": "2021-06-01T00:00:00Z",
    },
]

SITES = [
    {
        "id": f"site-{i}",
        "name": name,
        "notes": "",
        "project": PROJECTS[0]["id"],
        "country": "Fiji",
        "reef_type": "fringing",
        "reef_zone": "crest",
        "exposure": "exposed",
        "created_on": "2020-01-01T00:00:00Z",
        "updated_on": "2021-01-01T00:00:00Z",
    }
    for i, name in enumerate(["Namena", "Vatu-i-Ra", "Kubulau"], start=1)
]

FISH_FAMILIES = [
    {"id": "ff-1", "name": "Acanthuridae", "updated_on": "2020-01-01T00:00:00Z"},
    {"id": "ff-2", "name": "Scaridae", "updated_on": "2020-01-01T00:00:00Z"},
]

ME = {
    "id": "profile-1",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "full_name": "Ada Lovelace",
    "email": "ada@example.org",
}


def envelope(results: list[dict]) -> httpx.Response:
    """Wrap ``results`` in MERMAID's pagination envelope, as a single page."""
    payload = {"count": len(results), "next": None, "previous": None, "results": results}
    return httpx.Response(200, json=payload)


def handle(request: httpx.Request) -> httpx.Response:
    """Answer a request the way api.datamermaid.org would."""
    path = urlparse(str(request.url)).path.removeprefix("/v1/").strip("/")
    parts = path.split("/")

    if path == "me":
        return httpx.Response(200, json=ME)
    if path == "projects":
        return envelope(PROJECTS)
    if path == "fishfamilies":
        return envelope(FISH_FAMILIES)
    if parts[0] == "projects" and parts[2:] == ["sites"]:
        return envelope(SITES)
    if parts[0] == "projects" and parts[-1] == "csv":
        # projects/{id}/beltfishes/{slug}/csv -> tests/fixtures/fishbelt_{level}.csv
        level = {
            "obstransectbeltfishes": "observations",
            "sampleunits": "sampleunits",
            "sampleevents": "sampleevents",
        }[parts[3]]
        return httpx.Response(200, text=(FIXTURES / f"fishbelt_{level}.csv").read_text())
    return httpx.Response(404, json={"detail": f"Not found: {path}"})


def main() -> None:
    # A real session would call ``datamermaid.authenticate()`` here.  With a
    # token in hand -- from that call, or from MERMAID_API_TOKEN -- the client
    # sends it on every request that needs a login.
    client = MermaidClient(token="not-a-real-token", transport=httpx.MockTransport(handle))
    datamermaid.set_default_client(client)

    me = datamermaid.get_me()
    print(f"Signed in as {me['full_name']} <{me['email']}>\n")

    # Find projects: yours, or anyone's public ones.
    my_projects = datamermaid.get_my_projects()
    print("My projects:")
    print(my_projects[["id", "name", "countries", "num_sites"]].to_string(index=False), "\n")

    fiji = datamermaid.search_projects(country="Fiji", tag="WCS")
    print("Public projects matching country=Fiji, tag=WCS:")
    print(fiji[["name", "tags"]].to_string(index=False), "\n")

    # Pull project data.  Any function taking a project accepts an id, a list
    # of ids, or a frame of projects.
    sites = datamermaid.get_project_sites(fiji)
    print("Sites:")
    print(sites[["project", "name", "reef_type", "reef_zone"]].to_string(index=False), "\n")

    # Set a default so it can be left out of later calls.
    datamermaid.set_default_project(fiji)

    fishbelt = datamermaid.get_project_data(method="fishbelt", data="all")
    for level, frame in fishbelt["fishbelt"].items():
        print(f"fishbelt/{level}: {len(frame)} rows x {frame.shape[1]} columns")
    sample_events = fishbelt["fishbelt"]["sampleevents"]
    print(sample_events[["site", "sample_date", "biomass_kgha_avg"]].to_string(index=False), "\n")

    # Reference data needs no login.
    families = datamermaid.get_reference("fishfamilies")
    print("Fish families:", ", ".join(families["name"]), "\n")

    # The method/level -> endpoint mapping is pure and needs no login either.
    print("Endpoints for fishbelt:")
    print(json.dumps(datamermaid.construct_endpoints()["fishbelt"], indent=2))

    datamermaid.set_default_project(None)
    datamermaid.set_default_client(None)
    client.close()


if __name__ == "__main__":
    main()
