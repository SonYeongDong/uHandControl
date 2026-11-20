"""Remote controller integration with real TCP servers and explicit fault injection."""
import time
import unittest
import uhand_client_module as hand
from uhand_virtual_server.server import VirtualServer
from uhand_server.server import PhysicalServer
from uhand_server.backend import RecordingBackend
from uhand_motion_creator.remote import RemoteSession
from uhand_motion_creator.motion import Motion, Buzzer, LED


class Audio:
    def __init__(self):self.frequency = 0
    def start(self, frequency):self.frequency = frequency
    def stop(self):self.frequency = 0
    def play(self, frequency, duration, cancel):
        self.frequency = frequency


def done(session, timeout=4):
    events = [];deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        events.extend(session.poll())
        if not session.busy:return events
        time.sleep(.005)
    raise AssertionError("Remote operation did not finish")


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.audio = Audio()
        self.server = VirtualServer(port=0, audio=self.audio);self.server.start()
        self.session = RemoteSession()
        self.session.submit("connect", endpoint=("127.0.0.1", self.server.port))
        self.assertFalse(done(self.session)[-1]["errors"])

    def tearDown(self):
        if self.session.busy:self.session.stop();done(self.session)
        if self.session.connected:
            self.session.submit("disconnect");done(self.session)
        hand.Disconnect();self.server.shutdown()

    def run_cards(self, cards, cleanup=True):
        self.session.submit("run", cards=tuple(enumerate(cards)), cleanup=cleanup)
        return done(self.session)

    def test_connect_does_not_drive_outputs(self):
        from uhand_server_lifecycle import reset_status
        self.assertEqual(self.server.status, reset_status())

    def test_mixed_sequence_order_cleanup_and_final_status(self):
        cards=(Buzzer(1000,100,continuous=True), Motion((1300,)*6,100), LED(True), Buzzer(0,100), LED())
        events=self.run_cards(cards)
        self.assertFalse(events[-1]["errors"])
        self.assertEqual([e["index"] for e in events if e["type"]=="progress"],list(range(5)))
        status=events[-1]["status"]
        self.assertEqual(status["TargetPulses"],[1300]*6)
        self.assertEqual(status["BuzzerFrequency"],0)
        self.assertEqual(status["LED"],[False]*3)
        self.assertEqual(self.audio.frequency,0)

    def test_direct_continuous_remains_during_hand_and_led(self):
        self.run_cards((Buzzer(1900,100,continuous=True),),False)
        self.assertEqual(self.audio.frequency,1900)
        self.run_cards((Motion((1400,)*6,100),LED(False,True)),False)
        self.assertEqual(self.audio.frequency,1900)
        self.run_cards((Buzzer(0,100,continuous=True),),False)
        self.assertEqual(self.audio.frequency,0)

    def test_stop_waits_current_and_skips_later_cards(self):
        self.session.submit("run",cards=((0,Motion((1200,)*6,300)),(1,LED(True))))
        deadline=time.monotonic()+2
        while not self.server.busy and time.monotonic()<deadline:time.sleep(.005)
        self.session.stop()
        events=done(self.session)
        self.assertTrue(events[-1]["stopped"])
        self.assertEqual(events[-1]["status"]["TargetPulses"],[1200]*6)
        self.assertEqual(events[-1]["status"]["LED"], [0]*3)
        self.assertEqual(events[-1]["status"]["BuzzerFrequency"],0)
        self.assertEqual([e["index"] for e in events if e["type"]=="progress"],[0])

    def test_requests_cannot_overlap(self):
        self.session.submit("run",cards=((0,Motion(running_time=200)),))
        with self.assertRaises(RuntimeError):self.session.submit("status")
        done(self.session)

    def test_disconnect_silences_direct_continuous(self):
        self.run_cards((Buzzer(1000,100,continuous=True),),False)
        self.session.submit("disconnect")
        self.assertFalse(done(self.session)[-1]["connected"])
        self.assertEqual(self.audio.frequency,0)

    def test_transport_failure_marks_disconnected_no_retry(self):
        self.server.shutdown()
        self.session.submit("status")
        result=done(self.session)[-1]
        self.assertFalse(result["connected"]);self.assertTrue(result["errors"])

    def test_physical_server_protocol_with_recording_backend(self):
        self.session.submit("disconnect");done(self.session)
        backend=RecordingBackend();server=PhysicalServer(backend,port=0);server.start()
        try:
            self.session.submit("connect",endpoint=("127.0.0.1",server.port));done(self.session)
            self.assertEqual([c[1] for c in backend.commands if c[0]=="pulse"], [500, 500])
            result=self.run_cards((Motion((1500,)*6,100),Buzzer(1900,100,continuous=True),LED(True,False,True)))[-1]
            self.assertFalse(result["errors"])
            self.assertEqual(result["status"]["LED"],[255,0,255])
            self.assertEqual(result["status"]["BuzzerFrequency"],0)
            self.assertTrue(any(c[0]=="pulse" for c in backend.commands))
            self.session.submit("disconnect");done(self.session)
        finally:server.shutdown()


class FailureTests(unittest.TestCase):
    def test_remote_rejection_aborts_remainder_but_retains_connection(self):
        class Client:
            def __init__(self):self.calls=[]
            def SetuHandPulse(self,*args):raise hand.RemoteError("INVALID_ARGUMENT","calibrated pulse out of range")
            def SetuHandBuzzer(self,*args):self.calls.append(("mute",args))
            def SetuHandLED(self,*args):self.calls.append(("led",args))
            def GetStatus(self):return {}
            def Disconnect(self):self.calls.append(("disconnect",))
        client=Client();s=RemoteSession(client);s.connected=True
        s.submit("run",cards=((0,Motion()),(1,LED(True))))
        result=done(s)[-1]
        self.assertTrue(result["connected"]);self.assertIn("INVALID_ARGUMENT",result["errors"][0])
        self.assertEqual(client.calls,[("mute",(0,100,True))])

    def test_cleanup_failure_is_reported(self):
        class Client:
            def SetuHandLED(self,*args):pass
            def SetuHandBuzzer(self,*args):raise hand.DeviceError("DEVICE_ERROR","cannot silence")
            def GetStatus(self):return {}
            def Disconnect(self):pass
        s=RemoteSession(Client());s.connected=True;s.submit("run",cards=((0,LED()),))
        self.assertIn("부저 종료 확인 실패",done(s)[-1]["errors"][0])

    def test_timeout_no_repeat_output_and_close_transport(self):
        class Client:
            def __init__(self):self.commands=0;self.closed=False
            def SetuHandPulse(self,*args):self.commands+=1;raise hand.RequestTimeoutError("deadline")
            def Disconnect(self):self.closed=True
        client=Client();s=RemoteSession(client);s.connected=True
        s.submit("run",cards=((0,Motion()),(1,LED())))
        result=done(s)[-1]
        self.assertFalse(result["connected"]);self.assertTrue(client.closed);self.assertEqual(client.commands,1)

    def test_connect_failure_does_not_claim_connection(self):
        class Client:
            def Connect(self,*args):raise hand.ConnectionFailedError("refused")
            def Disconnect(self):pass
        s=RemoteSession(Client());s.submit("connect",endpoint=("127.0.0.1",1))
        result=done(s)[-1]
        self.assertFalse(result["connected"]);self.assertTrue(result["errors"])
