import subprocess
from pathlib import Path

import pytest

from scienceme.workspace import Workspace

REPO = Path(__file__).resolve().parent.parent
TEST_IMAGE = "scienceme-worker:test"


def pytest_addoption(parser):
    parser.addoption("--docker", action="store_true", default=False, help="run the tests that need a docker daemon")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--docker"):
        return
    skip = pytest.mark.skip(reason="needs a docker daemon; run with --docker")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def ws(tmp_path):
    return Workspace.create(tmp_path)


@pytest.fixture(scope="session")
def docker_image() -> str:
    """Build the worker image from the working tree once per session; return its tag."""
    subprocess.run(
        ["docker", "build", "-q", "-f", "scorer/Dockerfile", "-t", TEST_IMAGE, "."],
        cwd=REPO,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return TEST_IMAGE
