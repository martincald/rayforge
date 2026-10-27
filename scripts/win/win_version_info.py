"""Write the Windows version resource for SwiftCut.exe.

PyInstaller reads this text file through --version-file and embeds it
as the exe's version resource, which Explorer shows under Properties >
Details. Usage: win_version_info.py <version> <output path>
"""

import re
import sys
from pathlib import Path

COMPANY = "Martín Calderón"
COPYRIGHT = "© 2026 Martín Calderón"
PRODUCT = "SwiftCut"
ORIGINAL_FILENAME = "SwiftCut.exe"


def numeric_version(version: str) -> tuple[int, int, int, int]:
    """The four numbers of a version string; a part that does not start
    with a number, or is missing, counts as 0."""
    numbers = []
    for part in version.split(".")[:4]:
        match = re.match(r"\d+", part)
        numbers.append(int(match.group()) if match else 0)
    numbers += [0] * (4 - len(numbers))
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def version_info_text(version: str) -> str:
    """The VSVersionInfo text PyInstaller loads, for a version string."""
    numbers = numeric_version(version)
    strings = [
        ("CompanyName", COMPANY),
        ("FileDescription", PRODUCT),
        ("FileVersion", version),
        ("LegalCopyright", COPYRIGHT),
        ("OriginalFilename", ORIGINAL_FILENAME),
        ("ProductName", PRODUCT),
        ("ProductVersion", version),
    ]
    rows = ",\n".join(
        f"            StringStruct({key!r}, {value!r})"
        for key, value in strings
    )
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers!r},
    prodvers={numbers!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
{rows}
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(
        version_info_text(sys.argv[1]), encoding="utf-8"
    )
    print("Version resource generation complete.")
