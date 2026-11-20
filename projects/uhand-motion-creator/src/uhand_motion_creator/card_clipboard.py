"""Validated JSON card clipboard; no executable object deserialization."""
import json
from .card_serialization import card_to_dict, card_from_dict
MIME_TYPE="application/x-uhand-motion-cards+json"
MAX_BYTES=1024*1024

def encode_cards(items):
    cards=[card_to_dict(item) for item in items]
    if not cards:raise ValueError("복사할 카드를 선택하세요.")
    data=json.dumps(dict(version=1,cards=cards),ensure_ascii=False,allow_nan=False,separators=(",",":")).encode("utf-8")
    if len(data)>MAX_BYTES:raise ValueError("한 번에 복사할 카드 데이터는 1MB 이하여야 합니다.")
    return data

def decode_cards(data):
    if not isinstance(data,bytes) or len(data)>MAX_BYTES:raise ValueError("잘못되었거나 너무 큰 카드 데이터입니다.")
    try:
        value=json.loads(data.decode("utf-8"))
        if type(value) is not dict or set(value)!={"version","cards"} or type(value["version"]) is not int or value["version"]!=1:
            raise ValueError("지원하지 않는 카드 형식입니다.")
        if type(value["cards"]) is not list or not value["cards"]:raise ValueError("비어 있는 카드 데이터입니다.")
        return tuple(card_from_dict(card) for card in value["cards"])
    except (ValueError,TypeError,UnicodeError,RecursionError) as exc:
        raise ValueError("붙여넣을 카드 데이터가 올바르지 않습니다.") from exc
