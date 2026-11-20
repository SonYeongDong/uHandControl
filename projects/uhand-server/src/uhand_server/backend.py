"""Validated hardware mapping and transmit-only use of the unmodified vendor SDK."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from .protocol import CommandError, integer, PULSE_NAMES, PULSE_LIMITS

def seconds_exact(milliseconds):
    integer("RunningTime", milliseconds,100,20000)
    seconds=math.nextafter(milliseconds/1000.0,math.inf)
    if int(seconds*1000)!=milliseconds:
        raise ValueError("Cannot represent exact SDK milliseconds")
    return seconds

class Profile:
    def __init__(self,data):
        version = data.get("version") if isinstance(data, dict) else None
        capability = "max_buzzer_hz" if version == 2 else "allowed_buzzer_hz"
        expected={"version","mapping_reviewed","axes_verified","servo_ids","deviations","raw_min","raw_max",capability,"sdk_path","sdk_sha256","deviation_path","deviation_sha256","serial_device"}
        if type(data) is not dict or set(data)!=expected or type(data["version"]) is not int or version not in (1, 2):
            raise ValueError("Invalid hardware profile schema")
        for key in ("mapping_reviewed","axes_verified"):
            if type(data[key]) is not bool:raise ValueError(key)
        ids=data["servo_ids"];offsets=data["deviations"]
        if type(ids) is not list or len(ids)!=6 or any(type(i) is not int for i in ids) or set(ids)!=set(range(1,7)):
            raise ValueError("servo_ids must be a permutation of 1..6")
        if type(offsets) is not list or len(offsets)!=6 or any(type(i) is not int or not -100<=i<=100 for i in offsets):
            raise ValueError("Six device-ID offsets in -100..100 required")
        # Only the user-approved physical envelope is implemented.
        if type(data["raw_min"]) is not int or type(data["raw_max"]) is not int or (data["raw_min"],data["raw_max"])!=(500,2500):
            raise ValueError("Physical pulse envelope must be 500..2500")
        if version == 2:
            maximum = data[capability]
            if type(maximum) is not int or not 1 <= maximum <= 10000:
                raise ValueError("Invalid maximum buzzer frequency")
            self.buzzer_frequencies = range(1, maximum + 1)
        else:
            frequencies = data[capability]
            if type(frequencies) is not list or not frequencies or any(type(f) is not int or not 1 <= f <= 65535 for f in frequencies):
                raise ValueError("Invalid allowed buzzer frequencies")
            self.buzzer_frequencies = frozenset(f for f in frequencies if f <= 10000)
        for field in ("sdk_path","deviation_path","serial_device"):
            if type(data[field]) is not str or not data[field].startswith("/"):raise ValueError(field)
        for field in ("sdk_sha256","deviation_sha256"):
            if type(data[field]) is not str or len(data[field])!=64 or any(x not in "0123456789abcdef" for x in data[field]):
                raise ValueError(field)
        self.data=json.loads(json.dumps(data))
    @classmethod
    def load(cls,path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))
    def verify_files(self):
        for field in ("sdk","deviation"):
            path=Path(self.data[field+"_path"])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=self.data[field+"_sha256"]:
                raise RuntimeError(f"{field} file changed since review; review the profile again")
    def positions(self,pulses,require_axes=True):
        if not self.data["mapping_reviewed"] or (require_axes and not self.data["axes_verified"]):
            raise CommandError("DEVICE_ERROR","Physical servo mapping has not been verified.")
        if len(pulses)!=6:raise CommandError("INVALID_ARGUMENT","Six pulses required.")
        positions=[]
        for name,limits,servo_id,pulse in zip(PULSE_NAMES,PULSE_LIMITS,self.data["servo_ids"],pulses):
            integer(name,pulse,*limits)
            raw=3000-pulse+self.data["deviations"][servo_id-1]
            if not 500<=raw<=2500:
                raise CommandError("INVALID_ARGUMENT",f"Servo {servo_id}: calibrated output {raw} is outside 500..2500; no output sent.")
            positions.append([servo_id,raw])
        return positions
    def buzzer(self,freq):
        if type(freq) is not int or (freq != 0 and freq not in self.buzzer_frequencies):
            raise CommandError("UNSUPPORTED_FREQUENCY","Frequency is not in the reviewed hardware profile.")

class RecordingBackend:
    """Explicit no-output test double. It never imports serial or the vendor SDK."""
    def __init__(self,profile=None):
        self.profile=profile
        self.commands=[]
        self.closed=False
    def set_pulses(self,pulses,ms):
        raw=self.profile.positions(pulses) if self.profile else list(enumerate(pulses,1))
        self.commands.append(("pulse",ms,raw))
    def set_buzzer(self,freq,ms):
        if self.profile:self.profile.buzzer(freq)
        self.commands.append(("buzzer",ms,freq))
    def start_buzzer(self,freq):
        if self.profile:self.profile.buzzer(freq)
        self.commands.append(("buzzer_continuous",freq))
    def silence_buzzer(self):
        self.finish_buzzer(1000)
    def finish_buzzer(self,freq):
        self.commands.append(("buzzer_off",freq))
    def set_led(self,rgb):
        self.commands.append(("led",list(rgb)))
    def close(self):
        self.closed=True

class CheckedPort:
    """Propagate short writes; the vendor buf_write otherwise ignores the byte count."""
    def __init__(self,port):self.port=port
    def write(self,data):
        payload=bytes(data);count=self.port.write(payload)
        if count!=len(payload):raise OSError(f"Short serial write: {count}/{len(payload)}")
        return count

class HardwareBackend:
    def __init__(self,profile,board,verify=True):
        self.profile=profile;self.board=board;self.verify=verify
    def check(self):
        if self.verify:self.profile.verify_files()
    def set_pulses(self,pulses,ms):
        positions=self.profile.positions(pulses)
        seconds=seconds_exact(ms)
        self.check()
        self.board.pwm_servo_set_position(seconds,positions)
    def set_buzzer(self,freq,ms):
        self.profile.buzzer(freq);seconds=seconds_exact(ms);self.check()
        self.board.set_buzzer(freq,seconds,0.1,1)
    def start_buzzer(self,freq):
        self.profile.buzzer(freq);self.check()
        self.board.set_buzzer(freq,1.0,0.0,0)
    def silence_buzzer(self):
        self.check()
        self.finish_buzzer(1000)
    def finish_buzzer(self,freq):
        # Manufacturer demo stop packet; no public Stop API is introduced.
        self.board.set_buzzer(freq,0.0,0.0,1)
    def set_led(self,rgb):
        colors = [255 * v if type(v) is bool else v for v in rgb]
        if len(colors) != 3:
            raise CommandError("INVALID_ARGUMENT", "Expected three RGB channels.")
        for value in colors:
            integer("RGB", value, 0, 255)
        self.check()
        self.board.set_rgb([[1,*colors],[2,*colors]])
    def close(self):
        self.board.port.port.close()
        if hasattr(self,"process_lock"):self.process_lock.close()

def open_hardware(profile,lock_path="/run/uhand-server.lock"):
    """No initial servo/LED/buzzer command; rejects existing owners before opening UART."""
    if sys.platform!="linux" or os.geteuid()!=0:
        raise RuntimeError("Hardware mode requires sudo on Raspberry Pi OS for complete device-owner inspection.")
    model=Path("/proc/device-tree/model").read_text().rstrip("\x00")
    if "Raspberry Pi" not in model:raise RuntimeError("Hardware mode requires Raspberry Pi.")
    if not profile.data["mapping_reviewed"]:raise RuntimeError("Mapping profile is not reviewed.")
    profile.verify_files()
    import fcntl
    import termios
    lock=open(lock_path,"a+")
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        device=Path(profile.data["serial_device"]).resolve(strict=True)
        owners=[]
        for process in Path("/proc").iterdir():
            if not process.name.isdigit():continue
            try:
                for fd in (process/"fd").iterdir():
                    try:
                        if fd.resolve(strict=True)==device:owners.append(int(process.name));break
                    except (FileNotFoundError,OSError):pass
            except FileNotFoundError:pass
        if owners:raise RuntimeError(f"Serial device is already open by PIDs {sorted(set(owners))}.")
        import serial
        port=serial.Serial(None,1000000,timeout=.2,write_timeout=1,exclusive=True)
        port.rts=False;port.dtr=False;port.port=str(device);port.open()
        try:
            fcntl.ioctl(port.fileno(),termios.TIOCEXCL)
            spec=importlib.util.spec_from_file_location("uhand_vendor_sdk",profile.data["sdk_path"])
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            # Only the audited output methods are needed. Avoid constructor receive threads.
            board=module.Board.__new__(module.Board);board.port=CheckedPort(port)
            backend=HardwareBackend(profile,board);backend.process_lock=lock
            return backend
        except BaseException:
            port.close();raise
    except BaseException:
        lock.close();raise
