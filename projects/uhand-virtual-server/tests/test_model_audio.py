import io
import unittest
import wave

import numpy as np
from uhand_virtual_server.audio import make_tone
from uhand_virtual_server.model import hand_mesh
from uhand_virtual_server.protocol import CommandError


class ModelAudioTests(unittest.TestCase):
    def test_geometry_finite_and_faces_valid_for_extremes(self):
        for pulses in ([800,800,800,800,800,500],[1500]*6,[2200,2000,2000,2000,2000,2500]):
            vertices,faces,colors=hand_mesh(pulses)
            self.assertTrue(np.isfinite(vertices).all())
            self.assertTrue((faces>=0).all())
            self.assertLess(faces.max(),len(vertices))
            self.assertEqual(len(colors),len(faces))

    def test_each_axis_changes_geometry(self):
        original,_,_=hand_mesh([1500]*6)
        for axis in range(6):
            values=[1500]*6
            values[axis]=2000
            changed,_,_=hand_mesh(values)
            self.assertFalse(np.allclose(original,changed))

    def test_pcm_frequency_duration_and_channels(self):
        for frequency,duration in ((1000,100),(1900,500),(1000,20000)):
            with wave.open(io.BytesIO(make_tone(frequency,duration)),"rb") as wav:
                self.assertEqual(wav.getframerate(),48000)
                self.assertEqual(wav.getnchannels(),1)
                self.assertEqual(wav.getsampwidth(),2)
                self.assertEqual(wav.getnframes(),48000*duration//1000)
                data=np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2")
            spectrum=np.abs(np.fft.rfft(data))
            peak=np.argmax(spectrum)*48000/len(data)
            self.assertAlmostEqual(peak,frequency,delta=10)
            self.assertEqual(data[0],0)
            self.assertEqual(data[-1],0)

    def test_audio_cannot_alias_unsupported_frequency(self):
        for frequency in (10001,24000,65535):
            with self.assertRaises(CommandError) as error:
                make_tone(frequency,100)
            self.assertEqual(error.exception.code,"UNSUPPORTED_FREQUENCY")

class PhysicalFingerDirectionTests(unittest.TestCase):
    def test_observed_finger_directions(self):
        from uhand_model import hand_mesh_parts
        # Height of each fingertip decreases as that finger closes.
        for axis in range(5):
            low=[1500]*6;high=[1500]*6;low[axis]=1000;high[axis]=2000
            lv,lf,_,lp=hand_mesh_parts(low);hv,hf,_,hp=hand_mesh_parts(high)
            indices=np.unique(lf[lp==axis].ravel())
            low_height=lv[indices,2].max();high_height=hv[indices,2].max()
            if axis==0:self.assertLess(high_height,low_height)
            else:self.assertGreater(high_height,low_height)
