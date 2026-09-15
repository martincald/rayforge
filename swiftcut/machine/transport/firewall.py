"""
Best-effort Windows Firewall inbound UDP rule, for the Ruida response
port.

A Ruida controller replies to a fixed local UDP port (see
RuidaDriver.RESPONSE_PORT); Windows Firewall silently dropping those
replies looks identical to a wrong-port misconfiguration -- a clean
timeout with no exception. Adding an inbound allow rule needs
administrator rights, which a normal launch does not have. This module
only ever adds the rule when the process already happens to be
elevated; it never triggers a UAC prompt. When it cannot add the rule,
the caller is expected to show the manual instruction instead (see
device_settings_page.FIREWALL_NOTE).
"""

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

RULE_NAME_PREFIX = "SwiftCut UDP"


def is_elevated() -> bool:
    """Whether this process already holds administrator rights."""
    if sys.platform != "win32":
        return False
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore
    except OSError:
        return False


def _rule_exists(port: int) -> bool:
    result = subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "show",
            "rule",
            f"name={RULE_NAME_PREFIX} {port}",
        ],
        capture_output=True,
        text=True,
    )
    # netsh exits non-zero when no rule matches. Use the exit code
    # rather than matching "No rules match", which is localised and
    # would misreport the rule as present on a non-English Windows.
    return result.returncode == 0


def ensure_udp_inbound_rule(port: int) -> bool:
    """
    Add an inbound UDP allow rule for `port`, if possible without
    elevation.

    Returns True if the rule is present after this call (already
    there, or freshly added), False if it is missing and could not be
    added without a UAC prompt. Never elevates.
    """
    if sys.platform != "win32":
        return False
    try:
        if _rule_exists(port):
            return True
        if not is_elevated():
            logger.info(
                f"Not elevated; cannot add a firewall rule for UDP "
                f"port {port} without a UAC prompt."
            )
            return False
        subprocess.run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={RULE_NAME_PREFIX} {port}",
                "dir=in",
                "action=allow",
                "protocol=UDP",
                f"localport={port}",
                "profile=private",
            ],
            check=True,
            capture_output=True,
        )
        logger.info(f"Added inbound firewall rule for UDP port {port}.")
        return True
    except (OSError, subprocess.CalledProcessError) as e:
        logger.warning(
            f"Could not add firewall rule for UDP port {port}: {e}"
        )
        return False
