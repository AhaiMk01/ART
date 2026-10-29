"""Entry point of ``art-axi``: answers a bare version flag before importing
the CLI (pydantic, the schema and the operations take a while to load)."""

import sys

VERSION_FLAGS = ("-v", "-V", "--version")


def main() -> None:
    argv = sys.argv[1:]
    if len(argv) == 1 and argv[0] in VERSION_FLAGS:
        from art_mcp.axi.version import VERSION

        print(VERSION)
        return
    from art_mcp.axi.cli import run

    sys.exit(run(argv))


if __name__ == "__main__":
    main()
