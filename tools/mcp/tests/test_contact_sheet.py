import json
import sys
from datetime import datetime
from pathlib import Path

import anyio
import pytest
from mcp.client.client import Client
from PIL import Image

from art_mcp.contactsheet import HEADER_HEIGHT, LABEL_HEIGHT, PAD
from art_mcp.preview import PreviewFolder
from art_mcp.render import sheet_ops
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def real_jpegs(monkeypatch):
    monkeypatch.setenv("FAKE_REAL_JPEG", "1")


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    paths = []
    for name in ("FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"):
        (folder / name).write_bytes(b"raw")
        paths.append(folder / name)
    return paths


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def make_server(tmp_path, previews, **cli_args):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    return build_server(ArtCli((sys.executable, str(FAKE)), **cli_args), config, PreviewFolder(tmp_path / previews))


@pytest.fixture
def server(tmp_path):
    return make_server(tmp_path, "previews")


async def open_all(client, images):
    for image in images:
        await client.call_tool("open_image", {"path": str(image)})


def compensation(value):
    return [{"group": "Exposure", "key": "Compensation", "value": value}]


async def sheet(client, images, folder=None, **kwargs):
    args = {"images": [str(p) for p in images], **kwargs}
    if folder is not None:
        args["folder"] = str(folder)
    return await client.call_tool("contact_sheet", args)


async def test_renders_the_open_images_into_a_labelled_grid_saved_as_pass_one(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        result = await sheet(client, images, out)

    assert not result.is_error, result.content
    data = result.structured_content
    jpeg = out / "sheets" / "pass-01.jpg"
    assert data["path"] == str(jpeg)
    assert data["index"] == 1
    assert data["rendered"] == 3 and data["failed"] == 0
    with Image.open(jpeg) as grid:
        assert grid.format == "JPEG"
        assert grid.size == (data["width"], data["height"])
    assert [i["name"] for i in data["images"]] == ["FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"]
    assert [i["path"] for i in data["images"]] == [str(p.resolve()) for p in images]
    assert {p.name for p in (out / "sheets").iterdir()} == {"pass-01.jpg", "pass-01.json", "profiles.json"}
    assert list(out.iterdir()) == [out / "sheets"]
    assert not any(p.suffix == ".jpg" for p in images[0].parent.iterdir())  # nothing next to the sources


def thumbnail_colour(jpeg, entry):
    x, y, w, h = entry["box"]
    with Image.open(jpeg) as grid:
        return grid.convert("RGB").getpixel((x + w // 2, y + h // 2))


def same_colour(a, b):
    return all(abs(p - q) <= 3 for p, q in zip(a, b, strict=True))


async def test_thumbnails_are_small_fast_renders_of_each_working_profile(images, out, tmp_path, monkeypatch):
    log = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
    # one art-cli at a time: the fake's log is not safe for concurrent appends
    server = make_server(tmp_path, "previews", max_processes=1)
    async with Client(server) as client:
        await open_all(client, images)
        await client.call_tool("edit_profile", {"path": str(images[1]), "raw_edits": compensation("1.5")})
        log.write_text("")
        result = await sheet(client, images, out, thumb_size=200)

    runs = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(runs) == 3
    assert all("-f" in r and "-d" not in r for r in runs)
    data = result.structured_content
    first, second, third = data["images"]
    assert max(first["box"][2:]) == 200  # long edge = thumb_size
    colours = [thumbnail_colour(data["path"], e) for e in (first, second, third)]
    assert same_colour(colours[0], colours[2]) and not same_colour(colours[0], colours[1])


async def test_every_call_saves_a_new_numbered_pass_and_keeps_the_earlier_ones(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        first = await sheet(client, images, out)
        first_bytes = Path(first.structured_content["path"]).read_bytes()
        second = await sheet(client, images, out, label="Black Point!")
        third = await sheet(client, images, out, label="roll ratios")

    assert [r.structured_content["index"] for r in (first, second, third)] == [1, 2, 3]
    names = sorted(p.name for p in (out / "sheets").iterdir() if p.name.startswith("pass-"))
    assert names == [
        "pass-01.jpg", "pass-01.json",
        "pass-02-Black-Point.jpg", "pass-02-Black-Point.json",
        "pass-03-roll-ratios.jpg", "pass-03-roll-ratios.json",
    ]  # fmt: skip
    assert Path(first.structured_content["path"]).read_bytes() == first_bytes
    record = json.loads((out / "sheets" / "pass-02-Black-Point.json").read_text())
    assert record["label"] == "Black Point!" and record["sheet"] == "pass-02-Black-Point.jpg"
    assert datetime.fromisoformat(record["time"]).tzinfo is not None


async def test_numbering_continues_after_passes_already_in_the_folder(server, images, out):
    sheets = out / "sheets"
    sheets.mkdir()
    (sheets / "pass-07-old.jpg").write_bytes(b"old")
    (sheets / "pass-07-old.json").write_text("{}")
    async with Client(server) as client:
        await open_all(client, images)
        result = await sheet(client, images, out)

    assert result.structured_content["index"] == 8
    assert (sheets / "pass-07-old.jpg").read_bytes() == b"old"


async def test_a_label_with_nothing_to_name_a_file_by_is_refused(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        result = await sheet(client, images, out, label="***")

    assert result.is_error and "out_of_range" in result.content[0].text
    assert not (out / "sheets").exists()


def black(value):
    return [{"group": "Exposure", "key": "Black", "value": value}]


def record(result):
    """The pass JSON the result points at: the per-frame detail."""
    return json.loads(Path(result.structured_content["json_path"]).read_text(encoding="utf-8"))


def compensation_change(before, after, images):
    return {"group": "Exposure", "key": "Compensation", "before": before, "after": after, "images": images}


async def test_the_result_summarises_the_keys_changed_since_the_last_pass_and_the_record_has_them_per_frame(
    server, images, out
):
    async with Client(server) as client:
        await open_all(client, images)
        first = await sheet(client, images, out)
        await client.call_tool("edit_profile", {"path": str(images[1]), "raw_edits": compensation("1.5")})
        second = await sheet(client, images, out)
        third = await sheet(client, images, out)

    assert all(i["changed"] is None and i["since_pass"] is None for i in first.structured_content["images"])
    one, two, three = second.structured_content["images"]
    assert (one["changed"], one["since_pass"]) == (0, 1)
    assert (two["changed"], two["since_pass"]) == (1, 1)
    assert second.structured_content["changes"] == {
        "groups": [compensation_change("0", "1.5", ["FILM_2.ARW"])],
        "more": 0,
    }
    assert all(i["changed"] == 0 and i["since_pass"] == 2 for i in third.structured_content["images"])
    assert third.structured_content["changes"] == {"groups": [], "more": 0}
    on_disk = record(second)
    assert on_disk["index"] == 2
    assert on_disk["images"][1]["changes"] == [
        {"group": "Exposure", "key": "Compensation", "before": "0", "after": "1.5"}
    ]
    assert on_disk["images"][0]["changes"] == [] and on_disk["images"][0]["since_pass"] == 1
    assert [i["name"] for i in on_disk["images"]] == ["FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"]


async def test_the_first_pass_has_nothing_to_compare_with(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        first = await sheet(client, images, out)

    data = first.structured_content
    assert data["changes"] is None
    assert all(i["changed"] is None and i["since_pass"] is None for i in data["images"])
    assert all("changes" not in i for i in data["images"])  # the per-frame lists are only in the record
    assert all(i["changes"] is None and i["since_pass"] is None for i in record(first)["images"])


async def test_an_identical_change_on_three_frames_is_one_entry_naming_them_and_the_record_keeps_each(
    server, images, out
):
    async with Client(server) as client:
        await open_all(client, images)
        await sheet(client, images, out)
        for image in images:
            await client.call_tool("edit_profile", {"path": str(image), "raw_edits": compensation("1.5")})
        await client.call_tool("edit_profile", {"path": str(images[1]), "raw_edits": black("40")})
        second = await sheet(client, images, out)

    data = second.structured_content
    assert data["changes"] == {
        "groups": [
            compensation_change("0", "1.5", ["FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"]),
            {"group": "Exposure", "key": "Black", "before": "0", "after": "40", "images": ["FILM_2.ARW"]},
        ],
        "more": 0,
    }
    assert [i["changed"] for i in data["images"]] == [1, 2, 1]
    per_frame = [[(c["key"], c["after"]) for c in i["changes"]] for i in record(second)["images"]]
    assert per_frame == [
        [("Compensation", "1.5")],
        [("Compensation", "1.5"), ("Black", "40")],
        [("Compensation", "1.5")],
    ]


async def test_only_the_most_shared_changes_are_listed_and_the_warning_points_at_the_record(
    server, images, out, monkeypatch
):
    monkeypatch.setattr(sheet_ops, "MAX_SHARED_CHANGES", 2)
    async with Client(server) as client:
        await open_all(client, images)
        await sheet(client, images, out)
        for image in images:
            await client.call_tool("edit_profile", {"path": str(image), "raw_edits": compensation("1.5")})
        await client.call_tool("edit_profile", {"path": str(images[1]), "raw_edits": black("40")})
        await client.call_tool("edit_profile", {"path": str(images[2]), "raw_edits": black("50")})
        second = await sheet(client, images, out)
        third = await sheet(client, images, out)

    data = second.structured_content
    assert [(g["key"], len(g["images"])) for g in data["changes"]["groups"]] == [("Compensation", 3), ("Black", 1)]
    assert data["changes"]["more"] == 1
    assert "1 more" in data["warnings"][0] and data["json_path"] in data["warnings"][0]
    assert [i["changed"] for i in data["images"]] == [1, 2, 2]  # the counts and the record are complete
    assert sum(len(i["changes"]) for i in record(second)["images"]) == 5
    assert third.structured_content["warnings"] == []  # nothing left out, nothing to warn about


async def test_numbers_come_out_in_their_shortest_form_in_the_result_and_the_record(server, images, out):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await client.call_tool("edit_profile", {"path": str(images[0]), "raw_edits": compensation("1.355")})
        await sheet(client, images[:1], out)
        await client.call_tool(
            "edit_profile", {"path": str(images[0]), "raw_edits": compensation("1.3700000000000001")}
        )
        second = await sheet(client, images[:1], out)

    assert second.structured_content["changes"]["groups"] == [compensation_change("1.355", "1.37", ["FILM_1.ARW"])]
    assert [(c["before"], c["after"]) for c in record(second)["images"][0]["changes"]] == [("1.355", "1.37")]
    assert "1.3700000000000001" not in Path(second.structured_content["json_path"]).read_text()
    # the bookkeeping profile is not a report: it keeps the value as ART wrote it
    kept = json.loads((out / "sheets" / "profiles.json").read_text())
    assert [e["profile"]["Exposure"]["Compensation"] for e in kept.values()] == ["1.3700000000000001"]


async def test_a_curve_is_shortened_token_by_token(images, out, tmp_path, monkeypatch):
    default = tmp_path / "default.arp"
    default.write_text("[Exposure]\nCompensation=0\n\n[ToneCurve]\nEnabled=false\nCurve=0;\n")
    monkeypatch.setenv("FAKE_DEFAULT_PROFILE", str(default))
    curve = "1;0.098000000000000004;0;0.59999999999999998;0.59999999999999998;1;1;"
    async with Client(make_server(tmp_path, "previews")) as client:
        await open_all(client, images[:1])
        await sheet(client, images[:1], out)
        edit = await client.call_tool(
            "edit_profile",
            {"path": str(images[0]), "raw_edits": [{"group": "ToneCurve", "key": "Curve", "value": curve}]},
        )
        second = await sheet(client, images[:1], out)

    assert not edit.is_error, edit.content
    [group] = second.structured_content["changes"]["groups"]
    assert (group["group"], group["key"]) == ("ToneCurve", "Curve")
    assert (group["before"], group["after"]) == ("0;", "1;0.098;0;0.6;0.6;1;1;")
    assert record(second)["images"][0]["changes"][0]["after"] == "1;0.098;0;0.6;0.6;1;1;"


async def test_a_number_written_differently_is_not_a_change(server, images, out):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await client.call_tool("edit_profile", {"path": str(images[0]), "raw_edits": compensation("-0.0216")})
        await sheet(client, images[:1], out)
        await client.call_tool(
            "edit_profile", {"path": str(images[0]), "raw_edits": compensation("-0.021600000000000001")}
        )
        second = await sheet(client, images[:1], out)
        await client.call_tool("edit_profile", {"path": str(images[0]), "raw_edits": compensation("-0.03")})
        third = await sheet(client, images[:1], out)

    assert second.structured_content["images"][0]["changed"] == 0
    assert second.structured_content["changes"] == {"groups": [], "more": 0}
    assert record(second)["images"][0]["changes"] == []
    # and the pass after it is measured from what it was, shown short
    assert third.structured_content["changes"]["groups"] == [compensation_change("-0.0216", "-0.03", ["FILM_1.ARW"])]


async def test_changes_are_measured_from_the_last_pass_an_image_was_in(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        await sheet(client, images[:2], out)  # pass 1: frames 1 and 2
        await client.call_tool("edit_profile", {"path": str(images[0]), "raw_edits": compensation("0.5")})
        second = await sheet(client, images[1:], out)  # pass 2: frames 2 and 3
        third = await sheet(client, images, out)

    # frame 3 is new in pass 2: nothing to compare, and it counts for nothing in the summary
    assert [i["changed"] for i in second.structured_content["images"]] == [0, None]
    assert second.structured_content["changes"] == {"groups": [], "more": 0}
    one, two, three = third.structured_content["images"]
    assert one["since_pass"] == 1 and one["changed"] == 1
    assert two["since_pass"] == 2 and two["changed"] == 0
    assert three["since_pass"] == 2 and three["changed"] == 0
    assert third.structured_content["changes"]["groups"] == [compensation_change("0", "0.5", ["FILM_1.ARW"])]
    assert [c["key"] for c in record(third)["images"][0]["changes"]] == ["Compensation"]


async def test_changes_survive_a_restart_of_the_server(server, images, out, tmp_path):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await sheet(client, images[:1], out)
    restarted = make_server(tmp_path, "previews2")
    async with Client(restarted) as client:
        await open_all(client, images[:1])
        await client.call_tool("edit_profile", {"path": str(images[0]), "raw_edits": compensation("2")})
        result = await sheet(client, images[:1], out)

    entry = result.structured_content["images"][0]
    assert result.structured_content["index"] == 2 and entry["since_pass"] == 1 and entry["changed"] == 1
    assert [g["after"] for g in result.structured_content["changes"]["groups"]] == ["2"]
    assert [c["after"] for c in record(result)["images"][0]["changes"]] == ["2"]


async def test_the_folder_defaults_to_where_the_last_batch_was_exported(server, images, out, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    async with Client(server) as client:
        await open_all(client, images)
        refused = await sheet(client, images)
        await client.call_tool(
            "export_batch",
            {"items": [{"path": str(images[0])}], "folder": str(elsewhere), "format": "jpeg"},
        )
        await client.call_tool(
            "export_batch",
            {"items": [{"path": str(images[0])}], "folder": str(out), "format": "jpeg"},
        )
        result = await sheet(client, images)

    assert refused.is_error and "out_of_range" in refused.content[0].text
    assert result.structured_content["path"] == str(out / "sheets" / "pass-01.jpg")
    assert not (elsewhere / "sheets").exists()


async def test_a_batch_that_exported_nothing_does_not_set_the_default_folder(server, images, out):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await client.call_tool(
            "export_batch",
            {"items": [{"path": str(images[1])}], "folder": str(out), "format": "jpeg"},  # not open
        )
        result = await sheet(client, images[:1])

    assert result.is_error and "out_of_range" in result.content[0].text


async def test_the_folder_must_exist(server, images, tmp_path):
    async with Client(server) as client:
        await open_all(client, images)
        result = await sheet(client, images, tmp_path / "nope")

    assert result.is_error and "not_found" in result.content[0].text


async def test_an_image_that_is_not_open_is_a_placeholder_and_the_others_still_render(server, images, out):
    async with Client(server) as client:
        await open_all(client, images[:1])
        result = await sheet(client, images[:2], out)

    assert not result.is_error, result.content
    data = result.structured_content
    first, second = data["images"]
    assert first["error"] is None and first["box"] is not None
    assert second["error"].startswith("not_open") and second["box"] is None
    assert second["changed"] is None and second["since_pass"] is None
    assert data["rendered"] == 1 and data["failed"] == 1
    assert (out / "sheets" / "pass-01.jpg").is_file()


async def test_one_failing_render_is_that_images_error(server, images, out):
    async with Client(server) as client:
        await open_all(client, images[:2])
        images[1].unlink()  # art-cli exits 2 for a missing input
        result = await sheet(client, images[:2], out)
        images[1].write_bytes(b"raw")
        await client.call_tool("edit_profile", {"path": str(images[1]), "raw_edits": compensation("1")})
        again = await sheet(client, images[:2], out)

    first, second = result.structured_content["images"]
    assert first["error"] is None
    assert second["error"].startswith("render_failed") and second["box"] is None
    # its profile was still recorded, so the next pass compares with it
    redone = again.structured_content["images"][1]
    assert redone["error"] is None and redone["since_pass"] == 1 and redone["changed"] == 1
    assert [(c["before"], c["after"]) for c in record(again)["images"][1]["changes"]] == [("0", "1")]


async def test_an_image_without_a_profile_has_nothing_to_compare(server, images, out):
    async with Client(server) as client:
        await open_all(client, images[:2])
        await sheet(client, images[:2], out)
        again = await sheet(client, images[:2], out)
        gone = await sheet(client, [images[2], images[0]], out)  # frame 3 was never open

    assert [i["since_pass"] for i in again.structured_content["images"]] == [1, 1]
    assert gone.structured_content["images"][0]["since_pass"] is None
    assert gone.structured_content["images"][0]["changed"] is None
    assert record(gone)["images"][0]["changes"] is None
    assert gone.structured_content["images"][1]["since_pass"] == 2


async def test_a_damaged_bookkeeping_file_is_no_earlier_pass(server, images, out):
    sheets = out / "sheets"
    sheets.mkdir()
    (sheets / "profiles.json").write_text('{"x": 1, "' + str(images[0]).lower() + '": {"pass": "no"}}')
    async with Client(server) as client:
        await open_all(client, images[:1])
        first = await sheet(client, images[:1], out)
        (sheets / "profiles.json").write_text("not json")
        second = await sheet(client, images[:1], out)

    for result in (first, second):
        entry = result.structured_content["images"][0]
        assert entry["since_pass"] is None and entry["changed"] is None
        assert result.structured_content["changes"] is None


async def test_nothing_rendered_fails_the_call_and_saves_no_pass(server, images, out):
    async with Client(server) as client:
        result = await sheet(client, images, out)  # none open

    assert result.is_error and "render_failed" in result.content[0].text
    assert not (out / "sheets").exists()


async def test_a_folder_stands_for_the_open_images_in_it(server, images, out, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "OTHER_1.ARW").write_bytes(b"raw")
    async with Client(server) as client:
        await open_all(client, [images[2], images[0], other / "OTHER_1.ARW"])
        result = await sheet(client, [images[0].parent, images[0]], out)  # the folder, then one of its images again
        empty = await sheet(client, [tmp_path / "out"], out)

    assert [i["name"] for i in result.structured_content["images"]] == ["FILM_1.ARW", "FILM_3.ARW"]
    assert empty.is_error and "not_open" in empty.content[0].text


async def test_arguments_are_checked_before_anything_renders(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        results = [
            await client.call_tool("contact_sheet", {"images": [], "folder": str(out)}),
            await sheet(client, images, out, thumb_size=10),
            await sheet(client, images, out, thumb_size=5000),
            await sheet(client, images, out, columns=0),
            await sheet(client, images, out, columns=99),
        ]

    assert all(r.is_error and "out_of_range" in r.content[0].text for r in results)
    assert not (out / "sheets").exists()


async def test_columns_set_the_grid_and_fewer_images_than_columns_make_a_narrower_sheet(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        wide = await sheet(client, images, out)
        two = await sheet(client, images, out, columns=2, thumb_size=100)

    assert wide.structured_content["columns"] == 3
    assert two.structured_content["columns"] == 2
    boxes = [i["box"] for i in two.structured_content["images"]]
    assert boxes[0][1] == boxes[1][1] and boxes[2][1] > boxes[0][1]  # two to a row
    assert boxes[2][0] == boxes[0][0]


async def test_a_sheet_too_big_to_be_shown_whole_carries_a_warning(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        big = await sheet(client, images, out, columns=3, thumb_size=1000)
        small = await sheet(client, images, out, thumb_size=100)

    assert "2576" in big.structured_content["warnings"][0]
    assert small.structured_content["warnings"] == []


async def test_reports_progress_per_image(server, images, out):
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total))

    async with Client(server) as client:
        await open_all(client, images)
        await client.call_tool(
            "contact_sheet",
            {"images": [str(p) for p in images], "folder": str(out)},
            progress_callback=on_progress,
        )

    assert sorted(seen) == [(1, 3), (2, 3), (3, 3)]


async def test_overlapping_calls_get_different_numbers(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        async with anyio.create_task_group() as tg:
            results = []

            async def one():
                results.append(await sheet(client, images, out))

            for _ in range(3):
                tg.start_soon(one)

    assert sorted(r.structured_content["index"] for r in results) == [1, 2, 3]
    assert len(list((out / "sheets").glob("pass-*.jpg"))) == 3


async def test_a_pass_that_cannot_be_written_leaves_no_files(server, images, out):
    sheets = out / "sheets"
    (sheets / "profiles.json").mkdir(parents=True)  # in the way of the bookkeeping file
    async with Client(server) as client:
        await open_all(client, images)
        result = await sheet(client, images, out)

    assert result.is_error and "render_failed" in result.content[0].text
    assert [p.name for p in sheets.iterdir()] == ["profiles.json"]


async def test_leaves_no_temporary_files_behind(server, images, out, tmp_path):
    async with Client(server) as client:
        await open_all(client, images)
        await sheet(client, images, out)
        leftovers = list((tmp_path / "previews").iterdir())

    assert leftovers == []


# -- record=false: a look, not a pass ---------------------------------------


async def test_without_record_the_sheet_goes_to_the_preview_folder_and_no_pass_is_kept(server, images, out, tmp_path):
    previews = tmp_path / "previews"
    async with Client(server) as client:
        await open_all(client, images)
        # no folder, and no export_batch to default to: a pass would be refused
        result = await sheet(client, images, record=False, thumb_size=700)
        with_folder = await sheet(client, images, out, record=False, thumb_size=100)
        listing = sorted(p.name for p in previews.iterdir())
        with Image.open(result.structured_content["path"]) as grid:  # the folder goes with the server
            grid_format, grid_size = grid.format, grid.size

    assert not result.is_error, result.content
    data = result.structured_content
    jpeg = Path(data["path"])
    assert jpeg.parent == previews and jpeg.suffix == ".jpg" and data["sheet"] == jpeg.name
    assert grid_format == "JPEG" and grid_size == (data["width"], data["height"])
    assert data["rendered"] == 3 and data["failed"] == 0 and data["warnings"] == []
    assert data["index"] is None and data["json_path"] is None and data["changes"] is None
    assert [i["name"] for i in data["images"]] == ["FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"]
    assert all(i["error"] is None and i["since_pass"] is None and i["changed"] is None for i in data["images"])
    assert all(i["box"] and max(i["box"][2:]) == 700 for i in data["images"])
    # a folder that is given is not used; each sheet is a new file, and the thumbnails are gone
    other = Path(with_folder.structured_content["path"])
    assert other.parent == previews and other != jpeg
    assert listing == sorted([jpeg.name, other.name])
    assert list(out.iterdir()) == []


async def test_an_unrecorded_sheet_takes_no_part_in_the_passes_comparisons(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        await sheet(client, images, out, thumb_size=100)
        await client.call_tool("edit_profile", {"path": str(images[1]), "raw_edits": compensation("1.5")})
        look = await sheet(client, images, out, record=False, thumb_size=100)
        await client.call_tool("edit_profile", {"path": str(images[2]), "raw_edits": compensation("0.5")})
        second = await sheet(client, images, out, thumb_size=100)

    assert look.structured_content["changes"] is None
    assert second.structured_content["index"] == 2  # the look took no number
    assert {p.name for p in (out / "sheets").iterdir()} == {
        "pass-01.jpg", "pass-01.json", "pass-02.jpg", "pass-02.json", "profiles.json"
    }
    # both edits count against pass 1: the look did not move the baseline
    assert [i["changed"] for i in second.structured_content["images"]] == [0, 1, 1]
    assert [i["since_pass"] for i in second.structured_content["images"]] == [1, 1, 1]


async def test_without_record_the_columns_default_to_what_suits_the_number_of_frames(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        recorded = await sheet(client, images, out, thumb_size=700)
        quick = await sheet(client, images, record=False, thumb_size=700)
        three = await sheet(client, images, record=False, thumb_size=700, columns=3)
        bad = await sheet(client, images, record=False, columns=0)
        small = await sheet(client, images, record=False, thumb_size=10)

    assert recorded.structured_content["columns"] == 3  # unchanged: min(frames, 6)
    assert quick.structured_content["columns"] == 2
    assert quick.structured_content["width"] < 2576 and quick.structured_content["warnings"] == []
    assert three.structured_content["columns"] == 3
    assert bad.is_error and "out_of_range" in bad.content[0].text
    assert small.is_error and "out_of_range" in small.content[0].text


async def test_an_unrecorded_sheet_still_names_a_failing_image_and_renders_the_others(server, images):
    async with Client(server) as client:
        await open_all(client, images[:2])
        result = await sheet(client, images, record=False, thumb_size=100)
        nothing = await sheet(client, images[2:], record=False)

    first, _, third = result.structured_content["images"]
    assert result.structured_content["rendered"] == 2 and result.structured_content["failed"] == 1
    assert first["error"] is None and third["error"].startswith("not_open:") and third["box"] is None
    assert nothing.is_error and "render_failed" in nothing.content[0].text


@pytest.mark.parametrize(
    ("count", "thumb_size", "columns"),
    [
        (1, 400, 1), (2, 700, 2), (3, 700, 2), (4, 1000, 2), (5, 700, 3),
        (6, 700, 3), (6, 1000, 2), (12, 400, 4), (40, 32, 7),
    ],
)  # fmt: skip
def test_quick_columns_make_a_square_grid_that_still_fits_the_width_claude_shows(count, thumb_size, columns):
    assert sheet_ops.quick_columns(count, thumb_size) == columns


# -- compare_passes ---------------------------------------------------------


async def compare(client, first, second, folder=None, **kwargs):
    args = {"first": first, "second": second, **kwargs}
    if folder is not None:
        args["folder"] = str(folder)
    return await client.call_tool("compare_passes", args)


async def before_and_after(client, images, out):
    """Pass 1 as opened, pass 2 after frame 2's exposure changed."""
    await open_all(client, images)
    await sheet(client, images, out, label="before", thumb_size=100)
    await client.call_tool("edit_profile", {"path": str(images[1]), "raw_edits": compensation("1.5")})
    await sheet(client, images, out, label="after", thumb_size=100)


def pair_colours(jpeg, index, columns=2, size=100):
    """The colours at the centre of the left and right frame of pair ``index``
    (the fake's 6000x4000 frame is 100x67 at ``size`` 100)."""
    cell_w, frame_h = 2 * size + PAD, round(size * 4000 / 6000)
    x0 = PAD + (index % columns) * (cell_w + PAD)
    y0 = HEADER_HEIGHT + PAD + (index // columns) * (frame_h + LABEL_HEIGHT + PAD)
    y = y0 + frame_h // 2
    with Image.open(jpeg) as grid:
        rgb = grid.convert("RGB")
        return rgb.getpixel((x0 + size // 2, y)), rgb.getpixel((x0 + size + PAD + size // 2, y))


async def test_two_passes_side_by_side_for_every_frame_they_share(server, images, out):
    async with Client(server) as client:
        await before_and_after(client, images, out)
        result = await compare(client, 1, 2, out)

    assert not result.is_error, result.content
    data = result.structured_content
    jpeg = out / "sheets" / "compare-01-02.jpg"
    assert data["path"] == str(jpeg) and (data["first"], data["second"]) == (1, 2)
    assert data["images"] == ["FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"]
    with Image.open(jpeg) as grid:
        assert grid.format == "JPEG" and grid.size == (data["width"], data["height"])
    (left0, right0), (left1, right1) = pair_colours(jpeg, 0), pair_colours(jpeg, 1)
    assert same_colour(left0, right0)  # frame 1 did not change
    assert same_colour(left1, left0) and not same_colour(left1, right1)  # frame 2 did


async def test_chosen_frames_by_path_or_file_name(server, images, out):
    async with Client(server) as client:
        await before_and_after(client, images, out)
        result = await compare(client, 1, 2, out, images=[str(images[2]), "film_2.arw"])

    assert result.structured_content["images"] == ["FILM_3.ARW", "FILM_2.ARW"]


async def test_comparisons_are_kept_too(server, images, out):
    async with Client(server) as client:
        await before_and_after(client, images, out)
        first = await compare(client, 1, 2, out)
        second = await compare(client, 1, 2, out, images=["FILM_2.ARW"])

    assert [Path(r.structured_content["path"]).name for r in (first, second)] == [
        "compare-01-02.jpg",
        "compare-01-02-2.jpg",
    ]
    assert (out / "sheets" / "compare-01-02.jpg").is_file()


async def test_a_frame_that_failed_in_either_pass_is_left_out(server, images, out):
    async with Client(server) as client:
        await open_all(client, images[:2])
        await sheet(client, images[:2], out, thumb_size=100)
        await sheet(client, images, out, thumb_size=100)  # frame 3 is not open: a placeholder
        everything = await compare(client, 1, 2, out)
        asked_for = await compare(client, 1, 2, out, images=["FILM_3.ARW"])

    assert everything.structured_content["images"] == ["FILM_1.ARW", "FILM_2.ARW"]
    assert asked_for.is_error and "not_found" in asked_for.content[0].text


async def test_comparing_needs_two_existing_passes_and_a_folder(server, images, out):
    async with Client(server) as client:
        await before_and_after(client, images, out)
        missing = await compare(client, 1, 9, out)
        same = await compare(client, 2, 2, out)
        no_default = await compare(client, 1, 2)

    assert missing.is_error and "not_found" in missing.content[0].text
    assert same.is_error and "out_of_range" in same.content[0].text
    assert no_default.is_error and "out_of_range" in no_default.content[0].text


async def test_the_folder_defaults_to_the_last_batch_here_too(server, images, out):
    async with Client(server) as client:
        await before_and_after(client, images, out)
        await client.call_tool(
            "export_batch", {"items": [{"path": str(images[0])}], "folder": str(out), "format": "jpeg"}
        )
        result = await compare(client, 1, 2)

    assert not result.is_error, result.content
    assert result.structured_content["path"] == str(out / "sheets" / "compare-01-02.jpg")


