"""Regression tests for the Ruida UDP port defaults and local bind.

A user's live ilab-614 profile was found on disk with port 50201 and
jog_port 50200 -- neither value exists anywhere in source, and
neither matches the device's real listening ports. These tests pin
the correct defaults (port 50200, jog_port 50207, response port
40200) and confirm the driver actually binds the local response port
so a Ruida controller's replies have somewhere to land.

No real socket is opened and nothing is sent to a real laser: the
UdpTransport constructor is mocked and only its call arguments are
inspected.
"""

from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.models.machine import Machine


def test_default_ports_are_pinned():
    """port 50200, jog_port 50207, response port 40200."""
    setup_vars = RuidaDriver.get_setup_vars()
    port_var = setup_vars.get("port")
    jog_port_var = setup_vars.get("jog_port")

    assert port_var is not None
    assert jog_port_var is not None
    assert port_var.default == 50200
    assert jog_port_var.default == 50207
    assert RuidaDriver.RESPONSE_PORT == 40200


def test_setup_binds_the_response_port_locally(lite_context, mocker):
    """
    The main UDP channel must bind local port 40200 (the Ruida
    response port) so the controller's replies have a socket to land
    on. The jog channel is not a reply target and binds no local port.
    """
    udp_transport_cls = mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_driver.UdpTransport"
    )
    machine = Machine(lite_context)
    driver = RuidaDriver(lite_context, machine)

    driver._setup_implementation(
        host="192.168.1.100", port=50200, jog_port=50207
    )

    main_call, jog_call = udp_transport_cls.call_args_list
    assert main_call.args == ("192.168.1.100", 50200)
    assert main_call.kwargs == {"local_port": 40200}
    assert jog_call.args == ("192.168.1.100", 50207)
    assert jog_call.kwargs == {}


def test_get_diagnostics_before_setup_has_no_endpoints_or_transport(
    lite_context,
):
    """
    Before setup, diagnostics must not claim any endpoint or bind
    state -- there is nothing to report yet.
    """
    machine = Machine(lite_context)
    driver = RuidaDriver(lite_context, machine)

    diagnostics = driver.get_diagnostics()

    assert diagnostics.driver_class == "RuidaDriver"
    assert diagnostics.host is None
    assert diagnostics.port is None
    assert diagnostics.jog_port is None
    assert diagnostics.response_port == 40200
    assert diagnostics.response_port_bound is None
    assert diagnostics.response_port_error is None
    assert diagnostics.last_enq_sent_at is None
    assert diagnostics.last_ack_received_at is None


def test_get_diagnostics_after_setup_reports_configured_endpoints(
    lite_context, mocker
):
    """
    After setup, diagnostics must report the configured host/ports and
    the main channel's (the response-port channel's) bind state.
    """
    udp_transport_cls = mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_driver.UdpTransport"
    )
    udp_transport_cls.return_value.is_connected = True
    udp_transport_cls.return_value.last_bind_error = None
    machine = Machine(lite_context)
    driver = RuidaDriver(lite_context, machine)

    driver._setup_implementation(
        host="192.168.1.100", port=50200, jog_port=50207
    )

    diagnostics = driver.get_diagnostics()

    assert diagnostics.host == "192.168.1.100"
    assert diagnostics.port == 50200
    assert diagnostics.jog_port == 50207
    assert diagnostics.response_port == 40200
    assert diagnostics.response_port_bound is True
    assert diagnostics.response_port_error is None


def test_get_diagnostics_surfaces_a_bind_failure(lite_context, mocker):
    """
    When the response port failed to bind, diagnostics must surface
    the friendly error text so the owner can self-diagnose it.
    """
    udp_transport_cls = mocker.patch(
        "swiftcut.machine.driver.ruida.ruida_driver.UdpTransport"
    )
    udp_transport_cls.return_value.is_connected = False
    udp_transport_cls.return_value.last_bind_error = (
        "port in use (another SwiftCut instance?)"
    )
    machine = Machine(lite_context)
    driver = RuidaDriver(lite_context, machine)

    driver._setup_implementation(
        host="192.168.1.100", port=50200, jog_port=50207
    )

    diagnostics = driver.get_diagnostics()

    assert diagnostics.response_port_bound is False
    assert (
        diagnostics.response_port_error
        == "port in use (another SwiftCut instance?)"
    )


def test_expected_ports_reads_the_canonical_values():
    """
    expected_ports must not hardcode a fourth copy of the numbers --
    it has to agree with default_profile.ILAB_614_PROFILE and
    RuidaDriver.RESPONSE_PORT, whatever they are.
    """
    from swiftcut.machine.models.default_profile import ILAB_614_PROFILE

    default_args = ILAB_614_PROFILE["machine"]["driver_args"]
    assert RuidaDriver.expected_ports() == {
        "port": default_args["port"],
        "jog_port": default_args["jog_port"],
        "response_port": RuidaDriver.RESPONSE_PORT,
    }
    assert RuidaDriver.expected_ports() == {
        "port": 50200,
        "jog_port": 50207,
        "response_port": 40200,
    }


def test_port_mismatches_flags_the_owner_s_actual_wrong_port():
    """Regression for the real bug: port 50201 instead of 50200."""
    mismatches = RuidaDriver.port_mismatches(
        {"host": "192.168.1.100", "port": 50201, "jog_port": 50207}
    )
    assert mismatches == {"port": (50201, 50200)}


def test_port_mismatches_flags_a_wrong_response_port():
    mismatches = RuidaDriver.port_mismatches(
        {"port": 50200, "jog_port": 50207, "response_port": 12345}
    )
    assert mismatches == {"response_port": (12345, 40200)}


def test_port_mismatches_is_empty_for_the_correct_profile():
    assert (
        RuidaDriver.port_mismatches(
            {"host": "192.168.1.100", "port": 50200, "jog_port": 50207}
        )
        == {}
    )


def test_port_mismatches_treats_a_missing_key_as_the_default():
    """
    _setup_implementation itself falls back to the canonical value for
    a missing key, so an absent port is not a mismatch.
    """
    assert RuidaDriver.port_mismatches({"host": "192.168.1.100"}) == {}
