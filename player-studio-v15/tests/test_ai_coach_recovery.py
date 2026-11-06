import time,unittest
from unittest.mock import patch
import ai_match_manager as policy
from test_ai_match_manager import fixture

class CoachRecoveryTests(unittest.TestCase):
    def formation(self):
        spec,snap=fixture();snap.update(minute=30,period=1,phase='play',score=[0,2],
            safe_to_change=False,native_formation_window=True,safe_to_queue=True,native_pending_count=0)
        manager=policy.Manager(spec);proposal=manager.propose(snap)
        self.assertEqual(proposal['kind'],'formation')
        snap.update(minute=34,sequence=10);self.assertIsNone(manager.propose(snap))
        return manager,snap,proposal

    def test_cancel_ack_finishes_a_formation_without_a_substitution_queue(self):
        manager,snap,old=self.formation();cancel=manager.cancellation()
        self.assertEqual(cancel['generation'],1)
        snap.update(minute=34.1,ack_id=old['id'],ack_status='cancelled')
        manager.observe(snap);self.assertIsNone(manager.state['pending'])
        snap.update(minute=35,sequence=12)
        self.assertIsNotNone(manager.propose(snap))

    def test_missing_cancel_ack_republishes_bounded_and_reconciles_empty_native_queue(self):
        manager,snap,old=self.formation();generations=[manager.cancellation()['generation']]
        for minute in (35,36):
            snap.update(minute=minute,sequence=snap['sequence']+2)
            self.assertIsNone(manager.propose(snap));generations.append(manager.cancellation()['generation'])
        self.assertEqual(generations,[1,2,3])
        snap.update(minute=37,sequence=16)
        manager.observe(snap);self.assertIsNone(manager.state['pending']);self.assertIsNone(manager.cancellation())
        self.assertTrue(any(r['event']=='cancel_reconciled_from_native'for r in manager.state['journal']))
        snap.update(minute=37.5,sequence=18)
        self.assertIsNotNone(manager.propose(snap))

    def test_unknown_native_queue_is_not_cleared_on_a_timeout(self):
        manager,snap,old=self.formation();snap['native_pending_count']=1
        for minute in (35,36,45,60):
            snap.update(minute=minute,sequence=snap['sequence']+2)
            manager.observe(snap)
        self.assertEqual(manager.state['pending']['id'],old['id'])
        self.assertEqual(manager.cancellation()['generation'],3)

    def test_fatigue_substitution_retries_stale_and_temporary_native_busy(self):
        for status,reason in (('stale',0),('rejected',18),('rejected',5)):
            spec,snap=fixture();snap.update(minute=60,period=3,phase='play',score=[0,0],
                safe_to_change=False,native_formation_window=False,safe_to_queue=True)
            snap['stamina']['7']=20;manager=policy.Manager(spec);old=manager.propose(snap)
            self.assertEqual(old['kind'],'substitution')
            snap.update(minute=60.1,sequence=10,ack_id=old['id'],ack_status=status,rejection_reason=reason)
            self.assertIsNone(manager.propose(snap));snap['stamina']['7']=10
            snap.update(minute=61,sequence=12)
            new=manager.propose(snap);self.assertIsNotNone(new);self.assertEqual(new['kind'],'substitution')
            self.assertIn(7,new['outgoing']);self.assertNotEqual(new['id'],old['id'])

    def test_slow_shape_search_cannot_starve_first_same_shape_fatigue_attempt(self):
        spec,snap=fixture();snap.update(minute=60,period=3,score=[0,0],safe_to_queue=True)
        snap['stamina']['7']=20;manager=policy.Manager(spec)
        current=manager.profile(manager.state['profile_id']);manager.candidates=lambda *a:[current]
        calls=[];original=policy.legal_assignment
        def slow(*args,**kwargs):
            calls.append(args[3]);out=original(*args,**kwargs)
            if args[3]==0:time.sleep(.21)
            return out
        with patch.object(policy,'legal_assignment',side_effect=slow):proposal=manager.propose(snap)
        self.assertGreater(calls[0],0);self.assertEqual(proposal['kind'],'substitution')
        self.assertIn(7,proposal['outgoing'])

if __name__=='__main__':unittest.main()
