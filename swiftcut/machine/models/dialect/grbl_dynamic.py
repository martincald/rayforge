from gettext import gettext as _

from .base import GcodeDialect
from .grbl import grbl_common

GRBL_DYNAMIC_DIALECT = GcodeDialect(
    uid="grbl_dynamic",
    label=_("GRBL Dynamic"),
    description=_(
        "GRBL with M4 dynamic power (Depth-Aware) mode. "
        "S parameter is included in motion commands"
    ),
    can_g0_with_speed=False,
    laser_on="M4 S0",
    travel_move="G0{x_cmd}{y_cmd}{z_cmd}{extra_cmd}",
    linear_move="G1{x_cmd}{y_cmd}{z_cmd}{extra_cmd}{f_command}{s_command}",
    arc_cw=(
        "G2{x_cmd}{y_cmd}{z_cmd}{extra_cmd} I{i} J{j}{f_command}{s_command}"
    ),
    arc_ccw=(
        "G3{x_cmd}{y_cmd}{z_cmd}{extra_cmd} I{i} J{j}{f_command}{s_command}"
    ),
    **grbl_common(),
)
