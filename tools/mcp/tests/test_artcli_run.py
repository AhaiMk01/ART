"""ArtCli.run against a misbehaving fake art-cli."""

import sys
import threading
import time
from pathlib import Path

import pytest

from art_mcp.render.artcli import ArtCli, ArtCliError, ArtCliTimeout

CTL = Path(__file__).with_name("fake_artcli_ctl.py")


@pytest.fixture
def cli():
    return ArtCli((sys.executable, str(CTL)))


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "IMG_1.ARW"
    img.write_bytes(b"raw")
    return img


def test_a_per_call_timeout_overrides_the_instance_timeout(cli, monkeypatch, image, tmp_path):
    monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "10")
    started = time.monotonic()

    with pytest.raises(ArtCliTimeout, match="0.5"):
        cli.run(["-o", str(tmp_path / "o.jpg"), "-c", str(image)], timeout=0.5)

    assert time.monotonic() - started < 5


@pytest.mark.parametrize(
    ("code", "meaning"),
    [
        (-3, "bad arguments"),
        (-2, "load or save"),
        (-1, "unknown option"),
        (1, "stray argument"),
        (2, "no input"),
    ],
)
def test_exit_codes_are_explained(cli, monkeypatch, image, tmp_path, code, meaning):
    monkeypatch.setenv("FAKE_ARTCLI_EXIT", str(code))

    with pytest.raises(ArtCliError) as e:
        cli.run(["-o", str(tmp_path / "o.jpg"), "-c", str(image)])

    assert meaning in str(e.value)
    assert f"exited with {code}" in str(e.value)
    assert "fake failure" in str(e.value)


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows NTSTATUS exit code")
def test_a_missing_dll_is_explained(cli, monkeypatch, image, tmp_path):
    monkeypatch.setenv("FAKE_ARTCLI_EXIT", str(-1073741515))  # 0xC0000135

    with pytest.raises(ArtCliError) as e:
        cli.run(["-o", str(tmp_path / "o.jpg"), "-c", str(image)])

    assert "DLL" in str(e.value) and "PATH" in str(e.value)


def peak_overlap(log: Path) -> tuple[int, int]:
    """(runs, most that ran at once) from the fake's event files."""
    events = sorted(p.name.split("-", 2)[0::2] for p in log.iterdir())
    running = peak = starts = 0
    for _, event in events:
        starts += event == "start"
        running += 1 if event == "start" else -1
        peak = max(peak, running)
    return starts, peak


def test_at_most_two_art_cli_processes_run_at_once(cli, monkeypatch, image, tmp_path):
    log = tmp_path / "log"
    log.mkdir()
    monkeypatch.setenv("FAKE_ARTCLI_LOG", str(log))
    monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0.4")

    def render(n):
        cli.run(["-o", str(tmp_path / f"o{n}.jpg"), "-c", str(image)])

    threads = [threading.Thread(target=render, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak_overlap(log) == (6, 2)
