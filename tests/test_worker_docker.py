import subprocess

import pytest
from helpers import CONST, at, count_spec, make_mission, publish, write_program

from scienceme.archive import Archive
from scienceme.model import Isolation, Target
from scienceme.pmf import Pmf
from scienceme.predict import run_origin
from scienceme.record import RecordStore
from scienceme.registry import Registry
from scienceme.worker import IMAGE_ENV, WorkerError, build_order, resolve_image, run_order
from scienceme.worker_entry import Failure

pytestmark = pytest.mark.docker

STREAM = "w/adm"
BARE_IMAGE = "scienceme-bare:test"
NO_PYTHON_IMAGE = "scienceme-no-python:test"
TARGET = Target(stream=STREAM, jurisdiction="A", reference_week=2, horizon=0)

NET = (
    "import socket\nfrom scienceme.sdk import Pmf\n"
    "def predict(ctx, target):\n"
    "    try:\n        socket.create_connection(('1.1.1.1', 80), timeout=2)\n        return Pmf.point(0)\n"
    "    except OSError:\n        return Pmf.point(1)\n"
)
SLEEP = "import time\nfrom scienceme.sdk import Pmf\ndef predict(ctx, target):\n    time.sleep(300)\n    return Pmf.point(1)\n"
WRITE_WORK = (
    "from scienceme.sdk import Pmf\n"
    "def predict(ctx, target):\n"
    "    try:\n        open('/work/intruder', 'w')\n        return Pmf.point(0)\n"
    "    except OSError:\n        return Pmf.point(1)\n"
)


@pytest.fixture
def view(ws):
    publish(ws, count_spec(), 3, {("A", 1): 5, ("B", 1): 6}, at(1))
    return Archive(ws).view([STREAM], as_of=3, published_by=at(2))


def run_in_container(ws, view, image, code, timeout_s=120, name="p", **fields):
    write_program(ws, name, code, **fields)
    h = Registry(ws).freeze(name, at(0)).closure_hash
    return run_order(ws, build_order(ws, h, view, [TARGET]), Isolation.CONTAINER, timeout_s, image).results[0]


def running_workers() -> str:
    return subprocess.run(
        ["docker", "ps", "-q", "--filter", "name=sm-"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_container_runs_a_program_and_its_imports(ws, view, docker_image):
    write_program(ws, "core", "def level():\n    return 3\n", library=True)
    hc = Registry(ws).freeze("core", at(0)).closure_hash
    code = (
        "from scienceme.sdk import Pmf, imports_of\n"
        "IMPORTS = imports_of(__name__)\n"
        "def predict(ctx, target):\n    return Pmf.point(IMPORTS['core'].level())\n"
    )
    assert run_in_container(ws, view, docker_image, code, imports={"core": hc}).pmf == Pmf.point(3)


def test_container_has_no_network(ws, view, docker_image):
    assert run_in_container(ws, view, docker_image, NET).pmf == Pmf.point(1)


def test_container_cannot_see_the_host_archive(ws, view, docker_image):
    assert ws.archive.is_dir()
    code = (
        "import os\nfrom scienceme.sdk import Pmf\n"
        "def predict(ctx, target):\n"
        f"    return Pmf.point(int(os.path.exists({str(ws.archive)!r}) is False))\n"
    )
    assert run_in_container(ws, view, docker_image, code).pmf == Pmf.point(1)


def test_container_work_mount_is_read_only(ws, view, docker_image):
    assert run_in_container(ws, view, docker_image, WRITE_WORK).pmf == Pmf.point(1)


def test_container_timeout_kills_the_container(ws, view, docker_image):
    result = run_in_container(ws, view, docker_image, SLEEP, timeout_s=5)
    assert result == Failure(target=TARGET, error="timeout")
    assert running_workers() == ""


def test_a_missing_image_is_a_worker_error(ws, view):
    with pytest.raises(WorkerError, match="exit code 125") as error:
        run_in_container(ws, view, "scienceme-no-such-image:0", CONST)
    assert "scienceme-no-such-image" in str(error.value)
    assert running_workers() == ""


def build_image(tag: str, dockerfile: str) -> str:
    subprocess.run(["docker", "build", "-q", "-t", tag, "-"], input=dockerfile, text=True, capture_output=True, check=True)
    return tag


def test_an_image_with_a_shell_but_no_python_is_a_worker_error(ws, view, docker_image):
    image = build_image(NO_PYTHON_IMAGE, f"FROM {docker_image}\nRUN rm /usr/local/bin/python /usr/local/bin/python3*\n")
    with pytest.raises(WorkerError, match="exit code 127"):
        run_in_container(ws, view, image, CONST)


def test_an_image_without_a_shell_is_a_worker_error(ws, view):
    image = build_image(BARE_IMAGE, 'FROM scratch\nCMD ["/nothing"]\n')
    with pytest.raises(WorkerError, match="exit code 127"):
        run_in_container(ws, view, image, CONST)


def test_a_program_that_crashes_the_interpreter_fails_its_targets(ws, view, docker_image):
    code = "import os\ndef predict(ctx, target):\n    os._exit(3)\n"
    assert run_in_container(ws, view, docker_image, code) == Failure(target=TARGET, error="no-result")


@pytest.mark.parametrize("status", [125, 126, 127])
def test_a_program_cannot_forge_dockers_exit_codes(ws, view, docker_image, status):
    code = f"import os\ndef predict(ctx, target):\n    os._exit({status})\n"
    assert run_in_container(ws, view, docker_image, code) == Failure(target=TARGET, error="no-result")


def test_container_has_no_capabilities_and_cannot_gain_privileges(ws, view, docker_image):
    code = (
        "from scienceme.sdk import Pmf\n"
        "def predict(ctx, target):\n"
        "    status = dict(line.split(':\\t', 1) for line in open('/proc/self/status').read().splitlines() if ':\\t' in line)\n"
        "    caps = int(status['CapEff'], 16) | int(status['CapBnd'], 16)\n"
        "    return Pmf.point(int(caps == 0 and status['NoNewPrivs'].strip() == '1'))\n"
    )
    assert run_in_container(ws, view, docker_image, code).pmf == Pmf.point(1)


FILL_OUT = (
    "import os\nfrom scienceme.sdk import Pmf\n"
    "def predict(ctx, target):\n"
    "    junk = os.path.join('/out', 'junk')\n"
    "    try:\n"
    "        with open(junk, 'wb') as f:\n"
    "            for _ in range(256):\n                f.write(b'x' * (1 << 20))\n"
    "        return Pmf.point(0)\n"
    "    except OSError:\n"
    "        os.remove(junk)\n        return Pmf.point(1)\n"
)


def test_container_output_is_bounded(ws, view, docker_image):
    assert run_in_container(ws, view, docker_image, FILL_OUT).pmf == Pmf.point(1)


def test_a_program_printing_to_stdout_keeps_its_result(ws, view, docker_image):
    code = "from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    print('noise ' * 1000)\n    return Pmf.point(2)\n"
    assert run_in_container(ws, view, docker_image, code).pmf == Pmf.point(2)


def image_id(image: str) -> str:
    return subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_resolve_image_gives_the_content_id(docker_image):
    assert resolve_image(docker_image) == image_id(docker_image)
    assert resolve_image(docker_image).startswith("sha256:")


def test_resolving_a_missing_image_is_a_worker_error():
    with pytest.raises(WorkerError):
        resolve_image("scienceme-no-such-image:test")


def test_a_container_origin_records_the_image_it_ran(ws, docker_image, monkeypatch):
    monkeypatch.setenv(IMAGE_ENV, docker_image)
    write_program(ws, "p", CONST)
    Registry(ws).freeze("p", at(0))
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    run_origin(ws, make_mission(required_isolation=Isolation.CONTAINER), 1, Isolation.CONTAINER, at(3))
    records = RecordStore(ws).all("m")
    assert records and {r.image for r in records} == {image_id(docker_image)}
