import itertools
import json
import socket
import threading
import time
import unittest
from uhand_server.backend import RecordingBackend
from uhand_server.server import PhysicalServer
from uhand_server.protocol import PULSE_NAMES
from uhand_server_lifecycle import reset_status
class Peer:
    def __init__(self,port):
        self.socket=socket.create_connection(("127.0.0.1",port));self.socket.settimeout(3)
        self.file=self.socket.makefile("rb");self.counter=itertools.count(1)
    def send(self,method,params=None):
        rid=next(self.counter);self.socket.sendall((json.dumps({"version":2,"request_id":rid,"method":method,"params":params or {}})+"\n").encode());return rid
    def receive(self):return json.loads(self.file.readline())
    def call(self,method,params=None):
        rid=self.send(method,params);response=self.receive();assert response["request_id"]==rid;return response
    def close(self):
        self.file.close();self.socket.close()
def pulse(value=1500,ms=100):
    return {**dict.fromkeys(PULSE_NAMES,value),"RunningTime":ms}
def led():return {"RedEnable":True,"GreenEnable":False,"BlueEnable":True}
class ServerTests(unittest.TestCase):
    def setUp(self):
        self.backend=RecordingBackend();self.server=PhysicalServer(self.backend,port=0);self.server.start()
        self.peer=Peer(self.server.port);self.assertTrue(self.peer.call("Hello")["ok"])
        self.initial_commands = list(self.backend.commands)
    def tearDown(self):
        self.peer.close();self.server.shutdown()
    def test_failed_logger_does_not_break_reply(self):
        def broken(*args):raise OSError("log full")
        self.server.logger=broken
        self.assertTrue(self.peer.call("SetuHandLED",led())["ok"])
        self.assertEqual(self.peer.call("GetStatus")["result"]["LED"],[True,False,True])
    def test_ready_and_connect_sequences(self):
        self.assertEqual(self.peer.call("GetStatus", {"IncludeLEDBrightness":True})["result"],reset_status());self.assertEqual(self.backend.commands,self.initial_commands)
        tones = [(c[2],c[1]) for c in self.backend.commands if c[0]=="buzzer"]
        self.assertEqual(tones, [(f,175) for f in (523,659,784,659,880)])
        self.assertEqual([c[1] for c in self.backend.commands if c[0]=="pulse"], [500,500])
    def test_pulse_waits_and_commits(self):
        start=time.monotonic();self.assertTrue(self.peer.call("SetuHandPulse",pulse())["ok"])
        self.assertGreaterEqual(time.monotonic()-start,.099)
        status=self.peer.call("GetStatus")["result"]
        self.assertEqual(status["TargetPulses"],[1500]*6);self.assertEqual(status["PulseRunningTime"],100);self.assertEqual(status["LED"],[False]*3)
    def test_status_previous_and_busy_during_output(self):
        self.peer.call("SetuHandPulse",pulse(1000))
        rid=self.peer.send("SetuHandPulse",pulse(1700,500))
        query=self.peer.send("GetStatus");start=time.monotonic();reply=self.peer.receive()
        self.assertEqual(reply["request_id"],query);self.assertEqual(reply["result"]["TargetPulses"],[1000]*6);self.assertLess(time.monotonic()-start,.3)
        busy=self.peer.send("SetuHandLED",led());reply=self.peer.receive()
        self.assertEqual(reply["request_id"],busy);self.assertEqual(reply["error"]["code"],"BUSY")
        self.assertEqual(self.peer.receive()["request_id"],rid)
    def test_buzzer_independent_records(self):
        self.peer.call("SetuHandLED",led())
        self.peer.call("SetuHandBuzzer",{"Frequency":1000,"RunningTime":100})
        rid=self.peer.send("SetuHandBuzzer",{"Frequency":1900,"RunningTime":300})
        q=self.peer.send("GetStatus");reply=self.peer.receive();self.assertEqual(reply["request_id"],q)
        self.assertEqual(reply["result"]["BuzzerFrequency"],1000)
        self.peer.receive();state=self.peer.call("GetStatus")["result"]
        self.assertEqual(state["BuzzerFrequency"],1900);self.assertEqual(state["BuzzerRunningTime"],300);self.assertEqual(state["LED"],[True,False,True])
    def test_buzzer_off_failure_preserves_status(self):
        self.peer.call("SetuHandBuzzer",{"Frequency":1000,"RunningTime":100})
        self.assertEqual(self.backend.commands[-1],("buzzer_off",1000))
        def fail(*args):raise OSError("off write failed")
        self.backend.finish_buzzer=fail
        reply=self.peer.call("SetuHandBuzzer",{"Frequency":1900,"RunningTime":100})
        self.assertEqual(reply["error"]["code"],"DEVICE_ERROR")
        self.assertEqual(self.peer.call("GetStatus")["result"]["BuzzerFrequency"],1000)
    def test_led_all_eight_combinations(self):
        for values in itertools.product((False,True),repeat=3):
            response=self.peer.call("SetuHandLED",dict(zip(led(),values)));self.assertTrue(response["ok"])
            self.assertEqual(self.peer.call("GetStatus")["result"]["LED"],list(values))
    def test_invalid_argument_never_outputs(self):
        for params in (pulse(True),pulse(499),pulse(2501),pulse(1500,99),pulse(1500,20001)):
            self.assertEqual(self.peer.call("SetuHandPulse",params)["error"]["code"],"INVALID_ARGUMENT")
        self.assertEqual(self.backend.commands,self.initial_commands)
    def test_device_error_preserves_last_record(self):
        self.peer.call("SetuHandPulse",pulse(1000))
        def fail(*args):raise OSError("serial write failed")
        self.backend.set_pulses=fail
        self.assertEqual(self.peer.call("SetuHandPulse",pulse(1500))["error"]["code"],"DEVICE_ERROR")
        self.assertEqual(self.peer.call("GetStatus")["result"]["TargetPulses"],[1000]*6)
        self.assertTrue(self.peer.call("SetuHandLED",led())["ok"])
    def test_owner_loss_resets_before_next_connection(self):
        self.peer.send("SetuHandPulse",pulse(1600,20000))
        time.sleep(.05)
        self.peer.close()
        time.sleep(.1)
        self.peer=Peer(self.server.port)
        self.assertEqual(self.peer.call("Hello")["error"]["code"],"BUSY")
        self.peer.close()
        deadline=time.monotonic()+3
        while self.server.lifecycle.phase and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.server.status,reset_status())
        tones=[c[2] for c in self.backend.commands if c[0]=="buzzer"]
        self.assertEqual(tones[-3:],[440,370,294])
        self.peer=Peer(self.server.port)
        self.assertTrue(self.peer.call("Hello")["ok"])
    def test_second_client_cannot_take_over(self):
        other=Peer(self.server.port)
        try:self.assertEqual(other.call("Hello")["error"]["code"],"BUSY")
        finally:other.close()
        self.assertTrue(self.peer.call("GetStatus")["ok"])
    def test_hello_required(self):
        other=Peer(self.server.port)
        try:self.assertEqual(other.call("SetuHandLED",led())["error"]["code"],"INVALID_ARGUMENT")
        finally:other.close()
        self.assertEqual(self.backend.commands,self.initial_commands)
    def test_invalid_duplicate_json_closes(self):
        other=Peer(self.server.port)
        try:
            other.socket.sendall(b'{"request_id":1,"request_id":2}\n')
            self.assertEqual(other.file.readline(),b"")
        finally:other.close()
    def test_maximum_frame_enforced(self):
        other=Peer(self.server.port)
        try:
            other.socket.sendall(b" "*65536)
            self.assertEqual(other.file.readline(),b"")
        finally:other.close()
    def test_fragmented_request(self):
        data=b'{"version":2,"request_id":50,"method":"GetStatus","params":{}}\n'
        self.peer.socket.sendall(data[:9]);self.peer.socket.sendall(data[9:]);self.assertEqual(self.peer.receive()["request_id"],50)
    def test_duplicate_request_id_closes(self):
        self.peer.socket.sendall(b'{"version":2,"request_id":1,"method":"GetStatus","params":{}}\n')
        self.assertEqual(self.peer.file.readline(),b"")
    def test_port_conflict_no_output(self):
        other=PhysicalServer(RecordingBackend(),port=self.server.port)
        with self.assertRaises(OSError):other.start()
        self.assertEqual(other.backend.commands,[])
    def test_shutdown_drains_active_motion(self):
        self.peer.send("SetuHandPulse",pulse(1700,300));time.sleep(.05)
        start=time.monotonic();self.assertTrue(self.server.shutdown())
        self.assertGreaterEqual(time.monotonic()-start,.2)
        self.assertEqual(self.server.status["TargetPulses"],[1700]*6);self.assertTrue(self.backend.closed)
    def test_maximum_20_second_motion(self):
        self.peer.socket.settimeout(23)
        start=time.monotonic();self.assertTrue(self.peer.call("SetuHandPulse",pulse(1500,20000))["ok"])
        self.assertGreaterEqual(time.monotonic()-start,19.99)
    def test_query_snapshot_cannot_mutate_server(self):
        status=self.server.snapshot()["status"];status["LED"]=[True]*3
        self.assertEqual(self.peer.call("GetStatus")["result"]["LED"],[False]*3)
