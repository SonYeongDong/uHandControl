"""Finite Windows audio with a persistent device and immediate buffer reset."""
import ctypes
import io
import math
from functools import lru_cache
import wave
import numpy as np

SAMPLE_RATE=48000

# Half a second of 48 kHz, mono, signed 16-bit silence, looped by the device.
IDLE_PCM = bytes(SAMPLE_RATE)
WHDR_DONE = 0x00000001

def make_pcm(frequency,duration,rate=48000,channels=1,sample_format="Int16",fade_edges=True):
    if type(frequency) is not int or not 0<=frequency<=min(10000,(rate-1)//2):
        raise ValueError(f"PC 소리 미리듣기는 0~{min(10000,(rate-1)//2)}Hz를 지원합니다.")
    if not isinstance(duration,(int,float)) or not math.isfinite(duration) or not 0<duration<=20000:
        raise ValueError("잘못된 소리 재생 시간입니다.")
    count=max(1,round(rate*duration/1000))
    signal=np.sin(np.arange(count)*2*np.pi*frequency/rate)*0.198
    fade=min(round(rate*.005),count//2)
    if fade and fade_edges:
        ramp=np.linspace(0,1,fade)
        signal[:fade]*=ramp;signal[-fade:]*=ramp[::-1]
    if sample_format=="Int16":signal=(signal*32767).astype("<i2")
    elif sample_format=="Int32":signal=(signal*2147483647).astype("<i4")
    elif sample_format=="Float":signal=signal.astype("<f4")
    elif sample_format=="UInt8":signal=(signal*127+128).astype("u1")
    else:raise ValueError("지원하지 않는 PC 오디오 형식입니다.")
    return np.repeat(signal,channels).tobytes()

def make_tone(frequency,duration):
    output=io.BytesIO()
    with wave.open(output,"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(SAMPLE_RATE)
        wav.writeframes(make_pcm(frequency,duration))
    return output.getvalue()


class WaveFormat(ctypes.Structure):
    _fields_=[("tag",ctypes.c_uint16),("channels",ctypes.c_uint16),
              ("rate",ctypes.c_uint32),("bytes_sec",ctypes.c_uint32),
              ("align",ctypes.c_uint16),("bits",ctypes.c_uint16),("extra",ctypes.c_uint16)]

class WaveHeader(ctypes.Structure):
    _fields_=[("data",ctypes.c_void_p),("length",ctypes.c_uint32),
              ("recorded",ctypes.c_uint32),("user",ctypes.c_size_t),
              ("flags",ctypes.c_uint32),("loops",ctypes.c_uint32),
              ("next",ctypes.c_void_p),("reserved",ctypes.c_size_t)]

class WaveDevice:
    """One open device, prepared finite PCM buffers; no callbacks or worker races."""
    def __init__(self):
        self.dll=ctypes.WinDLL("winmm")
        self.dll.waveOutOpen.argtypes=(ctypes.POINTER(ctypes.c_void_p),ctypes.c_uint32,ctypes.POINTER(WaveFormat),ctypes.c_size_t,ctypes.c_size_t,ctypes.c_uint32)
        for name in ("waveOutPrepareHeader","waveOutWrite","waveOutUnprepareHeader"):
            getattr(self.dll,name).argtypes=(ctypes.c_void_p,ctypes.POINTER(WaveHeader),ctypes.c_uint32)
        for name in ("waveOutReset","waveOutClose"):getattr(self.dll,name).argtypes=(ctypes.c_void_p,)
        for name in ("waveOutOpen","waveOutPrepareHeader","waveOutWrite","waveOutUnprepareHeader","waveOutReset","waveOutClose"):
            getattr(self.dll,name).restype=ctypes.c_uint32
    @staticmethod
    def check(result):
        if result:raise RuntimeError(f"PC 오디오 출력 오류 (Windows 코드 {result}). 출력 장치를 확인하세요.")
    def open(self):
        handle=ctypes.c_void_p();fmt=WaveFormat(1,1,SAMPLE_RATE,SAMPLE_RATE*2,2,16,0)
        self.check(self.dll.waveOutOpen(ctypes.byref(handle),0xFFFFFFFF,ctypes.byref(fmt),0,0,0))
        return handle
    def prepare(self,handle,header):self.check(self.dll.waveOutPrepareHeader(handle,ctypes.byref(header),ctypes.sizeof(header)))
    def write(self,handle,header):self.check(self.dll.waveOutWrite(handle,ctypes.byref(header),ctypes.sizeof(header)))
    def reset(self,handle):self.check(self.dll.waveOutReset(handle))
    def unprepare(self,handle,header):self.check(self.dll.waveOutUnprepareHeader(handle,ctypes.byref(header),ctypes.sizeof(header)))
    def close(self,handle):self.check(self.dll.waveOutClose(handle))

@lru_cache(maxsize=8)
def continuous_pcm(frequency):
    # One second contains an integer number of cycles at every supported integer Hz.
    # Let the audio driver loop it; Python scheduling cannot leave gaps between blocks.
    return make_pcm(frequency, 1000, fade_edges=False)

class WindowsAudio:
    """Open at app startup without sound; play/stop never reopen the device."""
    def __init__(self,device=None):
        self._device=device;self._handle=None;self._buffer=None;self._header=None;self._prepared=False
        self._loop_frequency = None
        self._keep_warm = False
        self._idle = False
        try:self._open()
        except (OSError,RuntimeError):pass  # Editing still works without speakers.
    def _open(self):
        if self._device is None:self._device=WaveDevice()
        if self._handle is None:self._handle=self._device.open()
    def play(self,frequency,duration,continuous=False):
        if type(continuous) is not bool:raise ValueError("Continuous must be bool")
        if type(frequency) is not int or not 0 <= frequency <= 10000:
            raise ValueError("Frequency must be an integer in 0..10000")
        if frequency == 0:
            self.stop()
        elif continuous:
            if self._loop_frequency != frequency:
                self.play_pcm(continuous_pcm(frequency), continuous=True)
                self._loop_frequency = frequency
        else:
            self.play_pcm(make_pcm(frequency, duration))

    def play_pcm(self, data, continuous=False):
        self._release_buffer()
        self._open()
        self._buffer=ctypes.create_string_buffer(data)
        self._header=WaveHeader(ctypes.cast(self._buffer,ctypes.c_void_p),len(data),0,0,12 if continuous else 0,0xFFFFFFFF if continuous else 0,None,0)
        try:
            self._device.prepare(self._handle,self._header);self._prepared=True
            self._device.write(self._handle,self._header)
        except (OSError,RuntimeError):
            self._release_buffer();raise
    def playback_done(self):
        return self._prepared and bool(self._header.flags & WHDR_DONE)

    def enable_idle_output(self):
        self._keep_warm = True
        self.stop()

    def stop(self):
        if self._keep_warm:
            if not self._idle:
                self.play_pcm(IDLE_PCM, continuous=True)
                self._idle = True
        else:
            self._release_buffer()

    def _release_buffer(self):
        self._loop_frequency = None
        if self._prepared:
            # Keep memory alive if the driver fails to return/unprepare the buffer.
            if not self.playback_done():
                self._device.reset(self._handle)
            self._device.unprepare(self._handle,self._header)
        self._prepared=False;self._header=None;self._buffer=None
        self._idle = False

    def close(self):
        self._keep_warm = False
        self._release_buffer()
        if self._handle is not None:
            self._device.close(self._handle);self._handle=None
