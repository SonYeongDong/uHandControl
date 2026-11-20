import io
import sys
import types
import unittest
import wave
from unittest.mock import patch
import numpy as np
from uhand_motion_creator.motion import Motion,Buzzer,LED,Sequence,generate_code,call_code
from uhand_motion_creator.playback import MotionPlayback
from uhand_motion_creator.audio import make_tone,make_pcm

class MixedModelTests(unittest.TestCase):
    def test_validation_and_boundaries(self):
        for freq in (0,1,99,100,10000):self.assertEqual(Buzzer(freq,100).frequency,freq)
        for freq in (-1,10001,65536,True,1.5,"1000"):
            with self.assertRaises(ValueError):Buzzer(freq)
        for t in (99,20001,True,1.5):
            with self.assertRaises(ValueError):Buzzer(running_time=t)
        for bad in (-1,256,None,"True"):
            with self.assertRaises(ValueError):LED(bad,False,True)
        for cls in (Buzzer,LED):
            for name in ("", " ", "x\ny","x"*61,None):
                with self.assertRaises(ValueError):cls(name=name)
        self.assertEqual(LED(True,False,True).running_time,0)

    def test_mixed_reorder_delete_and_export(self):
        items=(LED(True),Motion((1600,)*6,100),Buzzer(1900,200),LED())
        seq=Sequence()
        for item in items:seq.add(item)
        self.assertEqual(seq.move_group((0,2),4),(2,3))
        self.assertEqual(seq.items,(items[1],items[3],items[0],items[2]))
        seq.delete_group((0,2))
        self.assertEqual(seq.items,(items[3],items[2]))
        self.assertIn("hand.SetuHandLED(0, 0, 0, 100)",generate_code(seq.items))
        self.assertIn("hand.SetuHandBuzzer(1900, 200)",generate_code(seq.items))

    def test_generated_calls_in_order_and_cleanup(self):
        calls=[];fake=types.ModuleType("uhand_client_module")
        for name in ("Connect","Disconnect","SetuHandPulse","SetuHandBuzzer","SetuHandLED"):
            setattr(fake,name,lambda *a,n=name:calls.append((n,a)))
        items=(LED(True),Buzzer(1900,100),Motion((1200,)*6,200),LED())
        with patch.dict(sys.modules,uhand_client_module=fake):exec(generate_code(items),{})
        self.assertEqual([n for n,a in calls],["Connect","SetuHandLED","SetuHandBuzzer","SetuHandPulse","SetuHandLED","Disconnect"])
        self.assertEqual(calls[1][1],(255,0,0,100))
        self.assertEqual(calls[2][1],(1900,100))
        def fail(*a):raise RuntimeError("failed")
        fake.SetuHandBuzzer=fail;calls.clear()
        with patch.dict(sys.modules,uhand_client_module=fake):
            with self.assertRaises(RuntimeError):exec(generate_code(items),{})
        self.assertEqual(calls[-1][0],"Disconnect")

class MixedTimelineTests(unittest.TestCase):
    def setUp(self):
        self.items=(LED(True),Motion((1000,)*6,100),LED(False,True),Buzzer(1000,200),Motion((2000,)*6,100),LED())
    def test_interleaved_states_and_boundaries(self):
        t=MotionPlayback(self.items,0,(1500,)*6)
        f=t.frame(50);self.assertEqual((f.index,f.pulses,f.led),(1,(1250,)*6,(255,0,0)))
        f=t.frame(100);self.assertEqual((f.index,f.pulses,f.led,f.remaining),(3,(1000,)*6,(0,255,0),200))
        f=t.frame(350);self.assertEqual((f.index,f.pulses,f.led),(4,(1500,)*6,(0,255,0)))
        f=t.frame(400);self.assertTrue(f.finished);self.assertEqual(f.pulses,(2000,)*6);self.assertEqual(f.led,(False,)*3)
    def test_led_only_consecutive_and_empty_time(self):
        t=MotionPlayback((LED(True),LED(False,True),LED(0,0,255)),0,(1500,)*6)
        f=t.frame(0);self.assertTrue(f.finished);self.assertEqual(f.index,2);self.assertEqual(f.led,(0,0,255))
        self.assertEqual(t.ends,(0,0,0))
    def test_start_at_buzzer_uses_current_state(self):
        t=MotionPlayback(self.items,3,(1700,)*6,(255,0,255))
        f=t.frame(0);self.assertEqual(f.pulses,(1700,)*6);self.assertEqual(f.led,(255,0,255))
        f=t.frame(250);self.assertEqual(f.pulses,(1850,)*6)
    def test_final_buzzer_retains_pose_and_led(self):
        t=MotionPlayback((Motion((1300,)*6,100),LED(True),Buzzer()),0,(1500,)*6)
        f=t.frame(99999);self.assertTrue(f.finished);self.assertEqual(f.pulses,(1300,)*6);self.assertEqual(f.led,(255,0,0))

class AudioTests(unittest.TestCase):
    def test_pcm_duration_frequency_and_fades(self):
        data=make_tone(1900,500)
        with wave.open(io.BytesIO(data)) as wav:
            self.assertEqual((wav.getframerate(),wav.getnchannels(),wav.getsampwidth(),wav.getnframes()),(48000,1,2,24000))
            samples=np.frombuffer(wav.readframes(24000),dtype="<i2")
        self.assertEqual(samples[0],0);self.assertEqual(samples[-1],0)
        peak=np.argmax(abs(np.fft.rfft(samples)))*48000/len(samples)
        self.assertEqual(peak,1900)
    def test_unsupported_preview_does_not_alias(self):
        for f in (-1,10001,24000,65535,True):
            with self.assertRaises(ValueError):make_tone(f,100)
        for t in (0,-1,float("inf"),20001):
            with self.assertRaises(ValueError):make_tone(1000,t)
    def test_device_sample_formats_and_stereo(self):
        for fmt,dtype in (("Int16","<i2"),("Int32","<i4"),("Float","<f4"),("UInt8","u1")):
            data=make_pcm(1900,100,48000,2,fmt)
            samples=np.frombuffer(data,dtype=dtype).reshape(-1,2)
            self.assertEqual(len(samples),4800)
            np.testing.assert_array_equal(samples[:,0],samples[:,1])
        samples=np.frombuffer(make_pcm(1000,100,sample_format="Float"),dtype="<f4")
        self.assertLessEqual(abs(samples).max(),0.2)
    def test_device_nyquist_and_invalid_format(self):
        with self.assertRaises(ValueError):make_pcm(23999,100,44100)
        with self.assertRaises(ValueError):make_pcm(1000,100,sample_format="Unknown")

class WaveLifecycleTests(unittest.TestCase):
    class Device:
        def __init__(self):self.calls=[];self.fail=None
        def action(self,name):
            self.calls.append(name)
            if self.fail==name:raise RuntimeError(name)
        def open(self):self.action("open");return 1
        def prepare(self,*a):self.action("prepare")
        def write(self,*a):self.action("write")
        def reset(self,*a):self.action("reset")
        def unprepare(self,*a):self.action("unprepare")
        def close(self,*a):self.action("close")
    def test_device_opens_once_and_buffers_return_before_release(self):
        from uhand_motion_creator.audio import WindowsAudio
        d=self.Device();a=WindowsAudio(d)
        self.assertEqual(d.calls,["open"])
        a.play(1000,100);self.assertIsNotNone(a._buffer)
        a.play(1900,100);a.close()
        self.assertEqual(d.calls,["open","prepare","write","reset","unprepare","prepare","write","reset","unprepare","close"])
        self.assertIsNone(a._buffer);self.assertIsNone(a._handle)
    def test_failed_write_cleans_prepared_buffer(self):
        from uhand_motion_creator.audio import WindowsAudio
        d=self.Device();a=WindowsAudio(d);d.fail="write"
        with self.assertRaises(RuntimeError):a.play(1000,100)
        self.assertEqual(d.calls[-2:],["reset","unprepare"])
        self.assertIsNone(a._buffer);a.close()
    def test_failed_reset_retains_driver_owned_memory(self):
        from uhand_motion_creator.audio import WindowsAudio
        d=self.Device();a=WindowsAudio(d);a.play(1000,100);buffer=a._buffer;d.fail="reset"
        with self.assertRaises(RuntimeError):a.stop()
        self.assertIs(a._buffer,buffer);self.assertTrue(a._prepared)
        d.fail=None;a.close()
