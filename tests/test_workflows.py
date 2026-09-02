"""Drift guards for the GitHub Actions workflows.

Nothing here runs a workflow -- only a push to ``main`` can prove the Pages
deploy works.  What these tests do catch is the two ways the docs workflow
regressed before: a marketplace action pinned to a major that still ships
Node 20 (the runners warn about it and will eventually refuse), and a deploy
job that reaches ``actions/deploy-pages`` without Pages having been switched to
"GitHub Actions" as its source, which answers 404 and reads as a broken build.

The files are parsed as text, like ``mkdocs.yml`` in ``tests/test_docs.py``:
the offline suite has no PyYAML, and the shapes these workflows use are simple
enough for a line-oriented split.  ``actionlint`` is the real validation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

#: Action -> the first major version that runs on Node 24.  A pin below this is
#: what raises "Node 20 is being deprecated" on every run.  Raising a bound
#: here is fine; lowering one is the regression.
MIN_ACTION_MAJORS = {
    "actions/checkout": 5,
    "actions/configure-pages": 6,
    "actions/upload-pages-artifact": 5,
    "actions/deploy-pages": 5,
}


def _jobs(workflow: str) -> dict[str, str]:
    """Split a workflow's ``jobs:`` block into ``name -> body`` text.

    Whole-line comments are dropped first: the block explaining a job sits
    above its name, so it would otherwise be read as part of the job before it.
    """
    block = re.search(r"^jobs:\n(.*)\Z", workflow, re.M | re.S)
    assert block, "workflow has no jobs: block"
    lines = [line for line in block.group(1).splitlines() if not line.lstrip().startswith("#")]
    body = "\n".join(lines)
    starts = list(re.finditer(r"^  (\w+):$", body, re.M))
    assert starts, "jobs: block names no jobs"
    bounds = [match.start() for match in starts] + [len(body)]
    return {match.group(1): body[bounds[i] : bounds[i + 1]] for i, match in enumerate(starts)}


@pytest.fixture(scope="module")
def workflows() -> dict[str, str]:
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files, f"no workflows found in {WORKFLOWS}"
    return {path.name: path.read_text() for path in files}


@pytest.fixture(scope="module")
def docs_jobs(workflows) -> dict[str, str]:
    return _jobs(workflows["docs.yml"])


def test_actions_are_pinned_past_node_20(workflows):
    outdated = []
    for name, text in workflows.items():
        for action, major in re.findall(r"uses:\s*(actions/[\w-]+)@v(\d+)", text):
            minimum = MIN_ACTION_MAJORS.get(action)
            assert minimum, f"{name} uses {action}, which needs a MIN_ACTION_MAJORS entry"
            if int(major) < minimum:
                outdated.append(f"{name}: {action}@v{major} (needs >= v{minimum})")
    assert not outdated, f"actions still on a Node 20 major: {outdated}"


def test_docs_workflow_enables_pages_itself(docs_jobs):
    """The 404 this fixes: nothing had ever set Source = "GitHub Actions"."""
    assert "configure" in docs_jobs, "docs.yml has no configure job"
    configure = docs_jobs["configure"]
    assert "actions/configure-pages@" in configure
    assert "enablement: true" in configure
    # Without this the workflow trades one red job for another.
    assert "continue-on-error: true" in configure
    assert "pages: write" in configure


def test_deploy_is_gated_on_pages_being_enabled(docs_jobs):
    deploy = docs_jobs["deploy"]
    assert "needs.configure.outputs.pages_ready == 'success'" in deploy
    assert re.search(r"needs:.*\bconfigure\b", deploy)


def test_docs_build_job_needs_no_write_permission(docs_jobs):
    """`pages: write` on the build job would hand it to pull request code too."""
    build = docs_jobs["build"]
    assert not re.search(r"^    permissions:", build, re.M)
    assert "write" not in build


def test_docs_workflow_still_gates_pull_requests(docs_jobs):
    build = docs_jobs["build"]
    assert "mkdocs build --strict" in build
    # The build itself is unconditional; only the upload is main-only.
    assert not re.search(r"^    if:", build, re.M)
