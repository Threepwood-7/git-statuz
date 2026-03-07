"""Tests for git_statuz."""

import importlib


def test_package_importable() -> None:
    assert importlib.import_module("git_statuz")
