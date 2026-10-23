import pytest

from scienceme.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    return Workspace.create(tmp_path)
