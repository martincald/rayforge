# -----------------------------------------------------------------------------
# Hook for swiftcut package - ensures all submodules are collected
# This is needed because builtin addons import from swiftcut but are
# loaded dynamically, so PyInstaller's static analysis misses these imports.
# -----------------------------------------------------------------------------

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all submodules from swiftcut and its subpackages
hiddenimports = collect_submodules("swiftcut")

# Collect data files from swiftcut (locale, resources, etc.)
datas = collect_data_files("swiftcut", include_py_files=False)
