"""
Tests for the best-effort Windows Firewall inbound UDP rule helper.

No real `netsh` process is ever run and no real elevation check is
made: subprocess.run and ctypes are mocked throughout. The mechanism
under test must never elevate -- these tests pin that it only adds
the rule when the process already reports itself as elevated, and
otherwise leaves the rule missing for the caller to show the manual
instruction instead.
"""

import subprocess

from swiftcut.machine.transport import firewall


def test_ensure_rule_is_a_noop_off_windows(monkeypatch, mocker):
    monkeypatch.setattr(firewall.sys, "platform", "linux")
    run = mocker.patch("swiftcut.machine.transport.firewall.subprocess.run")

    assert firewall.ensure_udp_inbound_rule(40200) is False
    run.assert_not_called()


def test_is_elevated_is_false_off_windows(monkeypatch):
    monkeypatch.setattr(firewall.sys, "platform", "linux")

    assert firewall.is_elevated() is False


def test_ensure_rule_does_nothing_when_rule_already_exists(
    monkeypatch, mocker
):
    monkeypatch.setattr(firewall.sys, "platform", "win32")
    run = mocker.patch(
        "swiftcut.machine.transport.firewall.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Rule Name: SwiftCut UDP 40200\n"
        ),
    )

    assert firewall.ensure_udp_inbound_rule(40200) is True
    # Only the existence check ran; nothing was added.
    run.assert_called_once()
    assert run.call_args.args[0][:4] == [
        "netsh",
        "advfirewall",
        "firewall",
        "show",
    ]


def test_ensure_rule_never_elevates_when_missing_and_not_elevated(
    monkeypatch, mocker
):
    monkeypatch.setattr(firewall.sys, "platform", "win32")
    mocker.patch(
        "swiftcut.machine.transport.firewall.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="No rules match the criteria.\n"
        ),
    )
    mocker.patch(
        "swiftcut.machine.transport.firewall.is_elevated",
        return_value=False,
    )

    assert firewall.ensure_udp_inbound_rule(40200) is False


def test_ensure_rule_adds_it_when_missing_and_already_elevated(
    monkeypatch, mocker
):
    monkeypatch.setattr(firewall.sys, "platform", "win32")
    run = mocker.patch(
        "swiftcut.machine.transport.firewall.subprocess.run",
        side_effect=[
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="No rules match the criteria.\n",
            ),
            subprocess.CompletedProcess(args=[], returncode=0),
        ],
    )
    mocker.patch(
        "swiftcut.machine.transport.firewall.is_elevated",
        return_value=True,
    )

    assert firewall.ensure_udp_inbound_rule(40200) is True
    assert run.call_count == 2
    add_call_args = run.call_args_list[1].args[0]
    assert add_call_args[:5] == [
        "netsh",
        "advfirewall",
        "firewall",
        "add",
        "rule",
    ]
    assert "localport=40200" in add_call_args
