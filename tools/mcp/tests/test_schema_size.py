"""The size of the tool input schemas clients load, on both servers.

`edit_profile`'s typed `adjustments` once cost 30,000 characters of every
session's tool listing; the emitted JSON schema is compacted (no `title`s,
`default: null`s, optional wrappers or ART bookkeeping, repeated shapes in
`$defs`), while `describe_adjustments` keeps the full documentation and the
pydantic models validate exactly as before.
"""

import json
import sys
from pathlib import Path

import pytest
from fake_live_art import FakeArt
from mcp.client.client import Client

from art_mcp.compactschema import compact_tool_schema
from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server as build_render

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

EDIT_PROFILE_CEILING = 20_000
"""edit_profile's input schema in characters (compact JSON): 29,984 before it
was compacted, about 16,600 now. The bound leaves room for a few more fields
and fails if the schema grows back."""
TOTAL_CEILING = {"render": 24_000, "live": 21_000}
"""All of a server's input schemas together, as a client is told them (Render about 23,400 now, Live
20,400; 26,300 and 22,200 before the titles and null defaults were dropped from every tool's schema).
Raise it deliberately for an option worth its characters; the bound is there to stop silent growth."""
OUTPUT_CEILING = {"render": 20_000, "live": 15_000}
"""All of a server's output schemas together: a client loads these as often as the input schemas
(about 19,600 and 14,500 now, from 25,100 and 18,700)."""


@pytest.fixture
def anyio_backend():
    return "asyncio"


def compact_size(node) -> int:
    return len(json.dumps(node, separators=(",", ":")))


@pytest.fixture
def servers(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    art = FakeArt(tmp_path / "live")
    yield {
        "render": build_render(ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews")),
        "live": build_live(ControlChannel(art.config_dir)),
    }
    art.close()


async def tools_of(server):
    async with Client(server) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


@pytest.fixture(params=["render", "live"])
def server_name(request):
    return request.param


@pytest.fixture
async def tools(server_name, servers):
    return await tools_of(servers[server_name])


def resolve(schema, node):
    """``node`` with a ``$ref`` followed (one level)."""
    if "$ref" in node:
        return schema["$defs"][node["$ref"].rsplit("/", 1)[-1]]
    return node


def tool_schema(schema, name):
    """The JSON schema of one curated tool of edit_profile's `adjustments`."""
    adjustments = resolve(schema, next(b for b in schema["properties"]["adjustments"]["anyOf"] if "$ref" in b))
    return resolve(schema, adjustments["properties"][name])


async def test_edit_profile_input_schema_stays_small(tools):
    size = compact_size(tools["edit_profile"].input_schema)

    assert size <= EDIT_PROFILE_CEILING, f"{size} characters"


async def test_the_input_schemas_of_a_server_together_stay_small(tools, server_name):
    total = sum(compact_size(t.input_schema) for t in tools.values())

    assert total <= TOTAL_CEILING[server_name], f"{total} characters"


async def test_the_adjustments_schema_has_no_pydantic_or_ART_bookkeeping_noise(tools):
    schema = tools["edit_profile"].input_schema
    noise = {"title", "default", "additionalProperties", "key", "art_default", "unit", "group",
             "stored_as", "default_from", "curve", "read_as", "rgb"}  # fmt: skip

    for name, model in schema["$defs"].items():
        assert not noise & model.keys(), name
        for field, prop in model.get("properties", {}).items():
            assert not noise & prop.keys(), f"{name}.{field}"
            # An optional field is just its type: omitting it is "not set".
            assert not any(b == {"type": "null"} for b in prop.get("anyOf", [])), f"{name}.{field}"


async def test_repeated_shapes_are_defined_once(tools):
    schema = tools["edit_profile"].input_schema
    text = json.dumps(schema)

    assert {"ChannelCdl", "PointCurve", "LinearCurve", "RectangleShape", "GradientShape"} <= schema["$defs"].keys()
    assert text.count("Multiplier, applied first") == 1  # r, g, b share one definition
    assert text.count("[x, y] pairs in 0..1") == 1  # curve 1 and 2 share one
    region = resolve(schema, schema["$defs"]["ColorCorrectionRegion"]["properties"]["r"])
    assert region is schema["$defs"]["ChannelCdl"]


async def test_the_schema_keeps_what_a_caller_needs_to_form_a_request(tools):
    schema = tools["edit_profile"].input_schema
    exposure = tool_schema(schema, "exposure")["properties"]

    assert exposure["compensation"]["minimum"] == -12 and exposure["compensation"]["maximum"] == 12
    assert "EV" in exposure["compensation"]["description"]  # the unit travels with the description
    assert exposure["hl_recovery"]["enum"] == ["Off", "Blend", "Color", "Balanced"]
    crop = tool_schema(schema, "crop")["properties"]
    assert "3:2" in crop["ratio"]["enum"] and "px" in crop["x"]["description"]
    vignetting = tool_schema(schema, "vignetting")["properties"]
    assert "% of image width" in vignetting["center_x"]["description"]
    film = tool_schema(schema, "film_negative")
    ref_input = film["properties"]["ref_input"]
    assert ref_input["minItems"] == 3 and "linear value" in ref_input["description"]
    assert "sample_spots" in film["description"]  # the tool's prose is kept
    assert "v*slope + offset/2" in tool_schema(schema, "color_correction")["description"]
    text = json.dumps(schema)
    for needle in ("catmull_rom", "strength_start", "intersect", "Shapes by position", "roundness"):
        assert needle in text


async def test_a_position_in_a_list_may_still_be_null(tools):
    """`regions` and `shapes` are matched by position: a null skips one."""
    schema = tools["edit_profile"].input_schema

    regions = schema["$defs"]["ColorCorrection"]["properties"]["regions"]
    assert {"type": "null"} in regions["items"]["anyOf"]
    shapes = schema["$defs"]["AreaMaskAdjustment"]["properties"]["shapes"]
    assert {"type": "null"} in shapes["items"]["anyOf"]


async def test_the_compact_schema_is_a_valid_schema_that_agrees_with_the_server_on_values(tools):
    """Every `$ref` resolves, and a request the server accepts validates (null fields apart: the schema leaves
    them out, the server takes them as "not set"), while ranges and enums reject what the server rejects."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = tools["edit_profile"].input_schema
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    accepted = [
        {"exposure": {"compensation": 0.7, "hl_recovery": "Balanced"}},
        {"crop": {"x": 10, "y": 10, "w": 100, "h": 100, "ratio": "3:2"}},
        {"tone_curve": {
            "curve1": {"type": "spline", "points": [[0, 0], [0.5, 0.6], [1, 1]]}, "curve2": {"type": "linear"}}},
        {"color_correction": {"regions": [
            None, {"b": {"slope": 0.85}, "mask": {"shapes": [None, {"type": "gradient"}]}}]}},
        {"film_negative": {"ref_input": [1, 2, 3]}},
    ]  # fmt: skip
    rejected = [
        {"exposure": {"compensation": 12.5}},
        {"exposure": {"hl_recovery": "Extreme"}},
        {"crop": {"x": -1}},
        {"tone_curve": {"curve1": {"type": "wavy", "points": [[0, 0], [1, 1]]}}},
        {"color_correction": {"regions": [{"r": {"slope": 11}}]}},
        {"color_correction": {"regions": [{"mask": {"shapes": [{"type": "rectangle", "mode": "xor"}]}}]}},
        {"film_negative": {"ref_input": [1, 2]}},
    ]  # fmt: skip

    for adjustments in accepted:
        assert not list(validator.iter_errors({"path": "a.ARW", "adjustments": adjustments})), adjustments
    for adjustments in rejected:
        assert list(validator.iter_errors({"path": "a.ARW", "adjustments": adjustments})), adjustments


async def test_edit_profile_names_the_fields_of_its_result_including_created(tools, server_name):
    edit_profile = tools["edit_profile"]
    # The result is one image's change set or, with `paths`, a list of one entry per image.
    single = edit_profile.output_schema["$defs"]["LiveEditResult" if server_name == "live" else "EditResult"]

    for field in ("changed", "implied", "created", "drawn", "warnings"):
        assert f"`{field}`" in edit_profile.description
        assert field in single["properties"]
    assert "counted, not listed" in edit_profile.description


async def test_describe_adjustments_keeps_the_full_documentation(servers):
    async with Client(servers["render"]) as client:
        described = (await client.call_tool("describe_adjustments", {})).structured_content

    compensation = described["tools"]["exposure"]["fields"]["compensation"]
    assert compensation == {
        "group": "Exposure", "key": "Compensation", "type": "number", "minimum": -12, "maximum": 12,
        "unit": "EV", "enum": None, "default": 0, "description": "Exposure compensation",
    }  # fmt: skip
    assert described["tools"]["exposure"]["fields"]["enabled"]["description"] == "Turn the tool on or off"
    assert described["tools"]["vignetting"]["fields"]["amount"]["description"] == "Amount"
    curve = described["tools"]["tone_curve"]["fields"]["curve1"]
    assert curve["type"] == "curve" and curve["key"] == "Curve" and curve["default"] == {"type": "linear"}
    assert described["tools"]["tone_curve"]["fields"]["mode2"]["default"] == "as mode"
    for tool in described["tools"].values():
        assert tool["description"]
        for field in tool["fields"].values():
            assert field["key"] and field["description"] and "default" in field


# -- the schemas a client loads carry no annotation noise ------------------------------------------


def schema_nodes(node, is_map=False):
    """Every schema object in ``node`` (the keys of a `properties` or `$defs` map are names, not
    schemas)."""
    if isinstance(node, list):
        for item in node:
            yield from schema_nodes(item)
    elif isinstance(node, dict):
        if not is_map:
            yield node
        for key, value in node.items():
            yield from schema_nodes(value, is_map=key in ("properties", "$defs") and isinstance(value, dict))
        if is_map:
            for value in node.values():
                yield from schema_nodes(value)


async def test_no_schema_has_a_title_or_a_null_default(tools):
    for name, tool in tools.items():
        for kind, schema in (("input", tool.input_schema), ("output", tool.output_schema)):
            for node in schema_nodes(schema or {}):
                assert not isinstance(node.get("title"), str), f"{name} {kind}: title {node.get('title')!r}"
                assert node.get("default", 0) is not None, f"{name} {kind}: default null in {sorted(node)}"


async def test_a_parameter_that_may_be_null_still_says_so(tools):
    """Only annotations go: `path` of image_stats (a string or null) keeps its null, so a client
    that sends null for an unset argument still validates."""
    path = tools["image_stats"].input_schema["properties"]["path"]
    assert {"type": "null"} in path["anyOf"] and "default" not in path


def test_compact_tool_schema_drops_titles_and_null_defaults_only():
    schema = {
        "type": "object",
        "title": "fArguments",
        "properties": {
            "title": {"type": "string", "title": "Title"},  # a parameter named title: the name stays
            "size": {"type": "integer", "default": 5, "title": "Size"},
            "region": {"anyOf": [{"$ref": "#/$defs/Region"}, {"type": "null"}], "default": None, "title": "Region"},
        },
        "$defs": {"Region": {"type": "object", "title": "Region", "properties": {"x": {"type": "number"}}}},
        "required": ["title"],
    }
    before = json.dumps(schema)

    compact = compact_tool_schema(schema)

    assert compact == {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "size": {"type": "integer", "default": 5},
            "region": {"anyOf": [{"$ref": "#/$defs/Region"}, {"type": "null"}]},
        },
        "$defs": {"Region": {"type": "object", "properties": {"x": {"type": "number"}}}},
        "required": ["title"],
    }
    assert json.dumps(schema) == before  # the argument is not changed
    assert compact_tool_schema(compact) == compact  # and compacting again changes nothing


async def test_the_schemas_a_client_loads_are_smaller_than_ever(tools, server_name):
    inputs = sum(compact_size(t.input_schema) for t in tools.values())
    outputs = sum(compact_size(t.output_schema) for t in tools.values() if t.output_schema)

    assert inputs <= TOTAL_CEILING[server_name] and outputs <= OUTPUT_CEILING[server_name], (inputs, outputs)


async def test_a_call_with_nulls_for_unset_arguments_still_works(servers, tmp_path):
    from mcp.client.client import Client

    async with Client(servers["render"]) as client:
        result = await client.call_tool("image_stats", {"path": None, "paths": None, "region": None})
    assert result.is_error and "out_of_range" in result.content[0].text  # refused for what it is, not as bad input
