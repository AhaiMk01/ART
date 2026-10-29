import pytest

from art_mcp.axi.toon import encode


def test_object_and_nested_object():
    assert encode({"id": 1, "user": {"name": "Ada", "active": True}}) == "id: 1\nuser:\n  name: Ada\n  active: true"


def test_primitive_array_and_empty_array():
    assert encode({"tags": ["a", "b"], "none": []}) == "tags[2]: a,b\nnone: []"


def test_uniform_objects_are_a_table():
    items = [{"sku": "A1", "qty": 2, "price": 9.99}, {"qty": 1, "sku": "B2", "price": 14.5}]
    assert encode({"items": items}) == "items[2]{sku,qty,price}:\n  A1,2,9.99\n  B2,1,14.5"


def test_objects_with_a_list_value_are_list_items():
    items = [{"id": 1, "tags": ["x"]}, {"id": 2, "tags": []}]
    assert encode({"items": items}) == "items[2]:\n  - id: 1\n    tags[1]: x\n  - id: 2\n    tags: []"


def test_list_item_whose_first_field_is_a_table():
    item = {"users": [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bob"}], "status": "active"}
    assert encode({"items": [item]}) == (
        "items[1]:\n  - users[2]{id,name}:\n      1,Ada\n      2,Bob\n    status: active"
    )


def test_list_item_whose_first_field_is_an_object():
    assert encode({"x": [{"a": {"b": 1}, "c": 2}, 3]}) == "x[2]:\n  - a:\n      b: 1\n    c: 2\n  - 3"


def test_array_of_arrays():
    assert encode({"pairs": [[1, 2], [3, 4]]}) == "pairs[2]:\n  - [2]: 1,2\n  - [2]: 3,4"


@pytest.mark.parametrize(
    ("text", "encoded"),
    [
        ("", '""'),
        (" a", '" a"'),
        ("true", '"true"'),
        ("null", '"null"'),
        ("05", '"05"'),
        ("1e-6", '"1e-6"'),
        ("a:b", '"a:b"'),
        ("a,b", '"a,b"'),
        ("[x]", '"[x]"'),
        ("-x", '"-x"'),
        ("#x", '"#x"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("line\nbreak", '"line\\nbreak"'),
        ("\x01", '"\\u0001"'),
        ("C:\\raw", '"C:\\\\raw"'),
        ("Hello 世界", "Hello 世界"),
        (".5", ".5"),
        ("a b", "a b"),
    ],
)
def test_string_quoting(text, encoded):
    assert encode({"v": text}) == f"v: {encoded}"


@pytest.mark.parametrize(
    ("number", "encoded"),
    [(1.0, "1"), (-0.0, "0"), (1.5, "1.5"), (1e16, "10000000000000000"), (1.5e-5, "0.000015"),
     (1e-7, "1e-7"), (float("nan"), "null"), (float("inf"), "null"), (3, "3")],
)  # fmt: skip
def test_numbers(number, encoded):
    assert encode({"n": number}) == f"n: {encoded}"


def test_keys_that_need_quotes():
    assert encode({"my-key": 1, "a.b": 2, "1a": [1]}) == '"my-key": 1\na.b: 2\n"1a"[1]: 1'


def test_root_forms():
    assert encode([]) == "[]"
    assert encode([1, "a"]) == "[2]: 1,a"
    assert encode([{"a": 1}, {"a": 2}]) == "[2]{a}:\n  1\n  2"
    assert encode("hello") == "hello"
    assert encode({}) == ""
