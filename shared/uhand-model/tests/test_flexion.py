"""Geometry contracts for closure contact, thumb gap and five-degree extension."""
from pathlib import Path
import sys,unittest,io,math
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
if "--installed" not in sys.argv:sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"tools"))
from uhand_model import hand_mesh_parts,finger_frames,rotation_x,rotation_y,FINGER_ANCHORS,FINGER_LENGTHS
from audit_geometry import overlap
OPEN=(800,2000,2000,2000,2000,1500)
CLOSED=(2200,800,800,800,800,1500)

class FlexionTests(unittest.TestCase):
    def test_new_range_preserves_old_full_geometry_and_yaw(self):
        fixture=np.load(ROOT/"tests/fixtures/range-map-0.1.2.npz")
        for pose,expected in zip(fixture["new_pulses"],fixture["vertices"]):
            actual,*_=hand_mesh_parts(pose)
            np.testing.assert_array_equal(actual,expected)
    def test_four_terminal_surfaces_contact_palm(self):
        v,*_=hand_mesh_parts(CLOSED);boxes=v.reshape(-1,8,3)
        for i in range(1,5):
            tip=boxes[9+i*9+7];surface=tip[np.isclose(tip[:,1],tip[:,1].max(),atol=1e-7)]
            self.assertAlmostEqual(float(tip[:,1].max()),-.18,places=6)
            self.assertTrue(np.all(abs(surface[:,0])<=.625))
            self.assertTrue(np.all((surface[:,2]>=.095+.35)&(surface[:,2]<=1.225+.35)))
    def test_thumb_gap_is_one_original_terminal_segment(self):
        v,*_=hand_mesh_parts(CLOSED)
        thumb=v.reshape(-1,8,3)[9+7]
        self.assertAlmostEqual(-.18-float(thumb[:,1].max()),.25,places=6)
        self.assertEqual(FINGER_LENGTHS[0][-1],.25)
    def test_open_geometry_is_exactly_five_degrees_back_from_reference(self):
        old=np.load(ROOT/"tests/fixtures/open-0.1.1.npz")
        v,f,c,parts=hand_mesh_parts(OPEN);expected=old["vertices"].astype(float).copy()
        for i,anchor in enumerate(FINGER_ANCHORS):
            indices=np.unique(f[parts==i])
            spread=rotation_y(math.radians(-57 if i==0 else (i-2.5)*3))
            delta=spread@rotation_x(math.radians(-5))@spread.T
            center=np.array(anchor)+(0,0,.35)
            expected[indices]=(expected[indices]-center)@delta.T+center
        np.testing.assert_allclose(v,expected,atol=3e-7)
        np.testing.assert_array_equal(f,old["faces"]);np.testing.assert_array_equal(c,old["colors"]);np.testing.assert_array_equal(parts,old["parts"])
    def test_fixed_body_and_anchors_unchanged(self):
        old=np.load(ROOT/"tests/fixtures/open-0.1.1.npz")["vertices"]
        for pose in (OPEN,CLOSED,(1500,)*6):
            v,*_=hand_mesh_parts(pose)
            np.testing.assert_array_equal(v[:72],old[:72])
        for flex in (0,.25,.5,.75,1):
            for i,anchor in enumerate(FINGER_ANCHORS):
                frames=finger_frames(i,flex)
                np.testing.assert_array_equal(frames[0][0],anchor)
                for j in range(2):
                    self.assertAlmostEqual(float(np.linalg.norm(frames[j+1][0]-frames[j][0])),FINGER_LENGTHS[i][j])
    def test_free_links_do_not_penetrate_palm_or_screws_during_motion(self):
        for step in range(201):
            flex=step/200
            v,*_=hand_mesh_parts((800+1400*flex,*([2000-1200*flex]*4),1500))
            boxes=v.reshape(-1,8,3)
            for finger in range(5):
                for link in range(3,9):
                    for body in range(3,9):
                        self.assertFalse(overlap(boxes[9+finger*9+link],boxes[body]),(step,finger,link,body))
    def test_interpolation_is_finite_continuous_and_keeps_topology(self):
        previous=None
        for step in range(201):
            flex=step/200;v,f,c,parts=hand_mesh_parts((800+1400*flex,*([2000-1200*flex]*4),1500))
            self.assertTrue(np.isfinite(v).all());self.assertLess(f.max(),len(v))
            self.assertEqual((len(v),len(f),len(c),len(parts)),(432,648,648,648))
            if previous is not None:self.assertLess(float(np.max(np.linalg.norm(v-previous,axis=1))),.025)
            previous=v
    def test_wrist_remains_rigid_yaw(self):
        neutral,*_=hand_mesh_parts(CLOSED)
        for wrist in (500,950,2050,2500):
            v,*_=hand_mesh_parts((*CLOSED[:5],wrist))
            np.testing.assert_array_equal(v[:24],neutral[:24])
            np.testing.assert_allclose(v[:,2],neutral[:,2],atol=1e-6)
            np.testing.assert_allclose(np.linalg.norm(v[24:]-v[24],axis=1),np.linalg.norm(neutral[24:]-neutral[24],axis=1),atol=1e-6)
    def test_each_finger_pulse_changes_only_its_part(self):
        base,faces,_,parts=hand_mesh_parts((1500,)*6)
        for i in range(5):
            pulses=[1500]*6;pulses[i]=2000;v,*_=hand_mesh_parts(pulses)
            own=np.unique(faces[parts==i]);other=np.setdiff1d(np.arange(len(v)),own)
            np.testing.assert_array_equal(v[other],base[other]);self.assertFalse(np.allclose(v[own],base[own]))

if __name__=="__main__":
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FlexionTests))
    text=stream.getvalue();out=ROOT/"reports";out.mkdir(exist_ok=True)
    (out/("tests-installed.txt" if "--installed" in sys.argv else "tests-source.txt")).write_text(text,encoding="utf-8")
    print(text);sys.exit(not result.wasSuccessful())
