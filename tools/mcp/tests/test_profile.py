from art_mcp.profile import RawEdit, WorkingChanges, read_format


def profile():
    return {
        "Version": {"Version": "1045"},
        "Exposure": {"Enabled": "true", "Compensation": "0"},
        "Sharpening": {"Enabled": "false"},
    }


def edit(group, key, value):
    return RawEdit(group=group, key=key, value=value)


def test_partial_profile_holds_only_the_keys_the_agent_changed():
    changes = WorkingChanges(profile())

    changes.apply([edit("Exposure", "Compensation", "1"), edit("Sharpening", "Enabled", "true")])

    assert changes.partial_profile() == {
        "Exposure": {"Compensation": "1"},
        "Sharpening": {"Enabled": "true"},
    }


def test_changed_reports_final_values_once_and_skips_no_ops():
    changes = WorkingChanges(profile())

    changed = changes.apply([
        edit("Exposure", "Compensation", "2"),
        edit("Exposure", "Compensation", "3"),
        edit("Exposure", "Enabled", "true"),
        edit("Sharpening", "Enabled", "true"),
        edit("Sharpening", "Enabled", "false"),
    ])

    assert changed == [edit("Exposure", "Compensation", "3")]


def test_read_format_shows_the_version_once():
    view = read_format(profile())

    assert view.ppversion == 1045
    assert "Version" not in view.raw
