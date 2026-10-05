"""The opt-in call log (ART_MCP_CALL_LOG): one JSON line per tool call, written
by one hook for every tool of both servers."""

import json
import re
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from fake_live_art import FakeArt, answer
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer

from art_mcp.calllog import ENV_VAR, CallLog, error_code, shrink_args
from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server as build_render

FAKE = Path(__file__).with_name("fake_artcli.py")
SLOW = Path(__file__).with_name("fake_artcli_ctl.py")  # sleeps FAKE_ARTCLI_SLEEP seconds first
pytestmark = pytest.mark.anyio

LINE_KEYS = {"t", "server", "tool", "ms", "ok", "error", "args", "result_chars", "images", "in_flight"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "calls.jsonl"
    monkeypatch.setenv(ENV_VAR, str(path))
    return path


def read_log(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def compact(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def render_server(tmp_path, script=FAKE):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    return build_render(ArtCli((sys.executable, str(script))), config, PreviewFolder(tmp_path / "previews"))


@pytest.fixture
def server(tmp_path, log_file):
    return render_server(tmp_path)


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    paths = []
    for name in ("FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"):
        (folder / name).write_bytes(b"raw")
        paths.append(folder / name)
    return paths


# --- what one line holds -------------------------------------------------------------------------


async def test_a_call_is_one_line_with_everything_the_summary_needs(server, image, log_file):
    before = datetime.now(UTC) - timedelta(milliseconds=2)
    async with Client(server) as client:
        await client.list_tools()  # not a tool call: not logged
        opened = await client.call_tool("open_image", {"path": str(image)})
    after = datetime.now(UTC)

    (line,) = read_log(log_file)
    assert set(line) == LINE_KEYS
    assert line["server"] == "art-render" and line["tool"] == "open_image"
    assert line["ok"] is True and line["error"] is None
    assert line["args"] == {"path": str(image)}
    assert line["result_chars"] == len(compact(opened.structured_content))
    assert line["images"] == 0 and line["in_flight"] == 1
    assert line["ms"] >= 0
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", line["t"])
    assert before <= datetime.fromisoformat(line["t"]) <= after


async def test_a_tool_error_records_its_code(server, image, log_file):
    async with Client(server) as client:
        result = await client.call_tool("render_preview", {"path": str(image)})

    assert result.is_error
    (line,) = read_log(log_file)
    assert (line["ok"], line["error"]) == (False, "not_open")
    assert line["result_chars"] == len(result.content[0].text)


async def test_arguments_the_schema_refuses_are_invalid_arguments(server, log_file):
    async with Client(server) as client:
        result = await client.call_tool("render_preview", {})  # `path` is required (open_image's is `path` or `paths`)

    assert result.is_error
    (line,) = read_log(log_file)
    assert (line["tool"], line["ok"], line["error"], line["args"]) == ("render_preview", False, "invalid_arguments", {})


async def test_a_tool_the_server_does_not_have_is_unknown_tool(server, log_file):
    async with Client(server) as client:
        result = await client.call_tool("no_such_tool", {"x": 1})

    assert result.is_error
    (line,) = read_log(log_file)
    assert (line["tool"], line["ok"], line["error"], line["args"]) == ("no_such_tool", False, "unknown_tool", {"x": 1})


async def test_an_async_tool_is_timed_to_completion(tmp_path, images, log_file, monkeypatch):
    server = render_server(tmp_path, SLOW)
    out = tmp_path / "out"
    out.mkdir()
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(images[0])})
        monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0.4")
        result = await client.call_tool(
            "export_batch", {"items": [{"path": str(images[0])}], "folder": str(out), "format": "jpeg"}
        )

    assert not result.is_error, result.content
    assert result.structured_content["exported"] == 1
    _, line = read_log(log_file)
    assert line["tool"] == "export_batch" and line["ok"] is True
    assert line["ms"] >= 350


async def test_overlapping_calls_record_how_many_were_being_handled(tmp_path, images, log_file, monkeypatch):
    server = render_server(tmp_path, SLOW)
    async with Client(server) as client:
        for image in images:
            await client.call_tool("open_image", {"path": str(image)})
        monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0.5")

        async def render(image):
            result = await client.call_tool("render_preview", {"path": str(image)})
            assert not result.is_error, result.content

        async with anyio.create_task_group() as tg:
            for image in images:
                tg.start_soon(render, image)
        monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0")
        await render(images[0])  # alone again

    renders = [line for line in read_log(log_file) if line["tool"] == "render_preview"]
    assert sorted(line["in_flight"] for line in renders) == [1, 1, 2, 3]


async def test_a_failing_call_still_counts_down_in_flight(server, image, log_file):
    async with Client(server) as client:
        for _ in range(3):
            await client.call_tool("render_preview", {"path": str(image)})  # not_open

    assert [line["in_flight"] for line in read_log(log_file)] == [1, 1, 1]


async def test_a_result_with_an_image_counts_it_and_not_its_bytes(server, image, log_file):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        preview = await client.call_tool("render_preview", {"path": str(image), "inline": True})

    assert not preview.is_error, preview.content
    assert [c.type for c in preview.content] == ["text", "image"]
    opened, line = read_log(log_file)
    assert opened["images"] == 0
    assert line["images"] == 1
    assert line["result_chars"] == len(compact(preview.structured_content))


async def test_long_arguments_are_cut_down(server, log_file):
    long_path = "a" * 300
    edits = [{"group": "Exposure", "key": "Compensation", "value": str(i)} for i in range(12)]
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": long_path})
        await client.call_tool("edit_profile", {"path": "x", "raw_edits": edits, "adjustments": {"exposure": {"a": 1}}})

    opened, edited = read_log(log_file)
    assert opened["args"] == {"path": "a" * 117 + "..."}
    assert edited["args"] == {
        "path": "x",
        "raw_edits": [["group", "key", "value"], ["group", "key", "value"], "...+10"],
        "adjustments": ["exposure"],
    }


# --- the live server -----------------------------------------------------------------------------


async def test_the_live_server_logs_under_its_own_name(tmp_path, log_file):
    art = FakeArt(tmp_path / "art")
    try:
        art.ops["status"] = answer({"version": "1.26.test", "images": []})
        async with Client(build_live(ControlChannel(art.config_dir))) as client:
            status = await client.call_tool("status", {})
    finally:
        art.close()

    (line,) = read_log(log_file)
    assert (line["server"], line["tool"], line["ok"], line["error"]) == ("art-live", "status", True, None)
    assert line["result_chars"] == len(compact(status.structured_content))


async def test_the_live_server_records_a_tool_error_code(tmp_path, log_file):
    async with Client(build_live(ControlChannel(tmp_path / "no-art"))) as client:
        await client.call_tool("status", {})

    (line,) = read_log(log_file)
    assert (line["server"], line["ok"], line["error"]) == ("art-live", False, "art_not_running")


# --- off, and failing safely ---------------------------------------------------------------------


async def test_without_the_variable_nothing_is_written_and_no_hook_is_added(tmp_path, image, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    server = render_server(tmp_path)
    async with Client(server) as client:
        result = await client.call_tool("open_image", {"path": str(image)})

    assert not result.is_error, result.content
    assert not list(tmp_path.rglob("*.jsonl"))
    assert len(server.middleware) == len(MCPServer("bare").middleware)


async def test_an_empty_variable_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "")
    server = render_server(tmp_path)

    assert len(server.middleware) == len(MCPServer("bare").middleware)


async def test_an_unwritable_log_warns_once_and_the_calls_still_work(tmp_path, image, monkeypatch, capsys):
    monkeypatch.setenv(ENV_VAR, str(tmp_path))  # a folder, not a file
    server = render_server(tmp_path)
    async with Client(server) as client:
        opened = await client.call_tool("open_image", {"path": str(image)})
        again = await client.call_tool("render_preview", {"path": str(image)})
        third = await client.call_tool("render_preview", {"path": str(image)})

    assert not opened.is_error and not again.is_error and not third.is_error
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and ENV_VAR in err[0]


async def test_a_missing_log_folder_is_created(tmp_path, image, monkeypatch):
    path = tmp_path / "runs" / "omp-1" / "calls.jsonl"
    monkeypatch.setenv(ENV_VAR, str(path))
    async with Client(render_server(tmp_path)) as client:
        await client.call_tool("open_image", {"path": str(image)})

    assert len(read_log(path)) == 1


# --- the hook itself -----------------------------------------------------------------------------


def request(name="open_image", arguments=None, method="tools/call"):
    return SimpleNamespace(method=method, params={"name": name, "arguments": arguments or {}})


async def test_an_exception_in_the_chain_is_logged_and_still_raised(tmp_path):
    path = tmp_path / "calls.jsonl"

    async def boom(ctx):
        raise RuntimeError("secret detail")

    with pytest.raises(RuntimeError):
        await CallLog(path, "art-render")(request(), boom)

    (line,) = read_log(path)
    assert (line["ok"], line["error"], line["result_chars"], line["images"]) == (False, "exception", 0, 0)
    assert "secret detail" not in path.read_text(encoding="utf-8")


async def test_a_cancelled_call_is_logged_as_cancelled(tmp_path):
    path = tmp_path / "calls.jsonl"

    async def hang(ctx):
        await anyio.sleep_forever()

    with anyio.move_on_after(0.1):
        await CallLog(path, "art-render")(request(), hang)

    (line,) = read_log(path)
    assert (line["ok"], line["error"]) == (False, "cancelled")
    assert line["ms"] >= 50


async def test_other_requests_pass_straight_through(tmp_path):
    path = tmp_path / "calls.jsonl"

    async def reply(ctx):
        return {"tools": []}

    assert await CallLog(path, "art-render")(request(method="tools/list"), reply) == {"tools": []}
    assert not path.exists()


async def test_a_result_that_cannot_be_measured_does_not_break_the_call(tmp_path):
    path = tmp_path / "calls.jsonl"

    async def odd(ctx):
        return {"content": 5, "structuredContent": object()}

    assert await CallLog(path, "art-render")(request(), odd) is not None


def test_error_codes_come_from_the_text_of_the_error():
    assert error_code("Error executing tool open_image: not_found: no such file") == "not_found"
    assert error_code("Error executing tool edit_profile: out_of_range: x") == "out_of_range"
    assert error_code("art_not_running: start ART") == "art_not_running"
    assert error_code("Error executing tool open_image") == "exception"
    assert error_code("Error executing tool open_image: 1 validation error for open_imageArguments") == (
        "invalid_arguments"
    )
    assert error_code("Unknown tool: nope") == "unknown_tool"
    assert error_code("something else entirely") == "error"
    assert error_code("") == "error"


def test_arguments_are_shrunk_by_type():
    long = "x" * 121
    assert shrink_args({}) == {}
    assert shrink_args({"n": 3, "f": 0.5, "b": True, "none": None, "s": "short"}) == {
        "n": 3, "f": 0.5, "b": True, "none": None, "s": "short",
    }  # fmt: skip
    assert shrink_args({"s": "y" * 120}) == {"s": "y" * 120}
    assert shrink_args({"s": long}) == {"s": "x" * 117 + "..."}
    assert shrink_args({"l": ["a", "b"]}) == {"l": ["a", "b"]}
    assert shrink_args({"l": ["a", "b", "c", "d", "e"]}) == {"l": ["a", "b", "...+3"]}
    assert shrink_args({"l": []}) == {"l": []}
    assert shrink_args({"d": {"x": 1, "y": {"deep": 1}}}) == {"d": ["x", "y"]}
    assert shrink_args({"l": [{"a": 1, "b": 2}, long, [1, 2, 3]]}) == {"l": [["a", "b"], "x" * 117 + "...", "...+1"]}
    many = {f"k{i}": i for i in range(200)}
    assert len(shrink_args({"d": many})["d"]) == 51  # the first 50 keys and "...+150"
    assert shrink_args({"d": many})["d"][-1] == "...+150"


def test_lines_from_several_threads_and_servers_never_mix(tmp_path):
    path = tmp_path / "calls.jsonl"
    logs = [CallLog(path, "art-render"), CallLog(path, "art-live")]

    def write(log, tag):
        for i in range(100):
            log.write({"tag": tag, "i": i, "pad": "é" * 2000})

    threads = [threading.Thread(target=write, args=(logs[n % 2], n)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = read_log(path)
    assert len(lines) == 600
    assert sorted((line["tag"], line["i"]) for line in lines) == [(t, i) for t in range(6) for i in range(100)]


def test_lines_from_several_processes_never_mix(tmp_path):
    path = tmp_path / "calls.jsonl"
    script = (
        "import sys\n"
        "from art_mcp.calllog import CallLog\n"
        "log = CallLog(sys.argv[1], 'art-render')\n"
        "for i in range(100):\n"
        "    log.write({'tag': sys.argv[2], 'i': i, 'pad': 'é' * 2000})\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", script, str(path), str(n)]) for n in range(4)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]

    lines = read_log(path)
    assert sorted((line["tag"], line["i"]) for line in lines) == [(str(t), i) for t in range(4) for i in range(100)]
