import unittest
from unittest.mock import patch

import numpy as np
import uhand_client_module as hand
from uhand_model import hand_mesh, hand_mesh_parts
from uhand_virtual_server.model import hand_mesh as virtual_mesh
from uhand_virtual_server.server import VirtualServer
from uhand_motion_creator.motion import Motion, Buzzer, LED, generate_code

def run_generated(items, server):
    # Capture the completed state before the real disconnect starts its home sequence.
    status = {}
    disconnect = hand.Disconnect
    def capture():
        try:
            status.update(hand.GetStatus())
        finally:
            disconnect()
    with patch.object(hand, "Disconnect", side_effect=capture):
        exec(generate_code(items, "127.0.0.1", server.port), {})
    return status


class IntegrationTests(unittest.TestCase):
    def test_export_runs_real_client_server(self):
        server=VirtualServer(port=0);server.start()
        items=[Motion((800,800,1200,1800,2000,950),100,"one"),Motion((2200,2000,1900,1800,1700,2050),120,"two")]
        try:
            status = run_generated(items, server)
            self.assertEqual(status["TargetPulses"],list(items[-1].pulses))
            self.assertEqual(status["PulseRunningTime"],120)
            self.assertEqual(status["BuzzerFrequency"], 0)
            self.assertEqual(status["LED"], [0, 0, 0])
        finally:
            hand.Disconnect();server.shutdown()
    def test_shared_geometry_identical(self):
        self.assertIs(hand_mesh,virtual_mesh)
        for wrist in (500,950,1500,2050,2500):
            p=(800,900,1300,1700,2000,wrist)
            for a,b in zip(hand_mesh(p),virtual_mesh(p)):np.testing.assert_array_equal(a,b)
    def test_yaw_and_part_labels(self):
        base=hand_mesh((1500,)*6)[0]
        for wrist in (500,2500):
            v,f,c,parts=hand_mesh_parts((1500,)*5+(wrist,))
            np.testing.assert_allclose(v[:,2],base[:,2],atol=1e-6)
            np.testing.assert_array_equal(v[:24],base[:24])
            self.assertEqual(set(parts),{-1,0,1,2,3,4,5})
            self.assertEqual(len(parts),len(f))


class MixedIntegrationTests(unittest.TestCase):
    def test_mixed_export_through_client_to_virtual_server(self):
        class Audio:
            def __init__(self):self.calls=[]
            def play(self,f,t,cancel):self.calls.append((f,t))
        audio=Audio();server=VirtualServer(port=0,audio=audio);server.start()
        items=(LED(True),Motion((1300,)*6,100),Buzzer(1000,100),LED(False,False,True),Buzzer(1900,120),LED())
        try:
            status = run_generated(items, server)
            self.assertEqual(status["TargetPulses"],[1300]*6)
            self.assertEqual(status["PulseRunningTime"],100)
            self.assertEqual(status["BuzzerFrequency"],1900)
            self.assertEqual(status["BuzzerRunningTime"],120)
            self.assertEqual(status["LED"],[False]*3)
            self.assertEqual([note for note in audio.calls if note[1] != 175], [(1000,100),(1900,120)])
            starts=[msg.split()[0] for n,t,level,msg in server.snapshot()["events"] if msg.endswith(" 시작") and msg.startswith("Set")]
            self.assertEqual(starts,["SetuHandLED","SetuHandPulse","SetuHandBuzzer","SetuHandLED","SetuHandBuzzer","SetuHandLED"])
        finally:
            hand.Disconnect();server.shutdown()
