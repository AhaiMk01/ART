from pathlib import Path

from art_mcp import keyfile

PROFILES = Path(__file__).resolve().parents[3] / "data" / "profiles"


def test_parses_groups_and_keys_as_raw_strings():
    text = "# comment\n[Exposure]\nEnabled=true\nCompensation=0.5\n\n[Resize]\nWidth=1024\n"

    kf = keyfile.loads(text)

    assert kf == {
        "Exposure": {"Enabled": "true", "Compensation": "0.5"},
        "Resize": {"Width": "1024"},
    }


def test_bundled_profiles_round_trip():
    for path in PROFILES.glob("*.arp"):
        kf = keyfile.loads(path.read_text(encoding="utf-8"))

        assert kf, path.name
        assert keyfile.loads(keyfile.dumps(kf)) == kf, path.name
