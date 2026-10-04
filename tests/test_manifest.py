"""Sanity checks on the integration metadata and tooling configuration."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

from custom_components.zwolle_parkeerloket import services as service_module

REPO_ROOT = Path(__file__).parents[1]
COMPONENT_DIR = REPO_ROOT / "custom_components" / "zwolle_parkeerloket"


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
        "sensor": set(strings["entity"]["sensor"]),
        "binary_sensor": set(strings["entity"]["binary_sensor"]),
    }

    for module, platform in (
        ("sensor.py", "sensor"),
        ("binary_sensor.py", "binary_sensor"),
    ):
        source = (COMPONENT_DIR / module).read_text(encoding="utf-8")
        used = set(
            re.findall(r'super\(\).__init__\(coordinator, "([a-z_]+)"\)', source)
        )
        assert used, f"no entity keys found in {module}"
        assert used <= translated[platform], (
            f"{module} uses untranslated keys: {used - translated[platform]}"
        )


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
