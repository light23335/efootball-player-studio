import struct
import unittest

from ai_match_channel import encode_command,publish,read_snapshot,checksum,decode_match_clock


# Explicit ABI fixture, independently exercised against the compiled C adapter
# by maintenance probes. These are public data offsets, not engine addresses.
LAYOUT={'command_bytes':440,'placement_bytes':28,'snapshot_bytes':4880,'live_player_bytes':36,
        'configuration_sequence':0,'snapshot':400,'command':5280,'ack_id':5720,'ack_status':5728}
for field,at in {'sequence':0,'checksum':4,'epoch':8,'game_id':16,'plan_id':24,'kind':32,
                 'based_on_snapshot':36,'active_count':40,'score_for':44,'score_against':48,
                 'substitutions_left':52,'windows_left':56,'attack_level':60,'placement_count':64,
                 'sub_count':68,'issued_clock_frames':72,'incoming':76,'outgoing':84,'placement':92,
                 'captain':400,'set_piece':404,'overlap':428}.items():LAYOUT['command.'+field]=at
for field,at in {'sequence':0,'configuration_sequence':4,'epoch':8,'game_id':16,'team':24,'phase':28,
                 'period':32,'stop_reason':36,'clock_frames':40,'score_for':44,'score_against':48,
                 'substitutions_left':52,'windows_left':56,'native_pending':60,'roster_count':64,
                 'native_event':68,'post_event':72,'live':76,'raw_plan':904,
                 'yellow_count':4596,'direct_red':4688,'injury_state':4780,'current_attack_level':4872}.items():LAYOUT['snapshot.'+field]=at


def fixture():
    spec={'game_id':123,'entry_id':'A','profiles':[{'id':'base','attack':[0]+[5]*10,'defence':[0]+[5]*10,
          'attack_coords':[[24,0]]+[[i*4,50]for i in range(10)],
          'defence_coords':[[24,0]]+[[i*4,40]for i in range(10)]}]}
    snapshot={'sequence':4,'game_id':123,'entry_id':'A','clock_frames':216000.,'substitutions_left':5,'windows_left':3}
    proposal={'id':7,'game_id':123,'entry_id':'A','kind':'substitution','active_count':11,'score':[0,1],
              'attack_level':3,'profile_id':'base','mapping':{i:(12 if i==7 else i)for i in range(11)},
              'incoming':[12],'outgoing':[7],'pairs':[(12,7)]}
    return spec,snapshot,proposal


class ChannelTests(unittest.TestCase):
    def test_reduced_placement_is_contiguous_without_filling_departure(self):
        spec,snap,p=fixture();p.update(kind='formation',active_count=10,incoming=[],outgoing=[],pairs=[])
        p['mapping']={i:i for i in range(11)if i!=8}
        raw=encode_command(LAYOUT,spec,snap,p,2,456)
        self.assertEqual(struct.unpack_from('<I',raw,64)[0],10)
        identities=[struct.unpack_from('<I',raw,92+i*28)[0]for i in range(10)]
        self.assertEqual(identities,[i for i in range(11)if i!=8])
        self.assertEqual(struct.unpack_from('<7I',raw,92+8*28),(9,5,5,32,50,32,40))
        p['active_count']=11
        with self.assertRaises(ValueError):encode_command(LAYOUT,spec,snap,p,2,456)

    def test_native_half_clock_is_separate_from_tactical_match_minute(self):
        for period,offset,end in ((1,0,90),(3,45,90),(5,90,120),(7,105,120)):
            for local in (0,2.5,14.9,17.2,44.9,47.5):
                clock=decode_match_clock(period,local*3600)
                self.assertAlmostEqual(clock['stage_minute'],local)
                self.assertAlmostEqual(clock['minute'],offset+local)
                self.assertEqual(clock['period_end'],end)
        self.assertEqual(decode_match_clock(3,2*3600)['minute'],47)
        self.assertEqual(decode_match_clock(7,12*3600)['minute'],117)
        self.assertGreater(decode_match_clock(1,47*3600)['minute'],45)
        for period in (0,2,4,6,8,9,10,True,'3'):
            self.assertIsNone(decode_match_clock(period,100))
        for frames in (-1,float('nan'),float('inf'),True,'100'):
            self.assertIsNone(decode_match_clock(3,frames))

    def test_command_contains_full_identity_context_and_legal_pair_order(self):
        spec,snap,p=fixture();raw=encode_command(LAYOUT,spec,snap,p,2,456)
        self.assertEqual(len(raw),440)
        self.assertEqual(struct.unpack_from('<QQQ',raw,8),(456,123,7))
        self.assertEqual(struct.unpack_from('<II',raw,76),(12,0))
        self.assertEqual(struct.unpack_from('<II',raw,84),(7,0))
        self.assertEqual(struct.unpack_from('<I',raw,4)[0],checksum(raw))

    def test_real_generator_coordinate_records_keep_role_depth_and_lane(self):
        spec,snap,p=fixture();profile=spec['profiles'][0]
        for phase in ('attack','defence'):
            profile[phase+'_coords']=[{'role':role,'position_x':xy[0],'position_y':xy[1]}
                                      for role,xy in zip(profile[phase],profile[phase+'_coords'])]
        raw=encode_command(LAYOUT,spec,snap,p,2,456)
        self.assertEqual(struct.unpack_from('<7I',raw,LAYOUT['command.placement']+7*28),(12,5,5,24,50,24,40))
        profile['defence_coords'][7]['role']=8
        with self.assertRaises(ValueError):encode_command(LAYOUT,spec,snap,p,2,456)

    def test_transport_rejects_old_entry_and_incomplete_or_invalid_placement(self):
        for change in ('entry','missing','duplicate','coordinate','clock','pairs'):
            spec,snap,p=fixture()
            if change=='entry':p['entry_id']='old'
            elif change=='missing':p['mapping'].pop(3)
            elif change=='duplicate':p['mapping'][3]=p['mapping'][4]
            elif change=='coordinate':spec['profiles'][0]['attack_coords'][3][0]=49
            elif change=='clock':snap['clock_frames']=float('nan')
            elif change=='pairs':p['pairs']=[]
            with self.assertRaises(ValueError,msg=change):encode_command(LAYOUT,spec,snap,p,2,456)

    def test_publish_orders_write_in_progress_payload_and_committed_sequence_with_fences(self):
        spec,snap,p=fixture();raw=encode_command(LAYOUT,spec,snap,p,2,456);events=[]
        publish(lambda at,data:events.append((at,data)),5000,raw,lambda:events.append('fence'))
        self.assertEqual(events[0],(5000,struct.pack('<I',3)))
        self.assertEqual(events[1],'fence');self.assertEqual(events[2],(5004,raw[4:]))
        self.assertEqual(events[3],'fence');self.assertEqual(events[4],(5000,raw[:4]))
        self.assertEqual(events[5],'fence')
        broken=bytearray(raw);broken[-1]^=1
        with self.assertRaises(ValueError):publish(lambda *a:None,5000,broken,lambda:None)

    def memory(self):
        memory=bytearray(6000)
        struct.pack_into('<I',memory,0,2)
        def put(name,value,fmt='I'):struct.pack_into('<'+fmt,memory,400+LAYOUT['snapshot.'+name],value)
        for field,value in (('sequence',4),('configuration_sequence',2),('game_id',123),('epoch',456),
                             ('roster_count',23),('phase',1),('team',1),('clock_frames',216000.)):
            put(field,value,'Q'if field in ('epoch','game_id')else'f'if field=='clock_frames'else'I')
        for i in range(23):struct.pack_into('<IIIiIIIII',memory,400+76+i*36,i,i,i,80 if i<11 else -1,1,0,1,0 if i==0 else 5,0 if i==0 else 5)
        return memory

    def test_unknown_bench_stamina_and_uninterpreted_native_flags_are_preserved(self):
        mem=self.memory();snap=read_snapshot(lambda at,n:bytes(mem[at:at+n]),LAYOUT,lambda:None)
        self.assertEqual(snap['live'][12]['stamina'],-1)
        self.assertEqual(snap['live'][12]['stamina_source'],'unknown')
        self.assertEqual(snap['live'][0]['stamina_source'],'native_live_ratio')
        self.assertEqual(snap['live'][0]['native_flag_4202'],1)
        self.assertEqual(snap['live'][0]['yellow_count'],0)
        self.assertEqual(snap['live'][0]['direct_red'],0)
        self.assertEqual(snap['live'][0]['injury_state'],0)
        self.assertNotIn('unavailable',snap['live'][0])

    def test_snapshot_changed_during_copy_is_discarded(self):
        for key in ('sequence','configuration'):
            mem=self.memory()
            def read(at,n):
                result=bytes(mem[at:at+n])
                if at==400 and n==4880:
                    struct.pack_into('<I',mem,400 if key=='sequence' else 0,6 if key=='sequence' else 4)
                return result
            self.assertIsNone(read_snapshot(read,LAYOUT,lambda:None))

    def test_duplicate_physical_identity_and_nonfinite_clock_are_discarded(self):
        for mutate in (lambda m:struct.pack_into('<I',m,400+76+36+8,0),
                       lambda m:struct.pack_into('<f',m,400+40,float('nan'))):
            mem=self.memory();mutate(mem)
            self.assertIsNone(read_snapshot(lambda at,n:bytes(mem[at:at+n]),LAYOUT,lambda:None))

    def test_receipt_id_changed_during_read_is_not_joined_to_old_status(self):
        mem=self.memory();struct.pack_into('<QII',mem,5720,7,1,0)
        def read(at,n):
            result=bytes(mem[at:at+n])
            if at==5728:struct.pack_into('<Q',mem,5720,8)
            return result
        snap=read_snapshot(read,LAYOUT,lambda:None)
        self.assertIsNotNone(snap);self.assertNotIn('ack_id',snap)

    def test_cancel_is_scoped_to_entry_and_exact_plan(self):
        spec,snap,p=fixture();p={'id':7,'game_id':123,'entry_id':'A','kind':'cancel'}
        raw=encode_command(LAYOUT,spec,snap,p,4,456)
        self.assertEqual(struct.unpack_from('<I',raw,32)[0],3)
        self.assertEqual(struct.unpack_from('<Q',raw,24)[0],7)

    def test_duties_carry_expected_identity_until_native_physical_resolution(self):
        spec,snap,p=fixture()
        p['duties']={'captain':12,'set_piece_taker':[12,8,9,8,9,12],'df_overlap_setplay':[12,8,9]}
        raw=encode_command(LAYOUT,spec,snap,p,2,456)
        self.assertEqual(struct.unpack_from('<10I',raw,400),(12,12,8,9,8,9,12,12,8,9))
        p['duties']['captain']=7
        with self.assertRaisesRegex(ValueError,'on-field'):encode_command(LAYOUT,spec,snap,p,2,456)


if __name__=='__main__':unittest.main()
