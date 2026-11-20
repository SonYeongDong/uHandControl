"""Regression contract: wrist rotates only around world +Z (vertical yaw)."""
import unittest
import numpy as np
from uhand_virtual_server.model import hand_mesh


class WristYawTests(unittest.TestCase):
    def test_yaw_keeps_height_for_every_vertex(self):
        for fingers in ([800]*5, [2000]*5, [800,1200,1800,900,2000]):
            neutral, _, _ = hand_mesh([*fingers,1500])
            for pulse in (500,950,1500,2050,2500):
                with self.subTest(fingers=fingers, wrist=pulse):
                    vertices, _, _ = hand_mesh([*fingers,pulse])
                    np.testing.assert_allclose(vertices[:,2],neutral[:,2],atol=1e-6)

    def test_endpoints_turn_in_horizontal_plane(self):
        neutral, _, _ = hand_mesh([800]*5+[1500])
        # First three boxes are the fixed pedestal/coupling (24 vertices).
        moving=neutral[24:]
        for pulse, sign in ((2500,-1),(500,1)):
            with self.subTest(wrist=pulse):
                vertices, _, _ = hand_mesh([800]*5+[pulse])
                np.testing.assert_allclose(vertices[24:,0],-sign*moving[:,1],atol=1e-6)
                np.testing.assert_allclose(vertices[24:,1],sign*moving[:,0],atol=1e-6)
                np.testing.assert_allclose(vertices[24:,2],moving[:,2],atol=1e-6)

    def test_fixed_base_and_rigid_finger_pose(self):
        fingers=[800,1300,2000,1700,800]
        neutral, faces, colors=hand_mesh(fingers+[1500])
        distances=np.linalg.norm(neutral[24:]-neutral[24],axis=1)
        for pulse in (500,950,2050,2500):
            with self.subTest(wrist=pulse):
                vertices, actual_faces, actual_colors=hand_mesh(fingers+[pulse])
                np.testing.assert_array_equal(vertices[:24],neutral[:24])
                np.testing.assert_array_equal(actual_faces,faces)
                np.testing.assert_array_equal(actual_colors,colors)
                np.testing.assert_allclose(np.linalg.norm(vertices[24:]-vertices[24],axis=1),
                                           distances,atol=1e-6)


if __name__=="__main__":
    unittest.main()
