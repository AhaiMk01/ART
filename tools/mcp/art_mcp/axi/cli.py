"""``art-axi``: the Render server's operations as a command-line tool for
agents, following AXI (https://axi.md): TOON on stdout, errors on stdout in
the same format, exit codes 0 / 1 (the operation failed) / 2 (bad usage),
progress on stderr, no prompts.

Each run is its own process, so the working profiles live in a state folder
(``state.py``) and an image stays open from one run to the next until
``close``. The operations are the MCP server's (``render/*_ops.py``).

This module dispatches: global flags, the command table, unknown-flag checks
and the exit code. The commands live by concern: ``images`` (home, open,
close, reset, inspect), ``editing`` (profile, edit, describe), ``measuring``
(stats, sample), ``viewing`` (preview, sheet) and ``writing`` (save, export);
``core`` has the errors, session and ``Command``, ``args`` the flag types and
PATH selection, ``output`` the shaping of results.
"""

from collections.abc import Callable
from typing import Any

from art_mcp.axi.args import has_failures, select_paths
from art_mcp.axi.core import (
    EXIT_FAILED,
    EXIT_OK,
    GLOBAL_FLAGS,
    Command,
    Context,
    Failure,
    UsageError,
    emit,
    error_output,
)
from art_mcp.axi.editing import build_describe, build_edit, build_profile, run_describe, run_edit, run_profile
from art_mcp.axi.images import (
    build_close,
    build_inspect,
    build_open,
    build_reset,
    run_close,
    run_home,
    run_inspect,
    run_open,
    run_reset,
)
from art_mcp.axi.measuring import build_sample, build_stats, run_sample, run_stats
from art_mcp.axi.output import rows
from art_mcp.axi.state import default_home
from art_mcp.axi.viewing import build_preview, build_sheet, run_preview, run_sheet
from art_mcp.axi.writing import build_export, build_save, run_export, run_save

COMMANDS = {
    c.name: c
    for c in (
        Command(
            "open",
            "Open images: load each one's sidecar (else ART's default) as its working profile.",
            build_open,
            run_open,
            ["art-axi open ~/raw/IMG_1.ARW", "art-axi open ~/raw/*.ARW --profile look.arp"],
            {"--path": "give paths as arguments: art-axi open <path>..."},
        ),
        Command(
            "close",
            "Forget images' working profiles (unsaved edits are dropped).",
            build_close,
            run_close,
            ["art-axi close ~/raw/IMG_1.ARW", "art-axi close --all"],
        ),
        Command(
            "reset",
            "Reload working profiles from the sidecar or ART's default.",
            build_reset,
            run_reset,
            ["art-axi reset IMG_1.ARW --to sidecar"],
        ),
        Command(
            "profile",
            "Read an open image's working profile (default: values that differ from ART's default). Each value "
            "has its Group/Key and stored value (what edit --set takes) and, for a curated tool, its name and value "
            "(what edit --adjust takes). unsaved_edits: values changed since the image was opened, reset or saved.",
            build_profile,
            run_profile,
            ["art-axi profile IMG_1.ARW", "art-axi profile IMG_1.ARW --all --groups Exposure,ToneCurve"],
            {
                "--changed-only": "that is the default; --all reads every value",
                "--changed": "that is the default; --all reads every value",
            },
        ),
        Command(
            "edit",
            "Change working-profile values; prints only what changed.",
            build_edit,
            run_edit,
            [
                "art-axi edit IMG_1.ARW --set Exposure/Compensation=0.5",
                'art-axi edit a.ARW b.ARW --adjust \'{"exposure":{"compensation":0.5}}\'',
            ],
            {"--raw-edits": "use --set Group/Key=value (repeatable)", "--adjustments": "use --adjust '<json>'"},
        ),
        Command(
            "describe",
            "The curated adjustments `edit --adjust` takes.",
            build_describe,
            run_describe,
            ["art-axi describe", "art-axi describe exposure"],
        ),
        Command(
            "preview",
            "Render the working profile as a JPEG and print its path.",
            build_preview,
            run_preview,
            [
                "art-axi preview IMG_1.ARW",
                "art-axi preview IMG_1.ARW --region 0.4,0.4,0.2,0.2",
                "art-axi preview IMG_1.ARW --mark 3000,2000 --mark 1200,800,64,A --zoom",
            ],
            {"--max-size": "use --size", "--output": "use --out", "--marks": "use --mark (repeatable)"},
        ),
        Command(
            "stats",
            "Clipping and percentiles of a rendered image, per channel. clipped_high/clipped_low are fractions "
            "(0..1) of the pixels at 255 / 0 of a render whose long edge is --size (raise it to catch small clipped "
            "areas); percentiles are 8-bit values. --set measures values without storing them; --sweep measures "
            "several values of one key in one call.",
            build_stats,
            run_stats,
            [
                "art-axi stats IMG_1.ARW",
                "art-axi stats *.ARW --detail compact --lum-max 250",
                "art-axi stats IMG_1.ARW --sweep Exposure/Compensation=0.4,0.5,0.6,0.7",
            ],
            {"--max-size": "use --size"},
        ),
        Command(
            "sample",
            "Linear RGB averages of squares of frame pixels, as ART's spot pickers read.",
            build_sample,
            run_sample,
            ["art-axi sample IMG_1.ARW --spot 3000,2000 --spot 1200,800,64"],
            {"--spots": "use --spot x,y[,size] (repeatable)"},
        ),
        Command(
            "save",
            "Write the working profile to the image's sidecar (the old one kept as .bak).",
            build_save,
            run_save,
            ["art-axi save IMG_1.ARW", "art-axi save IMG_1.ARW --on-conflict merge"],
        ),
        Command(
            "export",
            "Render the working profile at full size to a file.",
            build_export,
            run_export,
            [
                "art-axi export IMG_1.ARW --out ~/out/IMG_1.jpg --quality 92",
                "art-axi export IMG_1.ARW --out ~/out/IMG_1.tif --bit-depth 16",
            ],
            {"--output": "use --out"},
        ),
        Command(
            "inspect",
            "Camera metadata and frame size of open images.",
            build_inspect,
            run_inspect,
            ["art-axi inspect IMG_1.ARW", "art-axi inspect *.ARW --tags Software"],
        ),
        Command(
            "sheet",
            "Render several open images into one contact-sheet JPEG to look at them in one read.",
            build_sheet,
            run_sheet,
            [
                "art-axi sheet roll/*.ARW",
                "art-axi sheet roll/ --thumb 400 --columns 5",
                "art-axi sheet roll/*.ARW --record ~/work --label exposure",
            ],
            {"--thumb-size": "use --thumb", "--folder": "use --record <folder>"},
        ),
    )  # fmt: skip
}


def split_globals(argv: list[str]) -> tuple[list[str], dict[str, str]]:
    rest, found = [], {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        name, eq, value = arg.partition("=")
        if name in GLOBAL_FLAGS:
            if not eq:
                if i + 1 >= len(argv):
                    raise UsageError(f"{name} needs a value", f"art-axi {name} <value> ...")
                value = argv[i + 1]
                i += 1
            found[name] = value
        else:
            rest.append(arg)
        i += 1
    return rest, found


def unknown_flag_check(command: Command, argv: list[str]) -> None:
    """Reject flags the command doesn't take by name, with the valid ones, before
    argparse's own message."""
    valid = command.valid_flags()
    for arg in argv:
        if arg == "--":
            return
        if not arg.startswith("--") or arg == "--help":
            continue
        name = arg.split("=", 1)[0]
        if name in valid:
            continue
        if name in command.renamed:
            raise UsageError(f"unknown flag {name} for `{command.name}`: {command.renamed[name]}")
        raise UsageError(
            f"unknown flag {name} for `{command.name}`",
            f"valid flags for `{command.name}`: {', '.join(valid)} (--help always allowed)",
        )


def top_help() -> dict[str, Any]:
    return {
        "usage": "art-axi [<command>] [flags]   (no command: the open images)",
        "workflow": "open -> stats/preview -> edit -> preview -> save -> export -> close",
        "commands": rows(
            [{"name": c.name, "summary": c.summary, "usage": c.usage()} for c in COMMANDS.values()],
            ["name", "summary", "usage"],
        ),
        "globals": "--art-dir <folder> (ART-cli's folder; default ART_DIR, PATH, newest install), --timeout <s>",
        "state": "working profiles persist between runs in ART_AXI_HOME (default: per-user state folder)",
        "help": ["art-axi <command> --help"],
    }


def run(argv: list[str], session_factory: Callable[[Context], Any] | None = None) -> int:
    try:
        argv, globals_ = split_globals(argv)
        timeout = None
        if "--timeout" in globals_:
            try:
                timeout = float(globals_["--timeout"])
            except ValueError:
                raise UsageError(f"--timeout takes seconds, not {globals_['--timeout']!r}") from None
        ctx = Context(default_home(), globals_.get("--art-dir"), timeout, session_factory)
        if not argv:
            emit(run_home(ctx))
            return EXIT_OK
        if argv[0] in ("--help", "-h", "help"):
            emit(top_help())
            return EXIT_OK
        command = COMMANDS.get(argv[0])
        if command is None:
            kind = "flag" if argv[0].startswith("-") else "command"
            raise UsageError(f"unknown {kind} {argv[0]}", f"commands: {', '.join(COMMANDS)}; art-axi --help")
        args = argv[1:]
        if "--help" in args or "-h" in args:
            print(command.parser().format_help().rstrip())
            return EXIT_OK
        unknown_flag_check(command, args)
        parsed = command.parser().parse_args(args)
        skipped = select_paths(ctx, command, parsed)
        out = command.run(ctx, parsed)
        if skipped:
            out["skipped"] = skipped
        emit(out)
        return EXIT_FAILED if has_failures(out) else EXIT_OK
    except Failure as e:
        emit(error_output(e))
        return e.exit_code
