from __future__ import annotations

import logging
from collections.abc import Callable
from gettext import gettext as _
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib

from ...core.layer import Layer
from ...core.source_asset import SourceAsset
from ...core.vectorization_spec import TraceSpec, VectorizationSpec
from ...doceditor.file_cmd import ImportAction
from ...image.registry import importer_registry
from . import file_dialogs
from .import_dialog import ImportDialog

if TYPE_CHECKING:
    from ...doceditor.editor import DocEditor
    from ..mainwindow import MainWindow

logger = logging.getLogger(__name__)


def _start_interactive_import(
    win: MainWindow,
    editor: DocEditor,
    file_path: Path,
    mime_type: str,
    position_mm: tuple[float, float] | None = None,
):
    """Creates and presents the main interactive import dialog."""
    logger.info("Starting interactive import...")

    _, features = editor.file.get_importer_info(file_path, mime_type)
    import_dialog = ImportDialog(
        parent=win,
        editor=editor,
        file_path=file_path,
        mime_type=mime_type,
        features=features,
    )

    # Define the handler locally to capture context from its closure.
    def on_dialog_response(
        sender,
        *,
        response_id: str,
        spec: VectorizationSpec,
        split_paths: bool = False,
    ):
        _on_import_dialog_response(
            sender,
            response_id,
            spec,
            win,
            editor,
            file_path,
            mime_type,
            position_mm,
            split_paths,
        )

    # Use weak=False to prevent the handler from being garbage collected.
    import_dialog.response.connect(on_dialog_response, weak=False)
    import_dialog.present()


def _on_import_dialog_response(
    dialog,
    response_id: str,
    spec: VectorizationSpec,
    win: MainWindow,
    editor: DocEditor,
    file_path: Path,
    mime_type: str,
    position_mm: tuple[float, float] | None = None,
    split_paths: bool = False,
):
    """Callback for when the interactive import dialog is closed."""
    logger.info(f"Received response '{response_id}' from ImportDialog.")
    if response_id == "import":
        logger.info(
            f"Executing final import for {file_path} with spec: {spec}"
        )
        editor.file.load_file_from_path(
            file_path, mime_type, spec, position_mm, split_paths=split_paths
        )
        win.item_revealer.set_reveal_child(False)


def fix_macos_file_uri(gfile: Gio.File) -> Gio.File:
    """
    GTK 4 on macOS percent-encodes the whole dropped URI, including the
    scheme colon ("file%3A///..."), which GLib cannot resolve to a path.
    Restore the colon; any other file is returned unchanged.
    """
    uri = gfile.get_uri()
    if uri.lower().startswith("file%3a"):
        return Gio.File.new_for_uri("file:" + uri[len("file%3a") :])
    return gfile


def _get_file_infos(
    editor: DocEditor, files: list[Gio.File]
) -> list[tuple[Path, str]]:
    """Get path and MIME type of the files an importer supports."""
    file_infos = []
    for gfile in files:
        gfile = fix_macos_file_uri(gfile)
        path_str = gfile.get_path()
        if not path_str:
            logger.warning(
                f"File has no path, skipping (uri={gfile.get_uri()!r})"
            )
            continue

        file_path = Path(path_str)
        try:
            file_info = gfile.query_info(
                Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE,
                Gio.FileQueryInfoFlags.NONE,
                None,
            )
        except GLib.Error as e:
            logger.warning(f"Could not query file info for {file_path}: {e}")
            continue
        # The raw content type: the registered extension picks the
        # importer; a type macOS converts to application/octet-stream
        # would hand files of unknown suffix to the Ruida importer.
        mime_type = file_info.get_content_type()

        # Check if we support this file by asking the backend.
        importer_cls, __ = editor.file.get_importer_info(
            file_path, mime_type
        )
        if not importer_cls:
            logger.warning(
                f"Unsupported file type: {mime_type} for {file_path}"
            )
            continue

        file_infos.append((file_path, mime_type))

    return file_infos


def import_files(
    win: MainWindow,
    editor: DocEditor,
    files: list[Gio.File],
    position_mm: tuple[float, float] | None = None,
) -> bool:
    """
    The one import entry of the file dialog and the canvas drop.

    Skips files no importer supports, opens the import dialog for files
    that need configuration and loads the others directly (several of
    them as one batch).

    Args:
        win: MainWindow instance
        editor: DocEditor instance
        files: The chosen or dropped files
        position_mm: Optional (x, y) tuple in world coordinates (mm)
            to center the imported items

    Returns:
        True if any file is imported.
    """
    file_infos = _get_file_infos(editor, files)
    files_for_batch_import: list[tuple[Path, str]] = []

    for file_path, mime_type in file_infos:
        action = editor.file.analyze_import_target(file_path, mime_type)

        if action == ImportAction.INTERACTIVE_CONFIG:
            # These files need their own dialog, so handle them one by one.
            logger.info(
                f"Routing for individual import: {file_path.name} at "
                f"{position_mm}"
            )
            import_file_at_position(
                win, editor, file_path, mime_type, position_mm
            )
        else:
            # These files can be batched together for a single
            # import command.
            files_for_batch_import.append((file_path, mime_type))

    # Handle any files that were collected for batch import.
    if len(files_for_batch_import) == 1:
        file_path, mime_type = files_for_batch_import[0]
        logger.info(f"Importing direct-load file: {file_path.name}")
        import_file_at_position(win, editor, file_path, mime_type, position_mm)
    elif files_for_batch_import:
        logger.info(
            f"Batch importing {len(files_for_batch_import)} "
            "direct-load files."
        )
        import_multiple_files_at_position(
            win, editor, files_for_batch_import, position_mm
        )

    return bool(file_infos)


def ask_scale_to_fit(
    win: MainWindow,
    file_path: Path,
    size_mm: tuple[float, float],
    bed_mm: tuple[float, float],
    answer: Callable[[bool], None],
):
    """
    The UI's oversize policy: asks whether an import larger than the
    bed is scaled to fit or cancelled. Returns at once; the answer
    follows the dialog's response.
    """
    dialog = Adw.MessageDialog(
        transient_for=win,
        modal=True,
        heading=_("Larger Than the Bed"),
        body=_(
            "{name} is {width:.0f} x {height:.0f} mm, larger than the "
            "{bed_width:.0f} x {bed_height:.0f} mm bed."
        ).format(
            name=file_path.name,
            width=size_mm[0],
            height=size_mm[1],
            bed_width=bed_mm[0],
            bed_height=bed_mm[1],
        ),
    )
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("scale", _("Scale to fit"))
    dialog.set_default_response("scale")
    dialog.set_close_response("cancel")
    dialog.connect(
        "response", lambda _dialog, response: answer(response == "scale")
    )
    dialog.present()


def _on_file_selected(dialog, result, user_data):
    """Callback for when the user selects a file from the dialog."""
    win, editor = user_data
    try:
        file = dialog.open_finish(result)
        if not file:
            return
    except GLib.Error:
        return

    import_files(win, editor, [file])


def start_interactive_import(win: MainWindow, editor: DocEditor):
    """
    Initiates the full interactive file import process, starting with a
    file chooser dialog.
    """
    # Now passing editor to get supported file types
    file_dialogs.show_import_dialog(
        win, editor, _on_file_selected, (win, editor)
    )


def import_file_at_position(
    win: MainWindow,
    editor: DocEditor,
    file_path: Path,
    mime_type: str,
    position_mm: tuple[float, float] | None = None,
):
    """
    Import a file and optionally position it at specified coordinates.

    Args:
        win: MainWindow instance
        editor: DocEditor instance
        file_path: Path to file to import
        mime_type: MIME type of the file
        position_mm: Optional (x, y) tuple in world coordinates (mm)
            to center the imported item
    """
    # Ask backend for routing decision
    action = editor.file.analyze_import_target(file_path, mime_type)

    if action == ImportAction.INTERACTIVE_CONFIG:
        _start_interactive_import(
            win, editor, file_path, mime_type, position_mm
        )
    elif action == ImportAction.DIRECT_LOAD:
        editor.file.load_file_from_path(
            file_path, mime_type, None, position_mm
        )
        win.item_revealer.set_reveal_child(False)
    else:
        logger.warning(f"Unsupported file type: {mime_type} for {file_path}")


def _on_batch_trace_response(
    dialog,
    response_id: str,
    editor: DocEditor,
    file_list: list[tuple[Path, str]],
    position_mm: tuple[float, float],
    win: MainWindow,
):
    """
    Handles the user's choice from the batch tracing configuration dialog.
    """
    if response_id == "import":
        # User confirmed - execute batch import via backend
        # We extract just the paths for the backend method
        paths = [f[0] for f in file_list]
        vectorization_spec = TraceSpec()

        editor.file.execute_batch_import(
            paths, vectorization_spec, position_mm
        )
        logger.info(f"Batch import started for {len(file_list)} files")
    # else: user cancelled, do nothing


def import_multiple_files_at_position(
    win: MainWindow,
    editor: DocEditor,
    file_list: list[tuple[Path, str]],
    position_mm: tuple[float, float],
):
    """
    Import multiple files with a single batch configuration dialog.

    Args:
        win: MainWindow instance
        editor: DocEditor instance
        file_list: List of (file_path, mime_type) tuples
        position_mm: (x, y) tuple in world coordinates (mm)
            to center the imported items
    """
    if not file_list:
        return

    # Check if any file in the list actually requires interactive config
    needs_config = False
    for path, mime in file_list:
        if (
            editor.file.analyze_import_target(path, mime)
            == ImportAction.INTERACTIVE_CONFIG
        ):
            needs_config = True
            break

    if not needs_config:
        # If no files need config, just load them all directly
        paths = [f[0] for f in file_list]
        vectorization_spec = TraceSpec()
        editor.file.execute_batch_import(
            paths, vectorization_spec, position_mm
        )
        return

    # If configuration is needed, show the batch dialog
    file_count = len(file_list)
    file_names = ", ".join(f.name for f, _ in file_list[:3])
    if file_count > 3:
        file_names += f" and {file_count - 3} more"

    # Show batch tracing configuration dialog
    dialog = Adw.MessageDialog(
        transient_for=win,
        modal=True,
        heading=_("Batch Import {file_count} Images").format(
            file_count=file_count
        ),
        body=_(
            "Import {file_count} images:\n{file_names}\n\n"
            "All images will be traced using the default tracing settings "
            "and positioned at the drop location."
        ).format(file_count=file_count, file_names=file_names),
    )
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("import", _("Import All"))
    dialog.set_default_response("import")
    dialog.set_close_response("cancel")

    dialog.connect(
        "response",
        _on_batch_trace_response,
        editor,
        file_list,
        position_mm,
        win,
    )
    dialog.present()

    # Hide properties widget
    win.item_revealer.set_reveal_child(False)


def start_reimport(
    win: MainWindow,
    editor: DocEditor,
    source_asset: SourceAsset,
    position_mm: tuple[float, float] | None = None,
    target_layer: Layer | None = None,
):
    """
    Re-open the import dialog for an existing SourceAsset so the user
    can edit settings and produce a fresh set of workpieces.
    """
    meta = source_asset.metadata
    importer_cls_name = meta.get("_importer_class")
    if not importer_cls_name:
        logger.warning("Cannot reimport: missing _importer_class metadata")
        return
    importer_cls = importer_registry.get_by_name(importer_cls_name)
    if not importer_cls:
        logger.warning(
            f"Cannot reimport: importer '{importer_cls_name}' not registered"
        )
        return

    mime_type = meta.get("_importer_mime", "")
    file_path = source_asset.source_file or Path(
        source_asset.name or "Untitled"
    )
    features = importer_cls.features

    initial_spec = None
    for wp in editor.doc.all_workpieces:
        if (
            wp.source_segment
            and wp.source_segment.source_asset_uid == source_asset.uid
        ):
            initial_spec = wp.source_segment.vectorization_spec
            break

    dialog = ImportDialog(
        parent=win,
        editor=editor,
        file_path=file_path,
        mime_type=mime_type,
        features=features,
        source_asset=source_asset,
        initial_spec=initial_spec,
    )

    # A re-import offers no "Import as": it repeats the original import.
    def on_response(
        sender, *, response_id: str, spec: VectorizationSpec, **kwargs
    ):
        if response_id == "import":
            editor.file.reimport_from_source_asset(
                source_asset, spec, position_mm, target_layer
            )

    dialog.response.connect(on_response, weak=False)
    dialog.present()
