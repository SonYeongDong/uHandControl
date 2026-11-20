import json,unittest
from uhand_motion_creator.card_clipboard import encode_cards,decode_cards,MAX_BYTES
from uhand_motion_creator.motion import Motion,Buzzer,LED,Sequence

class ClipboardTests(unittest.TestCase):
    def setUp(self):self.cards=(Motion((1000,1200,1400,1600,1800,2000),1234,"손동작"),Buzzer(1900,777,"연속음",True),Buzzer(0,100,"무음"),LED(True,False,True,"빛"))
    def test_mixed_roundtrip_preserves_every_field(self):
        result=decode_cards(encode_cards(self.cards))
        self.assertEqual(result,self.cards)
        for a,b in zip(result,self.cards):self.assertIsNot(a,b)
    def test_payload_is_snapshot_of_saved_cards(self):
        payload=encode_cards(self.cards)
        sequence=Sequence();sequence.commit(self.cards);sequence.replace(1,Buzzer(1000))
        self.assertEqual(decode_cards(payload),self.cards)
    def test_empty_invalid_and_oversized_payload(self):
        for data in (b"",b"null",b"[]",b"bad",b"\xff",b"x"*(MAX_BYTES+1)):
            with self.subTest(data=data[:10]),self.assertRaises(ValueError):decode_cards(data)
        for items in ((),(object(),)):
            with self.assertRaises(ValueError):encode_cards(items)
    def test_schema_versions_and_fields_rejected(self):
        value=json.loads(encode_cards(self.cards))
        for key,bad in (("version",True),("version",2),("cards",[]),("cards","text")):
            changed=dict(value);changed[key]=bad
            with self.assertRaises(ValueError):decode_cards(json.dumps(changed).encode())
        value["cards"][0]["unexpected"]=1
        with self.assertRaises(ValueError):decode_cards(json.dumps(value).encode())
    def test_malformed_last_card_rejects_entire_payload(self):
        for field,bad in (("frequency",-1),("frequency",True),("running_time",99),("continuous",1),("name","")):
            value=json.loads(encode_cards(self.cards));value["cards"][1][field]=bad
            with self.subTest(field=field),self.assertRaises(ValueError):decode_cards(json.dumps(value).encode())
    def test_unknown_type_cannot_construct_objects(self):
        with self.assertRaises(ValueError):decode_cards(b'{"version":1,"cards":[{"kind":"__import__","name":"x"}]}')
    def test_group_insert_order_and_independent_instances(self):
        seq=Sequence();seq.commit((LED(name="before"),LED(name="after")))
        positions=seq.insert_many(1,self.cards)
        self.assertEqual(positions,(1,2,3,4));self.assertEqual(seq.items[1:5],self.cards)
        self.assertEqual(seq.items[-1].name,"after")
        for a,b in zip(seq.items[1:5],self.cards):self.assertIsNot(a,b)
    def test_invalid_insert_is_atomic(self):
        seq=Sequence();seq.add(Motion());before=seq.items
        for index,items in ((-1,self.cards),(2,self.cards),(True,self.cards),(0,()),(0,(Motion(),object()))):
            with self.assertRaises((ValueError,IndexError)):seq.insert_many(index,items)
            self.assertEqual(seq.items,before)
    def test_empty_sequence_and_append(self):
        seq=Sequence();seq.insert_many(0,self.cards);seq.insert_many(len(seq.items),self.cards)
        self.assertEqual(seq.items,self.cards+self.cards)
