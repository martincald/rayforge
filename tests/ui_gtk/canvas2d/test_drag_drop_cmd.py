from gi.repository import Gio

from swiftcut.ui_gtk.doceditor.import_handler import fix_macos_file_uri


def test_escaped_scheme_resolves_to_local_path():
    # What GTK 4 on macOS hands over for a Finder drop.
    gfile = Gio.File.new_for_uri("file%3A///Users/me/Downloads/a%20b.dxf")
    assert gfile.get_path() is None

    fixed = fix_macos_file_uri(gfile)
    assert fixed.get_path() == "/Users/me/Downloads/a b.dxf"


def test_regular_file_uri_is_unchanged():
    gfile = Gio.File.new_for_uri("file:///Users/me/a.dxf")
    assert fix_macos_file_uri(gfile) is gfile
