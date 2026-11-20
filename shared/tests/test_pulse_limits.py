"""Cross-package pulse contract, raw TCP rejection, and no-output backend checks."""
from pathlib import Path
import sys,unittest,json,socket,io
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
if "--installed" not in sys.argv:
    for p in ("uhand-client-module","uhand-virtual-server","uhand-server","uhand-motion-creator"):
        sys.path.insert(0,str(ROOT/"projects"/p/"src"))
import uhand_client_module as hand
from uhand_client_module._validation import PULSE_LIMITS as CLIENT, status_result
from uhand_virtual_server.protocol import PULSE_LIMITS as VIRTUAL
from uhand_server.protocol import PULSE_LIMITS as PHYSICAL,CommandError
from uhand_server.backend import Profile,HardwareBackend,RecordingBackend
from uhand_server.server import PhysicalServer
from uhand_virtual_server.server import VirtualServer
from uhand_motion_creator.motion import Motion,PULSE_LIMITS as CREATOR,generate_code
from uhand_motion_creator.card_clipboard import encode_cards,decode_cards
EXPECTED=((800,2200),(800,2000),(800,2000),(800,2000),(800,2000),(500,2500))
NAMES=tuple(f"Finger{i}Pulse" for i in range(1,6))+("WristPulse",)

class ContractTests(unittest.TestCase):
    def test_all_four_definitions_match_user_ranges(self):
        for actual in (CLIENT,VIRTUAL,PHYSICAL,CREATOR):self.assertEqual(actual,EXPECTED)
    def test_client_each_axis_rejects_before_transport(self):
        with patch.object(hand._client,"request") as request:
            for axis,(low,high) in enumerate(EXPECTED):
                for value in (low-1,high+1,True,float(low),str(low),None):
                    values=[1500]*6;values[axis]=value
                    with self.subTest(axis=axis,value=value),self.assertRaises(hand.InputValidationError):
                        hand.SetuHandPulse(*values,100)
            request.assert_not_called()
    def test_creator_each_axis_and_clipboard_reject_invalid(self):
        base=json.loads(encode_cards([Motion()]))
        for axis,(low,high) in enumerate(EXPECTED):
            for value in (low-1,high+1):
                values=[1500]*6;values[axis]=value
                with self.subTest(axis=axis,value=value):
                    with self.assertRaises(ValueError):Motion(values)
                    base["cards"][0]["pulses"]=values
                    with self.assertRaises(ValueError):decode_cards(json.dumps(base).encode())
    def test_limits_are_inclusive_and_export_preserves_values(self):
        for values in (tuple(p[0] for p in EXPECTED),tuple(p[1] for p in EXPECTED)):
            motion=Motion(values,100)
            fake=Mock()
            with patch.dict("sys.modules",{"uhand_client_module":fake}):
                exec(generate_code([motion]),{})
            fake.SetuHandPulse.assert_called_once_with(*values,100)
            with patch.object(hand._client,"request") as request:
                hand.SetuHandPulse(*values,100)
                self.assertEqual([request.call_args.args[1][key] for key in NAMES],list(values))
    def test_invalid_completed_status_is_rejected(self):
        value=dict(TargetPulses=[1500]*6,PulseRunningTime=100,BuzzerFrequency=None,BuzzerRunningTime=None,BuzzerContinuous=None,LED=None)
        for axis,(low,high) in enumerate(EXPECTED):
            for bad in (low-1,high+1):
                value["TargetPulses"]=[1500]*6;value["TargetPulses"][axis]=bad
                with self.assertRaises(hand.InputValidationError):status_result(value)
    def test_backend_rejects_before_any_sdk_call(self):
        profile=Profile.load(ROOT/"projects/uhand-server/config/hardware-profile.json")
        board=Mock();backend=HardwareBackend(profile,board,verify=False)
        for axis,(low,high) in enumerate(EXPECTED):
            for bad in (low-1,high+1):
                values=[1500]*6;values[axis]=bad
                with self.assertRaises(CommandError):backend.set_pulses(values,100)
        board.pwm_servo_set_position.assert_not_called()

class WireTests(unittest.TestCase):
    def check_server(self,server,backend=None):
        server.start()
        sock=socket.create_connection(("127.0.0.1",server.port),timeout=3)
        stream=sock.makefile("rb");rid=0
        def call(method,params=None):
            nonlocal rid
            rid+=1;sock.sendall((json.dumps(dict(version=2,request_id=rid,method=method,params=params or {}))+"\n").encode())
            response=json.loads(stream.readline());self.assertEqual(response["request_id"],rid);return response
        try:
            self.assertTrue(call("Hello")["ok"])
            for values in (tuple(p[0] for p in EXPECTED),tuple(p[1] for p in EXPECTED),(1500,)*6):
                self.assertTrue(call("SetuHandPulse",dict(zip(NAMES,values),RunningTime=100))["ok"])
                self.assertEqual(call("GetStatus")["result"]["TargetPulses"],list(values))
            before=call("GetStatus")["result"]
            commands=list(backend.commands) if backend else None
            for axis,(low,high) in enumerate(EXPECTED):
                for bad in (low-1,high+1,True,low+.5):
                    values=[1500]*6;values[axis]=bad
                    result=call("SetuHandPulse",dict(zip(NAMES,values),RunningTime=100))
                    self.assertFalse(result["ok"]);self.assertEqual(result["error"]["code"],"INVALID_ARGUMENT")
                    self.assertIn(NAMES[axis],result["error"]["message"])
                    self.assertEqual(call("GetStatus")["result"],before)
            if backend:self.assertEqual(backend.commands,commands)
        finally:
            stream.close();sock.close();server.shutdown()
    def test_virtual_server_raw_tcp(self):self.check_server(VirtualServer(port=0))
    def test_physical_server_raw_tcp_without_hardware(self):
        backend=RecordingBackend()
        self.check_server(PhysicalServer(backend,port=0),backend)

if __name__=="__main__":
    stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    out=ROOT/"reports/pulse-limits-2026-11-18";out.mkdir(parents=True,exist_ok=True)
    (out/("contract-installed.txt" if "--installed" in sys.argv else "contract-source.txt")).write_text(stream.getvalue(),encoding="utf-8")
    print(stream.getvalue());sys.exit(not result.wasSuccessful())
