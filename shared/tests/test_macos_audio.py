"""Mac output routing and SDL playback through an isolated dummy audio device."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from uhand_motion_creator import audio as editor_audio
from uhand_virtual_server import audio as server_audio

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "shared/uhand-desktop-audio/src"


class MacAudioTests(unittest.TestCase):
    def test_both_entry_points_select_mac_output_without_opening_device(self):
        with patch.object(sys, "platform", "darwin"), patch.object(sys, "path", [str(SOURCE), *sys.path]):
            from uhand_desktop_audio import MacAudioOutput
            self.assertIsInstance(editor_audio.create_audio(), MacAudioOutput)
            self.assertIsInstance(server_audio.create_audio()._get(), MacAudioOutput)

    @unittest.skipUnless(importlib.util.find_spec("pygame"), "requires pygame-ce (macOS dependency)")
    def test_sdl_playback_and_server_lifecycle(self):
        env = dict(os.environ, SDL_AUDIODRIVER="dummy", PYGAME_HIDE_SUPPORT_PROMPT="1",
                   PYTHONPATH=os.pathsep.join([str(SOURCE), os.environ.get("PYTHONPATH", "")]))
        subprocess.run([sys.executable, __file__, "--sdl"], env=env, check=True, timeout=30)


def check_sdl():
    import time
    import uhand_client_module as hand
    from uhand_desktop_audio import MacAudioOutput
    from uhand_virtual_server.server import VirtualServer

    output = MacAudioOutput(editor_audio.make_pcm)
    output.play(440, 100)
    assert not output.playback_done()
    deadline = time.monotonic() + 2
    while not output.playback_done():
        assert time.monotonic() < deadline
        time.sleep(.01)
    output.play(880, 100, continuous=True)
    time.sleep(1.2)
    assert not output.playback_done()
    output.play(0, 100, continuous=True)
    assert output.playback_done()
    output.close()

    server = VirtualServer("127.0.0.1", 0, audio=server_audio.MacAudio())
    try:
        server.start()
        hand.Connect("127.0.0.1", server.port)
        hand.SetuHandBuzzer(440, 100, True)
        hand.SetuHandLED(32, 64, 128, 50)
        assert hand.GetStatus()["BuzzerContinuous"]
        hand.SetuHandBuzzer(0, 100, True)
        assert hand.GetStatus()["BuzzerFrequency"] == 0
        hand.Disconnect()
        deadline = time.monotonic() + 5
        while server.owner is not None or server.lifecycle.phase:
            assert time.monotonic() < deadline
            time.sleep(.01)
        hand.Connect("127.0.0.1", server.port)
    finally:
        hand.Disconnect()
        server.shutdown()


if __name__ == "__main__" and sys.argv[1:] == ["--sdl"]:
    check_sdl()
