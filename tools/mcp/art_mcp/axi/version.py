"""The version ``art-axi --version`` prints. A leaf module: nothing beyond
the standard library, so the version answers without loading the CLI."""

from importlib.metadata import PackageNotFoundError, version

try:
    VERSION = version("art-mcp")
except PackageNotFoundError:
    VERSION = "0+unknown"
