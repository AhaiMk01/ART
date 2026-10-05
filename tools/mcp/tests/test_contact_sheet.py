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


async def test_the_record_lists_the_keys_changed_since_the_last_pass(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        first = await sheet(client, images, out)
        await client.call_tool("edit_profile", {"path": str(images[1]), "raw_edits": compensation("1.5")})
        second = await sheet(client, images, out)
        third = await sheet(client, images, out)

    assert all(i["changes"] is None and i["since_pass"] is None for i in first.structured_content["images"])
    one, two, three = second.structured_content["images"]
    assert one["changes"] == [] and one["since_pass"] == 1
    assert two["since_pass"] == 1
    assert two["changes"] == [{"group": "Exposure", "key": "Compensation", "before": "0", "after": "1.5"}]
    assert all(i["changes"] == [] and i["since_pass"] == 2 for i in third.structured_content["images"])
    on_disk = json.loads(Path(second.structured_content["json_path"]).read_text())
    assert on_disk["index"] == 2
    assert on_disk["images"][1]["changes"] == two["changes"]
    assert [i["name"] for i in on_disk["images"]] == ["FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"]


async def test_changes_are_measured_from_the_last_pass_an_image_was_in(server, images, out):
    async with Client(server) as client:
        await open_all(client, images)
        await sheet(client, images[:2], out)  # pass 1: frames 1 and 2
        await client.call_tool("edit_profile", {"path": str(images[0]), "raw_edits": compensation("0.5")})
        await sheet(client, images[1:], out)  # pass 2: frames 2 and 3
        third = await sheet(client, images, out)

    one, two, three = third.structured_content["images"]
    assert one["since_pass"] == 1 and [c["key"] for c in one["changes"]] == ["Compensation"]
    assert two["since_pass"] == 2 and two["changes"] == []
    assert three["since_pass"] == 2 and three["changes"] == []


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
    assert result.structured_content["index"] == 2 and entry["since_pass"] == 1
    assert [c["after"] for c in entry["changes"]] == ["2"]


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
    assert second["changes"] is None and second["since_pass"] is None
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
    assert redone["error"] is None and redone["since_pass"] == 1
    assert [(c["before"], c["after"]) for c in redone["changes"]] == [("0", "1")]


async def test_an_image_without_a_profile_has_nothing_to_compare(server, images, out):
    async with Client(server) as client:
        await open_all(client, images[:2])
        await sheet(client, images[:2], out)
        again = await sheet(client, images[:2], out)
        gone = await sheet(client, [images[2], images[0]], out)  # frame 3 was never open

    assert [i["since_pass"] for i in again.structured_content["images"]] == [1, 1]
    assert gone.structured_content["images"][0]["since_pass"] is None
    assert gone.structured_content["images"][0]["changes"] is None
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
        assert entry["since_pass"] is None and entry["changes"] is None


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


