"""Procedural six-channel visual model. Kinematic illustration, not a measured CAD model."""
import math
import numpy as np

# One scalar per finger drives the linked knuckles; no independent phalanx controls.
FACES = np.array([
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
    [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5],
], dtype=np.uint32)
UNIT_BOX = np.array([
    [-1,-1,-1], [1,-1,-1], [1,1,-1], [-1,1,-1],
    [-1,-1,1], [1,-1,1], [1,1,1], [-1,1,1],
], dtype=float) / 2


def rotation_y(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c,0,s],[0,1,0],[-s,0,c]])


def rotation_z(angle):
    """Yaw about the world vertical axis; positive angles follow the right-hand rule."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c,-s,0],[s,c,0],[0,0,1]])


def rotation_x(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]])


# Model units are proportional, not measured centimetres.
PALM_FRONT_Y = -0.18
OPEN_EXTENSION_DEG = 5.0
FINGER_ANCHORS = ((-0.62,0,0.45),(-0.48,0,1.30),(-0.16,0,1.35),(0.18,0,1.30),(0.50,0,1.18))
FINGER_LENGTHS = ((0.38,0.31,0.25),(0.48,0.36,0.28),(0.54,0.40,0.30),(0.49,0.37,0.28),(0.39,0.31,0.24))
THUMB_CLEARANCE = FINGER_LENGTHS[0][-1]
# Per-joint increments. Four terminal link faces meet the palm at full closure.
# Thumb terminal link keeps a gap equal to its last kinematic segment (0.25).
CLOSED_JOINTS_DEG = (
    (75.0,65.0,50.64573442167563),
    (102.0, 82.3029537520772, 85.6970462479228),
    (100.0,89.97628037214804,80.02371962785196),
    (100.0,86.2149594273522,83.7850405726478),
    (100.0,76.59259383616305,93.40740616383695),
)

def finger_frames(index,flex):
    """Local knuckle positions/orientations/lengths before the common wrist YAW."""
    spread=rotation_y(math.radians(-57 if index==0 else (index-2.5)*3))
    point=np.array(FINGER_ANCHORS[index],dtype=float)
    total=math.radians(-OPEN_EXTENSION_DEG*(1-flex))
    frames=[]
    for length,angle in zip(FINGER_LENGTHS[index],CLOSED_JOINTS_DEG[index]):
        total+=math.radians(flex*angle)
        orientation=spread @ rotation_x(total)
        frames.append((point.copy(),orientation,length))
        point+=orientation @ np.array([0,0,length])
    return tuple(frames)

def hand_mesh_parts(pulses):
    """Returns vertices/faces/colors. Each finger and wrist has exactly one input."""
    vertices, faces, colors, parts = [], [], [], []
    current_part = 5
    # World coordinates: X lateral, Y depth, Z up. Wrist has YAW only.
    wrist = rotation_z(math.radians((1500 - pulses[5]) * 0.09))
    silver = (0.68, 0.73, 0.82, 1)
    dark = (0.15, 0.20, 0.29, 1)
    blue = (0.16, 0.35, 0.91, 1)

    def box(center, size, color, rotation=None, moving=True):
        matrix = np.eye(3) if rotation is None else rotation
        points = (UNIT_BOX * size) @ matrix.T + center
        if moving:
            points = points @ wrist.T + (0, 0, 0.35)
        offset = len(vertices)
        vertices.extend(points)
        faces.extend(FACES + offset)
        colors.extend([color] * len(FACES))
        parts.extend([current_part if moving else -1] * len(FACES))

    # Stationary base and wrist coupling.
    box((0,0,-0.55), (1.5,1.0,0.15), dark, moving=False)
    box((0,0,-0.28), (0.48,0.52,0.48), silver, moving=False)
    box((0,0,0.12), (0.46,0.38,0.25), blue, moving=False)
    # Front plate and rear body.
    box((0,0,0.66), (1.35,0.22,1.25), dark)
    box((0,-0.14,0.66), (1.25,0.08,1.13), silver)
    for x in (-0.48,0.48):
        for z in (0.25,1.03):
            box((x,-0.20,z), (0.10,0.06,0.10), dark)

    # F1 thumb; F2..F5 index through little finger, physically observed 2026-11-17.
    for index in range(5):
        current_part = index
        # Thumb closes as input increases; the other fingers open.
        flex = (pulses[index] - 800) / 1400 if index == 0 else (2000 - pulses[index]) / 1200
        for part,(point,orientation,length) in enumerate(finger_frames(index,flex)):
            direction = orientation @ np.array([0,0,1])
            box(point, (0.23,0.24,0.14), blue if part == 0 else dark, orientation)
            center = point + direction * (length/2)
            box(center, (0.20,0.19,length-0.035), silver, orientation)
            # Dark front inset makes the mechanical links legible.
            inset = center + orientation @ np.array([0,-0.106,0])
            box(inset, (0.11,0.035,length*0.6), dark, orientation)
    return np.asarray(vertices, np.float32), np.asarray(faces, np.uint32), np.asarray(colors, np.float32), np.asarray(parts, np.int8)


def hand_mesh(pulses):
    return hand_mesh_parts(pulses)[:3]
