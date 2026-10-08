from gettext import gettext as _
from typing import TYPE_CHECKING, Optional

from gi.repository import Adw, Gdk, Gtk

from ...context import get_context
from ...core.layer import Layer
from ..icons import get_icon
from ..machine.wcs_dialog import WcsDialog
from ..shared.patched_dialog_window import PatchedDialogWindow

if TYPE_CHECKING:
    from ...doceditor.editor import DocEditor


class LayerSettingsDialog(PatchedDialogWindow):
    """Dialog for configuring layer-level settings."""

    def __init__(
        self,
        layer: Layer,
        transient_for: Gtk.Window,
        editor: Optional["DocEditor"] = None,
        **kwargs,
    ):
        super().__init__(transient_for=transient_for, **kwargs)
        self.layer = layer
        self.editor = editor
        self._is_initializing = True

        self.set_title(_("{name} - Settings").format(name=layer.name))
        self.set_default_size(600, -1)
        self.set_modal(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        main_box.append(header)

        close_button = Gtk.Button(label=_("Close"))
        close_button.add_css_class("suggested-action")
        close_button.connect("clicked", lambda w: self.close())
        header.pack_end(close_button)

        content = Adw.PreferencesPage()
        main_box.append(content)

        general_group = Adw.PreferencesGroup(
            title=_("General"),
            description=_(
                "Basic layer settings such as appearance and "
                "coordinate system."
            ),
        )
        content.add(general_group)

        self.name_row = Adw.EntryRow(title=_("Name"))
        self.name_row.set_text(layer.name)
        self.name_row.connect("changed", self._on_name_changed)
        general_group.add(self.name_row)

        color_dialog = Gtk.ColorDialog()
        color_dialog.set_with_alpha(False)
        self.color_button = Gtk.ColorDialogButton(dialog=color_dialog)
        rgba = Gdk.RGBA()
        rgba.parse(layer.color)
        self.color_button.set_rgba(rgba)
        self.color_button.connect("notify::rgba", self._on_color_changed)

        color_row = Adw.ActionRow(
            title=_("Layer Color"),
            subtitle=_("Color used for operations in this layer"),
        )
        color_row.add_suffix(self.color_button)
        general_group.add(color_row)

        self._populate_wcs_store()
        self.wcs_row = Adw.ComboRow(
            title=_("Coordinate System"),
            subtitle=_(
                "Defaults to the WCS chosen in the main window"
            ),
            model=self._wcs_store,
        )
        self.edit_offsets_btn = Gtk.Button(child=get_icon("edit-symbolic"))
        self.edit_offsets_btn.set_tooltip_text(_("Edit Offsets Manually"))
        self.edit_offsets_btn.add_css_class("flat")
        self.edit_offsets_btn.set_valign(Gtk.Align.CENTER)
        self.edit_offsets_btn.connect("clicked", self._on_edit_offsets_clicked)
        self.wcs_row.add_suffix(self.edit_offsets_btn)

        self._select_current_wcs()
        self._update_edit_button_sensitivity()
        self.wcs_row.connect("notify::selected", self._on_wcs_changed)
        general_group.add(self.wcs_row)

        self._is_initializing = False

    def _populate_wcs_store(self):
        self._wcs_store = Gtk.StringList()
        self._wcs_values: list[str | None] = [None]
        self._wcs_store.append(_("Default"))
        machine = get_context().machine
        if machine:
            for wcs in machine.supported_wcs:
                self._wcs_store.append(wcs)
                self._wcs_values.append(wcs)

    def _select_current_wcs(self):
        wcs = self.layer.wcs
        if wcs and wcs in self._wcs_values:
            self.wcs_row.set_selected(self._wcs_values.index(wcs))
        else:
            self.wcs_row.set_selected(0)

    def _get_selected_wcs(self) -> str | None:
        idx = self.wcs_row.get_selected()
        if idx < len(self._wcs_values):
            return self._wcs_values[idx]
        return None

    def _on_wcs_changed(self, row, _param):
        if self._is_initializing:
            return
        wcs = self._get_selected_wcs()
        self.layer.set_wcs(wcs)
        self._update_edit_button_sensitivity()

    def _update_edit_button_sensitivity(self):
        wcs = self._get_selected_wcs()
        self.edit_offsets_btn.set_sensitive(wcs is not None)

    def _on_edit_offsets_clicked(self, button):
        machine = get_context().machine
        if not machine:
            return

        root = self.get_root()
        self._edit_dialog = WcsDialog(
            machine=machine,
            transient_for=root if isinstance(root, Gtk.Window) else None,
        )
        self._edit_dialog.connect("destroy", self._on_edit_dialog_destroy)
        self._edit_dialog.present()

    def _on_edit_dialog_destroy(self, *_):
        self._edit_dialog = None

    def _on_color_changed(self, button, _param):
        if self._is_initializing:
            return
        rgba = button.get_rgba()
        r = round(rgba.red * 255)
        g = round(rgba.green * 255)
        b = round(rgba.blue * 255)
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        self.layer.set_color(hex_color)

    def _on_name_changed(self, row):
        if self._is_initializing:
            return
        new_name = row.get_text().strip()
        if not new_name:
            return
        if self.editor:
            self.editor.layer.rename_layer(self.layer, new_name)
