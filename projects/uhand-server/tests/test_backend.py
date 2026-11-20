import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import Mock
from uhand_server.backend import Profile,HardwareBackend,CheckedPort,seconds_exact
from uhand_server.protocol import CommandError
ROOT=Path(__file__).resolve().parents[1]
def profile(axes=True):
    data=json.loads((ROOT/"config/hardware-profile.json").read_text(encoding="utf-8"))
    data["axes_verified"]=axes
    return Profile(data)

class MappingTests(unittest.TestCase):
    def test_slider_formula(self):
        self.assertEqual(profile().positions([1500]*6),[[1,1500],[2,1470],[3,1500],[4,1500],[5,1450],[6,1500]])
    def test_unverified_axes_block_servo(self):
        with self.assertRaises(CommandError):profile(False).positions([1500]*6)
    def test_safe_calibrated_endpoints(self):
        self.assertEqual([p[1] for p in profile().positions([2200,2000,2000,2000,2000,2500])],[800,970,1000,1000,950,500])
        self.assertEqual([p[1] for p in profile().positions([800,800,800,800,800,500])],[2200,2170,2200,2200,2150,2500])
    def test_unsafe_command_sends_nothing(self):
        board=Mock();backend=HardwareBackend(profile(),board,verify=False)
        for value in ([2500]*6,[1500,2471,1500,1500,1500,1500],[1500,1500,1500,1500,2451,1500]):
            with self.subTest(value=value),self.assertRaises(CommandError):backend.set_pulses(value,100)
        board.pwm_servo_set_position.assert_not_called()
    def test_invalid_types(self):
        for value in (True,1500.0,"1500",499,2501):
            with self.subTest(value=value),self.assertRaises(CommandError):profile().positions([value]*6)
    def test_profile_rejects_bad_ids_offsets_envelope(self):
        for key,value in (("version",True),("servo_ids",[1]*6),("servo_ids",[True,2,3,4,5,6]),("deviations",[0]*5),("deviations",[101]*6),("raw_min",450),("axes_verified","yes")):
            data=dict(profile().data);data[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):Profile(data)
    def test_offset_follows_physical_id_after_remap(self):
        data=dict(profile().data);data["servo_ids"]=[5,4,3,2,1,6]
        self.assertEqual(Profile(data).positions([1500]*6),[[5,1450],[4,1500],[3,1500],[2,1470],[1,1500],[6,1500]])
    def test_led_both_ids_one_call(self):
        board=Mock();backend=HardwareBackend(profile(),board,verify=False)
        backend.set_led([True,False,True])
        board.set_rgb.assert_called_once_with([[1,255,0,255],[2,255,0,255]])
    def test_frequency_capability_error(self):
        board=Mock();backend=HardwareBackend(profile(),board,verify=False)
        with self.assertRaises(CommandError) as ctx:backend.set_buzzer(10001,100)
        self.assertEqual(ctx.exception.code,"UNSUPPORTED_FREQUENCY");board.set_buzzer.assert_not_called()
    def test_buzzer_once_with_silent_tail(self):
        board=Mock();backend=HardwareBackend(profile(),board,verify=False)
        backend.set_buzzer(1000,1001)
        frequency,seconds,gap,repeat=board.set_buzzer.call_args.args
        self.assertEqual((frequency,int(seconds*1000),gap,repeat),(1000,1001,0.1,1))
    def test_buzzer_explicit_off_packet(self):
        board=Mock();backend=HardwareBackend(profile(),board,verify=False)
        backend.finish_buzzer(1900)
        board.set_buzzer.assert_called_once_with(1900,0.0,0.0,1)
    def test_short_write_detected(self):
        port=Mock();port.write.return_value=1
        with self.assertRaises(OSError):CheckedPort(port).write([1,2])
    def test_file_change_blocks_output(self):
        p=profile();board=Mock();p.verify_files=Mock(side_effect=RuntimeError("changed"))
        with self.assertRaises(RuntimeError):HardwareBackend(p,board).set_led([True]*3)
        board.set_rgb.assert_not_called()

class VendorPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(os.environ.get("UHAND_SDK_TEST_PATH",profile().data["sdk_path"]))
        if not path.exists():raise unittest.SkipTest("Supply the read-only vendor SDK snapshot with UHAND_SDK_TEST_PATH")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=profile().data["sdk_sha256"]:raise RuntimeError("Unexpected SDK revision")
        previous=sys.modules.get("serial");sys.modules["serial"]=types.ModuleType("serial")
        try:
            spec=importlib.util.spec_from_file_location("vendor_packet_test",path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        finally:
            if previous is None:sys.modules.pop("serial",None)
            else:sys.modules["serial"]=previous
        cls.module=module
    def setUp(self):
        self.packet=None
        test=self
        class Capture:
            def write(self,data):test.packet=bytes(data);return len(data)
        self.board=self.module.Board.__new__(self.module.Board);self.board.port=Capture()
    def test_all_19901_times_in_actual_sdk_packets(self):
        for ms in range(100,20001):
            sec=seconds_exact(ms)
            self.board.pwm_servo_set_position(sec,[[1,1500]])
            self.assertEqual(struct.unpack_from("<H",self.packet,5)[0],ms)
            self.board.set_buzzer(1000,sec,0.1,1)
            self.assertEqual(struct.unpack_from("<H",self.packet,6)[0],ms)
    def test_every_positive_frequency_reaches_sdk_packet_unchanged(self):
        backend = HardwareBackend(profile(), self.board, verify=False)
        for frequency in range(1, 10001):
            backend.set_buzzer(frequency, 100)
            self.assertEqual(struct.unpack_from("<H", self.packet, 4)[0], frequency)

    def test_actual_servo_packet_mapping_and_crc(self):
        HardwareBackend(profile(),self.board,verify=False).set_pulses([1500]*6,1001)
        self.assertEqual(self.packet[:4],bytes([0xAA,0x55,4,22]))
        self.assertEqual(self.packet[4:8],bytes([1,233,3,6]))
        pairs=[struct.unpack_from("<BH",self.packet,8+i*3) for i in range(6)]
        self.assertEqual(pairs,[(1,1500),(2,1470),(3,1500),(4,1500),(5,1450),(6,1500)])
        crc=0
        for b in self.packet[2:-1]:
            crc^=b
            for _ in range(8):crc=(crc>>1)^0x8c if crc&1 else crc>>1
        self.assertEqual(self.packet[-1],crc)
    def test_actual_led_ids_and_values(self):
        HardwareBackend(profile(),self.board,verify=False).set_led([True,False,True])
        self.assertEqual(self.packet[2],11)
        self.assertEqual(self.packet[4:-1],bytes([1,2,0,255,0,255,1,255,0,255]))
        HardwareBackend(profile(),self.board,verify=False).set_led([128,64,1])
        self.assertEqual(self.packet[4:-1], bytes([1,2,0,128,64,1,1,128,64,1]))
