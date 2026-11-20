"""Measure fingertip/palm clearance and audit non-root links against palm solids."""
from pathlib import Path
import sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from uhand_model import hand_mesh_parts,PALM_FRONT_Y,THUMB_CLEARANCE

def overlap(a,b,tolerance=1e-7):
    aa=np.array([a[1]-a[0],a[3]-a[0],a[4]-a[0]])
    bb=np.array([b[1]-b[0],b[3]-b[0],b[4]-b[0]])
    aa/=np.linalg.norm(aa,axis=1)[:,None];bb/=np.linalg.norm(bb,axis=1)[:,None]
    axes=[*aa,*bb,*[np.cross(x,y) for x in aa for y in bb]]
    depth=float("inf")
    for axis in axes:
        norm=np.linalg.norm(axis)
        if norm<1e-8:continue
        axis=axis/norm;pa=a@axis;pb=b@axis
        gap=min(pa.max(),pb.max())-max(pa.min(),pb.min())
        if gap<=tolerance:return False
        depth=min(depth,gap)
    return depth

def audit():
    collisions=[];max_step=0.;previous=None
    for step in range(201):
        flex=step/200
        v,faces,colors,parts=hand_mesh_parts([800+1400*flex,*([2000-1200*flex]*4),1500])
        if previous is not None:max_step=max(max_step,float(np.max(np.linalg.norm(v-previous,axis=1))))
        previous=v
        boxes=v.reshape(-1,8,3)
        for finger in range(5):
            # Root mount + first segment meet the palm at their attachment.
            for link in range(3,9):
                for body in range(3,9):
                    penetration=overlap(boxes[9+finger*9+link],boxes[body])
                    if penetration:collisions.append((step,finger,link,body,float(penetration)))
    v,*_=hand_mesh_parts((2200,800,800,800,800,1500))
    boxes=v.reshape(-1,8,3)
    gaps=[float(PALM_FRONT_Y-boxes[9+i*9+7,:,1].max()) for i in range(5)]
    result={"closed_terminal_gaps":gaps,"thumb_target":THUMB_CLEARANCE,"collisions":collisions,"max_vertex_step":max_step}
    out=ROOT/"reports";out.mkdir(exist_ok=True)
    (out/"geometry-audit.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({**result,"collisions":collisions[:12],"collision_count":len(collisions)}))
if __name__=="__main__":audit()
