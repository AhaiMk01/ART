import os
import subprocess
import sys

import pytest

from art_mcp.preview import pid_alive, sweep_stale


@pytest.fixture
def dead_pid():
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    return done.pid


def make_folder(temp, name):
    folder = temp / name
    folder.mkdir()
    (folder / "preview-0001.jpg").write_bytes(b"x")
    return folder


def test_pid_alive_tells_this_process_from_a_finished_one(dead_pid):
    assert pid_alive(os.getpid())
    assert not pid_alive(dead_pid)


def test_sweep_removes_folders_of_dead_processes_only(tmp_path, dead_pid):
    stale = make_folder(tmp_path, f"art-mcp-{dead_pid}")
    mine = make_folder(tmp_path, f"art-mcp-{os.getpid()}")
    other_alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        alive = make_folder(tmp_path, f"art-mcp-{other_alive.pid}")
        foreign = make_folder(tmp_path, f"art-other-{dead_pid}")
        not_a_pid = make_folder(tmp_path, "art-mcp-preview")
        a_file = tmp_path / f"art-mcp-{dead_pid + 1}"
        a_file.write_text("not a folder")

        sweep_stale(tmp_path)

        assert not stale.exists()
        assert mine.exists() and alive.exists() and foreign.exists() and not_a_pid.exists()
        assert a_file.exists()
    finally:
        other_alive.kill()
        other_alive.wait()


def test_sweep_of_a_missing_temp_folder_does_nothing(tmp_path):
    sweep_stale(tmp_path / "nope")
