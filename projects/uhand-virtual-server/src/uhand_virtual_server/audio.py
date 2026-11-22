"""Finite PCM sine playback on the desktop default output device."""
import io
import math
import sys
import time
import wave

import numpy as np

from .protocol import CommandError

SAMPLE_RATE = 48000


def make_tone(frequency, duration):
    if type(frequency) is not int or not 0 <= frequency <= 10000:
        raise CommandError("UNSUPPORTED_FREQUENCY", "Virtual PCM output supports 0..10000 Hz at 48000 samples/s.")
    count = SAMPLE_RATE * duration // 1000
    phase = np.arange(count, dtype=np.float64) * (2 * math.pi * frequency / SAMPLE_RATE)
    signal = np.sin(phase) * 6500  # No changes to the system volume.
    fade = min(count // 2, SAMPLE_RATE * 5 // 1000)
    signal[:fade] *= np.linspace(0, 1, fade)
    signal[-fade:] *= np.linspace(1, 0, fade)
    pcm = np.rint(signal).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(pcm)
    return output.getvalue()


class DesktopAudio:
    def __init__(self):
        self._output = None

    def _get(self):
        if self._output is None:
            self._output = self._open_output()
        return self._output

    def enable_idle_output(self):
        self._get().enable_idle_output()

    def play_notice_note(self, index, notes, tone_ms, gap_ms, cancel):
        from ._waveout import make_pcm

        output = self._get()
        if cancel.is_set():
            return
        if index == 0:
            gap = bytes(SAMPLE_RATE * gap_ms // 1000 * 2)
            output.play_pcm(gap.join(make_pcm(note, tone_ms) for note in notes))
        if index < len(notes) - 1:
            # The lifecycle drives the UI and log. The driver clocks the actual notes.
            cancel.wait(tone_ms / 1000)
            return
        # A slow or lost device must not hold the server in a transition indefinitely.
        deadline = time.monotonic() + tone_ms / 1000 + 2
        try:
            while not output.playback_done():
                if cancel.wait(0.005):
                    return
                if time.monotonic() >= deadline:
                    raise CommandError("DEVICE_ERROR", "The audio device did not finish the notification sound.")
        finally:
            output.stop()

    def start(self, frequency):
        if type(frequency) is not int or not 0 < frequency <= 10000:
            raise CommandError("UNSUPPORTED_FREQUENCY", "Virtual PCM output supports 1..10000 Hz.")
        try:
            self._start_continuous(frequency)
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError("DEVICE_ERROR", str(exc)) from exc

    def _start_continuous(self, frequency):
        self._get().play(frequency, 1000, True)

    def play(self, frequency, duration, cancel):
        if type(frequency) is not int or not 0 < frequency <= 10000:
            raise CommandError("UNSUPPORTED_FREQUENCY", "Virtual PCM output supports 1..10000 Hz.")
        if cancel.is_set():
            raise CommandError("DEVICE_ERROR", "Server is stopping.")
        try:
            self._get().play(frequency, duration)
            try:
                if cancel.wait(duration / 1000):
                    raise CommandError("DEVICE_ERROR", "Server stopped before completion.")
            finally:
                self.stop()
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError("DEVICE_ERROR", str(exc)) from exc

    def stop(self):
        if self._output is not None:
            self._output.stop()

    def close(self):
        if self._output is not None:
            self._output.close()


class WindowsAudio(DesktopAudio):
    description = "Windows 기본 출력 · 48 kHz · 연속 재생"

    def _open_output(self):
        from ._waveout import WindowsAudio as Output
        return Output()


class MacAudio(DesktopAudio):
    description = "macOS 기본 출력 · 48 kHz · 연속 재생"

    def _start_continuous(self, frequency):
        from ._waveout import continuous_pcm
        self._get().play_pcm(continuous_pcm(frequency), continuous=True)

    def _open_output(self):
        from uhand_desktop_audio import MacAudioOutput
        from ._waveout import make_pcm
        return MacAudioOutput(make_pcm)


def create_audio():
    return MacAudio() if sys.platform == "darwin" else WindowsAudio()
