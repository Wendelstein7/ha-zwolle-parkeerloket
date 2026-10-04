"""Guards for the boundary between the API layer and Home Assistant.

The client, models and constants must stay importable and testable without Home
Assistant, so that the portal integration can be verified on its own and swapped
out if the portal changes.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

COMPONENT = Path(__file__).parents[1] / "custom_components" / "zwolle_parkeerloket"
API_LAYER_MODULES = ("api.py", "models.py", "const.py")


def _imported_modules(path: Path) -> set[str]:
    """Return every module name imported by the given source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    return imported


@pytest.mark.parametrize("module", API_LAYER_MODULES)
def test_api_layer_does_not_import_home_assistant(module: str) -> None:
    """Nothing in the API layer may depend on Home Assistant."""
    imported = _imported_modules(COMPONENT / module)

    offenders = sorted(
        name for name in imported if name.split(".")[0] == "homeassistant"
    )
    assert not offenders, f"{module} must not import Home Assistant: {offenders}"


@pytest.mark.parametrize("module", API_LAYER_MODULES)
def test_api_layer_stays_importable_without_home_assistant(
    module: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing the API layer must not pull Home Assistant into ``sys.modules``."""
    for name in [name for name in sys.modules if name.split(".")[0] == "homeassistant"]:
        monkeypatch.delitem(sys.modules, name)

    module_name = f"custom_components.zwolle_parkeerloket.{module.removesuffix('.py')}"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    importlib.import_module(module_name)

    assert not [name for name in sys.modules if name.split(".")[0] == "homeassistant"]
