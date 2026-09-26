from ..layout import stylesheet
from .gtk import apply_css

dock_css = stylesheet("""
box.dock-edge-zone {
    min-width: $dock_edge;
    min-height: $dock_edge;
    background: transparent;
    transition: background 150ms ease;
}

box.dock-edge-zone.highlight-left {
    background: alpha(@theme_selected_bg_color, 0.3);
    border-left: $stroke solid @theme_selected_bg_color;
}

box.dock-edge-zone.highlight-right {
    background: alpha(@theme_selected_bg_color, 0.3);
    border-right: $stroke solid @theme_selected_bg_color;
}

box.dock-area-drop-highlight {
    background: alpha(@theme_selected_bg_color, 0.08);
}
""")


apply_css(dock_css)


class DockItem:
    def __init__(self, name, icon_name, widget, label=None, expands=True):
        self.name = name
        self.icon_name = icon_name
        self.widget = widget
        self.label = label or name
        self.expands = expands
