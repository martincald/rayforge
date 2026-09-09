"""Bundled default machine profile for the shop's ilab-614 Ruida machine.

``ILAB_614_PROFILE`` is a verbatim copy of the shop's real
Duplotech-1490 Ruida machine profile (see
``docs/profiles/ilab-614.source.yaml``), with only the ``name`` field
changed to ``"ilab-614"``. ``MachineManager.create_default_machine``
uses it to seed a fresh install so the app comes up already configured
for this machine, instead of a bare 200x200mm placeholder.

The dict uses the same ``machine:``-wrapper shape that
``Machine.to_dict``/``Machine.from_dict`` read and write, so it is
loaded exactly like any other saved machine file.
"""

from typing import Any

ILAB_614_PROFILE: dict[str, Any] = {
    "machine": {
        "active_wcs": "REF0",
        "arc_tolerance": 0.03,
        "auto_connect": True,
        "axes": {
            "configs": [
                {
                    "axis_type": "linear",
                    "direction": "normal",
                    "extents": [
                        0,
                        1400.0
                    ],
                    "letter": "X",
                    "resolution": 0.01
                },
                {
                    "axis_type": "linear",
                    "direction": "normal",
                    "extents": [
                        0,
                        900.0
                    ],
                    "letter": "Y",
                    "resolution": 0.01
                },
                {
                    "axis_type": "linear",
                    "direction": "normal",
                    "extents": [
                        -50,
                        50
                    ],
                    "letter": "Z",
                    "resolution": 0.01
                }
            ]
        },
        "axis_extents": [
            1400.0,
            900.0
        ],
        "cameras": [],
        "capabilities": None,
        "clear_alarm_on_connect": False,
        "coordinate_systems": [
            {
                "name": "MACHINE",
                "offset": [
                    0.0,
                    0.0,
                    0.0
                ]
            }
        ],
        "default_rotary_module_uid": None,
        "dialect_uid": None,
        "driver": "RuidaDriver",
        "driver_args": {
            "host": "192.168.1.100",
            "jog_port": 50207,
            "port": 50200
        },
        "driver_config": {},
        "gcode": {
            "gcode_precision": 3
        },
        "heads": [
            {
                "cut_color": "#ff00ff",
                "focal_distance": 6.0,
                "focus_power_percent": 20.0,
                "frame_corner_pause": 0,
                "frame_power_percent": 0.0,
                "frame_repeat_count": 20,
                "frame_speed": 0,
                "laser_type": "diode",
                "max_power": 1000,
                "max_pulse_width": 500,
                "max_pwm_frequency": 5000,
                "min_pulse_width": 5,
                "model_path": None,
                "name": "Laser Head",
                "pulse_width": 50,
                "pwm_frequency": 500,
                "raster_color": "#000000",
                "spot_size_mm": [
                    0.1,
                    0.1
                ],
                "tool_number": 0,
                "transform": [
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0
                ],
                "type": "LaserHead",
                "uid": "1d88afa7-d70f-4608-acc8-165522c8124d"
            }
        ],
        "home_on_start": False,
        "hookmacros": {},
        "machine_hours": {
            "counters": {},
            "total_hours": 23.484947806160385
        },
        "macros": {},
        "name": "ilab-614",
        "nogo_zones": [],
        "origin": "top_left",
        "panel_orientation": "native",
        "reverse_x_axis": False,
        "reverse_y_axis": False,
        "reverse_z_axis": False,
        "rotary_enabled_default": False,
        "rotary_modules": [],
        "single_axis_homing_enabled": True,
        "soft_limits": None,
        "speeds": {
            "acceleration": 1000,
            "max_cut_speed": 9342,
            "max_travel_speed": 3000
        },
        "start_corner": "bottom_left",
        "supports_arcs": True,
        "supports_curves": False,
        "units": {
            "unit_system": "metric"
        },
        "wcs_origin_is_workarea_origin": False,
        "work_margins": [
            0.0,
            0.0,
            0.0,
            0.0
        ]
    }
}
