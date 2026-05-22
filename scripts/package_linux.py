from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import platform
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "trend-analyzer"
APP_TITLE = "Trend Analyzer"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


def run(
    cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    subprocess.run(cmd, cwd=cwd or ROOT, env=env, check=True)


def build_python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def venv_site_packages() -> Path | None:
    venv_lib = ROOT / ".venv" / "lib"
    if not venv_lib.is_dir():
        return None
    matches = sorted(venv_lib.glob("python*/site-packages"))
    return matches[0] if matches else None


def read_project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    return str(data["project"]["version"])


def detect_architecture() -> str:
    try:
        arch = subprocess.check_output(
            ["dpkg", "--print-architecture"], text=True, cwd=ROOT
        ).strip()
        if arch:
            return arch
    except Exception:
        pass
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine or "amd64"


def build_frontend() -> None:
    run(["npm", "run", "build", "--prefix", "frontend"])


def build_pyinstaller_bundle() -> Path:
    dist_dir = ROOT / "dist" / APP_NAME
    build_dir = ROOT / "build"

    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir)

    ui_dist = ROOT / "trend_analyzer" / "ui_dist"
    if not ui_dist.exists():
        raise SystemExit(
            "Frontend bundle is missing. Run the frontend build before packaging."
        )

    site_packages = venv_site_packages()
    paths = [str(ROOT)]
    if site_packages:
        paths.insert(0, str(site_packages))

    add_data = f"{ui_dist}:{'trend_analyzer/ui_dist'}"
    pythonpath_parts: list[str] = []
    if site_packages:
        pythonpath_parts.append(str(site_packages))
    existing_pythonpath = os.environ.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    run(
        [
            "pyinstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            APP_NAME,
            *sum([["--paths", p] for p in paths], []),
            "--add-data",
            add_data,
            "--collect-submodules",
            "uvicorn",
            "--collect-submodules",
            "fastapi",
            "--collect-submodules",
            "starlette",
            "--collect-submodules",
            "apscheduler",
            "--collect-all",
            "rich",
            "--exclude-module",
            "PyQt5",
            "--exclude-module",
            "PyQt6",
            "--exclude-module",
            "PySide2",
            "--exclude-module",
            "PySide6",
            str(ROOT / "trend_analyzer" / "__main__.py"),
        ],
        env={
            **os.environ,
            "MPLBACKEND": "Agg",
            "PYTHONPATH": os.pathsep.join(pythonpath_parts),
        },
    )

    bundle = ROOT / "dist" / APP_NAME
    if not bundle.exists():
        raise SystemExit("PyInstaller did not produce the expected bundle.")
    return bundle


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def stage_common_layout(
    stage_root: Path,
    bundle: Path,
    *,
    launcher_exec: str,
) -> None:
    opt_dir = stage_root / "opt" / APP_NAME
    if opt_dir.exists():
        shutil.rmtree(opt_dir)
    opt_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, opt_dir, symlinks=True)

    bin_dir = stage_root / "usr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / APP_NAME
    write_text(
        launcher,
        "#!/bin/sh\n"
        f"exec {launcher_exec} \"$@\"\n",
    )
    make_executable(launcher)


def stage_appimage_layout(stage_root: Path) -> None:
    write_text(
        stage_root / "AppRun",
        "#!/bin/sh\n"
        "HERE=\"$(dirname \"$(readlink -f \"$0\")\")\"\n"
        f"exec \"$HERE/usr/bin/{APP_NAME}\" \"$@\"\n",
    )
    make_executable(stage_root / "AppRun")

    write_text(
        stage_root / f"{APP_NAME}.desktop",
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                f"Name={APP_TITLE}",
                "Comment=Local trend analyzer and research scheduler",
                "Exec=AppRun %U",
                f"Icon={APP_NAME}",
                "Terminal=false",
                "Categories=Office;Business;Utility;",
            ]
        )
        + "\n",
    )

    icon_source = ROOT / "frontend" / "src" / "overview.png"
    if icon_source.exists():
        shutil.copy2(icon_source, stage_root / f"{APP_NAME}.png")


def stage_deb_layout(stage_root: Path, version: str, bundle: Path, arch: str) -> Path:
    stage_common_layout(
        stage_root,
        bundle,
        launcher_exec=f"/opt/{APP_NAME}/{APP_NAME}",
    )
    control_dir = stage_root / "DEBIAN"
    control_dir.mkdir(parents=True, exist_ok=True)
    write_text(
        control_dir / "control",
        "\n".join(
            [
                f"Package: {APP_NAME}",
                f"Version: {version}",
                "Section: utils",
                "Priority: optional",
                f"Architecture: {arch}",
                "Maintainer: Trend Analyzer",
                f"Description: {APP_TITLE}",
                " Local trend analyzer with a bundled web UI.",
            ]
        )
        + "\n",
    )

    desktop_dir = stage_root / "usr" / "share" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    write_text(
        desktop_dir / f"{APP_NAME}.desktop",
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                f"Name={APP_TITLE}",
                "Comment=Local trend analyzer and research scheduler",
                f"Exec={APP_NAME} %U",
                f"Icon={APP_NAME}",
                "Terminal=false",
                "Categories=Office;Business;Utility;",
            ]
        )
        + "\n",
    )

    icon_dir = stage_root / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_source = ROOT / "frontend" / "src" / "overview.png"
    if icon_source.exists():
        shutil.copy2(icon_source, icon_dir / f"{APP_NAME}.png")

    return stage_root / "DEBIAN"


def build_deb(bundle: Path, version: str, out_dir: Path, arch: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trend-analyzer-deb-") as tmp:
        stage_root = Path(tmp) / f"{APP_NAME}_{version}_{arch}"
        stage_root.mkdir(parents=True, exist_ok=True)
        stage_deb_layout(stage_root, version, bundle, arch)
        deb_path = out_dir / f"{APP_NAME}_{version}_{arch}.deb"
        run(["dpkg-deb", "--root-owner-group", "--build", str(stage_root), str(deb_path)])
        return deb_path


def build_appimage(bundle: Path, version: str, out_dir: Path) -> Path:
    appimagetool = shutil.which("appimagetool")
    if not appimagetool:
        raise SystemExit(
            "appimagetool is not installed, so an AppImage cannot be built here. "
            "Install appimagetool and rerun with --format appimage."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trend-analyzer-appimage-") as tmp:
        stage_root = Path(tmp) / f"{APP_NAME}.AppDir"
        stage_root.mkdir(parents=True, exist_ok=True)
        stage_common_layout(
            stage_root,
            bundle,
            launcher_exec=f'$(dirname "$(readlink -f "$0")")/../opt/{APP_NAME}/{APP_NAME}',
        )
        stage_appimage_layout(stage_root)
        appimage_path = out_dir / f"{APP_NAME}-{version}-x86_64.AppImage"
        run([appimagetool, str(stage_root), str(appimage_path)])
        return appimage_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Linux release artifacts for Trend Analyzer."
    )
    parser.add_argument(
        "--format",
        choices=("deb", "appimage", "both"),
        default="deb",
        help="Artifact format to build.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "dist" / "linux"),
        help="Output directory for built artifacts.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    version = read_project_version()
    arch = detect_architecture()

    build_frontend()
    bundle = build_pyinstaller_bundle()

    produced: list[Path] = []
    if args.format in ("deb", "both"):
        produced.append(build_deb(bundle, version, out_dir, arch))
    if args.format in ("appimage", "both"):
        produced.append(build_appimage(bundle, version, out_dir))

    for path in produced:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
