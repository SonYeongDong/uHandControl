"""Validated, immutable poses and a bounded undoable sequence."""
from dataclasses import dataclass, replace
import ipaddress

MAX_CARDS = 5000

PULSE_LIMITS = ((800, 2200), (800, 2000), (800, 2000), (800, 2000), (800, 2000), (500, 2500))

def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name}: {low}~{high} 정수만 입력하세요.")
    return value

@dataclass(frozen=True)
class Motion:
    pulses: tuple = (1500,)*6
    running_time: int = 1000
    name: str = "동작"
    def __post_init__(self):
        if not isinstance(self.pulses, (tuple, list)) or len(self.pulses) != 6:
            raise ValueError("펄스값은 6개가 필요합니다.")
        object.__setattr__(self, "pulses", tuple(integer(p,*limits,f"Pulse {index+1}") for index,(p,limits) in enumerate(zip(self.pulses,PULSE_LIMITS))))
        integer(self.running_time,100,20000,"RunningTime")
        if not isinstance(self.name,str) or not self.name.strip() or len(self.name)>60 or any(ord(c)<32 for c in self.name):
            raise ValueError("동작 이름은 줄바꿈 없이 1~60자로 입력하세요.")

def valid_name(name):
    if not isinstance(name,str) or not name.strip() or len(name)>60 or any(ord(c)<32 for c in name):
        raise ValueError("동작 이름은 줄바꿈 없이 1~60자로 입력하세요.")

@dataclass(frozen=True)
class Buzzer:
    frequency: int = 1000
    running_time: int = 1000
    name: str = "부저"
    continuous: bool = False
    def __post_init__(self):
        integer(self.frequency,0,10000,"Frequency")
        if type(self.continuous) is not bool:raise ValueError("Continuous는 bool이어야 합니다.")
        integer(self.running_time,100,20000,"RunningTime")
        valid_name(self.name)

@dataclass(frozen=True)
class LED:
    red: int = 0
    green: int = 0
    blue: int = 0
    name: str = "삼색 LED"
    brightness: int = 100
    def __post_init__(self):
        for key in ("red", "green", "blue"):
            v = getattr(self, key)
            object.__setattr__(self, key, integer(255 * v if type(v) is bool else v, 0, 255, key))
        integer(self.brightness, 0, 100, "Brightness")
        valid_name(self.name)
    @property
    def rgb(self):return (self.red,self.green,self.blue)
    @property
    def output_rgb(self):
        return tuple((v * self.brightness + 50) // 100 for v in self.rgb)
    @property
    def running_time(self):return 0

CARD_TYPES=(Motion,Buzzer,LED)

def timeline_duration(item):
    return 0 if isinstance(item,Buzzer) and item.continuous else item.running_time

def kind(item):return CARD_TYPES.index(type(item))
def detail(item):
    if isinstance(item,Motion):return f"{item.running_time} ms"
    if isinstance(item,Buzzer):return ("무음" if item.frequency == 0 else f"{item.frequency} Hz") + (" · 연속" if item.continuous else f" · {item.running_time} ms")
    return f"RGB {item.red}, {item.green}, {item.blue} · {item.brightness}%"

def call_code(motion):
    if isinstance(motion,Buzzer):return f"hand.SetuHandBuzzer({motion.frequency}, {motion.running_time}" + (", True)" if motion.continuous else ")")
    if isinstance(motion,LED):return "hand.SetuHandLED("+", ".join(map(str, (*motion.rgb, motion.brightness)))+")"
    if not isinstance(motion,Motion):raise ValueError("잘못된 동작입니다.")
    return "hand.SetuHandPulse(" + ", ".join(map(str, (*motion.pulses,motion.running_time))) + ")"

def generate_code(motions, ip="127.0.0.1", port=5000):
    motions = tuple(motions)
    if not motions:
        raise ValueError("먼저 동작을 추가하세요.")
    ipaddress.ip_address(ip)
    integer(port,1,65535,"Port")
    lines = ["import uhand_client_module as hand", "", f"hand.Connect({ip!r}, {port})", "try:"]
    for i,motion in enumerate(motions,1):
        if not isinstance(motion,CARD_TYPES):
            raise ValueError("잘못된 동작입니다.")
        lines.extend([f"    # {i:02d}. {motion.name}", "    "+call_code(motion)])
    lines.extend(["finally:", "    hand.Disconnect()", ""])
    return "\n".join(lines)

class Sequence:
    def __init__(self):
        self.items = ()
        self.undo_stack = []
        self.redo_stack = []
    @property
    def remaining_cards(self):
        return MAX_CARDS - len(self.items)

    def require_space(self, count):
        if count > self.remaining_cards:
            raise ValueError(f"남은 카드 {self.remaining_cards:,}장 · {count:,}장을 추가할 공간이 없습니다.")

    def commit(self, items):
        items = tuple(items)
        self.require_space(len(items) - len(self.items))
        if items == self.items:
            return
        self.undo_stack.append(self.items)
        self.undo_stack = self.undo_stack[-100:]
        self.items = items
        self.redo_stack.clear()
    def add(self,motion):
        if not isinstance(motion,CARD_TYPES): raise ValueError("Motion required")
        self.commit((*self.items,motion))
    def insert(self,index,motion):
        if type(index) is not int or not 0<=index<=len(self.items):raise IndexError(index)
        if not isinstance(motion,CARD_TYPES):raise ValueError("Card required")
        self.commit((*self.items[:index],motion,*self.items[index:]))
    def insert_many(self,index,items):
        if type(index) is not int or not 0<=index<=len(self.items):raise IndexError(index)
        items=tuple(items)
        if not items or not all(isinstance(item,CARD_TYPES) for item in items):raise ValueError("Cards required")
        # New immutable instances keep clipboard snapshots independent of later edits.
        copies=tuple(replace(item) for item in items)
        self.commit((*self.items[:index],*copies,*self.items[index:]))
        return tuple(range(index,index+len(copies)))
    def replace(self,index,motion):
        self._index(index)
        if not isinstance(motion,CARD_TYPES): raise ValueError("Motion required")
        items=list(self.items); items[index]=motion; self.commit(items)
    def delete(self,index):
        self._index(index)
        self.commit(self.items[:index]+self.items[index+1:])
    def delete_group(self,indices):
        """Delete selected rows together without changing remaining motions."""
        indices=tuple(indices)
        for index in indices:self._index(index)
        if len(set(indices))!=len(indices):raise ValueError("Duplicate indices")
        selected=set(indices)
        self.commit(m for i,m in enumerate(self.items) if i not in selected)
    def move(self,index,delta):
        self._index(index)
        if delta not in (-1,1): raise ValueError("Direction must be -1 or 1")
        target=index+delta
        if 0<=target<len(self.items):
            items=list(self.items);items[index],items[target]=items[target],items[index];self.commit(items)
            return target
        return index
    def move_to(self,index,target):
        """Move one saved motion to its final row, as one undoable operation."""
        self._index(index);self._index(target)
        if index!=target:
            items=list(self.items);items.insert(target,items.pop(index));self.commit(items)
        return target
    def move_group(self,indices,slot):
        """Insert selected rows at an original-list boundary, keeping their order."""
        indices=tuple(indices)
        if not indices or any(type(i) is not int for i in indices):
            raise IndexError(indices)
        for index in indices:self._index(index)
        if len(set(indices))!=len(indices):raise ValueError("Duplicate indices")
        if type(slot) is not int or not 0<=slot<=len(self.items):raise IndexError(slot)
        indices=tuple(sorted(indices));selected=set(indices)
        remaining=[m for i,m in enumerate(self.items) if i not in selected]
        start=slot-sum(i<slot for i in indices)
        self.commit((*remaining[:start],*(self.items[i] for i in indices),*remaining[start:]))
        return tuple(range(start,start+len(indices)))
    def _index(self,index):
        if type(index) is not int or not 0<=index<len(self.items): raise IndexError(index)
    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.items);self.items=self.undo_stack.pop()
    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.items);self.items=self.redo_stack.pop()
