from .version import (
    get_version_from_checkout,
    get_version_from_file,
    get_version_from_pkg,
)

# A checkout's VERSION wins over the version.txt an earlier build left.
__version__ = (
    get_version_from_checkout()
    or get_version_from_file()
    or get_version_from_pkg()
)
