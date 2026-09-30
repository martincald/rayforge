"""Haptics: silent when unavailable or disabled, one tap per 60 ms,
never raising. AppKit is faked, so these run on any platform."""

import sys
import types
from unittest.mock import MagicMock

import pytest

from swiftcut.ui_gtk.haptics import Haptics

ALIGNMENT, GENERIC, NOW = 11, 12, 13


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def appkit(monkeypatch):
    """A fake AppKit on a fake darwin."""
    module = types.ModuleType("AppKit")
    vars(module).update(
        NSHapticFeedbackManager=MagicMock(),
        NSHapticFeedbackPatternAlignment=ALIGNMENT,
        NSHapticFeedbackPatternGeneric=GENERIC,
        NSHapticFeedbackPerformanceTimeNow=NOW,
    )
    monkeypatch.setitem(sys.modules, "AppKit", module)
    monkeypatch.setattr(sys, "platform", "darwin")
    return module


def _performed(performer):
    return performer.performFeedbackPattern_performanceTime_


def test_unavailable_never_touches_the_performer(monkeypatch):
    monkeypatch.setitem(sys.modules, "AppKit", None)  # import fails
    monkeypatch.setattr(sys, "platform", "darwin")
    performer = MagicMock()
    h = Haptics(performer=performer, clock=Clock())

    h.perform("alignment")

    assert h.available is False
    assert performer.mock_calls == []


def test_disabled_never_touches_the_performer(appkit):
    performer = MagicMock()
    h = Haptics(performer=performer, clock=Clock())
    h.enabled = False

    h.alignment()

    assert h.available is True
    assert performer.mock_calls == []


def test_plays_the_named_pattern_now(appkit):
    performer = MagicMock()
    clock = Clock()
    h = Haptics(performer=performer, clock=clock)

    h.alignment()
    clock.t += 1.0
    h.generic()

    assert _performed(performer).call_args_list == [
        ((ALIGNMENT, NOW),),
        ((GENERIC, NOW),),
    ]


def test_uses_the_default_performer_when_none_is_given(appkit):
    h = Haptics(clock=Clock())

    h.alignment()

    default = appkit.NSHapticFeedbackManager.defaultPerformer.return_value
    _performed(default).assert_called_once_with(ALIGNMENT, NOW)


def test_two_calls_30_ms_apart_play_once(appkit):
    performer = MagicMock()
    clock = Clock()
    h = Haptics(performer=performer, clock=clock)

    h.alignment()
    clock.t += 0.030
    h.alignment()

    assert _performed(performer).call_count == 1


def test_two_calls_70_ms_apart_play_twice(appkit):
    performer = MagicMock()
    clock = Clock()
    h = Haptics(performer=performer, clock=clock)

    h.alignment()
    clock.t += 0.070
    h.alignment()

    assert _performed(performer).call_count == 2


def test_a_failing_performer_is_swallowed(appkit):
    performer = MagicMock()
    _performed(performer).side_effect = RuntimeError("no trackpad")
    clock = Clock()
    h = Haptics(performer=performer, clock=clock)

    h.alignment()
    clock.t += 1.0
    h.generic()

    assert _performed(performer).call_count == 2


def test_off_macos_even_with_appkit_importable(appkit, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    performer = MagicMock()
    h = Haptics(performer=performer, clock=Clock())

    h.alignment()

    assert h.available is False
    assert performer.mock_calls == []
