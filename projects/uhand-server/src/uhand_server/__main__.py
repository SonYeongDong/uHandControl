"""No GUI, auto-start outputs, reconnect, or network reconfiguration."""
import argparse
import json
from pathlib import Path
import signal
import sys
import threading
import time
from . import __version__
from .backend import Profile,RecordingBackend,open_hardware
from .server import PhysicalServer

def main():
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run",action="store_true",help="No SDK import or serial access")
    mode.add_argument("--hardware",action="store_true",help="Physical Pi outputs; requires reviewed profile")
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=5000)
    parser.add_argument("--profile",type=Path)
    parser.add_argument("--ready-file",type=Path)
    args=parser.parse_args()
    if args.hardware and not args.profile:parser.error("--hardware requires --profile")
    stop=threading.Event()
    def log(level,message):
        print(json.dumps({"time":time.time(),"level":level,"message":message},ensure_ascii=False),flush=True)
    def signal_handler(*_):stop.set()
    signal.signal(signal.SIGINT,signal_handler);signal.signal(signal.SIGTERM,signal_handler)
    backend=None;server=None
    try:
        profile=Profile.load(args.profile) if args.profile else None
        backend=open_hardware(profile) if args.hardware else RecordingBackend(profile)
        # The deployed uHandPi uses its dedicated eth0 port. Dry runs need no NIC.
        link_directory = Path("/sys/class/net/eth0") if args.hardware else None
        server = PhysicalServer(backend, args.host, args.port, logger=log, link_directory=link_directory)
        server.start()
        if args.ready_file:
            args.ready_file.write_text(json.dumps({"pid":__import__("os").getpid(),"version":__version__,"host":server.host,"port":server.port,"hardware":args.hardware}),encoding="utf-8")
        log("info","Hardware outputs enabled" if args.hardware else "DRY RUN: physical outputs disabled")
        stop.wait()
    finally:
        if server:server.shutdown()
        elif backend:backend.close()
    return 0
if __name__=="__main__":
    sys.exit(main())
