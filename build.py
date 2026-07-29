import contextlib
import io
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

if os.name == "posix":
    import fcntl

# Set UTF-8 encoding for all I/O operations
os.environ["PYTHONUTF8"] = "1"

# Force stdout to use UTF-8 encoding on Windows
if platform.system().lower() == "windows":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def get_architecture():
    """Get the current system architecture."""
    machine = platform.machine().lower()
    if machine in ["arm64", "aarch64"]:
        return "arm64"
    if machine in ["x86_64", "amd64"]:
        return "x86_64"
    return machine


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _legacy_pyinstaller_cache_dir() -> Path | None:
    system = platform.system().lower()
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "pyinstaller"
    if system == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "pyinstaller"
    return None


def _configure_pyinstaller_cache() -> Path:
    cache_dir = _project_root() / ".pyinstaller-cache"
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(cache_dir)
    return cache_dir


def _clean_pyinstaller_cache() -> None:
    cache_dir = _configure_pyinstaller_cache()
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
    legacy_cache = _legacy_pyinstaller_cache_dir()
    if legacy_cache and legacy_cache.exists():
        shutil.rmtree(legacy_cache, ignore_errors=True)


def _clean_local_build_artifacts() -> None:
    root = _project_root()
    for name in ("build", "dist"):
        path = root / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    for spec in root.glob("*.spec"):
        spec.unlink(missing_ok=True)


@contextlib.contextmanager
def _build_lock():
    lock_path = _project_root() / ".build.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        if os.name == "posix":
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_project_version() -> str:
    """Read version from pyproject.toml (source of truth for releases)."""
    text = (_project_root() / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise RuntimeError("Could not read version from pyproject.toml")
    return match.group(1).strip()


def _sync_version_artifacts(version: str) -> None:
    """Embed version into files that ship inside the frozen app."""
    root = _project_root()
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    version_data = root / "src" / "version_data.py"
    version_data.write_text(
        '"""Generated app version — keep in sync with pyproject.toml via build.py."""\n'
        "\n"
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    # Keep fallback constant aligned for source runs / partial bundles.
    version_py = root / "src" / "version.py"
    text = version_py.read_text(encoding="utf-8")
    updated = re.sub(
        r'FALLBACK_VERSION\s*=\s*["\'][^"\']*["\']',
        f'FALLBACK_VERSION = "{version}"',
        text,
        count=1,
    )
    if updated != text:
        version_py.write_text(updated, encoding="utf-8")
    print(f"Synced embedded version artifacts to {version}")


def build_app():
    system = platform.system().lower()
    arch = get_architecture()
    app_name = "hf-model-downloader"
    version = _read_project_version()
    _sync_version_artifacts(version)

    # Ensure assets directory exists
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)

    # Note: Icon generation is now a separate step in the Makefile
    # Please run `make icons` to generate icons before running this script
    # Or directly use the `make build` command

    # Base PyInstaller command
    # Bundle VERSION + pyproject.toml so frozen apps report the correct version.
    sep = ";" if system == "windows" else ":"
    cmd = [
        "pyinstaller",
        "--noconfirm",
        f"--name={app_name}",
        "--add-data",
        f"README.md{sep}.",
        "--add-data",
        f"VERSION{sep}.",
        "--add-data",
        f"pyproject.toml{sep}.",
        "--add-data",
        f"assets{sep}assets",
        "--add-data",
        f"scripts{sep}scripts",
        "--hidden-import",
        "huggingface_hub",
        "--hidden-import",
        "hf_xet",
        "--collect-all",
        "hf_xet",
        "--hidden-import",
        "tqdm",
        "--hidden-import",
        "requests",
        "--hidden-import",
        "src.version_data",
        "--onedir",  # Create a directory bundle
        "--windowed",  # No console window
    ]

    # Platform specific options
    if system == "darwin":  # macOS
        icon_path = os.path.join(assets_dir, "icon.icns")
        cmd.extend(
            [
                "--icon",
                icon_path,
                "--osx-bundle-identifier",
                "com.guozhijian611.hf-model-downloader",
                "--target-arch",
                arch,  # Specify target architecture for macOS
            ]
        )
        output_name = f"{app_name}-macos-{arch}.app"  # Explicitly include macos in name

    elif system == "windows":  # Windows
        icon_path = os.path.join(assets_dir, "icon.ico")
        # Use architecture-specific name for PyInstaller
        win_app_name = f"{app_name}-windows-{arch}"
        cmd[cmd.index(f"--name={app_name}")] = f"--name={win_app_name}"
        cmd.extend(
            [
                "--icon",
                icon_path,
            ]
        )
        output_name = win_app_name  # Directory name for onedir mode

    # Check if icon exists
    if not os.path.exists(icon_path):
        print(f"Warning: Icon file not found: {icon_path}")
        print("- macOS: assets/icon.icns")
        print("- Windows: assets/icon.ico")
        print(
            "You can continue building, but the application will not have a custom icon"
        )

    # Add main script
    cmd.append("main.py")

    try:
        print(f"Building {output_name} for {system} ({arch})...")
        print(f"Command: {' '.join(cmd)}")

        with _build_lock():
            for attempt in range(2):
                _clean_local_build_artifacts()
                _clean_pyinstaller_cache()
                try:
                    subprocess.run(cmd, check=True, env=os.environ.copy())
                    break
                except subprocess.CalledProcessError:
                    if attempt == 0:
                        print("Build failed, retrying after cleaning artifacts...")
                        continue
                    raise

        # Print build information
        output_path = os.path.join("dist", output_name)
        if os.path.exists(output_path):
            if os.path.isdir(output_path):
                # Calculate directory size for onedir mode
                total_size = 0
                for dirpath, _dirnames, filenames in os.walk(output_path):
                    for filename in filenames:
                        filepath = os.path.join(dirpath, filename)
                        total_size += os.path.getsize(filepath)
                size_mb = total_size / (1024 * 1024)
                print("\nBuild Summary:")
                print(f"- Output: dist/{output_name}/ (directory)")
                print(f"- Total Size: {size_mb:.2f} MB")
            else:
                # Single file mode
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                print("\nBuild Summary:")
                print(f"- Output: dist/{output_name}")
                print(f"- Size: {size_mb:.2f} MB")

            print(f"- System: {system}")
            print(f"- Architecture: {arch}")
            print(f"- Python Version: {platform.python_version()}")

            if system == "windows":
                exe_name = (
                    f"{output_name}.exe" if system == "windows" else f"{app_name}.exe"
                )
                exe_path = os.path.join(output_path, exe_name)
                if os.path.exists(exe_path):
                    print(f"- Executable: {exe_name}")

            print("\nTip: To fix icon issues, run `make fix-icons`")

        # Create zip package for Windows
        if system == "windows":
            print("\nCreating Windows package...")
            success = create_windows_package(output_name, arch)
            if success:
                # Remove original directory after creating package
                import shutil

                dist_dir = os.path.join("dist", output_name)
                if os.path.exists(dist_dir):
                    shutil.rmtree(dist_dir)
                    print(f"✓ Removed original directory: {dist_dir}")
                    print("✓ Windows package created successfully")

    except subprocess.CalledProcessError as e:
        print(f"Error: Build failed: {e}")
        sys.exit(1)


def create_windows_package(app_dir_name, arch):
    """Create Windows zip package"""
    try:
        print(f"Checking for app directory: dist/{app_dir_name}")
        app_dir_path = os.path.join("dist", app_dir_name)

        if not os.path.exists(app_dir_path):
            print(f"✗ App directory not found: {app_dir_path}")
            return False

        print(f"✓ App directory found: {app_dir_path}")
        print(f"Contents: {os.listdir(app_dir_path)}")

        # Create zip package
        import zipfile

        zip_name = f"hf-model-downloader-windows-{arch}.zip"

        print(f"Creating zip package: {zip_name}")
        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _dirs, files in os.walk(app_dir_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Create archive path relative to the app directory
                    archive_path = os.path.relpath(file_path, "dist")
                    zipf.write(file_path, archive_path)

        if os.path.exists(zip_name):
            zip_size = os.path.getsize(zip_name) / (1024 * 1024)
            print(f"✓ Windows package created: {zip_name} ({zip_size:.2f} MB)")
            return True
        print(f"✗ Package file not found: {zip_name}")
        return False

    except Exception as e:
        print(f"⚠ Failed to create package: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    build_app()
