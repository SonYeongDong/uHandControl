import ast
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch
from uhand_motion_creator.motion import Motion, Sequence, generate_code, call_code

class MotionTests(unittest.TestCase):
    def test_endpoints(self):
        for p,t in (((800,800,800,800,800,500),100),((2200,2000,2000,2000,2000,2500),20000)):
            self.assertEqual(Motion(p,t).pulses,p)
    def test_pulse_type_and_range(self):
        for value in (499,2501,True,500.0,"500",None):
            with self.subTest(value=value),self.assertRaises(ValueError):Motion((value,)*6)
    def test_time_type_and_range(self):
        for value in (99,20001,True,100.0,"100",None):
            with self.subTest(value=value),self.assertRaises(ValueError):Motion(running_time=value)
    def test_pulse_count(self):
        for value in ((),(500,)*5,(500,)*7,None):
            with self.subTest(value=value),self.assertRaises(ValueError):Motion(value)
    def test_invalid_names(self):
        for name in (""," ","x"*61,"hello\nimport os","a\rb","a\tb",None):
            with self.subTest(name=name),self.assertRaises(ValueError):Motion(name=name)
    def test_snapshot_immutable(self):
        values=[1000]*6;m=Motion(values);values[0]=2000
        self.assertEqual(m.pulses,(1000,)*6)
        with self.assertRaises(FrozenInstanceError):m.running_time=100
    def test_code_preserves_values(self):
        m=Motion((800,800,1200,1800,2000,2500),20000)
        self.assertEqual(call_code(m),"hand.SetuHandPulse(800, 800, 1200, 1800, 2000, 2500, 20000)")
    def test_empty_code_rejected(self):
        with self.assertRaises(ValueError):generate_code([])
    def test_bad_endpoint(self):
        for ip,port in (("bad",5000),("127.0.0.1';raise Exception",5000),("127.0.0.1",0),("127.0.0.1",65536),("127.0.0.1",True)):
            with self.subTest(ip=ip,port=port),self.assertRaises(ValueError):generate_code([Motion()],ip,port)
    def test_generated_order_and_cleanup(self):
        items=[Motion((1000,)*6,100,'open "quote"'),Motion((2000,)*6,20000,"닫기")]
        fake=Mock()
        with patch.dict("sys.modules",{"uhand_client_module":fake}):exec(generate_code(items),{})
        self.assertEqual([x[0] for x in fake.method_calls],["Connect","SetuHandPulse","SetuHandPulse","Disconnect"])
        self.assertEqual(fake.SetuHandPulse.call_args_list[1].args,(*items[1].pulses,20000))
    def test_disconnect_after_command_exception(self):
        fake=Mock();fake.SetuHandPulse.side_effect=RuntimeError("failed")
        with patch.dict("sys.modules",{"uhand_client_module":fake}),self.assertRaises(RuntimeError):exec(generate_code([Motion()]),{})
        fake.Disconnect.assert_called_once()
    def test_no_sleep_or_replay(self):
        tree=ast.parse(generate_code([Motion(),Motion()],"::1",65535))
        self.assertFalse(any(isinstance(n,(ast.For,ast.While)) for n in ast.walk(tree)))
        self.assertNotIn("sleep",ast.unparse(tree))

class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.s=Sequence()
        for n in ("a","b","c"):self.s.add(Motion(name=n))
    def test_replace(self):
        self.s.replace(1,Motion((1000,)*6,100,"new"))
        self.assertEqual([m.name for m in self.s.items],["a","new","c"])
    def test_move_both_directions(self):
        self.assertEqual(self.s.move(1,-1),0);self.assertEqual([m.name for m in self.s.items],["b","a","c"])
        self.s.move(0,1);self.assertEqual([m.name for m in self.s.items],["a","b","c"])
    def test_boundaries_no_history(self):
        count=len(self.s.undo_stack);self.assertEqual(self.s.move(0,-1),0);self.assertEqual(self.s.move(2,1),2)
        self.assertEqual(len(self.s.undo_stack),count)
    def test_delete_undo_redo(self):
        self.s.delete(1);self.assertEqual([m.name for m in self.s.items],["a","c"])
        self.s.undo();self.assertEqual([m.name for m in self.s.items],["a","b","c"])
        self.s.redo();self.assertEqual([m.name for m in self.s.items],["a","c"])
    def test_new_edit_clears_redo(self):
        self.s.undo();self.s.add(Motion(name="d"));self.assertFalse(self.s.redo_stack)
    def test_invalid_index_preserves(self):
        before=self.s.items
        for i in (-1,3,True):
            with self.subTest(i=i),self.assertRaises(IndexError):self.s.delete(i)
        self.assertEqual(self.s.items,before)
    def test_history_bound(self):
        for i in range(120):self.s.add(Motion(name=str(i)))
        self.assertEqual(len(self.s.undo_stack),100)
    def test_delete_to_empty(self):
        for _ in range(3):self.s.delete(0)
        self.assertFalse(self.s.items)
        self.s.undo();self.assertEqual(len(self.s.items),1)

class ReorderTests(unittest.TestCase):
    def test_arbitrary_move_keeps_data_and_code_order(self):
        seq=Sequence();motions=[Motion((1000+i*100,)*6,100+i*100,name=n) for i,n in enumerate("abcd")]
        for motion in motions:seq.add(motion)
        count=len(seq.undo_stack)
        seq.move_to(0,3)
        self.assertEqual(seq.items,tuple(motions[1:]+motions[:1]))
        self.assertEqual(len(seq.undo_stack),count+1)
        fake=Mock()
        with patch.dict("sys.modules",{"uhand_client_module":fake}):exec(generate_code(seq.items),{})
        self.assertEqual([c.args for c in fake.SetuHandPulse.call_args_list],[(*m.pulses,m.running_time) for m in seq.items])
        seq.undo();self.assertEqual(seq.items,tuple(motions))
        seq.redo();self.assertEqual(seq.items,tuple(motions[1:]+motions[:1]))
        seq.move_to(3,0);self.assertEqual(seq.items,tuple(motions))
    def test_noop_and_bad_drop_preserve_history(self):
        seq=Sequence();seq.add(Motion(name="a"));seq.add(Motion(name="b"));seq.undo()
        before=(seq.items,list(seq.undo_stack),list(seq.redo_stack))
        seq.move_to(0,0)
        for a,b in ((-1,0),(0,1),(0,True),(True,0)):
            with self.assertRaises(IndexError):seq.move_to(a,b)
        self.assertEqual((seq.items,seq.undo_stack,seq.redo_stack),before)
    def test_identical_cards_are_not_lost(self):
        seq=Sequence();same=Motion(name="same")
        for m in (same,same,Motion(name="last")):seq.add(m)
        seq.move_to(0,2)
        self.assertEqual([m.name for m in seq.items],["same","last","same"])

class GroupMoveTests(unittest.TestCase):
    def make_sequence(self,names="ABCDEFGH"):
        seq=Sequence()
        for i,n in enumerate(names):seq.add(Motion((1000+i*100,)*6,1000+i*100,n))
        return seq

    def test_contiguous_group_to_end_and_start(self):
        seq=self.make_sequence();original=seq.items
        self.assertEqual(seq.move_group((0,1,2),8),(5,6,7))
        self.assertEqual(seq.items,original[3:]+original[:3])
        self.assertEqual(seq.move_group((5,6,7),0),(0,1,2))
        self.assertEqual(seq.items,original)

    def test_selected_order_is_source_order_and_code_matches(self):
        seq=self.make_sequence();original=seq.items
        seq.move_group((4,0,2),8)
        self.assertEqual(seq.items,tuple(original[i] for i in (1,3,5,6,7,0,2,4)))
        fake=Mock()
        with patch.dict("sys.modules",{"uhand_client_module":fake}):exec(generate_code(seq.items),{})
        self.assertEqual([c.args for c in fake.SetuHandPulse.call_args_list],[(*m.pulses,m.running_time) for m in seq.items])

    def test_inside_group_and_select_all_keep_order(self):
        seq=self.make_sequence();before=seq.items
        for slot in (1,2,3,4):
            seq.move_group((1,2,3),slot);self.assertEqual(seq.items,before)
        for slot in range(9):
            seq.move_group(tuple(range(8)),slot);self.assertEqual(seq.items,before)

    def test_invalid_group_or_boundary_preserves_data(self):
        seq=self.make_sequence();before=seq.items
        for indices,slot in (((),0),((0,0),1),((True,),1),((-1,),1),((8,),1),((0,),-1),((0,),9),((0,),True)):
            with self.subTest(indices=indices,slot=slot),self.assertRaises((ValueError,IndexError)):
                seq.move_group(indices,slot)
            self.assertEqual(seq.items,before)

    def test_identical_cards_remain_present(self):
        seq=self.make_sequence("AB");same=seq.items[0]
        seq.add(same);seq.move_group((0,2),3)
        self.assertEqual(seq.items,(Motion((1100,)*6,1100,"B"),same,same))

class GroupDeleteTests(unittest.TestCase):
    def make_sequence(self):
        seq=Sequence()
        for i,n in enumerate("ABCDE"):seq.add(Motion((1000+i*100,)*6,1000+i*100,n))
        return seq

    def test_contiguous_and_nonadjacent_delete(self):
        for rows in ((1,2,3),(4,0,2)):
            seq=self.make_sequence();before=seq.items
            seq.delete_group(rows)
            self.assertEqual(seq.items,tuple(m for i,m in enumerate(before) if i not in rows))
            fake=Mock()
            with patch.dict("sys.modules",{"uhand_client_module":fake}):exec(generate_code(seq.items),{})
            self.assertEqual([c.args for c in fake.SetuHandPulse.call_args_list],[(*m.pulses,m.running_time) for m in seq.items])

    def test_empty_selection_and_delete_all(self):
        seq=self.make_sequence();before=seq.items
        seq.delete_group(());self.assertEqual(seq.items,before)
        seq.delete_group(range(5));self.assertEqual(seq.items,())

    def test_invalid_delete_is_atomic(self):
        for rows in ((0,5),(0,-1),(0,True),(0,0)):
            seq=self.make_sequence();before=seq.items
            with self.subTest(rows=rows),self.assertRaises((IndexError,ValueError)):seq.delete_group(rows)
            self.assertEqual(seq.items,before)

    def test_identical_cards_deleted_by_position(self):
        seq=Sequence();same=Motion()
        for m in (same,same,Motion(name="last")):seq.add(m)
        seq.delete_group((1,))
        self.assertEqual(seq.items,(same,Motion(name="last")))

class InsertTests(unittest.TestCase):
    def test_insert_boundaries_and_middle(self):
        from uhand_motion_creator.motion import Motion,Buzzer,LED
        s=Sequence();a=Motion(name="A");b=Buzzer(name="B");c=LED(name="C")
        s.insert(0,a);s.insert(0,b);s.insert(1,c)
        self.assertEqual(s.items,(b,c,a));s.insert(3,a);self.assertEqual(s.items,(b,c,a,a))
    def test_bad_insert_is_atomic(self):
        s=Sequence();s.add(Motion())
        before=s.items;history=list(s.undo_stack)
        for i in (-1,2,True,1.5):
            with self.assertRaises(IndexError):s.insert(i,Motion())
        with self.assertRaises(ValueError):s.insert(0,object())
        self.assertEqual(s.items,before);self.assertEqual(s.undo_stack,history)
