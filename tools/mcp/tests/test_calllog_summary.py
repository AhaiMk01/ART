"""The call-log summariser, on a hand-written log (every expected number is
worked out by hand, not computed by the code under test)."""

import json
import subprocess
import sys

import pytest

from art_mcp.calllog import main, summarise

# Written the way the servers write: one line per call when it ENDS, so the
# file is in completion order, not arrival order. Arrivals (t) and completions
# (t + ms), in seconds after 10:00:00:
#   open_image      0.0 -> 0.2     ok
#   open_image      1.0 -> 1.3     not_found
#   render_preview  2.0 -> 5.0     ok, 1 image     (overlaps the next two)
#   edit_profile    2.5 -> 2.7     ok
#   edit_profile    2.6 -> 2.7     out_of_range
#   render_preview  6.0 -> 6.5     ok, 1 image
LOG = "\n".join([
    '{"t":"2026-10-05T10:00:00.000Z","server":"art-render","tool":"open_image","ms":200,"ok":true,"error":null,'
    '"args":{"path":"a"},"result_chars":100,"images":0,"in_flight":1}',
    '{"t":"2026-10-05T10:00:01.000Z","server":"art-render","tool":"open_image","ms":300,"ok":false,'
    '"error":"not_found","args":{"path":"b"},"result_chars":50,"images":0,"in_flight":1}',
    '{"t":"2026-10-05T10:00:02.500Z","server":"art-render","tool":"edit_profile","ms":200,"ok":true,"error":null,'
    '"args":{},"result_chars":60,"images":0,"in_flight":2}',
    "",
    '{"t":"2026-10-05T10:00:02.600Z","server":"art-render","tool":"edit_profile","ms":100,"ok":false,'
    '"error":"out_of_range","args":{},"result_chars":40,"images":0,"in_flight":3}',
    "this line is not json",
    '{"t":"2026-10-05T10:00:02.000Z","server":"art-render","tool":"render_preview","ms":3000,"ok":true,'
    '"error":null,"args":{},"result_chars":400,"images":1,"in_flight":1}',
    '{"t":"2026-10-05T10:00:06.000Z","server":"art-render","tool":"render_preview","ms":500,"ok":true,'
    '"error":null,"args":{},"result_chars":4000,"images":1,"in_flight":1}',
    "",
])


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "calls.jsonl"
    path.write_text(LOG, encoding="utf-8")
    return path


def test_totals(log):
    s = summarise(log)

    assert s["calls"] == 6
    assert s["wall_seconds"] == pytest.approx(6.5)  # first arrival 10:00:00.000, last completion 10:00:06.500
    assert s["first_arrival"] == "2026-10-05T10:00:00.000Z"
    assert s["last_completion"] == "2026-10-05T10:00:06.500Z"
    assert s["distinct_tools"] == 3
    assert s["errors"] == 2
    assert s["error_codes"] == {"not_found": 1, "out_of_range": 1}
    assert s["images"] == 2
    assert s["max_in_flight"] == 3
    assert s["result_chars"] == 100 + 50 + 60 + 40 + 400 + 4000
    assert s["servers"] == ["art-render"]
    assert s["skipped_lines"] == 1  # the line that is not JSON; blank lines are not counted


def test_per_tool_in_order_of_calls_then_first_use(log):
    assert summarise(log)["per_tool"] == [
        {"tool": "open_image", "calls": 2, "errors": 1, "result_chars": 150, "ms": 500},
        {"tool": "render_preview", "calls": 2, "errors": 0, "result_chars": 4400, "ms": 3500},
        {"tool": "edit_profile", "calls": 2, "errors": 1, "result_chars": 100, "ms": 300},
    ]


def test_a_tool_with_more_calls_comes_first(tmp_path):
    lines = [
        {"t": f"2026-10-05T10:00:0{i}.000Z", "server": "s", "tool": tool, "ms": 1, "ok": True, "error": None,
         "args": {}, "result_chars": 1, "images": 0, "in_flight": 1}
        for i, tool in enumerate(["a", "b", "b", "c", "c", "c"])
    ]  # fmt: skip
    path = tmp_path / "x.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    assert [t["tool"] for t in summarise(path)["per_tool"]] == ["c", "b", "a"]


def test_largest_results_first(log):
    assert summarise(log)["largest_results"] == [
        {"tool": "render_preview", "result_chars": 4000, "t": "2026-10-05T10:00:06.000Z"},
        {"tool": "render_preview", "result_chars": 400, "t": "2026-10-05T10:00:02.000Z"},
        {"tool": "open_image", "result_chars": 100, "t": "2026-10-05T10:00:00.000Z"},
        {"tool": "edit_profile", "result_chars": 60, "t": "2026-10-05T10:00:02.500Z"},
        {"tool": "open_image", "result_chars": 50, "t": "2026-10-05T10:00:01.000Z"},
    ]


def test_first_errors_in_order_of_arrival(log):
    assert summarise(log)["first_errors"] == [
        {"t": "2026-10-05T10:00:01.000Z", "tool": "open_image", "error": "not_found"},
        {"t": "2026-10-05T10:00:02.600Z", "tool": "edit_profile", "error": "out_of_range"},
    ]


def test_only_the_first_five_errors_are_listed(tmp_path):
    lines = [
        {"t": f"2026-10-05T10:00:{i:02d}.000Z", "server": "s", "tool": "t", "ms": 1, "ok": False, "error": f"e{i}",
         "args": {}, "result_chars": 1, "images": 0, "in_flight": 1}
        for i in range(8)
    ]  # fmt: skip
    path = tmp_path / "x.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    s = summarise(path)

    assert s["errors"] == 8
    assert [e["error"] for e in s["first_errors"]] == ["e0", "e1", "e2", "e3", "e4"]


def test_the_sequence_is_in_arrival_order_with_runs_collapsed(log):
    assert summarise(log)["sequence"] == [
        ["open_image", 2],
        ["render_preview", 1],
        ["edit_profile", 2],
        ["render_preview", 1],
    ]


def test_an_empty_log_summarises_to_nothing(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    s = summarise(path)

    assert (s["calls"], s["wall_seconds"], s["distinct_tools"], s["max_in_flight"]) == (0, 0, 0, 0)
    assert s["per_tool"] == [] and s["sequence"] == [] and s["first_errors"] == []


def test_the_report_reads_at_a_glance(log, capsys):
    assert main(["summarise", str(log)]) == 0

    out = capsys.readouterr().out
    assert "6 calls in 6.5 s" in out
    assert "3 tools" in out and "max in flight 3" in out and "2 images" in out
    assert "2 errors" in out and "not_found x1" in out and "out_of_range x1" in out
    assert "open_image x2, render_preview, edit_profile x2, render_preview" in out
    assert "10:00:01.000" in out and "not_found" in out  # the first errors
    assert "4,000" in out  # the largest result
    assert "skipped 1 line" in out


def test_a_missing_file_is_a_clean_error(tmp_path, capsys):
    assert main(["summarise", str(tmp_path / "nope.jsonl")]) == 2
    assert "nope.jsonl" in capsys.readouterr().err


def test_json_output(log, capsys):
    assert main(["summarise", "--json", str(log)]) == 0

    assert json.loads(capsys.readouterr().out)["calls"] == 6


def test_runs_as_a_module(log):
    done = subprocess.run(
        [sys.executable, "-m", "art_mcp.calllog", "summarise", str(log)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )  # fmt: skip

    assert done.returncode == 0, done.stderr
    assert "6 calls in 6.5 s" in done.stdout
