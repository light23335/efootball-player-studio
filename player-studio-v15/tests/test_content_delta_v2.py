from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from content_delta import Delta
from content_delta_v2 import record_plan,dependency_map,art_routes,semantic_payload
from art_registry import merged_routes

class BinaryDelta:
    def blob(self,record):return record


class ContentV2Tests(unittest.TestCase):
    def record(self,cid,value):return bytes(8)+cid.to_bytes(8,'little')+bytes([value])*384
    def table(self,rows,updates=()):return {'path':'common/etc/pesdb/Player.bin','stride':400,'key_offset':8,'key_bytes':8,'added':rows,'updated':updates,'base_sha256':'intentionally-not-current'}
    def test_unrelated_target_changes_do_not_require_clean_baseline(self):
        current,actions,bad=record_plan(self.record(1,8)+self.record(99,9),self.table([{'key':'2','record':self.record(2,7)}]),BinaryDelta())
        self.assertEqual(current[99],self.record(99,9));self.assertEqual(actions[2][1],'added');self.assertFalse(bad)
    def test_partial_conflict_keeps_target_but_other_row_is_added(self):
        a=self.record(1,1);b=self.record(2,2)
        current,actions,bad=record_plan(a,self.table([{'key':'1','record':self.record(1,9)},{'key':'2','record':b}]),BinaryDelta())
        self.assertEqual(current[1],a);self.assertEqual(actions[1][1],'preserved_user');self.assertEqual(actions[2][1],'added');self.assertEqual(set(bad),{'1'})
    def test_identical_row_is_reused(self):
        raw=self.record(1,4);_,actions,bad=record_plan(raw,self.table([{'key':'1','record':raw}]),BinaryDelta())
        self.assertEqual(actions[1][1],'reused');self.assertFalse(bad)
    def test_update_requires_exact_before_hash(self):
        raw=self.record(1,4);new=self.record(1,6)
        for digest,expected in ((hashlib.sha256(raw).hexdigest(),'updated'),('0'*64,'preserved_user')):
            _,actions,_=record_plan(raw,self.table([], [{'key':'1','record':new,'expected_before_sha256':digest}]),BinaryDelta())
            self.assertEqual(actions[1][1],expected)
    def test_remove_or_mismatched_identity_is_rejected(self):
        for row in ({'key':'1','record':self.record(2,9)},{'key':'1','record':b'short'}):
            with self.assertRaises(ValueError):record_plan(self.record(1,4),self.table([row]),BinaryDelta())
        table=self.table([]);table['removed']=['1']
        with self.assertRaises(ValueError):record_plan(self.record(1,4),table,BinaryDelta())
    def test_registry_deduplicates_and_rejects_different_same_identity(self):
        row={'cardId':123,'portraitKey':'9500000'}
        self.assertEqual(merged_routes([row],[copy.deepcopy(row)]),[row])
        with self.assertRaisesRegex(ValueError,'冲突'):merged_routes([row],[dict(row,portraitKey='9500001')])
    def test_dependency_closure_includes_transitive_material_and_texture(self):
        def chunk(pid):return pid.to_bytes(8,'little')+bytes([0,0,0,2])
        players={'89136418985316':{'base_id':'10','definition':{}}}
        paths={'PesMobile/Content/A/89136418985316_.uasset':chunk(1),'PesMobile/Content/material.uasset':chunk(2),'PesMobile/Content/texture.uasset':chunk(3)}
        deps,_=dependency_map(players,[],{},paths,{1:{'imports':[2]},2:{'imports':[3]},3:{'imports':[1]}})
        self.assertEqual(deps['89136418985316'],{1,2,3})
    def test_preview_transient_metadata_is_not_a_user_definition_edit(self):
        original={'name':'mine','parameters':[1]}
        self.assertEqual(semantic_payload(original),semantic_payload(dict(original,_studio_client_record='raw')))
        self.assertNotEqual(semantic_payload(original),semantic_payload(dict(original,name='edited')))
    def test_explicit_long_native_lookup_is_not_truncated(self):
        class D:
            def json(self,name):return {'schema':'efootball-art-bindings/2','runtime_abi':'v17-content-art/1','routes':[{
                'entity_kind':'player_card','entity_id':'17','portrait':{'kind':'authored_key','key':'9500023','small_key':'9500023_','detail_key':'9500023f'},
                'model':{'kind':'native_lookup_id','id':'17592186048174'},'suite_donor_id':'18','club_id':1,'position':8,'presentation_rarity':10}]}
        route=art_routes(D(),{'17':{'definition':{}}})[0]
        self.assertEqual(route['modelNativeId'],17592186048174)
    def test_real_v2_package_hashes_and_explicit_data_only_binding(self):
        path=Path(__file__).resolve().parents[2]/'outputs/V17及工坊派生包-V18与V19内容增量-v2.zip'
        if not path.exists():self.skipTest('requires supplied content ZIP')
        with Delta(path)as d:
            self.assertEqual(d.summary()['schema_version'],2)
            players={r['card_id']:r for r in d.json('data/players.json')['players']}
            self.assertEqual(len(players),192);self.assertEqual(len(art_routes(d,players)),10)
            self.assertFalse(any(n.endswith(('.py','.pyc','.so','.dex'))for n in d.entries))

if __name__=='__main__':unittest.main()
