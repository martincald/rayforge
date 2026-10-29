from gettext import gettext as _

from .contour_step import ContourStep


class ScanStep(ContourStep):
    """Traces outlines like a Cut, fast and at low power, to mark them.

    Its own type so recipes and the add-step menu tell it from a Cut;
    the settings, assembler and output are a Cut's.
    """

    TYPELABEL = _("Scan")
    ICON = "step-contour-symbolic"
    # 30000 mm/min is 500 mm/s.
    TYPICAL_CUT_SPEED = 30000

    def __init__(self, name: str | None = None, typelabel: str | None = None):
        super().__init__(name=name, typelabel=typelabel)
        self.power = 0.10
