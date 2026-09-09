from .unit_spin_row import UnitSpinRow


class SpeedSpinRow(UnitSpinRow):
    """Unit-aware spin row for the ``speed`` quantity.

    Values are exchanged in application base units; the row displays
    and accepts the user's preferred speed unit (mm/s by default).
    """

    __gtype_name__ = "RayforgeSpeedSpinRow"

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        step_increment: float = 1.0,
        **kwargs,
    ):
        super().__init__(
            title,
            subtitle,
            quantity="speed",
            step_increment=step_increment,
            **kwargs,
        )
