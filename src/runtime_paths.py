import os
import shutil
import tempfile
from pathlib import Path


def is_ascii_path(path: Path | str) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def get_runtime_dir() -> Path:
    """
    Return a writable runtime directory that is likely safe for native tools.
    Piper and ffmpeg can be sensitive to non-ASCII paths on some Windows setups.
    """
    env_dir = os.getenv("UNIPUS_RUNTIME_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir))

    if os.name == "nt":
        system_root = os.getenv("SystemRoot", r"C:\Windows")
        candidates.append(Path(system_root) / "Temp" / "UnipusAIAutomator")

    candidates.append(Path(tempfile.gettempdir()) / "UnipusAIAutomator")
    candidates.append(Path.cwd() / ".runtime")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            if os.access(candidate, os.W_OK):
                return candidate
        except OSError:
            continue

    fallback = Path.cwd() / ".runtime"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_safe_temp_dir() -> Path:
    temp_dir = get_runtime_dir() / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def copy_to_safe_path(source: Path, safe_subdir: str) -> Path:
    """
    Copy a file into the runtime directory when its original path contains
    non-ASCII characters. Existing stale copies are overwritten.
    """
    if is_ascii_path(source):
        return source

    target_dir = get_runtime_dir() / safe_subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return target
