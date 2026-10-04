import os
from pathlib import Path

from art_mcp import artdir


def make_art(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "ART-cli.exe").write_bytes(b"")
    return folder


def test_newest_install_by_version_not_by_name(tmp_path):
    program_files = tmp_path / "ART"
    make_art(program_files / "1.26.9")
    newest = make_art(program_files / "1.26.10")

    assert artdir.find_art_dir(None, {}, program_files) == newest


def test_flag_then_env_then_path_then_install(tmp_path):
    flag = make_art(tmp_path / "flag")
    env_dir = make_art(tmp_path / "env")
    on_path = make_art(tmp_path / "path")
    program_files = tmp_path / "ART"
    installed = make_art(program_files / "1.26.9")
    path_var = os.pathsep.join([str(tmp_path / "nothing"), str(on_path)])

    assert artdir.find_art_dir(str(flag), {"ART_DIR": str(env_dir)}, program_files) == flag
    assert artdir.find_art_dir(None, {"ART_DIR": str(env_dir), "PATH": path_var}, program_files) == env_dir
    assert artdir.find_art_dir(None, {"PATH": path_var}, program_files) == on_path
    assert artdir.find_art_dir(None, {}, program_files) == installed
    assert artdir.find_art_dir(None, {}, tmp_path / "missing") is None


def test_sidecar_name_follows_strip_extension_option(tmp_path):
    image = tmp_path / "IMG_1.ARW"
    config = tmp_path / "config"
    config.mkdir()

    assert artdir.sidecar_path(image, config) == tmp_path / "IMG_1.ARW.arp"

    (config / "options").write_text("[Profiles]\nParamsSidecarStripExtension=true\n")
    assert artdir.sidecar_path(image, config) == tmp_path / "IMG_1.arp"

    (config / "options").write_text("[Profiles]\nParamsSidecarStripExtension=false\n")
    assert artdir.sidecar_path(image, config) == tmp_path / "IMG_1.ARW.arp"


def test_exiftool_is_found_beside_art_cli(tmp_path):
    art = make_art(tmp_path / "ART")
    assert artdir.find_exiftool(art) is None
    (art / "exiftool.exe").write_bytes(b"")
    assert artdir.find_exiftool(art) == art / "exiftool.exe"


def test_fast_export_box_is_the_smaller_side_of_the_users_box(tmp_path):
    assert artdir.fast_export_box(tmp_path) == 1920  # no options file: ART's default

    (tmp_path / "options").write_text(
        "[Fast Export]\nfastexport_resize_width=1600\nfastexport_resize_height=1200\n"
    )
    assert artdir.fast_export_box(tmp_path) == 1200

    (tmp_path / "options").write_text("[Fast Export]\nfastexport_resize_width=1600\n")
    assert artdir.fast_export_box(tmp_path) == 1600


def test_fast_export_box_falls_back_to_the_legacy_keys_like_art(tmp_path):
    (tmp_path / "options").write_text("[Fast Export]\nMaxWidth=1500\nMaxHeight=1000\n")
    assert artdir.fast_export_box(tmp_path) == 1000

    (tmp_path / "options").write_text(
        "[Fast Export]\nfastexport_resize_width=1600\nMaxWidth=900\nMaxHeight=1700\n"
    )
    assert artdir.fast_export_box(tmp_path) == 1600
