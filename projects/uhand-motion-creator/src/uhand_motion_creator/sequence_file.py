"""Versioned JSON files. No code execution, migration guessing or value clamping."""
from dataclasses import dataclass
from pathlib import Path
import json
import math
import os
import re
import tempfile
from . import __version__
from .motion import MAX_CARDS
from .card_serialization import card_to_dict, card_from_dict

DEFAULT_SUFFIX = ".uhjson"
SUPPORTED_SUFFIXES = (DEFAULT_SUFFIX, ".json")
FORMAT = "uhand-motion-sequence"
MAX_BYTES = 5 * 1024 * 1024
MAX_DEPTH = 32
UNITS = {"pulse": "us", "running_time": "ms", "frequency": "Hz"}
KINDS = ("motion", "buzzer", "led")
PREFIXES = ("동작", "부저", "LED")

@dataclass(frozen=True)
class SequenceFile:
    cards: tuple = ()
    serials: tuple = (1, 1, 1)
    extensions: dict = None

def derive_serials(cards):
    result = [1, 1, 1]
    for card in cards:
        index = KINDS.index(card_to_dict(card)["kind"])
        match = re.fullmatch(re.escape(PREFIXES[index]) + r" ([0-9]+)", card.name)
        if match:
            result[index] = max(result[index], int(match[1]) + 1)
    return tuple(result)

def _depth(value):
    pending = [(value, 1)]
    while pending:
        item, level = pending.pop()
        if level > MAX_DEPTH:
            raise ValueError("JSON 중첩 깊이는 32 이하여야 합니다.")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON 숫자는 유한한 값이어야 합니다.")
        if isinstance(item, dict):
            pending.extend((v, level + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, level + 1) for v in item)

def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("중복 JSON 키: " + key)
        result[key] = value
    return result

def _constant(value):
    raise ValueError("허용되지 않는 JSON 숫자: " + value)

def validate(value):
    _depth(value)
    required = {"format", "schema_version", "units", "cards"}
    optional = {"created_with", "editor", "extensions"}
    if type(value) is not dict or not required <= set(value) or set(value) - required - optional:
        raise ValueError("파일의 필수 항목 또는 최상위 필드가 올바르지 않습니다.")
    if value["format"] != FORMAT or type(value["schema_version"]) is not int or value["schema_version"] not in (1, 2):
        raise ValueError("지원하지 않는 파일 형식 또는 schema_version입니다.")
    if value["units"] != UNITS:
        raise ValueError("units: pulse=us, running_time=ms, frequency=Hz가 필요합니다.")
    raw = value["cards"]
    if type(raw) is not list or len(raw) > MAX_CARDS:
        raise ValueError(f"cards: {MAX_CARDS:,}개 이하의 배열이어야 합니다.")
    cards = []
    for index, card in enumerate(raw):
        try:
            cards.append(card_from_dict(card, value["schema_version"]))
        except ValueError as exc:
            raise ValueError(f"카드 {index + 1}: {exc}") from exc
    if "created_with" in value:
        meta = value["created_with"]
        if type(meta) is not dict or set(meta) != {"application", "version"} or any(type(v) is not str for v in meta.values()):
            raise ValueError("created_with 형식이 올바르지 않습니다.")
    serials = derive_serials(cards)
    if "editor" in value:
        editor = value["editor"]
        if type(editor) is not dict or set(editor) != {"next_name_serials"}:
            raise ValueError("editor 형식이 올바르지 않습니다.")
        counters = editor["next_name_serials"]
        if type(counters) is not dict or set(counters) != set(KINDS) or any(type(v) is not int or v < 1 for v in counters.values()):
            raise ValueError("next_name_serials: 종류별 양의 정수가 필요합니다.")
        serials = tuple(counters[k] for k in KINDS)
    extensions = value.get("extensions", {})
    if type(extensions) is not dict:
        raise ValueError("extensions: 객체여야 합니다.")
    return SequenceFile(tuple(cards), serials, extensions)

def decode(data):
    if type(data) is not bytes or len(data) > MAX_BYTES:
        raise ValueError("파일은 5 MiB 이하여야 합니다.")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        return validate(value)
    except (UnicodeError, RecursionError, TypeError) as exc:
        raise ValueError("올바른 UTF-8 JSON 파일이 아닙니다.") from exc

def encode(document):
    value = dict(format=FORMAT, schema_version=2,
                 created_with=dict(application="uHandMotionCreator", version=__version__),
                 units=UNITS, cards=[card_to_dict(card) for card in document.cards],
                 editor=dict(next_name_serials=dict(zip(KINDS, document.serials))),
                 extensions={} if document.extensions is None else document.extensions)
    try:
        validate(value)
        data = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    except (TypeError, RecursionError) as exc:
        raise ValueError("저장할 JSON 데이터가 올바르지 않습니다.") from exc
    if len(data) > MAX_BYTES:
        raise ValueError("파일은 5 MiB 이하여야 합니다.")
    return data

def sequence_path(path):
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("동작 시퀀스는 .uhjson 또는 .json 확장자만 지원합니다.")
    return path

def read_file(path):
    with sequence_path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    return decode(data)

def write_file(path, document):
    """Replace only after a complete, validated, flushed same-directory write."""
    path = sequence_path(path)
    data = encode(document)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix="." + path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
