"""Sanity checks on the integration metadata and tooling configuration."""

from __future__ import annotations

import json
import re
import struct
import tomllib
from pathlib import Path
from urllib.parse import urlparse

import voluptuous as vol
import yaml
from awesomeversion import AwesomeVersion

from custom_components.zwolle_parkeerloket import services as service_module

REPO_ROOT = Path(__file__).parents[1]
COMPONENT_DIR = REPO_ROOT / "custom_components" / "zwolle_parkeerloket"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# The HACS action validates these files with its own schemas, fetched directly
# from raw.githubusercontent.com. That action ships as a Docker image and cannot
# be run locally, so mirroring its schemas here means broken metadata fails in the
# test suite instead of only in CI.
# Source: hacs/integration custom_components/hacs/utils/validate.py
HACS_MANIFEST_SCHEMA = vol.Schema(
    {
        vol.Optional("content_in_root"): bool,
        vol.Optional("country"): vol.Any(str, [str]),
        vol.Optional("filename"): str,
        vol.Optional("hacs"): str,
        vol.Optional("hide_default_branch"): bool,
        vol.Optional("homeassistant"): str,
        vol.Optional("persistent_directory"): str,
        vol.Optional("render_readme"): bool,
        vol.Optional("zip_release"): bool,
        vol.Required("name"): str,
    },
    extra=vol.PREVENT_EXTRA,
)

# The only filenames Home Assistant serves out of a local brand directory.
# Source: homeassistant/components/brands/const.py
ALLOWED_BRAND_IMAGES = frozenset(
    {
        "icon.png",
        "logo.png",
        "icon@2x.png",
        "logo@2x.png",
        "dark_icon.png",
        "dark_logo.png",
        "dark_icon@2x.png",
        "dark_logo@2x.png",
    }
)


def _png_size(path: Path) -> tuple[int, int]:
    """Return the width and height read straight from the PNG header."""
    data = path.read_bytes()
    assert data[:8] == PNG_MAGIC, f"{path.name} is not a PNG image"
    return struct.unpack(">II", data[16:24])


def _manifest() -> dict:
    """Return the parsed manifest of the integration."""
    return json.loads((COMPONENT_DIR / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_matches_domain_and_directory() -> None:
    """The manifest must live in the directory named after its domain."""
    assert _manifest()["domain"] == COMPONENT_DIR.name


def test_manifest_is_hacs_compatible() -> None:
    """HACS requires a version on custom integrations and a matching display name."""
    manifest = _manifest()
    hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))

    assert manifest["version"], "custom integrations must declare a version"
    assert manifest["name"] == hacs["name"]
    assert not manifest["requirements"], "no external requirements should be needed"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["integration_type"] == "hub"


def test_manifest_version_is_parseable() -> None:
    """HACS compares the version string, so keep it parseable."""
    parts = _manifest()["version"].split(".")
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts[:2])


def test_hacs_json_matches_the_hacs_schema() -> None:
    """``hacs.json`` must satisfy the schema the HACS action validates it with."""
    hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))

    # Raises Invalid if a key is unknown or has the wrong type.
    HACS_MANIFEST_SCHEMA(hacs)


def test_declared_minimum_home_assistant_can_parse_the_code() -> None:
    """The declared floor has to be high enough for the syntax this module uses.

    Home Assistant moved to Python 3.14 in 2026.3, and 3.14 is what allows the
    parenthesis-free ``except`` clauses the formatter writes here. HACS refuses to
    install below the version declared in ``hacs.json``, so declaring anything
    lower would offer the integration to a Home Assistant that cannot parse it.
    """
    hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))

    declared = hacs.get("homeassistant")
    assert declared, "hacs.json should declare a minimum Home Assistant version"
    assert AwesomeVersion(declared) >= AwesomeVersion("2026.3.0"), (
        "the minimum has to stay at or above the release that runs Python 3.14"
    )


def test_manifest_declares_everything_hacs_requires() -> None:
    """HACS reads the manifest directly, so its required keys must all be present."""
    manifest = _manifest()

    assert manifest["codeowners"], "HACS requires at least one code owner"
    assert isinstance(manifest["codeowners"], list)
    assert manifest["name"]
    assert manifest["domain"]
    for key in ("documentation", "issue_tracker"):
        parsed = urlparse(manifest[key])
        assert parsed.scheme in {"http", "https"} and parsed.netloc, (
            f"{key} is not an absolute URL: {manifest[key]!r}"
        )
    assert AwesomeVersion(manifest["version"]).valid


def test_tooling_configuration_is_consistent() -> None:
    """Test and lint configuration should stay in sync with this test suite."""
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["tool"]["pytest"]["ini_options"]["asyncio_mode"] == "auto"
    assert pyproject["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    assert pyproject["tool"]["ruff"]["target-version"] == "py314"


def _translation_keys(data: dict, prefix: str = "") -> set[str]:
    """Return every dotted key path in a translation file."""
    keys: set[str] = set()
    for key, value in data.items():
        keys.add(f"{prefix}{key}")
        if isinstance(value, dict):
            keys |= _translation_keys(value, f"{prefix}{key}.")
    return keys


def test_brand_assets_are_present_and_correctly_sized() -> None:
    """The local brand directory is what HACS and Home Assistant look for.

    HACS passes its brands check when ``brand/icon.png`` is in the repository tree,
    and Home Assistant serves the local copy in preference to any image from the
    brands repository.
    """
    brand_dir = COMPONENT_DIR / "brand"
    assert (brand_dir / "icon.png").is_file(), "hacs validation requires brand/icon.png"
    assert {path.name for path in brand_dir.iterdir()} <= ALLOWED_BRAND_IMAGES

    # Sizes mandated by the brands repository specification.
    assert _png_size(brand_dir / "icon.png") == (256, 256)
    assert _png_size(brand_dir / "icon@2x.png") == (512, 512)


def test_translations_are_consistent() -> None:
    """``strings.json`` drives the English translation and every language matches."""
    component = COMPONENT_DIR
    strings = json.loads((component / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (component / "translations" / "en.json").read_text(encoding="utf-8")
    )
    dutch = json.loads(
        (component / "translations" / "nl.json").read_text(encoding="utf-8")
    )

    assert strings == english, "translations/en.json must mirror strings.json"
    assert _translation_keys(strings) == _translation_keys(dutch), (
        "nl.json is missing or has extra translation keys"
    )


def test_every_entity_used_in_code_is_translated() -> None:
    """Each translation key an entity uses must exist in the translation files."""
    strings = json.loads((COMPONENT_DIR / "strings.json").read_text(encoding="utf-8"))
    translated = {
        platform: set(strings["entity"][platform])
        for platform in ("sensor", "binary_sensor", "button", "text", "calendar")
    }

    for module, platform in (
        ("sensor.py", "sensor"),
        ("binary_sensor.py", "binary_sensor"),
        ("button.py", "button"),
        ("text.py", "text"),
        ("calendar.py", "calendar"),
    ):
        source = (COMPONENT_DIR / module).read_text(encoding="utf-8")
        used = set(
            re.findall(r'super\(\).__init__\(coordinator, "([a-z_]+)"\)', source)
        )
        assert used, f"no entity keys found in {module}"
        assert used <= translated[platform], (
            f"{module} uses untranslated keys: {used - translated[platform]}"
        )


def test_every_action_requires_a_licence_plate() -> None:
    """A plate is how an action names a booking, so every action needs one.

    The portal keeps several reservations at once, so an action that did not name
    a car could act on the wrong one. Home Assistant reads ``required`` from here
    to decide whether the field may be left empty in the UI.
    """
    described = yaml.safe_load(
        (COMPONENT_DIR / "services.yaml").read_text(encoding="utf-8")
    )

    for name, service in described.items():
        plate = (service.get("fields") or {}).get("license_plate")
        assert plate is not None, f"{name} does not accept a licence plate"
        assert plate.get("required") is True, f"{name} does not require a plate"


def test_every_action_is_described_and_translated() -> None:
    """Each service the code registers has a services.yaml entry and translations.

    This mirrors what hassfest checks for service actions, which cannot be run
    locally because it is only distributed as a Docker image.
    """
    registered = {
        service_module.SERVICE_START_BOOKING,
        service_module.SERVICE_STOP_BOOKING,
        service_module.SERVICE_CHANGE_BOOKING_TIME,
    }
    described = yaml.safe_load(
        (COMPONENT_DIR / "services.yaml").read_text(encoding="utf-8")
    )
    strings = json.loads((COMPONENT_DIR / "strings.json").read_text(encoding="utf-8"))
    dutch = json.loads(
        (COMPONENT_DIR / "translations" / "nl.json").read_text(encoding="utf-8")
    )

    assert registered == set(described), "services.yaml and the code disagree"
    assert registered == set(strings["services"]), "strings.json is missing an action"
    assert registered == set(dutch["services"]), "nl.json is missing an action"

    for name in sorted(registered):
        # An action without fields legitimately has no "fields" key at all.
        fields = set(described[name].get("fields") or {})
        described_in_strings = set(strings["services"][name].get("fields") or {})
        assert fields == described_in_strings, (
            f"{name}: services.yaml and strings.json describe different fields"
        )


def test_every_action_has_a_name_and_description() -> None:
    """An action without a description is invisible in the UI."""
    strings = json.loads((COMPONENT_DIR / "strings.json").read_text(encoding="utf-8"))

    for name, service in strings["services"].items():
        assert service.get("name"), f"{name} has no name"
        assert service.get("description"), f"{name} has no description"
        for field, described in (service.get("fields") or {}).items():
            assert described.get("name"), f"{name}.{field} has no name"
            assert described.get("description"), f"{name}.{field} has no description"


def test_exception_keys_used_in_code_are_translated() -> None:
    """Every exception the code can raise has a translation to show the user."""
    strings = json.loads((COMPONENT_DIR / "strings.json").read_text(encoding="utf-8"))
    translated = set(strings["exceptions"])

    used: set[str] = set()
    for module in COMPONENT_DIR.glob("*.py"):
        used |= set(
            re.findall(
                r'translation_key="([a-z_]+)"', module.read_text(encoding="utf-8")
            )
        )

    assert used, "no translated exceptions found, which cannot be right"
    assert used <= translated, f"untranslated exceptions: {sorted(used - translated)}"
