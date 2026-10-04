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
