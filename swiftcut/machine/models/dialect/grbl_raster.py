from gettext import gettext as _

from .base import GcodeDialect
from .grbl import grbl_common

GRBL_RASTER_DIALECT = GcodeDialect(
    uid="grbl_raster",
    label=_("GRBL Raster"),
    description=_(
        "Optimized for GRBL raster engraving. Keeps M4 dynamic power "
        "mode continuously active and uses modal feedrate to minimize "
        "command overhead during scan lines"
    ),
    can_g0_with_speed=True,
    continuous_laser_mode=True,
    modal_feedrate=True,
    laser_on="M4 S0",
    travel_move="G0{x_cmd}{y_cmd}{z_cmd}{extra_cmd}{f_command}{s_command}",
    linear_move="G1{x_cmd}{y_cmd}{z_cmd}{extra_cmd}{f_command}{s_command}",
    arc_cw=(
        "G2{x_cmd}{y_cmd}{z_cmd}{extra_cmd} I{i} J{j}{f_command}{s_command}"
    ),
    arc_ccw=(
        "G3{x_cmd}{y_cmd}{z_cmd}{extra_cmd} I{i} J{j}{f_command}{s_command}"
    ),
    **grbl_common(),
)
