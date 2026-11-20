"""Shared strict card schema for files and clipboard."""
from .motion import Motion, Buzzer, LED

SCHEMAS = {
    "motion": ({"pulses", "running_time", "name"}, Motion),
    "buzzer": ({"frequency", "running_time", "name", "continuous"}, Buzzer),
    "led": ({"red", "green", "blue", "name", "brightness"}, LED),
}

def card_to_dict(item):
    if type(item) is Motion:
        return dict(kind="motion", name=item.name, pulses=list(item.pulses), running_time=item.running_time)
    if type(item) is Buzzer:
        return dict(kind="buzzer", name=item.name, frequency=item.frequency,
                    running_time=item.running_time, continuous=item.continuous)
    if type(item) is LED:
        return dict(kind="led", name=item.name, red=item.red, green=item.green, blue=item.blue, brightness=item.brightness)
    raise ValueError("지원하지 않는 카드입니다.")

def card_from_dict(card, schema=None):
    if type(card) is not dict or type(card.get("kind")) is not str or card["kind"] not in SCHEMAS:
        raise ValueError("kind: 지원하지 않는 카드 종류입니다.")
    fields, constructor = SCHEMAS[card["kind"]]
    if constructor is LED:
        legacy = "brightness" not in card
        if (schema == 1 and not legacy) or (schema == 2 and legacy):
            raise ValueError("LED 카드 버전과 밝기 필드를 확인하세요.")
        channel_type = bool if legacy else int
        if any(type(card.get(k)) is not channel_type for k in ("red", "green", "blue")):
            raise ValueError("LED 채널 형식이 올바르지 않습니다.")
        if legacy:
            card = dict(card, brightness=100)
    if set(card) != fields | {"kind"}:
        raise ValueError("카드 필드가 올바르지 않습니다: " + ", ".join(sorted(set(card) ^ (fields | {"kind"}))))
    if constructor is Motion and type(card["pulses"]) is not list:
        raise ValueError("pulses: 배열이어야 합니다.")
    try:
        return constructor(**{key: card[key] for key in fields})
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
