"""Asynchronous PCM playback through SDL's default macOS audio device."""
from threading import RLock

# Half a second of 48 kHz, mono, signed 16-bit silence, looped by the device.
IDLE_PCM = bytes(48000)


class MacAudioOutput:
    def __init__(self, make_pcm):
        self._make_pcm = make_pcm
        self._sound = None
        self._keep_warm = False
        self._idle = False
        self._owns_mixer = False
        self._lock = RLock()

    def play(self, frequency, duration, continuous=False):
        if type(continuous) is not bool:
            raise ValueError("Continuous must be bool")
        pcm = self._make_pcm(frequency, 1000 if continuous else duration,
                             fade_edges=not continuous)
        if frequency == 0:
            self.stop()
        else:
            self.play_pcm(pcm, continuous)

    def play_pcm(self, pcm, continuous=False):
        from pygame import mixer

        with self._lock:
            self._stop_sound()
            if mixer.get_init() is None:
                mixer.init(frequency=48000, size=-16, channels=1, buffer=512,
                           allowedchanges=0)
                self._owns_mixer = True
            if mixer.get_init() != (48000, -16, 1):
                raise RuntimeError("부저 출력에는 48 kHz 16비트 모노 오디오가 필요합니다.")
            sound = mixer.Sound(buffer=pcm)
            if sound.play(loops=-1 if continuous else 0) is None:
                raise RuntimeError("부저 재생에 사용할 오디오 채널이 없습니다.")
            self._sound = sound

    def playback_done(self):
        with self._lock:
            return self._idle or self._sound is None or self._sound.get_num_channels() == 0

    def _stop_sound(self):
        if self._sound is not None:
            self._sound.stop()
            self._sound = None
        self._idle = False

    def enable_idle_output(self):
        with self._lock:
            self._keep_warm = True
            self.stop()

    def stop(self):
        with self._lock:
            if self._keep_warm:
                if not self._idle:
                    self.play_pcm(IDLE_PCM, continuous=True)
                    self._idle = True
            else:
                self._stop_sound()

    def close(self):
        with self._lock:
            self._keep_warm = False
            self._stop_sound()
            if self._owns_mixer:
                from pygame import mixer
                mixer.quit()
                self._owns_mixer = False
