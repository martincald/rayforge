import os

__dir__ = os.path.dirname(__file__)


def get_version_from_checkout() -> str | None:
    """VERSION at the root of a source checkout, the one source of the
    version (scripts/version.py). pyproject.toml beside it tells a
    checkout from a stray VERSION file in site-packages."""
    root = os.path.dirname(__dir__)
    if not os.path.isfile(os.path.join(root, "pyproject.toml")):
        return None
    try:
        with open(os.path.join(root, "VERSION"), "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def get_version_from_pkg() -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return None

    try:
        return version("swiftcut")
    except PackageNotFoundError:
        return None


def get_version_from_file() -> str | None:
    version_file = os.path.join(__dir__, "version.txt")
    try:
        with open(version_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
