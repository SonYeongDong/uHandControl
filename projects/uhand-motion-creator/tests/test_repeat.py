import unittest
from uhand_motion_creator.motion import Motion,Buzzer,LED
from uhand_motion_creator.playback import MotionPlayback

class RepeatTests(unittest.TestCase):
    def test_default_one_pass_unchanged(self):
        p=MotionPlayback((Motion((1000,)*6,100),),0,(1500,)*6)
        self.assertTrue(p.frame(100).finished)
    def test_wrap_preserves_last_pose_without_initial_jump(self):
        p=MotionPlayback((Motion((1000,)*6,100),Motion((2000,)*6,100)),0,(1500,)*6,repeat=True)
        self.assertEqual(p.frame(200).pulses,(2000,)*6)
        self.assertEqual(p.frame(250).pulses,(1500,)*6)
        self.assertEqual(p.frame(400).pulses,(2000,)*6)
        self.assertFalse(p.frame(100000).finished)
    def test_current_to_end_repeats_same_range(self):
        p=MotionPlayback((Motion((1000,)*6,100),Motion((1000,)*6,100),Motion((2000,)*6,100)),1,(1500,)*6,repeat=True)
        for t in (0,200,400,1000000):self.assertEqual(p.frame(t).index,1)
        self.assertEqual(p.duration,200)
    def test_led_carries_until_next_led_card(self):
        p=MotionPlayback((Motion((1500,)*6,100),LED(True)),0,(1500,)*6,repeat=True)
        self.assertEqual(p.frame(50).led,(False,)*3)
        self.assertEqual(p.frame(100).led,(255,0,0))
    def test_continuous_buzzer_carries_across_boundary(self):
        p=MotionPlayback((Motion((1500,)*6,100),Buzzer(1900,100,continuous=True)),0,(1500,)*6,repeat=True)
        self.assertIsNone(p.frame(50).buzzer)
        f=p.frame(100);self.assertEqual(f.buzzer.frequency,1900);self.assertEqual(f.buzzer_cycle,0)
        f=p.frame(150);self.assertEqual(f.buzzer_cycle,0)
        f=p.frame(200);self.assertEqual(f.buzzer_cycle,1)
    def test_single_finite_buzzer_gets_new_cycle_identity(self):
        p=MotionPlayback((Buzzer(1000,100),),0,(1500,)*6,repeat=True)
        self.assertEqual(p.frame(0).buzzer_cycle,0)
        f=p.frame(100);self.assertEqual((f.index,f.buzzer_cycle,f.buzzer_remaining),(0,1,100))
    def test_zero_hz_finite_delay_can_repeat(self):
        p=MotionPlayback((Buzzer(0,100),),0,(1500,)*6,repeat=True)
        f=p.frame(150);self.assertEqual((f.buzzer.frequency,f.remaining,f.cycle),(0,50,1))
    def test_zero_duration_rejected_for_selected_range(self):
        for cards in ((LED(),),(Buzzer(1000,100,continuous=True),),(LED(),Buzzer(0,100,continuous=True))):
            with self.assertRaisesRegex(ValueError,"즉시 적용"):MotionPlayback(cards,0,(1500,)*6,repeat=True)
        with self.assertRaises(ValueError):MotionPlayback((Motion(),LED()),1,(1500,)*6,repeat=True)
    def test_zero_duration_single_pass_still_allowed(self):
        self.assertTrue(MotionPlayback((LED(True),),0,(1500,)*6).frame(0).finished)
    def test_late_tick_skips_without_accumulated_timing_drift(self):
        p=MotionPlayback((Buzzer(1000,100,continuous=True),Motion((2000,)*6,200),Buzzer(0,100)),0,(1500,)*6,repeat=True)
        f=p.frame(300000250);self.assertEqual(f.cycle,1000000);self.assertEqual((f.index,f.remaining),(2,50))
        self.assertEqual(f.buzzer.frequency,0)
    def test_input_and_snapshot_validation(self):
        cards=[Motion()]
        p=MotionPlayback(cards,0,(1500,)*6,repeat=True);cards.clear()
        self.assertFalse(p.frame(1000).finished)
        for value in (0,1,None,"yes"):
            with self.assertRaises(ValueError):MotionPlayback((Motion(),),0,(1500,)*6,repeat=value)
        for value in (-1,float("nan"),float("inf")):
            with self.assertRaises(ValueError):p.frame(value)
