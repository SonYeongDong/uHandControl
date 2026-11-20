"""Deterministic timeline with instantaneous LED and continuous-buzzer commands."""
from dataclasses import dataclass, replace
import math
from .motion import Motion, Buzzer, LED, CARD_TYPES, integer, timeline_duration

@dataclass(frozen=True)
class Frame:
    index: int
    pulses: tuple
    led: tuple
    finished: bool
    remaining: float
    buzzer_index: object = None
    buzzer: object = None
    buzzer_remaining: float = 0
    cycle: int = 0
    buzzer_cycle: object = None

class MotionPlayback:
    def __init__(self,motions,start_index,initial_pulses,initial_led=(False,False,False),repeat=False):
        self.motions=tuple(motions)
        if not self.motions or not all(isinstance(m,CARD_TYPES) for m in self.motions):
            raise ValueError("A nonempty card sequence is required")
        integer(start_index,0,len(self.motions)-1,"Start index")
        if type(repeat) is not bool:raise ValueError("Repeat must be bool")
        self.repeat=repeat
        self.start_index=start_index
        self.initial=Motion(tuple(initial_pulses)).pulses
        self.initial_led=LED(*initial_led).rgb
        total=0;self.ends=[]
        for item in self.motions[start_index:]:
            total+=timeline_duration(item);self.ends.append(total)
        self.ends=tuple(self.ends)
        self.duration=total
        if repeat and total == 0:
            raise ValueError("반복할 구간에 시간이 있는 손동작 또는 일반 부저 카드를 추가하세요. 즉시 적용 카드만으로는 반복할 수 없습니다.")
        self.terminal=self._frame(total)

    def frame(self,elapsed_ms):
        if not math.isfinite(elapsed_ms) or elapsed_ms<0:raise ValueError("Invalid elapsed time")
        if not self.repeat:return self._frame(elapsed_ms)
        cycle=int(elapsed_ms//self.duration)
        frame=self._frame(elapsed_ms%self.duration,cycle)
        return replace(frame,finished=False,cycle=cycle)

    def _frame(self,elapsed_ms,cycle=0):
        pulses=self.terminal.pulses if cycle else self.initial
        led=self.terminal.led if cycle else self.initial_led
        beginning=0;buzzer=None;buzzer_index=None;buzzer_remaining=0;buzzer_cycle=None
        if cycle and self.terminal.buzzer is not None and self.terminal.buzzer.continuous:
            buzzer=self.terminal.buzzer;buzzer_index=self.terminal.buzzer_index;buzzer_cycle=cycle-1
        for index in range(self.start_index,len(self.motions)):
            item=self.motions[index];duration=timeline_duration(item);end=beginning+duration
            if isinstance(item,Buzzer):
                buzzer_index=index;buzzer_cycle=cycle
                buzzer=item if item.continuous or elapsed_ms<end else None
                buzzer_remaining=0 if item.continuous else max(0,end-elapsed_ms)
            if isinstance(item,LED):
                led=item.output_rgb
            elif elapsed_ms<end:
                if isinstance(item,Motion):
                    amount=(elapsed_ms-beginning)/duration
                    pulses=tuple(a+(b-a)*amount for a,b in zip(pulses,item.pulses))
                return Frame(index,pulses,led,False,end-elapsed_ms,buzzer_index,buzzer,buzzer_remaining,cycle,buzzer_cycle)
            elif isinstance(item,Motion):
                pulses=item.pulses
            beginning=end
        return Frame(len(self.motions)-1,pulses,led,True,0,buzzer_index,buzzer,buzzer_remaining,cycle,buzzer_cycle)

    def sample(self,elapsed_ms):
        frame=self.frame(elapsed_ms)
        return frame.index,frame.pulses,frame.finished
