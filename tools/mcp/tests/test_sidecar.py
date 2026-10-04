from art_mcp import sidecar


def test_hash_is_sha256_hex_of_the_bytes():
    assert sidecar.file_hash(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_changed_keys_names_added_removed_and_changed_values():
    before = {"A": {"x": "1", "y": "2"}, "B": {"z": "3"}}
    after = {"A": {"x": "1", "y": "9", "n": "0"}, "C": {"w": "1"}}

    assert sidecar.changed_keys(before, after) == [
        "[A] y",
        "[A] n",
        "[B] z",
        "[C] w",
    ]


def test_write_backs_up_the_previous_file_replacing_an_older_backup(tmp_path):
    target = tmp_path / "IMG.ARW.arp"
    target.write_bytes(b"first")
    (tmp_path / "IMG.ARW.arp.bak").write_bytes(b"ancient")

    sidecar.write_with_backup(target, "second")

    assert target.read_bytes() == b"second"
    assert (tmp_path / "IMG.ARW.arp.bak").read_bytes() == b"first"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["IMG.ARW.arp", "IMG.ARW.arp.bak"]


def test_write_without_a_previous_file_makes_no_backup(tmp_path):
    target = tmp_path / "IMG.ARW.arp"

    sidecar.write_with_backup(target, "new")

    assert target.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["IMG.ARW.arp"]


def test_failed_write_leaves_the_original_and_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "IMG.ARW.arp"
    target.write_bytes(b"first")

    def boom(src, dst):
        raise OSError("disk says no")

    monkeypatch.setattr(sidecar.os, "replace", boom)
    try:
        sidecar.write_with_backup(target, "second")
    except OSError:
        pass

    assert target.read_bytes() == b"first"
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_merge_puts_only_the_partial_values_onto_the_current_sidecar():
    current = {"A": {"x": "user", "y": "2"}, "B": {"z": "3"}}
    partial = {"A": {"y": "agent"}, "C": {"w": "1"}}

    merged = sidecar.merge(current, partial)

    assert merged == {"A": {"x": "user", "y": "agent"}, "B": {"z": "3"}, "C": {"w": "1"}}
    assert current["A"]["y"] == "2"
