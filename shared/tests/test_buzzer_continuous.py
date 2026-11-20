"""Four-project contract tests; only loopback sockets and recording hardware."""
from pathlib import Path
import io,json,socket,sys,threading,time,unittest
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
if "--installed" not in sys.argv:
    for slug in ("uhand-client-module","uhand-server","uhand-virtual-server","uhand-motion-creator"):
        sys.path.insert(0,str(ROOT/"projects"/slug/"src"))
else:sys.argv.remove("--installed")
import uhand_client_module as hand
from uhand_client_module._transport import _Client
from uhand_motion_creator.motion import Buzzer,Motion,LED,generate_code,detail,timeline_duration
from uhand_motion_creator.playback import MotionPlayback
from uhand_motion_creator.audio import WindowsAudio,make_pcm
from uhand_virtual_server.server import VirtualServer
from uhand_server.server import PhysicalServer
from uhand_server.backend import RecordingBackend,HardwareBackend,Profile

class Audio:
    def __init__(self):self.frequency=0;self.fail=False;self.calls=[]
    def start(self,f):
        if self.fail:raise OSError("start failed")
        self.frequency=f;self.calls.append(("start",f))
    def play(self,f,t,cancel):
        self.start(f);cancel.wait(t/1000);self.stop()
    def stop(self):self.frequency=0;self.calls.append(("stop",))
    def close(self):self.stop()

class Contract:
    def setUp(self):
        hand.Disconnect()
        self.output=RecordingBackend() if self.physical else Audio()
        self.server=PhysicalServer(self.output,port=0) if self.physical else VirtualServer(port=0,audio=self.output)
        self.server.start();hand.Connect("127.0.0.1",self.server.port)
    def tearDown(self):
        hand.Disconnect();self.server.shutdown()
    def status(self,f,t,c):
        state=hand.GetStatus()
        self.assertEqual((state["BuzzerFrequency"],state["BuzzerRunningTime"],state["BuzzerContinuous"]),(f,t,c))
    def test_frequency_range_and_rejected_inputs_preserve_state(self):
        for frequency in (0, 1, 99, 100, 10000):
            hand.SetuHandBuzzer(frequency, 100)
            self.status(frequency, 100, False)
        for frequency in (-1, 10001, True, 1.5):
            with self.assertRaises(hand.InputValidationError):
                hand.SetuHandBuzzer(frequency, 100)
            self.status(10000, 100, False)

    def test_immediate_return_and_other_outputs(self):
        start=time.monotonic();hand.SetuHandBuzzer(1000,20000,True)
        self.assertLess(time.monotonic()-start,1)
        self.status(1000,20000,True)
        hand.SetuHandPulse(*([1500]*6),100);hand.SetuHandLED(True,False,True)
        self.status(1000,20000,True)
        if self.physical:self.assertEqual(self.output.commands[-3][0],"buzzer_continuous")
        else:self.assertEqual(self.output.frequency,1000)
    def test_replacement_finite_and_zero_delay(self):
        hand.SetuHandBuzzer(1000,100,True)
        hand.SetuHandBuzzer(1900,20000,True);self.status(1900,20000,True)
        start=time.monotonic();hand.SetuHandBuzzer(0,150)
        self.assertGreaterEqual(time.monotonic()-start,.145);self.status(0,150,False)
        if not self.physical:self.assertEqual(self.output.frequency,0)
        hand.SetuHandBuzzer(1000,100);self.status(1000,100,False)
    def test_zero_continuous_immediate_and_stays_silent(self):
        hand.SetuHandBuzzer(1000,100,True)
        start=time.monotonic();hand.SetuHandBuzzer(0,20000,True)
        self.assertLess(time.monotonic()-start,1)
        hand.SetuHandLED(False,True,False);self.status(0,20000,True)
        if self.physical:self.assertEqual(self.output.commands[-2],("buzzer_off",1000))
        else:self.assertEqual(self.output.frequency,0)
    def test_invalid_continuous_and_range_do_not_change_output(self):
        hand.SetuHandBuzzer(1000,100,True)
        for value in (0,1,None,"true",[],1.0):
            with self.subTest(value=value),self.assertRaises(hand.InputValidationError):hand.SetuHandBuzzer(1900,100,value)
        for f,t in ((-1,100),(65536,100),(True,100),(1000,99),(1000,20001)):
            with self.assertRaises(hand.InputValidationError):hand.SetuHandBuzzer(f,t,True)
        self.status(1000,100,True)
    def test_wire_invalid_mode_and_legacy_default(self):
        hand.SetuHandBuzzer(1000,100,True)
        with self.assertRaises(hand.RemoteError):hand._client.request("SetuHandBuzzer",{"Frequency":1900,"RunningTime":100,"Continuous":1})
        self.status(1000,100,True)
        hand._client.request("SetuHandBuzzer",{"Frequency":0,"RunningTime":100})
        self.status(0,100,False)
    def test_status_previous_while_silent_delay_and_busy(self):
        hand.SetuHandBuzzer(1000,100,True)
        errors=[]
        def run():
            try:hand.SetuHandBuzzer(0,400)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=run);worker.start()
        deadline=time.monotonic()+1
        while not self.server.snapshot()["busy"] and time.monotonic()<deadline:time.sleep(.001)
        self.status(1000,100,True)
        with self.assertRaises(hand.BusyError):hand.SetuHandLED(True,False,False)
        worker.join(2);self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.status(0,400,False)
    def test_disconnect_resets_and_reconnect_can_silence(self):
        hand.SetuHandBuzzer(1000,100,True);hand.Disconnect()
        deadline=time.monotonic()+2
        while (self.server.owner is not None or self.server.lifecycle.phase) and time.monotonic()<deadline:time.sleep(.005)
        hand.Connect("127.0.0.1",self.server.port);self.status(0,100,False)
        hand.SetuHandBuzzer(0,100,True);self.status(0,100,True)
    def test_shutdown_stops_continuous_output(self):
        hand.SetuHandBuzzer(1000,100,True);self.server.shutdown()
        if self.physical:self.assertEqual(self.output.commands[-1],("buzzer_off",1000))
        else:self.assertEqual(self.output.frequency,0)
    def test_generated_mixed_sequence(self):
        cards=(Buzzer(1000,20000,continuous=True),LED(True),Motion((1500,)*6,100),Buzzer(0,150),Buzzer(1900,20000,continuous=True),LED(False,True),Buzzer(0,100,continuous=True))
        hand.Disconnect()
        deadline=time.monotonic()+2
        while (self.server.owner is not None or self.server.lifecycle.phase) and time.monotonic()<deadline:time.sleep(.005)
        start=time.monotonic();exec(generate_code(cards,"127.0.0.1",self.server.port),{})
        elapsed=time.monotonic()-start
        self.assertGreaterEqual(elapsed,.245);self.assertLess(elapsed,4)
        deadline=time.monotonic()+3
        while (self.server.owner is not None or self.server.lifecycle.phase) and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.server.status["LED"],[False]*3)
        self.assertEqual(self.server.status["BuzzerFrequency"],0)
    def test_old_protocol_rejected_before_output(self):
        s=socket.create_connection(("127.0.0.1",self.server.port));f=s.makefile("rb")
        try:
            s.sendall(b'{"version":1,"request_id":1,"method":"Hello","params":{}}\n')
            result=json.loads(f.readline());self.assertEqual(result["error"]["code"],"UNSUPPORTED_VERSION")
        finally:f.close();s.close()

class VirtualTests(Contract,unittest.TestCase):
    physical=False
    def test_unsupported_frequency_preserves_loop(self):
        hand.SetuHandBuzzer(1000,100,True)
        with self.assertRaises(hand.InputValidationError):hand.SetuHandBuzzer(10001,100,True)
        self.assertEqual(self.output.frequency,1000);self.status(1000,100,True)
    def test_no_audio_device_required_for_silence(self):
        from uhand_virtual_server.server import UnavailableAudio
        self.server.audio=UnavailableAudio()
        hand.SetuHandBuzzer(0,100,True);hand.SetuHandBuzzer(0,100);self.status(0,100,False)
    def test_failed_replacement_preserves_status(self):
        hand.SetuHandBuzzer(1000,100,True);self.output.fail=True
        with self.assertRaises(hand.DeviceError):hand.SetuHandBuzzer(1900,100,True)
        self.status(1000,100,True);self.assertFalse(self.server.busy)
class PhysicalTests(Contract,unittest.TestCase):
    physical=True

class ModelTests(unittest.TestCase):
    def test_timeline_and_zero_time_cards(self):
        cards=(Buzzer(1000,20000,continuous=True),LED(True),Motion((1600,)*6,200),Buzzer(0,100),Buzzer(1900,100,continuous=True))
        p=MotionPlayback(cards,0,(1500,)*6)
        self.assertEqual(p.ends,(0,0,200,300,300))
        f=p.frame(50);self.assertEqual(f.buzzer.frequency,1000);self.assertEqual(f.pulses,(1525,)*6)
        f=p.frame(250);self.assertEqual(f.buzzer.frequency,0);self.assertEqual(f.buzzer_remaining,50)
        f=p.frame(300);self.assertTrue(f.finished);self.assertEqual(f.buzzer.frequency,1900)
        f=p.frame(1e9);self.assertEqual(f.buzzer.frequency,1900)
    def test_late_frame_and_current_card_do_not_replay_previous_buzzer(self):
        cards=(Buzzer(1000,100,continuous=True),Buzzer(1900,100),Motion((1700,)*6,100))
        f=MotionPlayback(cards,0,(1500,)*6).frame(150);self.assertIsNone(f.buzzer)
        f=MotionPlayback(cards,2,(1500,)*6).frame(0);self.assertIsNone(f.buzzer)
    def test_all_instantaneous_and_muted_sequence(self):
        cards=(Buzzer(1000,100,continuous=True),Buzzer(0,100,continuous=True),LED())
        f=MotionPlayback(cards,0,(1500,)*6).frame(0)
        self.assertTrue(f.finished);self.assertEqual(f.buzzer.frequency,0)
    def test_card_and_code(self):
        self.assertEqual(timeline_duration(Buzzer(0,20000,continuous=True)),0)
        self.assertIn("무음",detail(Buzzer(0)));self.assertIn("연속",detail(Buzzer(1900,continuous=True)))
        self.assertIn("SetuHandBuzzer(1900, 1000, True)",generate_code([Buzzer(1900,continuous=True)]))
        for value in (None,0,1,"true"):
            with self.assertRaises(ValueError):Buzzer(continuous=value)
    def test_zero_pcm_is_silence(self):
        self.assertEqual(set(make_pcm(0,100)),{0})
    def test_loop_buffer_and_replacement_cleanup(self):
        from uhand_motion_creator.audio import WindowsAudio
        device=Mock();device.open.return_value=1
        audio=WindowsAudio(device);audio.play(1000,100,True)
        self.assertEqual(audio._header.flags,12);self.assertEqual(audio._header.loops,0xFFFFFFFF)
        self.assertEqual(audio._header.length,96000)
        audio.play(0,100,True);self.assertIsNone(audio._buffer)
        device.reset.assert_called_once();audio.close()
    def test_hardware_repeat_and_mute_packets(self):
        profile=Profile.load(ROOT/"projects/uhand-server/config/hardware-profile.json")
        board=Mock();backend=HardwareBackend(profile,board,verify=False)
        backend.start_buzzer(1000);board.set_buzzer.assert_called_with(1000,1.0,0.0,0)
        backend.silence_buzzer();board.set_buzzer.assert_called_with(1000,0.0,0.0,1)
        before=board.set_buzzer.call_count
        with self.assertRaises(Exception):backend.start_buzzer(10001)
        self.assertEqual(board.set_buzzer.call_count,before)

if __name__=="__main__":
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    out=ROOT/"reports/buzzer-continuous";out.mkdir(parents=True,exist_ok=True)
    (out/"contract-tests.txt").write_text(stream.getvalue(),encoding="utf-8")
    print(stream.getvalue());sys.exit(not result.wasSuccessful())
