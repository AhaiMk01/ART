"""ART's default processing profile for an image, as art-cli resolves it.

``get_profile``'s ``changed_only`` compares an image's profile with it, on
both servers (the Render session keeps one per opened image; the Live server
one per image it was asked about).
"""

from pathlib import Path

from art_mcp import keyfile
from art_mcp.keyfile import KeyFile
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli, ArtCliError, ArtCliTimeout, resolve_profile_args
from art_mcp.render.errors import no_profile_written, render_error


def resolve_default_profile(cli: ArtCli, previews: PreviewFolder, image: Path) -> KeyFile:
    """The complete profile ART would start ``image`` from without a sidecar
    (its default profile for that image type, dynamic rules applied): one
    art-cli run, as ``open_image`` does for an image without a sidecar. Raises
    ``RenderError`` (``render_failed``, ``timeout``)."""
    output = previews.new_file("default", ".jpg")
    arp = Path(str(output) + ".arp")
    try:
        try:
            cli.run(resolve_profile_args(image, output, None))
        except ArtCliTimeout as e:
            raise render_error("timeout", str(e)) from e
        except ArtCliError as e:
            raise render_error("render_failed", str(e)) from e
        if not arp.is_file():
            raise no_profile_written()
        return keyfile.loads(arp.read_text(encoding="utf-8"))
    finally:
        output.unlink(missing_ok=True)
        arp.unlink(missing_ok=True)
