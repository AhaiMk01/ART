"""The Render operations' errors: a code and a message, no MCP involved.

``str(error)`` is ``"<code>: <message>"``, which is the text an MCP tool error
carries (see ``adapter.py``); the ``art-tool`` CLI reads ``code`` and
``message`` instead.
"""

from typing import Literal

ErrorCode = Literal[
    "not_open", "not_found", "unknown_key", "render_failed", "timeout",
    "conflict", "exists", "out_of_range", "open_in_editor",
    "metadata_unavailable", "metadata_failed", "invalid_tag", "unsupported",
]  # fmt: skip


class RenderError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code: ErrorCode = code
        self.message = message


def render_error(code: ErrorCode, message: str) -> RenderError:
    return RenderError(code, message)


def no_profile_written() -> RenderError:
    return render_error(
        "render_failed",
        "art-cli wrote no profile beside its output; turn off "
        '"Embed processing parameters in metadata" in ART\'s preferences',
    )
