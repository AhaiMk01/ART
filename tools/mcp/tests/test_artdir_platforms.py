"""ART discovery on macOS and Linux. Every OS choice is injected (system, env,
home, root), so these run the same on any machine and never see its installs."""

from pathlib import Path

from art_mcp import artdir


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_binary_names_per_system(tmp_path):
    touch(tmp_path / "ART-cli.exe")
    assert artdir.find_cli(tmp_path, "linux") is None
    assert artdir.find_cli(tmp_path, "windows") == tmp_path / "ART-cli.exe"
    touch(tmp_path / "art-cli")
    assert artdir.find_cli(tmp_path, "macos") == tmp_path / "art-cli"
    touch(tmp_path / "ART-cli")
    assert artdir.find_cli(tmp_path, "macos") == tmp_path / "ART-cli"
    touch(tmp_path / "exiftool.exe")
    assert artdir.find_exiftool(tmp_path, "linux") is None


def test_macos_lookup_order(tmp_path):
    root, home = tmp_path / "root", tmp_path / "home"
    env = {"HOME": str(home)}
    kw = {"system": "macos", "home": home, "root": root}
    assert artdir.find_art_dir(None, env, None, **kw) is None

    user_app = touch(home / "Applications" / "ART.app" / "Contents" / "MacOS" / "ART-cli").parent
    assert artdir.find_art_dir(None, env, None, **kw) == user_app
    system_app = touch(root / "Applications" / "ART.app" / "Contents" / "Frameworks" / "ART-cli").parent
    assert artdir.find_art_dir(None, env, None, **kw) == system_app  # /Applications first

    on_path = touch(tmp_path / "bin" / "ART-cli").parent
    path_env = {**env, "PATH": str(on_path)}
    assert artdir.find_art_dir(None, path_env, None, **kw) == on_path
    given = tmp_path / "given"
    assert artdir.find_art_dir(str(given), path_env, None, **kw) == given
    assert artdir.find_art_dir(None, {**path_env, "ART_DIR": str(given)}, None, **kw) == given


def test_macos_bundle_frameworks_before_macos_folder(tmp_path):
    frameworks = touch(tmp_path / "Applications" / "ART.app" / "Contents" / "Frameworks" / "ART-cli").parent
    touch(tmp_path / "Applications" / "ART.app" / "Contents" / "MacOS" / "ART-cli")
    assert artdir.find_art_dir(None, {}, None, system="macos", home=tmp_path / "h", root=tmp_path) == frameworks


def test_macos_exiftool_from_pkg_or_homebrew(tmp_path):
    root, home = tmp_path / "root", tmp_path / "home"
    kw = {"system": "macos", "home": home, "root": root}
    assert artdir.locate_exiftool(None, {}, None, **kw) is None
    brew = touch(root / "opt" / "homebrew" / "bin" / "exiftool")
    assert artdir.locate_exiftool(None, {}, None, **kw) == brew
    pkg = touch(root / "usr" / "local" / "bin" / "exiftool")
    assert artdir.locate_exiftool(None, {}, None, **kw) == pkg
    beside = touch(tmp_path / "art" / "exiftool")
    assert artdir.locate_exiftool(beside.parent, {}, None, **kw) == beside


def test_linux_lookup_order(tmp_path):
    root, home = tmp_path / "root", tmp_path / "home"
    kw = {"system": "linux", "home": home, "root": root}
    assert artdir.find_art_dir(None, {}, None, **kw) is None

    touch(root / "opt" / "ART-1.9.0" / "ART-cli")
    newest = touch(root / "opt" / "ART-1.10.0" / "ART-cli").parent
    assert artdir.find_art_dir(None, {}, None, **kw) == newest  # numeric, not lexical
    local = touch(home / ".local" / "bin" / "ART-cli").parent
    assert artdir.find_art_dir(None, {}, None, **kw) == local
    usr = touch(root / "usr" / "bin" / "ART-cli").parent
    assert artdir.find_art_dir(None, {}, None, **kw) == usr
    usr_local = touch(root / "usr" / "local" / "bin" / "art-cli").parent
    assert artdir.find_art_dir(None, {}, None, **kw) == usr_local

    on_path = touch(tmp_path / "bin" / "ART-cli").parent
    assert artdir.find_art_dir(None, {"PATH": str(on_path)}, None, **kw) == on_path
    given = tmp_path / "given"
    assert artdir.find_art_dir(None, {"ART_DIR": str(given), "PATH": str(on_path)}, None, **kw) == given


def test_linux_exiftool_lookup_order(tmp_path):
    root, home = tmp_path / "root", tmp_path / "home"
    kw = {"system": "linux", "home": home, "root": root}
    bundle = touch(root / "opt" / "ART" / "ART-cli").parent
    assert artdir.locate_exiftool(bundle, {}, None, **kw) is None

    bundled = touch(bundle / "lib" / "exiftool" / "exiftool")  # tools/linux/bundle_ART.py layout
    assert artdir.locate_exiftool(bundle, {}, None, **kw) == bundled
    assert artdir.locate_exiftool(None, {}, None, **kw) == bundled  # found via /opt/ART*
    usr = touch(root / "usr" / "bin" / "exiftool")
    assert artdir.locate_exiftool(None, {}, None, **kw) == usr
    on_path = touch(tmp_path / "bin" / "exiftool")
    path_env = {"PATH": str(on_path.parent)}
    assert artdir.locate_exiftool(bundle, path_env, None, **kw) == bundled  # beside ART-cli wins
    assert artdir.locate_exiftool(None, path_env, None, **kw) == on_path


def test_linux_config_dir_follows_glib(tmp_path):
    home = tmp_path / "home"
    kw = {"system": "linux", "home": home}
    assert artdir.user_config_dir({}, **kw) == home / ".config" / "ART"
    other = tmp_path / "other"
    assert artdir.user_config_dir({"HOME": str(other)}, system="linux") == other / ".config" / "ART"
    xdg = tmp_path / "xdg"
    assert artdir.user_config_dir({"XDG_CONFIG_HOME": str(xdg)}, **kw) == xdg / "ART"
    # GLib ignores a relative XDG_CONFIG_HOME; LOCALAPPDATA means nothing here
    env = {"XDG_CONFIG_HOME": "rel", "LOCALAPPDATA": str(tmp_path / "local")}
    assert artdir.user_config_dir(env, **kw) == home / ".config" / "ART"
    assert artdir.user_config_dir({"ART_SETTINGS": str(xdg), "XDG_CONFIG_HOME": "x"}, **kw) == xdg


def test_macos_config_dir_prefers_glib_path_then_application_support(tmp_path):
    home = tmp_path / "home"
    kw = {"system": "macos", "home": home}
    assert artdir.user_config_dir({}, **kw) == home / ".config" / "ART"
    support = home / "Library" / "Application Support" / "ART"
    support.mkdir(parents=True)
    assert artdir.user_config_dir({}, **kw) == support
    (home / ".config" / "ART").mkdir(parents=True)
    assert artdir.user_config_dir({}, **kw) == home / ".config" / "ART"


def test_portable_install_config_dir_on_posix(tmp_path):
    art = touch(tmp_path / "ART" / "ART-cli").parent
    (art / "options").write_text("[General]\nMultiUser=false\n")
    assert artdir.user_config_dir({}, art_dir=art, system="linux", home=tmp_path) == art / "mysettings"
