"""Phase 1 smoke test: project skeleton imports and lives on E:."""
import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize("pkg", ["agent", "api", "eval", "llm", "policy", "shop_db", "tools"])
def test_packages_import(pkg):
    importlib.import_module(pkg)


def test_project_on_e_drive():
    assert Path(__file__).resolve().drive.upper() == "E:"
