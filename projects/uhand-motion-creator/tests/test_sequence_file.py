"""Real file round trips, strict parsing and failed-write preservation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uhand_motion_creator.motion import Motion, Buzzer, LED
from uhand_motion_creator.sequence_file import (SequenceFile, encode, decode, read_file,
    write_file, MAX_BYTES, MAX_CARDS, derive_serials)
from uhand_motion_creator.document import DocumentState

ROOT = Path(__file__).resolve().parents[1]
class SequenceFileTests(unittest.TestCase):
    def setUp(self):
        out = ROOT / "reports/file-0.7.0"
        out.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=out)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "한글 공백 동작.uhand.json"
        self.cards = (Motion((800,2000,800,2000,800,2500),100,"동작 09"),
                      Buzzer(0,20000,"무음",True),Buzzer(10000,100,"고음",False),
                      LED(True,False,True,"빛"))
        self.doc = SequenceFile(self.cards,(10,5,6),{"vendor":{"text":"한글", "items":[1,None,True]}})

    def test_actual_roundtrip_all_fields_unicode_extensions(self):
        write_file(self.path,self.doc)
        self.assertEqual(read_file(self.path),self.doc)
        data=self.path.read_bytes()
        self.assertTrue(data.endswith(b"\n"))
        self.assertIn("한글",data.decode())
        self.assertNotIn(b"\\u",data)
        self.assertEqual(data,encode(read_file(self.path)))

    def test_empty_document_and_replacement(self):
        write_file(self.path,self.doc)
        write_file(self.path,SequenceFile())
        self.assertEqual(read_file(self.path).cards,())
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])

    def test_atomic_replace_failure_preserves_previous_file(self):
        write_file(self.path,self.doc)
        before=self.path.read_bytes()
        with patch("uhand_motion_creator.sequence_file.os.replace",side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):write_file(self.path,SequenceFile())
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])

    def test_flush_failure_preserves_previous_file(self):
        write_file(self.path,self.doc)
        before=self.path.read_bytes()
        with patch("uhand_motion_creator.sequence_file.os.fsync",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):write_file(self.path,SequenceFile())
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])

    def test_invalid_save_never_touches_target(self):
        write_file(self.path,self.doc)
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):write_file(self.path,SequenceFile((object(),)))
        self.assertEqual(self.path.read_bytes(),before)

    def test_omitted_optional_fields_derive_counters(self):
        value=json.loads(encode(self.doc))
        for field in ("editor","extensions","created_with"):value.pop(field)
        result=decode(json.dumps(value).encode())
        self.assertEqual(result.serials,(10,1,1))
        self.assertEqual(result.extensions,{})
        self.assertEqual(derive_serials((Buzzer(name="부저 19"),LED(name="LED 02"),Motion(name="동작 1 extra"))),(1,20,3))

    def test_different_app_version_allowed(self):
        value=json.loads(encode(self.doc));value["created_with"]["version"]="99.0.0"
        self.assertEqual(decode(json.dumps(value).encode()).cards,self.cards)

    def test_bad_headers_and_counters(self):
        mutations=(("schema_version",True),("schema_version",3),("format","clipboard"),
                   ("units",{"pulse":"degrees"}),("cards",{}),("extensions",[]),
                   ("created_with",{"version":4}),
                   ("editor",{"next_name_serials":{"motion":True,"buzzer":1,"led":1}}),
                   ("editor",{"next_name_serials":{"motion":0,"buzzer":1,"led":1}}),
                   ("extra","not allowed"))
        for key,bad in mutations:
            value=json.loads(encode(self.doc));value[key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):decode(json.dumps(value).encode())

    def test_bad_card_fields_and_ranges_have_card_number(self):
        for index,key,bad in ((0,"pulses",[799,1500,1500,1500,1500,1500]),
                              (0,"pulses",[True]*6),(0,"running_time",99),(0,"running_time",20001),
                              (0,"name",""),(0,"extra",1),(0,"kind","script"),
                              (1,"frequency",-1),(1,"frequency",10001),(1,"continuous",1),
                              (3,"red",256)):
            value=json.loads(encode(self.doc));value["cards"][index][key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaisesRegex(ValueError,f"카드 {index+1}"):
                decode(json.dumps(value).encode())

    def test_boundaries_and_duplicate_names(self):
        cards=(Motion((2200,800,2000,800,2000,500),20000,"같은 이름"),LED(name="같은 이름"))
        self.assertEqual(decode(encode(SequenceFile(cards))).cards,cards)

    def test_malformed_duplicate_nonfinite_utf8(self):
        for data in (b"",b"\xff",b"null",b"[]",b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}',b'{"a":-Infinity}'):
            with self.subTest(data=data),self.assertRaises(ValueError):decode(data)
        value=encode(self.doc).replace(b'"frequency": 0',b'"frequency": 0, "frequency": 1')
        with self.assertRaises(ValueError):decode(value)

    def test_overflow_number_in_extensions_rejected(self):
        value=encode(self.doc).replace(b'"items": [', b'"overflow": 1e999, "items": [')
        with self.assertRaises(ValueError):decode(value)

    def test_resource_limits(self):
        with self.assertRaises(ValueError):decode(b" "*(MAX_BYTES+1))
        self.path.write_bytes(b" "*(MAX_BYTES+1))
        with self.assertRaises(ValueError):read_file(self.path)
        with self.assertRaises(ValueError):encode(SequenceFile((LED(),)*(MAX_CARDS+1)))
        self.assertEqual(len(decode(encode(SequenceFile((LED(),)*MAX_CARDS))).cards),MAX_CARDS)
        with self.assertRaises(ValueError):decode(b"["*10000+b"]"*10000)
        deep={}
        for _ in range(33):deep={"nested":deep}
        with self.assertRaises(ValueError):encode(SequenceFile(extensions=deep))

    def test_dirty_tracks_cards_extensions_not_counters(self):
        state=DocumentState();self.assertFalse(state.dirty(()))
        state.extensions={"a":[1]};state.mark_saved(self.path,self.cards)
        self.assertFalse(state.dirty(self.cards))
        self.assertTrue(state.dirty(self.cards[:-1]))
        self.assertFalse(state.dirty(self.cards))
        state.extensions["a"].append(2)
        self.assertTrue(state.dirty(self.cards))
