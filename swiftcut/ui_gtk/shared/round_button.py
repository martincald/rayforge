from gi.repository import Gtk

from ..layout import stylesheet

css = stylesheet("""
button.round-button {
    min-width: $fab_size;
    min-height: $fab_size;
    border-radius: $fab_radius;
    padding: 0;
    margin: $space_group;
    background-color: @theme_selected_bg_color; /* Material primary color */
    color: @theme_selected_fg_color;
    font-size: $display_font;
    border: none;
    box-shadow: $shadow_fab; /* Shadow for depth */
    transition: background-color 0.2s, box-shadow 0.2s;
}

button.round-button:hover {
    background-color: shade(@theme_selected_bg_color, 0.9);
    box-shadow: $shadow_fab_hover; /* Enhanced shadow on hover */
}

button.round-button:active {
    background-color: shade(@theme_selected_bg_color, 1.1); /* Lighter shade */
    box-shadow: $shadow_fab_active; /* Reduced shadow on click */
}
""")


class RoundButton(Gtk.Button):
    def __init__(self, label, **kwargs):
        super().__init__(**kwargs)
        self.apply_css()
        self.set_label(label)
        self.set_halign(Gtk.Align.CENTER)

    def apply_css(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(css)
        style_context = self.get_style_context()
        style_context.add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        style_context.add_class("round-button")
