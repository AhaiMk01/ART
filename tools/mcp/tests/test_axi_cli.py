import sys
from pathlib import Path

import pytest

from art_mcp.axi import cli
from art_mcp.axi.state import DiskStore, FileImageLocks, StatePreviews
from art_mcp.render.artcli import ArtCli
from art_mcp.render.session import RenderSession

FAKE = Path(__file__).with_name("fake_artcli.py")


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def axi(tmp_path, monkeypatch, capsys):
    """Runs `art-axi <args>` against the fake art-cli, each run a fresh session
    over one state folder (as separate processes would be)."""
    home = tmp_path / "state"
    monkeypatch.setenv("ART_AXI_HOME", str(home))
    config = tmp_path / "config"
    config.mkdir()

    def factory(ctx):
        return RenderSession(
            ArtCli((sys.executable, str(FAKE))), config, StatePreviews(ctx.home / "previews"), None, False,
            store=DiskStore(ctx.home), locks=FileImageLocks(ctx.home / "locks"),
        )  # fmt: skip

    def run(*args):
        code = cli.run([str(a) for a in args], factory)
        return code, capsys.readouterr().out

    return run


def test_home_with_nothing_open_says_so(axi):
    code, out = axi()

    assert code == 0
    assert "images: 0 open" in out
    assert "description:" in out and "art-axi open <path>" in out


def test_open_persists_between_runs(axi, image):
    code, out = axi("open", image)
    assert code == 0, out
    assert "from: default" in out

    code, out = axi()
    assert "images[1]{path,edits}:" in out
    assert image.as_posix().split("/")[-1] in out and "\\" not in out


def test_edit_in_one_run_is_seen_by_the_next(axi, image):
    axi("open", image)
    code, out = axi("edit", image, "--set", "Exposure/Compensation=1.5")
    assert code == 0, out
    assert "Compensation" in out

    code, out = axi("profile", image, "--groups", "Exposure")
    assert code == 0, out
    assert "unsaved_edits: 1" in out
    assert '"1.5"' in out or "1.5" in out


def test_same_value_again_is_a_no_op(axi, image):
    axi("open", image)
    axi("edit", image, "--set", "Exposure/Compensation=1.5")
    code, out = axi("edit", image, "--set", "Exposure/Compensation=1.5")

    assert code == 0
    assert "no change" in out


def test_not_open_is_an_error_with_the_fix(axi, image):
    code, out = axi("preview", image)

    assert code == 1
    assert "code: not_open" in out
    assert "call `art-axi open` first" in out
    assert f"art-axi open {image}" in out.replace('"', "").replace("\\\\", "\\")


def test_unknown_flag_lists_the_valid_ones(axi, image):
    code, out = axi("preview", image, "--siz", "100")

    assert code == 2
    assert "unknown flag --siz for `preview`" in out
    assert "--size" in out


def test_renamed_flag_points_at_its_replacement(axi, image):
    code, out = axi("preview", image, "--max-size", "100")

    assert code == 2
    assert "use --size" in out


def test_unknown_command(axi):
    code, out = axi("frobnicate")

    assert code == 2
    assert "unknown command frobnicate" in out


def test_preview_file_outlives_the_run(axi, image, tmp_path):
    axi("open", image)
    code, out = axi("preview", image, "--size", "64")

    assert code == 0, out
    line = next(line for line in out.splitlines() if line.strip().startswith("file:"))
    jpeg = Path(line.split(":", 1)[1].strip().strip('"'))
    assert jpeg.is_file() and jpeg.parent == tmp_path / "state" / "previews"
    assert jpeg.name.startswith("IMG_1.ARW-")


def test_save_takes_several_images(axi, tmp_path):
    images = []
    for name in ("A.ARW", "B.ARW"):
        img = tmp_path / name
        img.write_bytes(b"raw")
        images.append(img)
    axi("open", *images)
    axi("edit", *images, "--set", "Exposure/Compensation=1")
    code, out = axi("save", *images)

    assert code == 0, out
    assert "saved[2]{path,sidecar,how,error}:" in out and "failed: 0" in out
    assert all(img.with_name(img.name + ".arp").is_file() for img in images)


def test_extra_argument_error_shows_the_usage(axi, image):
    code, out = axi("profile", image, image)

    assert code == 2
    assert "art-axi profile [-h]" in out


def test_sample_rows_carry_the_size(axi, image):
    axi("open", image)
    code, out = axi("sample", image, "--spot", "100,100,16", "--spot", "200,200")

    assert code == 0, out
    assert "\nsize:" not in out
    assert "100,100,16," in out and "200,200,32," in out


def test_export_creates_its_folder(axi, image, tmp_path):
    axi("open", image)
    target = tmp_path / "new" / "deeper" / "out.jpg"
    code, out = axi("export", image, "--out", target)

    assert code == 0, out
    assert target.is_file()


def test_top_help_has_every_usage(axi):
    code, out = axi("--help")

    assert code == 0
    assert "workflow:" in out and "art-axi sample [-h] --spot" in out


def test_close_is_idempotent(axi, image):
    axi("open", image)
    _, first = axi("close", image)
    _, second = axi("close", image)

    assert ",closed" in first
    assert "not open (no-op)" in second


def test_edit_needs_something_to_change(axi, image):
    code, out = axi("edit", image)

    assert code == 2
    assert "nothing to change" in out


def test_help_is_per_command(axi):
    code, out = axi("sample", "--help")

    assert code == 0
    assert "--spot" in out and "examples:" in out
    assert "--on-conflict" not in out


def test_describe_lists_tools(axi):
    code, out = axi("describe")

    assert code == 0
    assert "tools[" in out and "{name,group,fields}:" in out


def test_version_fast_path(capsys, monkeypatch):
    from art_mcp.axi import main

    monkeypatch.setattr(sys, "argv", ["art-axi", "--version"])
    main.main()

    assert capsys.readouterr().out.strip()


def test_messages_use_the_cli_names():
    assert cli.in_cli_terms("x is not open; call open_image first") == "x is not open; call `art-axi open` first"
    assert cli.in_cli_terms("y already exists; pass overwrite=true to replace it") == (
        "y already exists; pass --overwrite to replace it"
    )


def two_images(tmp_path):
    images = []
    for name in ("A.ARW", "B.ARW"):
        img = tmp_path / name
        img.write_bytes(b"raw")
        images.append(img)
    return images


def test_edit_of_several_images_says_what_changed(axi, tmp_path):
    images = two_images(tmp_path)
    axi("open", *images)
    code, out = axi("edit", *images, "--set", "Exposure/Compensation=1.5")

    assert code == 0, out
    # The same change to both: listed once, old and new value as numbers.
    assert out.count("Exposure/Compensation,0,1.5") == 1
    assert "images[2]{path,error}:" in out and "failed: 0" in out


def test_edit_of_several_images_with_one_failing(axi, tmp_path):
    images = two_images(tmp_path)
    axi("open", images[0])
    code, out = axi("edit", *images, "--set", "Exposure/Compensation=1.5")

    assert code == 0, out
    assert "not_open" in out and "failed: 1" in out
    assert "Exposure/Compensation,0,1.5" in out


def test_reset_says_what_it_discarded(axi, image):
    axi("open", image)
    axi("edit", image, "--set", "Exposure/Compensation=1.5", "--set", "Exposure/Black=0.1")
    code, out = axi("reset", image, "--to", "default")

    assert code == 0, out
    assert "discarded[2]{key,edited,now}:" in out
    assert "Exposure/Compensation,1.5,0" in out and "unsaved_edits: 0" in out


@pytest.fixture
def rendered_png(tmp_path, monkeypatch):
    """What the fake art-cli renders for stats: a real 8-bit PNG."""
    from PIL import Image

    png = tmp_path / "render.png"
    Image.new("RGB", (64, 48), (120, 130, 140)).save(png)
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(png))


def test_stats_set_measures_without_storing(axi, image, rendered_png):
    axi("open", image)
    code, out = axi("stats", image, "--set", "Exposure/Compensation=2")
    assert code == 0, out

    _, profile = axi("profile", image, "--groups", "Exposure")
    assert "unsaved_edits: 0" in profile


def test_stats_sweep_measures_each_value(axi, image, rendered_png):
    axi("open", image)
    code, out = axi("stats", image, "--sweep", "Exposure/Compensation=0.5,1")

    assert code == 0, out
    assert "results[2]{value,clipped_high_r," in out
    assert "\n  0.5," in out and "\n  1," in out and "render:" in out
    _, profile = axi("profile", image, "--groups", "Exposure")
    assert "unsaved_edits: 0" in profile


def test_sweep_range(axi, image, rendered_png):
    axi("open", image)
    code, out = axi("stats", image, "--sweep", "Exposure/Compensation=0:0.3:0.1")

    assert code == 0, out
    assert "results[4]" in out
    assert all(f"\n  {v}," in out for v in ("0", "0.1", "0.2", "0.3"))


def test_sweep_range_too_long(axi, image):
    code, out = axi("stats", image, "--sweep", "Exposure/Compensation=0:10:0.1")

    assert code == 2
    assert "at most 50" in out


def test_profile_rows_carry_the_key_to_set(axi, image):
    axi("open", image)
    axi("edit", image, "--set", "Exposure/Compensation=0.5")
    code, out = axi("profile", image)

    assert code == 0, out
    assert "values[1]{key,stored,name,value}:" in out
    assert "Exposure/Compensation,0.5,exposure.compensation,0.5" in out


def test_paths_come_back_absolute(axi, image, monkeypatch):
    monkeypatch.chdir(image.parent)
    _, out = axi("open", image.name)

    assert f"path: {image.as_posix()}" in out.replace('"', "")


def test_sweep_goes_with_one_image(axi, tmp_path):
    images = two_images(tmp_path)
    code, out = axi("stats", *images, "--sweep", "Exposure/Compensation=0.5,1")

    assert code == 2
    assert "--sweep goes with one image" in out


def test_describe_shows_field_names_and_art_default(axi):
    _, listing = axi("describe")
    _, exposure = axi("describe", "exposure")

    assert "compensation" in listing
    assert "art_default" in exposure and "note:" in exposure
