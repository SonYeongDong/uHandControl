"""Repeat sequencing boundaries, cleanup and validation without physical movement."""
import unittest
import uhand_client_module as hand
from uhand_motion_creator.remote import RemoteSession
from uhand_motion_creator.motion import Motion, Buzzer, LED
from test_remote import done

class Client:
    def __init__(self):
        self.calls=[];self.pulses=0;self.session=None;self.fail=False
    def SetuHandPulse(self,*args):
        self.pulses+=1;self.calls.append(("pulse",args))
        if self.fail:raise hand.RemoteError("DEVICE_ERROR","test")
        if self.pulses==3:self.session.stop()
    def SetuHandBuzzer(self,*args):self.calls.append(("buzzer",args))
    def SetuHandLED(self,*args):self.calls.append(("led",args))
    def GetStatus(self):return {}
    def Disconnect(self):self.calls.append(("disconnect",()))

class RemoteRepeatTests(unittest.TestCase):
    def make(self):
        c=Client();s=RemoteSession(c);c.session=s;s.connected=True
        return c,s
    def test_repeat_keeps_range_order_and_continuous_sound_until_stop(self):
        c,s=self.make()
        s.submit("run",cards=((4,Motion()),(5,LED(True)),(6,Buzzer(1000,100,continuous=True))),repeat=True)
        events=done(s)
        self.assertEqual([(e["index"],e["cycle"]) for e in events if e["type"]=="progress"],
                         [(4,1),(5,1),(6,1),(4,2),(5,2),(6,2),(4,3)])
        self.assertEqual([a for n,a in c.calls if n=="buzzer"],[(1000,100,True),(1000,100,True),(0,100,True)])
        self.assertTrue(events[-1]["stopped"]);self.assertFalse(events[-1]["errors"])
    def test_selected_single_motion_repeats(self):
        c,s=self.make();s.submit("run",cards=((2,Motion()),),repeat=True)
        events=done(s);self.assertEqual(c.pulses,3)
        self.assertEqual([e["index"] for e in events if e["type"]=="progress"],[2,2,2])
    def test_error_does_not_restart_repeat(self):
        c,s=self.make();c.fail=True;s.submit("run",cards=((0,Motion()),(1,LED(True))),repeat=True)
        result=done(s)[-1];self.assertTrue(result["errors"]);self.assertEqual(c.pulses,1)
        self.assertEqual([n for n,a in c.calls],["pulse","buzzer"])
    def test_instant_only_range_rejected_before_sending(self):
        for cards in ((LED(),),(Buzzer(1000,100,continuous=True),),(LED(),Buzzer(0,100,continuous=True))):
            c,s=self.make()
            with self.assertRaisesRegex(ValueError,"즉시 적용"):s.submit("run",cards=tuple(enumerate(cards)),repeat=True)
            self.assertFalse(s.busy);self.assertEqual(c.calls,[])
    def test_finite_silent_delay_is_repeatable(self):
        c,s=self.make()
        def buzzer(*args):
            c.calls.append(("buzzer",args))
            if args==(0,100,False) and len(c.calls)==3:s.stop()
        c.SetuHandBuzzer=buzzer
        s.submit("run",cards=((0,Buzzer(0,100)),),repeat=True);done(s)
        self.assertEqual(c.calls,[("buzzer",(0,100,False))]*3+[("buzzer",(0,100,True))])
    def test_default_remains_single_pass(self):
        c,s=self.make();s.submit("run",cards=((0,Motion()),));events=done(s)
        self.assertEqual(c.pulses,1);self.assertFalse(events[-1]["stopped"])
    def test_invalid_repeat_mode_rejected(self):
        for flag in (1,0,None,"yes"):
            c,s=self.make()
            with self.assertRaises(ValueError):s.submit("run",cards=((0,Motion()),),repeat=flag)
        c,s=self.make()
        with self.assertRaises(ValueError):s.submit("run",cards=((0,Motion()),),cleanup=False,repeat=True)
        with self.assertRaises(ValueError):s.submit("status",repeat=True)
