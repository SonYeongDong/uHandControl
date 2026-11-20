import json
import unittest
from unittest.mock import Mock
import uhand_client_module as hand
from uhand_motion_creator.motion import LED, call_code
from uhand_motion_creator.sequence_file import SequenceFile, encode, decode
from uhand_server.backend import HardwareBackend
from uhand_server.server import PhysicalServer
from uhand_virtual_server.server import VirtualServer
from uhand_server_lifecycle import led_output


class RgbTests(unittest.TestCase):
    def test_v1_to_v2_and_export(self):
        card = LED(255,128,1,brightness=50)
        self.assertEqual(card.output_rgb, (128,64,1))
        self.assertEqual(call_code(card), "hand.SetuHandLED(255, 128, 1, 50)")
        data = encode(SequenceFile((card,)))
        self.assertEqual(decode(data).cards, (card,))
        old = json.loads(data)
        old["schema_version"] = 1
        old["cards"][0].update(red=True,green=False,blue=True)
        del old["cards"][0]["brightness"]
        restored = decode(json.dumps(old).encode())
        self.assertEqual(restored.cards[0], LED(255,0,255,brightness=100))
        self.assertEqual(decode(encode(restored)).cards, restored.cards)

    def test_physical_and_virtual(self):
        board = Mock()
        backend = HardwareBackend(Mock(),board,verify=False)
        self.exercise(PhysicalServer(backend,port=0),board)
        self.exercise(VirtualServer(port=0),None)

    def exercise(self,server,board):
        server.start()
        try:
            hand.Connect("127.0.0.1",server.port)
            for rgb,brightness,output in (
                ((255,128,1),50,[128,64,1]), ((1,0,255),100,[1,0,255]),
                ((255,128,0),0,[0,0,0]), ((255,128,0),100,[255,128,0])):
                hand.SetuHandLED(*rgb,brightness)
                state = hand.GetStatus()
                self.assertEqual((state["LED"],state["LEDBrightness"]), (list(rgb),brightness))
                self.assertEqual(led_output(state["LED"],brightness),output)
                if board is not None:
                    board.set_rgb.assert_called_with([[1,*output],[2,*output]])
            hand.SetuHandLED(RedEnable=True,GreenEnable=False,BlueEnable=True)
            self.assertEqual(hand.GetStatus()["LED"],[255,0,255])
            before = hand.GetStatus()
            for args in ((-1,0,0,100),(256,0,0,100),(0,0,0,101),(0,0,0,True)):
                with self.assertRaises(hand.InputValidationError): hand.SetuHandLED(*args)
            with self.assertRaises(hand.RemoteError):
                hand._client.request("SetuHandLED",dict(Red=256,Green=0,Blue=0,Brightness=100))
            self.assertEqual(hand.GetStatus(),before)
            legacy = hand._client.request("GetStatus",{})
            self.assertNotIn("LEDBrightness",legacy)
            self.assertIs(legacy["LED"][0],True)
        finally:
            hand.Disconnect()
            server.shutdown()
