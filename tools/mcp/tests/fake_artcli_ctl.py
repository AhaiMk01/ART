"""Misbehaving stand-in for ART-cli, steered by environment variables, for
tests of the runner's robustness. Without any of them it behaves exactly like
``fake_artcli.py``.

- ``FAKE_ARTCLI_SLEEP``: seconds to sleep before doing anything else.
- ``FAKE_ARTCLI_LOG``: folder to drop one ``<time_ns>-<pid>-start|end`` file
  into per event, to observe how many runs overlap (appending to a shared file
  loses lines on Windows).
- ``FAKE_ARTCLI_EXIT``: exit with this code (without writing any output).
- ``FAKE_ARTCLI_SKIP``: exit 0 without writing the output, like ART skipping
  an input.
"""

import os
import runpy
import sys
import time
from pathlib import Path

log = os.environ.get("FAKE_ARTCLI_LOG")


def note(event):
    if log:
        (Path(log) / f"{time.time_ns()}-{os.getpid()}-{event}").touch()


if sys.argv[1:] != ["-v"]:
    note("start")
    time.sleep(float(os.environ.get("FAKE_ARTCLI_SLEEP", "0")))
    note("end")
    if "FAKE_ARTCLI_EXIT" in os.environ:
        print("fake failure", file=sys.stderr)
        sys.exit(int(os.environ["FAKE_ARTCLI_EXIT"]))
    if "FAKE_ARTCLI_SKIP" in os.environ:
        sys.exit(0)

sys.argv[0] = str(Path(__file__).with_name("fake_artcli.py"))
runpy.run_path(sys.argv[0], run_name="__main__")
