"""CompactModel's JSON schema, on a small model."""

from typing import Literal

import pytest
from pydantic import Field, ValidationError

from art_mcp.compactschema import CompactModel, full_schema


class Item(CompactModel):
    """An item."""

    size: float | None = Field(None, ge=0, le=9, description="How big", json_schema_extra={"unit": "px", "key": "Size"})


class Toy(CompactModel):
    """A toy: what a caller needs.

    Reference text a caller can do without. It goes on for a while and
    mentions details."""

    amount: int | None = Field(None, description="Amount", json_schema_extra={"art_default": 3})
    radius: float | None = Field(None, description="Radius (usm)", json_schema_extra={"unit": "px"})
    centre: float | None = Field(
        None, description="Centre offset", json_schema_extra={"unit": "% of the width (100 = the whole width)"}
    )
    temperature: int | None = Field(None, description="Colour temperature", json_schema_extra={"unit": "K"})
    tint: float | None = Field(None, description="Tint multiplier", json_schema_extra={"unit": "tint multiplier"})
    enabled: bool | None = Field(None, description="Turn the tool on or off")
    mode: Literal["a", "b"] | None = Field(None, description="Which one")
    item: Item | None = None
    items: list[Item | None] | None = Field(None, description="By position; a null skips one")


def schema():
    return Toy.model_json_schema()


def test_the_noise_is_gone_and_an_optional_field_is_just_its_type():
    toy, props = schema(), schema()["properties"]

    assert "title" not in toy and "additionalProperties" not in toy
    assert props["mode"] == {"description": "Which one", "enum": ["a", "b"], "type": "string"}
    assert props["item"] == {"$ref": "#/$defs/Item"}
    assert "title" not in toy["$defs"]["Item"]
    for prop in props.values():
        assert not {"title", "default", "art_default", "key"} & prop.keys()


def test_a_null_position_in_a_list_stays():
    items = schema()["properties"]["items"]

    assert items["items"] == {"anyOf": [{"$ref": "#/$defs/Item"}, {"type": "null"}]}
    assert items["type"] == "array" and items["description"] == "By position; a null skips one"


def test_a_unit_joins_the_description_once():
    props = schema()["properties"]

    assert schema()["$defs"]["Item"]["properties"]["size"]["description"] == "How big (px)"
    assert props["radius"]["description"] == "Radius (usm, px)"  # inside the parenthesis it ends with
    assert props["centre"]["description"] == "Centre offset: % of the width (100 = the whole width)"
    assert props["temperature"]["description"] == "Colour temperature (K)"
    assert props["tint"]["description"] == "Tint multiplier"  # said already


def test_a_description_that_only_repeats_the_name_is_dropped():
    props = schema()["properties"]

    assert "description" not in props["amount"] and "description" not in props["enabled"]


def test_the_model_description_is_its_first_paragraph_on_one_line():
    assert schema()["description"] == "A toy: what a caller needs."


def test_full_schema_has_everything_pydantic_and_the_models_put_in():
    with full_schema():
        full = Toy.model_json_schema()
    props = full["properties"]

    assert props["amount"]["art_default"] == 3 and props["amount"]["title"] == "Amount"
    assert props["radius"]["unit"] == "px" and props["radius"]["description"] == "Radius (usm)"
    assert props["mode"]["anyOf"][-1] == {"type": "null"} and props["mode"]["default"] is None
    assert "Reference text" in full["description"] and full["additionalProperties"] is False
    assert schema()["properties"]["amount"] != props["amount"]  # and compact again afterwards


def test_validation_is_not_touched():
    assert Toy.model_validate({"amount": None, "item": {"size": 1}}).amount is None
    with pytest.raises(ValidationError):
        Toy.model_validate({"amount": 1, "gain": 2})  # extra fields are still refused
    with pytest.raises(ValidationError):
        Toy.model_validate({"item": {"size": 10}})
