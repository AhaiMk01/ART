import json
import os
import socket

import pytest

from art_mcp.live.channel import ArtNotRunning, ChannelError, ChannelTimeout, ControlChannel
from fake_live_art import FakeArt, answer, fail


@pytest.fixture
def art(tmp_path):
    fake = FakeArt(tmp_path / "config")
    yield fake
    fake.close()


def channel(art: FakeArt, **kw) -> ControlChannel:
    return ControlChannel(art.config_dir, **kw)


def test_token_goes_first_then_one_json_line_per_request(art):
    result = channel(art).request("status")

    assert result == {"version": "1.26.test", "images": []}
    token_line, request_line = art.received
    assert json.loads(token_line) == {"token": "s3cret"}
    assert token_line.endswith(b"\n") and request_line.endswith(b"\n")
    request = json.loads(request_line)
    assert request["op"] == "status" and request["args"] == {}
    assert isinstance(request["id"], int)


def test_args_are_sent_and_non_ascii_survives(art):
    art.ops["echo"] = lambda req: (json.dumps({"id": req["id"], "ok": True, "result": req["args"]}) + "\n").encode()

    assert channel(art).request("echo", {"path": "C:/Fotos/Größe.ARW"}) == {"path": "C:/Fotos/Größe.ARW"}


def test_error_reply_carries_arts_code_and_message(art):
    art.ops["status"] = fail("not_open", "no such image")

    with pytest.raises(ChannelError) as e:
        channel(art).request("status")

    assert (e.value.code, e.value.message) == ("not_open", "no such image")


def test_reply_to_another_id_is_rejected(art):
    art.ops["status"] = lambda req: b'{"id": 999, "ok": true, "result": {}}\n'

    with pytest.raises(ChannelError, match="bad_reply"):
        channel(art).request("status")


def test_reply_that_is_not_json_is_rejected(art):
    art.ops["status"] = lambda req: b"hello\n"

    with pytest.raises(ChannelError, match="bad_reply"):
        channel(art).request("status")


def test_wrong_token_is_closed_and_reported_as_not_running(art):
    art.write_discovery(pid=os.getpid(), token="stale")

    with pytest.raises(ArtNotRunning, match="refused"):
        channel(art).request("status")
    assert art.rejected == 1


def test_no_discovery_file_is_not_running_with_the_hint(tmp_path):
    with pytest.raises(ArtNotRunning, match="--live-control"):
        ControlChannel(tmp_path).request("status")


def test_dead_pid_is_not_running(art):
    with pytest.raises(ArtNotRunning, match="no longer running"):
        channel(art, is_alive=lambda pid: False).request("status")
    assert art.received == []


def test_refused_connection_is_not_running(tmp_path):
    with socket.create_server(("127.0.0.1", 0)) as s:
        port = s.getsockname()[1]
    (tmp_path / "live-control.json").write_text(json.dumps({"port": port, "token": "t", "pid": 1, "version": ""}))

    with pytest.raises(ArtNotRunning, match="--live-control"):
        ControlChannel(tmp_path, is_alive=lambda pid: True).request("status")


def test_garbled_discovery_file_is_not_running(tmp_path):
    (tmp_path / "live-control.json").write_text("{not json")

    with pytest.raises(ArtNotRunning):
        ControlChannel(tmp_path).request("status")


def test_no_answer_times_out(art):
    art.ops["status"] = lambda req: None

    with pytest.raises(ChannelTimeout):
        channel(art, timeout=0.3).request("status")


def test_each_request_rereads_the_discovery_file(art, tmp_path):
    ch = channel(art)
    ch.request("status")
    restarted = FakeArt(art.config_dir, token="new-token")
    restarted.ops["status"] = answer({"version": "2", "images": []})
    try:
        assert ch.request("status")["version"] == "2"
    finally:
        restarted.close()


def test_the_timeout_covers_the_whole_reply_not_each_chunk(art):
    import time

    art.ops["slow"] = lambda req: [b"{"] * 20  # never finishes a line
    started = time.monotonic()

    with pytest.raises(ChannelTimeout):
        channel(art, timeout=1.0).request("slow")
    assert time.monotonic() - started < 3


def test_a_reset_after_a_refused_token_still_names_the_token(art):
    art.reset_on_reject = True
    art.write_discovery(os.getpid(), token="stale")

    with pytest.raises(ArtNotRunning) as e:
        channel(art).request("status")
    assert "refused" in str(e.value)
