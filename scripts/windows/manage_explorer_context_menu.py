from __future__ import annotations

import argparse
import sys
import winreg
from dataclasses import dataclass
from pathlib import Path

MENU_LABEL = "Open with GitStatuz"
MENU_ICON = r"%SystemRoot%\System32\shell32.dll,-4"
MENU_VERB = "GitStatuz.OpenWith"
PYW_EXE = Path(r"C:\Windows\pyw.exe")


@dataclass(frozen=True)
class MenuTarget:
    key_path: str
    path_placeholder: str


TARGETS: tuple[MenuTarget, ...] = (
    MenuTarget(
        key_path=rf"Software\Classes\Directory\shell\{MENU_VERB}",
        path_placeholder="%1",
    ),
    MenuTarget(
        key_path=rf"Software\Classes\Directory\Background\shell\{MENU_VERB}",
        path_placeholder="%V",
    ),
)


def launcher_path() -> Path:
    return Path(__file__).resolve().with_name("run_app_gui.pyw")


def command_value(launcher: Path, path_placeholder: str) -> str:
    return f'"{PYW_EXE}" "{launcher}" --input "{path_placeholder}"'


def create_menu_entry(launcher: Path, target: MenuTarget) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, target.key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, MENU_LABEL)
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, MENU_ICON)

    command_key_path = f"{target.key_path}\\command"
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, command_key_path, 0, winreg.KEY_SET_VALUE
    ) as command_key:
        winreg.SetValueEx(
            command_key,
            None,
            0,
            winreg.REG_SZ,
            command_value(launcher, target.path_placeholder),
        )


def delete_tree(root: int, key_path: str) -> None:
    try:
        with winreg.OpenKey(
            root, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            while True:
                try:
                    child_name = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_tree(root, f"{key_path}\\{child_name}")
    except FileNotFoundError:
        return

    winreg.DeleteKey(root, key_path)


def install() -> int:
    launcher = launcher_path()
    if not launcher.exists():
        print(
            f"ERROR: launcher script not found: {launcher}",
            file=sys.stderr,
        )
        return 1

    try:
        for target in TARGETS:
            create_menu_entry(launcher, target)
    except OSError as exc:
        print(
            f"ERROR: failed to write Explorer context menu keys: {exc}", file=sys.stderr
        )
        return 1

    print("Explorer context menu installed for folder item and folder background.")
    return 0


def uninstall() -> int:
    try:
        for target in TARGETS:
            delete_tree(winreg.HKEY_CURRENT_USER, target.key_path)
    except OSError as exc:
        print(
            f"ERROR: failed to remove Explorer context menu keys: {exc}",
            file=sys.stderr,
        )
        return 1

    print("Explorer context menu removed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install or uninstall the GitStatuz Windows Explorer context menu."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("install", help="Install the context menu entries.")
    subparsers.add_parser("uninstall", help="Remove the context menu entries.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.action == "install":
        return install()
    if args.action == "uninstall":
        return uninstall()
    parser.error(f"Unsupported action: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
