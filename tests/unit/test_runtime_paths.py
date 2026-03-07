from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from threep_commons.paths import (
    configure_qsettings,
    resolve_data_root,
)

from git_statuz.constants import APP_IDENTITY, SETTINGS_APP_NAME, SETTINGS_ORG_NAME


def test_configure_qsettings_uses_override_root(tmp_path: Path) -> None:
    config_root = tmp_path / "cfg"
    configure_qsettings(
        APP_IDENTITY,
        config_dir_override=str(config_root),
    )
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        SETTINGS_ORG_NAME,
        SETTINGS_APP_NAME,
    )
    settings.setValue("ui/smoke", True)
    settings.sync()
    assert Path(settings.fileName()).parent == config_root / SETTINGS_ORG_NAME


def test_resolve_data_root_prefers_override(tmp_path: Path) -> None:
    data_root = resolve_data_root(APP_IDENTITY, str(tmp_path / "runtime"))
    assert data_root == tmp_path / "runtime"
