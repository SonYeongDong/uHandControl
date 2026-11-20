import unittest
from uhand_motion_creator.motion import Motion
from uhand_motion_creator.playback import MotionPlayback

class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.motions=(Motion((1000,)*6,100,"A"),Motion((2000,)*6,200,"B"),Motion((1000,)*6,100,"C"))
    def test_interpolation_and_exact_boundaries(self):
        p=MotionPlayback(self.motions,0,(1500,)*6)
        self.assertEqual(p.sample(0),(0,(1500,)*6,False))
        self.assertEqual(p.sample(50),(0,(1250,)*6,False))
        self.assertEqual(p.sample(100),(1,(1000,)*6,False))
        self.assertEqual(p.sample(200),(1,(1500,)*6,False))
        self.assertEqual(p.sample(300),(2,(2000,)*6,False))
        self.assertEqual(p.sample(400),(2,(1000,)*6,True))
    def test_start_at_current_and_late_tick(self):
        p=MotionPlayback(self.motions,1,(1300,)*6)
        self.assertEqual(p.sample(0),(1,(1300,)*6,False))
        self.assertEqual(p.sample(200),(2,(2000,)*6,False))
        self.assertEqual(p.sample(90000),(2,(1000,)*6,True))
    def test_snapshot_and_input_immutability(self):
        source=list(self.motions);p=MotionPlayback(source,0,(1500,)*6);source.clear()
        self.assertEqual(p.motions,self.motions);p.sample(50)
        self.assertEqual(self.motions[0].pulses,(1000,)*6)
    def test_duration_limits(self):
        p=MotionPlayback((Motion((1000,)*6,100),Motion((2000,)*6,20000)),0,(1500,)*6)
        self.assertFalse(p.sample(20099)[2]);self.assertTrue(p.sample(20100)[2])
        self.assertEqual(p.sample(10100)[1],(1500,)*6)
    def test_invalid_timeline_and_time(self):
        for start in (-1,3,True):
            with self.assertRaises(ValueError):MotionPlayback(self.motions,start,(1500,)*6)
        with self.assertRaises(ValueError):MotionPlayback((),0,(1500,)*6)
        with self.assertRaises(ValueError):MotionPlayback(self.motions,0,(400,)*6)
        p=MotionPlayback(self.motions,0,(1500,)*6)
        for time in (-1,float("nan"),float("inf")):
            with self.assertRaises(ValueError):p.sample(time)
