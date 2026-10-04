from pathlib import Path

from art_mcp.render import artcli

IMG = Path("D:/photos/IMG_1.ARW")
OUT = Path("C:/tmp/out.jpg")


def test_resolve_run_uses_sidecar_when_present():
    args = artcli.resolve_profile_args(IMG, OUT, sidecar=Path("D:/photos/IMG_1.ARW.arp"))

    assert args == ["-O", str(OUT), "-f", "-Y", "-a", "-p", str(Path("D:/photos/IMG_1.ARW.arp")), "-c", str(IMG)]


def test_resolve_run_uses_default_profile_without_sidecar():
    args = artcli.resolve_profile_args(IMG, OUT, sidecar=None)

    assert args == ["-O", str(OUT), "-f", "-Y", "-a", "-d", "-c", str(IMG)]


def test_preview_run_layers_working_profile_then_resize():
    args = artcli.preview_args(IMG, OUT, profile=Path("C:/tmp/w.arp"), resize=Path("C:/tmp/r.arp"))

    assert args == [
        "-o", str(OUT), "-f", "-Y", "-a",
        "-p", str(Path("C:/tmp/w.arp")), "-p", str(Path("C:/tmp/r.arp")),
        "-j85", "-c", str(IMG),
    ]
