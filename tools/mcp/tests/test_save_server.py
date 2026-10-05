"""save_sidecar and save_partial_profile through an in-process client."""

import json
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client
from mcp_types import ElicitResult

from art_mcp import keyfile
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

SIDECAR = "[Exposure]\nEnabled=true\nCompensation=1\nBlack=0\n"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def sidecar(image):
    path = image.with_name(image.name + ".arp")
    path.write_text(SIDECAR)
    return path


@pytest.fixture
def config(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    return config


@pytest.fixture
def server(tmp_path, config):
    cli = ArtCli((sys.executable, str(FAKE)))
    return build_server(cli, config, PreviewFolder(tmp_path / "previews"))


def edit(group, key, value):
    return {"group": group, "key": key, "value": value}


async def open_and_edit(client, image, *edits):
    await client.call_tool("open_image", {"path": str(image)})
    result = await client.call_tool(
        "edit_profile", {"path": str(image), "raw_edits": list(edits)}
    )
    assert not result.is_error, result.content


def text_of(result):
    return result.content[0].text


async def test_save_without_external_change_writes_sidecar_and_backs_up_the_old_one(
    server, image, sidecar
):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert not result.is_error, result.content
    assert result.structured_content["saved"] is True
    assert keyfile.loads(sidecar.read_text())["Exposure"]["Compensation"] == "2"
    backup = sidecar.with_name(sidecar.name + ".bak")
    assert backup.read_text() == SIDECAR


async def test_first_save_creates_the_sidecar_without_a_backup(server, image):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert not result.is_error, result.content
    assert (image.parent / "IMG_1.ARW.arp").is_file()
    assert not (image.parent / "IMG_1.ARW.arp.bak").exists()


async def test_sidecar_name_honours_the_strip_extension_option(server, image, config):
    (config / "options").write_text("[Profiles]\nParamsSidecarStripExtension=true\n")
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert result.structured_content["path"] == str(image.with_suffix(".arp"))
    assert image.with_suffix(".arp").is_file()
    assert not (image.parent / "IMG_1.ARW.arp").exists()


def change_externally(sidecar):
    sidecar.write_text(SIDECAR.replace("Black=0", "Black=7"))


async def save_after_external_change(server, image, sidecar, **args):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        return await client.call_tool("save_sidecar", {"path": str(image), **args})


async def test_on_conflict_overwrite_writes_the_working_profile_and_backs_up(
    server, image, sidecar
):
    result = await save_after_external_change(server, image, sidecar, on_conflict="overwrite")

    assert not result.is_error, result.content
    saved = keyfile.loads(sidecar.read_text())["Exposure"]
    assert (saved["Compensation"], saved["Black"]) == ("2", "0")
    assert "Black=7" in sidecar.with_name(sidecar.name + ".bak").read_text()


async def test_on_conflict_merge_applies_only_the_agents_keys_to_the_current_sidecar(
    server, image, sidecar
):
    result = await save_after_external_change(server, image, sidecar, on_conflict="merge")

    assert not result.is_error, result.content
    saved = keyfile.loads(sidecar.read_text())["Exposure"]
    assert (saved["Compensation"], saved["Black"]) == ("2", "7")
    assert "Black=7" in sidecar.with_name(sidecar.name + ".bak").read_text()


async def test_on_conflict_cancel_writes_nothing(server, image, sidecar):
    result = await save_after_external_change(server, image, sidecar, on_conflict="cancel")

    assert not result.is_error, result.content
    assert result.structured_content["saved"] is False
    assert "Black=7" in sidecar.read_text() and "Compensation=1" in sidecar.read_text()
    assert not sidecar.with_name(sidecar.name + ".bak").exists()


async def test_on_conflict_is_ignored_when_nothing_changed(server, image, sidecar):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        result = await client.call_tool(
            "save_sidecar", {"path": str(image), "on_conflict": "cancel"}
        )

    assert result.structured_content["saved"] is True


async def test_after_a_save_the_sidecar_is_the_new_baseline(server, image, sidecar):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        await client.call_tool("save_sidecar", {"path": str(image)})
        again = await client.call_tool("save_sidecar", {"path": str(image)})
        partial = await client.call_tool(
            "save_partial_profile",
            {"path": str(image), "dest": str(image.parent / "p.arp")},
        )

    assert again.structured_content["saved"] is True  # no conflict with our own write
    assert partial.structured_content["written"] is False  # nothing changed since the save


async def test_merge_brings_the_current_sidecar_values_into_the_working_profile(
    server, image, sidecar
):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        await client.call_tool("save_sidecar", {"path": str(image), "on_conflict": "merge"})
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert profile.structured_content["adjustments"]["exposure"]["black"] == 7


def answering(action, choice=None):
    """An elicitation callback that records what it was asked and answers."""
    asked = []

    async def callback(context, params):
        asked.append(params.message)
        return ElicitResult(action=action, content={"choice": choice} if choice else None)

    callback.asked = asked
    return callback


@pytest.mark.parametrize(
    "choice, compensation, black", [("merge", "2", "7"), ("overwrite", "2", "0")]
)
async def test_elicited_choice_decides_a_conflict(
    server, image, sidecar, choice, compensation, black
):
    callback = answering("accept", choice)
    async with Client(server, elicitation_callback=callback, mode="legacy") as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert not result.is_error, result.content
    saved = keyfile.loads(sidecar.read_text())["Exposure"]
    assert (saved["Compensation"], saved["Black"]) == (compensation, black)
    assert len(callback.asked) == 1
    assert "[Exposure] Black" in callback.asked[0]


@pytest.mark.parametrize("action", ["decline", "cancel"])
async def test_declining_the_question_cancels_the_save(server, image, sidecar, action):
    async with Client(server, elicitation_callback=answering(action), mode="legacy") as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert result.structured_content["saved"] is False
    assert "Compensation=1" in sidecar.read_text()


async def test_a_connection_that_cannot_be_asked_gets_the_conflict_error(
    server, image, sidecar
):
    """Newer protocol versions give a tool no back-channel to ask on."""
    async with Client(server, elicitation_callback=answering("accept", "merge")) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert result.is_error and "conflict" in text_of(result)
    assert "Compensation=1" in sidecar.read_text()


async def test_no_question_is_asked_without_a_conflict(server, image, sidecar):
    callback = answering("accept", "overwrite")
    async with Client(server, elicitation_callback=callback, mode="legacy") as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert result.structured_content["saved"] is True
    assert callback.asked == []


async def test_on_conflict_given_skips_the_question(server, image, sidecar):
    callback = answering("accept", "overwrite")
    async with Client(server, elicitation_callback=callback, mode="legacy") as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        result = await client.call_tool(
            "save_sidecar", {"path": str(image), "on_conflict": "merge"}
        )

    assert result.structured_content["how"] == "merged"
    assert callback.asked == []


async def partial_dest(tmp_path, image, client, **args):
    dest = tmp_path / "out.arp"
    return dest, await client.call_tool(
        "save_partial_profile", {"path": str(image), "dest": str(dest), **args}
    )


async def test_partial_profile_has_only_the_changed_keys(server, image, tmp_path):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        dest, result = await partial_dest(tmp_path, image, client)

    assert not result.is_error, result.content
    assert result.structured_content["keys"] == {"Exposure": 1}  # compact: keys written per group
    assert result.structured_content["total"] == 1
    assert keyfile.loads(dest.read_text()) == {"Exposure": {"Compensation": "2"}}


async def test_partial_profile_result_counts_the_keys_per_group_in_file_order_with_a_total(
    server, image, preset, tmp_path
):
    async with Client(server) as client:
        await open_from_preset_and_edit(client, image, preset, edit("Exposure", "Compensation", "2"))
        dest, result = await partial_dest(tmp_path, image, client, vs="default")

    assert not result.is_error, result.content
    assert result.structured_content["keys"] == {"Exposure": 3, "Film Negative": 2}
    assert list(result.structured_content["keys"]) == ["Exposure", "Film Negative"]
    assert result.structured_content["total"] == 5
    assert "[Exposure] Black" not in text_of(result)  # no list of every key
    assert sum(len(keys) for keys in keyfile.loads(dest.read_text()).values()) == 5


async def test_partial_profile_verbose_lists_every_key_as_before_and_still_has_the_total(
    server, image, preset, tmp_path
):
    async with Client(server) as client:
        await open_from_preset_and_edit(client, image, preset, edit("Exposure", "Compensation", "2"))
        dest, result = await partial_dest(tmp_path, image, client, vs="default", verbose=True)

    assert not result.is_error, result.content
    assert result.structured_content["keys"] == [
        "[Exposure] Enabled", "[Exposure] Compensation", "[Exposure] Black",
        "[Film Negative] Enabled", "[Film Negative] RedRatio",
    ]  # fmt: skip
    assert result.structured_content["total"] == 5


async def test_partial_profile_result_stays_small_for_a_group_of_many_keys(server, image, tmp_path):
    names = [f"SlopeR_{i}" for i in range(80)]  # a Color Correction region has about 80 keys
    image.with_name(image.name + ".arp").write_text("[ColorCorrection]\n" + "".join(f"{n}=0\n" for n in names))
    async with Client(server) as client:
        await open_and_edit(client, image, *(edit("ColorCorrection", n, "1") for n in names))
        _, compact = await partial_dest(tmp_path, image, client)
        _, verbose = await partial_dest(tmp_path, image, client, overwrite=True, verbose=True)

    assert compact.structured_content["keys"] == {"ColorCorrection": 80} and compact.structured_content["total"] == 80
    assert len(text_of(compact)) < len(text_of(verbose)) / 5  # the full list is what made it large
    assert len(verbose.structured_content["keys"]) == 80


async def test_partial_profile_refuses_an_existing_dest_unless_overwrite(
    server, image, tmp_path
):
    (tmp_path / "out.arp").write_text("keep me")
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        refused = await partial_dest(tmp_path, image, client)
        assert refused[1].is_error and "exists" in text_of(refused[1])
        assert refused[0].read_text() == "keep me"

        replaced = await partial_dest(tmp_path, image, client, overwrite=True)
        assert not replaced[1].is_error, replaced[1].content
        assert "Compensation=2" in replaced[0].read_text()
    assert not (tmp_path / "out.arp.bak").exists()


async def test_partial_profile_with_no_changes_writes_nothing(server, image, tmp_path):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        dest, result = await partial_dest(tmp_path, image, client)

    assert result.structured_content["written"] is False
    assert not dest.exists()


async def test_partial_profile_into_a_missing_folder_is_not_found(server, image, tmp_path):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        result = await client.call_tool(
            "save_partial_profile",
            {"path": str(image), "dest": str(tmp_path / "nope" / "p.arp")},
        )

    assert result.is_error and "not_found" in text_of(result)


async def test_saving_an_image_not_opened_is_not_open(server, image):
    async with Client(server) as client:
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert result.is_error and "not_open" in text_of(result)


async def test_external_change_without_elicitation_is_a_conflict_naming_the_keys(
    server, image, sidecar
):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert result.is_error
    message = text_of(result)
    assert "conflict" in message
    assert "[Exposure] Black" in message  # changed in the sidecar by someone else
    assert "[Exposure] Compensation" in message  # changed by the agent
    assert "on_conflict" in message
    assert "Black=7" in sidecar.read_text()  # untouched
    assert not sidecar.with_name(sidecar.name + ".bak").exists()


async def test_sidecar_changing_again_while_the_user_answers_is_not_overwritten(
    server, image, sidecar
):
    async def callback(context, params):
        sidecar.write_text(SIDECAR.replace("Black=0", "Black=9"))  # someone else, mid-question
        return ElicitResult(action="accept", content={"choice": "overwrite"})

    async with Client(server, elicitation_callback=callback, mode="legacy") as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        result = await client.call_tool("save_sidecar", {"path": str(image)})

    assert result.is_error and "conflict" in text_of(result)
    assert "Black=9" in sidecar.read_text()


async def test_an_edit_made_while_the_user_answers_is_saved_and_kept(server, image, sidecar):
    holder = {}

    async def callback(context, params):
        await holder["client"].call_tool(
            "edit_profile", {"path": str(image), "raw_edits": [edit("Exposure", "Compensation", "5")]}
        )
        return ElicitResult(action="accept", content={"choice": "merge"})

    async with Client(server, elicitation_callback=callback, mode="legacy") as client:
        holder["client"] = client
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        change_externally(sidecar)
        result = await client.call_tool("save_sidecar", {"path": str(image)})
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert not result.is_error, result.content
    assert keyfile.loads(sidecar.read_text())["Exposure"]["Compensation"] == "5"
    assert profile.structured_content["adjustments"]["exposure"]["compensation"] == 5


async def test_partial_profile_exclude_drops_a_group_or_a_single_key(
    server, image, sidecar, tmp_path
):
    async with Client(server) as client:
        await open_and_edit(
            client,
            image,
            edit("Exposure", "Compensation", "2"),
            edit("Exposure", "Black", "5"),
        )
        _, one_key = await partial_dest(tmp_path, image, client, exclude=["Exposure/Black"])
        dest, whole_group = await partial_dest(
            tmp_path, image, client, overwrite=True, exclude=["Exposure"]
        )

    assert one_key.structured_content["keys"] == {"Exposure": 1}
    assert whole_group.structured_content["written"] is False  # nothing left to write
    assert whole_group.structured_content["keys"] == {} and whole_group.structured_content["total"] == 0


async def test_partial_profile_exclude_writes_the_rest(server, image, sidecar, tmp_path):
    async with Client(server) as client:
        await open_and_edit(
            client,
            image,
            edit("Exposure", "Compensation", "2"),
            edit("Exposure", "Black", "5"),
        )
        dest, result = await partial_dest(tmp_path, image, client, exclude=["Exposure/Black"])

    assert keyfile.loads(dest.read_text()) == {"Exposure": {"Compensation": "2"}}


async def test_partial_profile_exclude_of_an_unknown_name_is_unknown_key(
    server, image, sidecar, tmp_path
):
    async with Client(server) as client:
        await open_and_edit(client, image, edit("Exposure", "Compensation", "2"))
        for bad in ("Nonsense", "Exposure/Nonsense"):
            dest, result = await partial_dest(tmp_path, image, client, exclude=[bad])
            assert result.is_error and "unknown_key" in text_of(result)
            assert not dest.exists()


# -- save_partial_profile vs: "default" ----------------------------------------

ROLL_PRESET = (
    "[Version]\nAppVersion=1.0.0\nVersion=1000\n\n"
    "[Exposure]\nEnabled=false\nBlack=5\n\n"
    "[Film Negative]\nEnabled=true\nRedRatio=1.5\n"
)
"""A roll preset: the base settings of a film roll, over ART's default profile
(which has Exposure on, Black 0 and no Film Negative group; a version of its
own, which the saved file must not take along)."""


@pytest.fixture
def preset(tmp_path):
    path = tmp_path / "roll.arp"
    path.write_text(ROLL_PRESET)
    return path


async def open_from_preset_and_edit(client, image, preset, *edits):
    await client.call_tool("open_image", {"path": str(image), "profile": str(preset)})
    result = await client.call_tool("edit_profile", {"path": str(image), "raw_edits": list(edits)})
    assert not result.is_error, result.content


async def test_partial_profile_vs_default_carries_the_keys_of_the_preset_the_frame_was_opened_from(
    server, image, preset, tmp_path
):
    async with Client(server) as client:
        await open_from_preset_and_edit(client, image, preset, edit("Exposure", "Compensation", "2"))
        _, opened = await partial_dest(tmp_path, image, client)
        dest, default = await partial_dest(tmp_path, image, client, overwrite=True, vs="default")

    assert opened.structured_content["keys"] == {"Exposure": 1}
    assert opened.structured_content["vs"] == "opened"
    assert not default.is_error, default.content
    assert keyfile.loads(dest.read_text()) == {
        "Exposure": {"Enabled": "false", "Compensation": "2", "Black": "5"},
        "Film Negative": {"Enabled": "true", "RedRatio": "1.5"},
    }
    assert default.structured_content["vs"] == "default"
    assert default.structured_content["written"] is True
    assert default.structured_content["keys"] == {"Exposure": 3, "Film Negative": 2}


async def test_partial_profile_vs_default_leaves_out_what_equals_the_default_and_the_version(
    server, image, preset, tmp_path
):
    async with Client(server) as client:
        await open_from_preset_and_edit(
            client, image, preset, edit("Exposure", "Compensation", "2")
        )
        await client.call_tool(  # back to ART's default value: not a difference
            "edit_profile",
            {"path": str(image), "raw_edits": [edit("Exposure", "Compensation", "0")]},
        )
        dest, result = await partial_dest(tmp_path, image, client, vs="default")

    saved = keyfile.loads(dest.read_text())
    assert saved == {
        "Exposure": {"Enabled": "false", "Black": "5"},
        "Film Negative": {"Enabled": "true", "RedRatio": "1.5"},
    }  # not White Balance, Crop, LensProfile (all the default's), nor [Version] (the preset's own)
    assert result.structured_content["keys"] == {"Exposure": 2, "Film Negative": 2}
    assert result.structured_content["total"] == 4


async def test_partial_profile_vs_default_of_an_unchanged_default_profile_writes_nothing(
    server, image, tmp_path
):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        dest, result = await partial_dest(tmp_path, image, client, vs="default")

    assert result.structured_content["written"] is False
    assert result.structured_content["keys"] == {} and result.structured_content["total"] == 0
    assert result.structured_content["vs"] == "default"
    assert not dest.exists()


async def test_partial_profile_vs_default_skips_the_keys_only_the_default_has(
    server, image, sidecar, tmp_path
):
    """The sidecar fixture lists only [Exposure]: with the fake art-cli the
    working profile has no White Balance, Crop or LensProfile keys at all."""
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        dest, result = await partial_dest(tmp_path, image, client, vs="default")

    assert not result.is_error, result.content
    assert keyfile.loads(dest.read_text()) == {"Exposure": {"Compensation": "1"}}


async def test_partial_profile_vs_default_applies_exclude(server, image, preset, tmp_path):
    async with Client(server) as client:
        await open_from_preset_and_edit(
            client, image, preset, edit("Exposure", "Compensation", "2")
        )
        dest, one_key = await partial_dest(
            tmp_path, image, client, vs="default", exclude=["Exposure/Black", "Film Negative"]
        )
        _, nothing = await partial_dest(
            tmp_path, image, client, vs="default", overwrite=True, exclude=["Exposure", "Film Negative"]
        )
        _, unknown = await partial_dest(
            tmp_path, image, client, vs="default", overwrite=True, exclude=["Nonsense"]
        )

    assert one_key.structured_content["keys"] == {"Exposure": 2}
    assert nothing.structured_content["written"] is False
    assert unknown.is_error and "unknown_key" in text_of(unknown)
    assert keyfile.loads(dest.read_text()) == {"Exposure": {"Enabled": "false", "Compensation": "2"}}


@pytest.mark.parametrize("vs", ["sidecar", "", "Default"])
async def test_partial_profile_with_another_baseline_is_out_of_range(
    server, image, preset, tmp_path, vs
):
    async with Client(server) as client:
        await open_from_preset_and_edit(client, image, preset, edit("Exposure", "Compensation", "2"))
        dest, result = await partial_dest(tmp_path, image, client, vs=vs)

    assert result.is_error and "out_of_range" in text_of(result) and "opened, default" in text_of(result)
    assert not dest.exists()


async def test_the_default_profile_is_only_asked_for_with_vs_default_and_once_per_opened_image(
    server, image, preset, tmp_path, monkeypatch
):
    log = tmp_path / "args.log"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))

    def default_runs():
        return sum("-d" in json.loads(line) for line in log.read_text().splitlines())

    async with Client(server) as client:
        await open_from_preset_and_edit(client, image, preset, edit("Exposure", "Compensation", "2"))
        opened_runs = default_runs()
        await partial_dest(tmp_path, image, client)
        assert default_runs() == opened_runs

        await partial_dest(tmp_path, image, client, overwrite=True, vs="default")
        assert default_runs() == opened_runs + 1
        await partial_dest(tmp_path, image, client, overwrite=True, vs="default")
        assert default_runs() == opened_runs + 1
