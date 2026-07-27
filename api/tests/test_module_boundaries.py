"""The modular monolith's boundaries, enforced.

A modular monolith is only modular while something checks. These rules are cheap to
break by accident (an editor's auto-import will happily reach into another module's
service.py) and expensive to unpick later, so they are asserted rather than documented.

Rules:
  1. A module may not import another module's submodules — only its package root.
  2. core may not import modules. Dependencies point inward, never back out.
  3. Nothing outside a module may import its models or service directly.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "furnitureos"
MODULES_DIR = SRC / "modules"

MODULE_NAMES = sorted(
    path.name for path in MODULES_DIR.iterdir() if path.is_dir() and (path / "__init__.py").exists()
)


def python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def imported_names(path: Path) -> list[str]:
    """Every dotted name this file imports, as written."""
    # utf-8-sig, not utf-8: a BOM-prefixed file is valid Python but ast.parse rejects it,
    # and Windows editors still write BOMs.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)

    return names


def owning_module(path: Path) -> str | None:
    """The module a source file belongs to, or None if it is core or the root."""
    try:
        relative = path.relative_to(MODULES_DIR)
    except ValueError:
        return None
    return relative.parts[0]


def test_there_is_at_least_one_module() -> None:
    """Guards the tests below from silently passing over an empty directory."""
    assert MODULE_NAMES


@pytest.mark.parametrize("path", python_files(MODULES_DIR), ids=str)
def test_modules_do_not_reach_into_each_other(path: Path) -> None:
    owner = owning_module(path)

    for name in imported_names(path):
        parts = name.split(".")
        if parts[:2] != ["furnitureos", "modules"]:
            continue

        target = parts[2] if len(parts) > 2 else None
        if target is None or target == owner:
            continue

        assert len(parts) == 3, (
            f"{path.name} reaches into {name}. Import `furnitureos.modules.{target}` "
            f"itself and use what its __init__ exports."
        )


@pytest.mark.parametrize("path", python_files(SRC / "core"), ids=str)
def test_core_does_not_depend_on_modules(path: Path) -> None:
    for name in imported_names(path):
        assert not name.startswith("furnitureos.modules"), (
            f"core/{path.name} imports {name}. Core is the shared kernel: modules "
            f"depend on it, not the other way round."
        )


@pytest.mark.parametrize(
    "path",
    [path for path in python_files(SRC) if owning_module(path) is None],
    ids=str,
)
def test_the_composition_root_uses_only_public_surfaces(path: Path) -> None:
    """main.py and registry.py wire modules together; they still go through the front door.

    registry.py is the one exception: model registration has to name the models module,
    because that import *is* the side effect being relied on.
    """
    allowed_depth_3 = {"furnitureos.modules.units.models"} if path.name == "registry.py" else set()

    for name in imported_names(path):
        if not name.startswith("furnitureos.modules."):
            continue
        if name in allowed_depth_3:
            continue
        assert name.count(".") == 2, f"{path.name} imports {name} instead of the module root"
