# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Transport buttons, seek bar and volume control for the main player."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from pulsedeck.audio.playback_engine import PlaybackState
from pulsedeck.audio.playback_queue import RepeatMode
from pulsedeck.library.models import format_duration
from pulsedeck.ui import icons
from pulsedeck.ui.widgets import JumpSlider

SEEK_RESOLUTION = 1000  # slider steps per second


def _button(tooltip: str, checkable: bool = False, size: int = 30) -> QToolButton:
    button = QToolButton()
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setCheckable(checkable)
    button.setAutoRaise(False)
    button.setFixedSize(size, size)
    button.setIconSize(QSize(size - 12, size - 12))
    button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return button


class SeekBar(QWidget):
    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.slider = JumpSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setAccessibleName("Seek")
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.sliderReleased.connect(self._on_released)
        self.slider.sliderMoved.connect(self._on_moved)
        self.elapsed = QLabel("0:00")
        self.total = QLabel("0:00")
        for label in (self.elapsed, self.total):
            label.setProperty("role", "muted")
            label.setMinimumWidth(44)
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.elapsed)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.total)
        controller.position_changed.connect(self.update_position)

    def update_position(self, position: float, duration: float) -> None:
        if self.slider.isSliderDown():
            return
        self.slider.blockSignals(True)
        self.slider.setRange(0, int(duration * SEEK_RESOLUTION) if duration > 0 else 0)
        self.slider.setValue(int(position * SEEK_RESOLUTION))
        self.slider.blockSignals(False)
        self.elapsed.setText(format_duration(position))
        self.total.setText(format_duration(duration) if duration else "--:--")

    def _on_moved(self, value: int) -> None:
        self.elapsed.setText(format_duration(value / SEEK_RESOLUTION))

    def _on_released(self) -> None:
        self.controller.seek(self.slider.value() / SEEK_RESOLUTION)


class TransportBar(QWidget):
    def __init__(self, controller, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.controller = controller
        self.icon_color = "#d6dbe4"
        self.accent_color = "#3ad6a0"

        self.previous_btn = _button("Previous track")
        self.rewind_btn = _button("Rewind")
        self.play_btn = _button("Play", size=38)
        self.stop_btn = _button("Stop")
        self.forward_btn = _button("Fast forward")
        self.next_btn = _button("Next track")
        self.shuffle_btn = _button("Shuffle", checkable=True)
        self.repeat_btn = _button("Repeat: off")
        self.mute_btn = _button("Mute", checkable=True)
        self.volume = JumpSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(110)
        self.volume.setAccessibleName("Volume")
        self.volume.setToolTip("Volume")
        self.volume.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume_label = QLabel("80%")
        self.volume_label.setProperty("role", "muted")
        self.volume_label.setMinimumWidth(36)

        self.previous_btn.clicked.connect(controller.previous_track)
        self.rewind_btn.clicked.connect(controller.rewind)
        self.play_btn.clicked.connect(controller.toggle_play_pause)
        self.stop_btn.clicked.connect(controller.stop)
        self.forward_btn.clicked.connect(controller.fast_forward)
        self.next_btn.clicked.connect(controller.next_track)
        self.shuffle_btn.clicked.connect(lambda checked: controller.set_shuffle(checked))
        self.repeat_btn.clicked.connect(controller.cycle_repeat)
        self.mute_btn.clicked.connect(lambda checked: controller.set_muted(checked))
        self.volume.valueChanged.connect(controller.set_volume)
        # Fast forward / rewind repeat while held.
        for button in (self.rewind_btn, self.forward_btn):
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(400)
            button.setAutoRepeatInterval(250)

        row = QHBoxLayout()
        row.setSpacing(4)
        for widget in (self.previous_btn, self.rewind_btn, self.play_btn, self.stop_btn, self.forward_btn,
                       self.next_btn):
            row.addWidget(widget)
        row.addSpacing(10)
        row.addWidget(self.shuffle_btn)
        row.addWidget(self.repeat_btn)
        row.addStretch(1)
        row.addWidget(self.mute_btn)
        row.addWidget(self.volume)
        row.addWidget(self.volume_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        controller.state_changed.connect(lambda _s: self.refresh())
        controller.options_changed.connect(self.refresh)
        self.refresh()

    def set_colors(self, text: str, accent: str) -> None:
        self.icon_color, self.accent_color = text, accent
        self.refresh()

    def refresh(self) -> None:
        c = self.controller
        color = self.icon_color
        self.previous_btn.setIcon(icons.icon("previous", color))
        self.rewind_btn.setIcon(icons.icon("rewind", color))
        self.stop_btn.setIcon(icons.icon("stop", color))
        self.forward_btn.setIcon(icons.icon("forward", color))
        self.next_btn.setIcon(icons.icon("next", color))
        playing = c.state is PlaybackState.PLAYING
        self.play_btn.setIcon(icons.icon("pause" if playing else "play", self.accent_color))
        self.play_btn.setToolTip("Pause" if playing else "Play")
        self.stop_btn.setEnabled(c.state is not PlaybackState.STOPPED)

        self.shuffle_btn.setChecked(c.shuffle)
        self.shuffle_btn.setIcon(icons.icon("shuffle", self.accent_color if c.shuffle else color))
        self.shuffle_btn.setToolTip("Shuffle: on" if c.shuffle else "Shuffle: off")
        mode = c.repeat
        self.repeat_btn.setIcon(icons.icon("repeat_one" if mode is RepeatMode.ONE else "repeat",
                                           color if mode is RepeatMode.OFF else self.accent_color))
        self.repeat_btn.setToolTip({RepeatMode.OFF: "Repeat: off", RepeatMode.ALL: "Repeat: all",
                                    RepeatMode.ONE: "Repeat: one"}[mode])
        self.mute_btn.setChecked(c.muted)
        self.mute_btn.setIcon(icons.icon("mute" if c.muted else "volume", color))
        self.mute_btn.setToolTip("Unmute" if c.muted else "Mute")
        if not self.volume.isSliderDown():
            self.volume.blockSignals(True)
            self.volume.setValue(c.volume)
            self.volume.blockSignals(False)
        self.volume_label.setText("Muted" if c.muted else f"{c.volume}%")
