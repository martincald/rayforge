from gi.repository import Gtk

from ..layout import stylesheet
from ..shared.gtk import apply_css

css = stylesheet("""
.key {
    padding: $space_tight $space_control;
    border-radius: $radius_chip;
    background-color: @theme_base_color;
    color: @theme_fg_color;
    border: $hairline solid @borders;
    font-size: $keycap_font;
    font-weight: 500;
}
""")


class Key(Gtk.Label):
    def __init__(self, label: str, **kwargs):
        super().__init__(label=label, **kwargs)
        apply_css(css)
        self.add_css_class("key")
        self.set_valign(Gtk.Align.CENTER)
