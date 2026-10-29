from pathlib import Path
import copy,json,shutil,sys,tempfile,unittest,os
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from custom_motion_import import convert
from native_library import NativeLibrary
from native_thumbnail import ThumbnailPreview
from private_card_motion import write_movie_pak,read_movie_pak

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT.parent/'.work/movie-integration-fixture'
LAB=Path(os.environ.get('STUDIO_MOVIE_LAB',str(FIXTURE/'data')))
HOME=Path(os.environ.get('STUDIO_MOVIE_HOME',str(FIXTURE/'home')))
RES=Path(os.environ.get('STUDIO_MOVIE_DATABASE',str(FIXTURE/'database')))
MOVIE=Path(os.environ.get('STUDIO_MOVIE_INPUT',str(FIXTURE/'input.mp4')))

@unittest.skipUnless(LAB.is_dir() and MOVIE.is_file(),'requires local tested project and video')
class CustomMotionIntegration(unittest.TestCase):
 def test_import_preview_project_roundtrip_and_movie_pack_merge(self):
  original_catalog=app.CATALOG
  try:
   app.CATALOG=json.loads((RES/'catalog.json').read_text(encoding='utf8'))
   with tempfile.TemporaryDirectory() as tmp:
    store=app.Store(Path(tmp));project=json.loads((LAB/'current-project.json').read_text(encoding='utf8'))
    converted=convert(store,ROOT/'tools/video/ffmpeg.exe',MOVIE,['large','mini'],50,-50)
    project['native_card']['custom_motion']=converted
    for name in app.referenced_assets(project):
     dst=store.root/'assets'/name
     if not dst.exists():shutil.copyfile(LAB/'assets'/name,dst)
    project=app.normalize_project(project)
    library=NativeLibrary(RES,HOME,store)
    preview=ThumbnailPreview(library).prepare(project)
    self.assertTrue(preview['animation']['animated'])
    self.assertEqual(preview['animation']['layers'][0]['asset_id'],converted['mini']['preview']['asset_id'])
    self.assertEqual(preview['animation']['layers'][0]['role'],'background')
    no_motion=copy.deepcopy(project);no_motion['appearance']['thumbnail_animation']=False
    self.assertFalse(ThumbnailPreview(library).prepare(no_motion)['animation']['animated'])
    exported=store.export_project(project);restored=store.import_project(exported['path'])
    self.assertEqual(restored['native_card']['custom_motion'],converted)
    legacy=store.import_project(LAB/'exports/球员工程-20261028-174909-f3b5.efproject')
    for role in ('large','mini'):
     self.assertTrue((store.root/'assets'/legacy['native_card']['custom_motion'][role]['preview']['asset_id']).is_file())
    large=(store.root/'assets'/converted['large']['asset_id']).read_bytes()
    mini=(store.root/'assets'/converted['mini']['asset_id']).read_bytes()
    pak=store.root/'tmp'/'movies.pak'
    first={'PlayerCard/c01234567890_v.usm':large};write_movie_pak(pak,first)
    previous=read_movie_pak(pak.read_bytes());previous['PlayerCard/c11234567890_v.usm']=mini
    merged=store.root/'tmp'/'merged.pak';write_movie_pak(merged,previous)
    self.assertEqual(read_movie_pak(merged.read_bytes()),{**first,'PlayerCard/c11234567890_v.usm':mini})
    corrupt=bytearray(merged.read_bytes());corrupt[60]^=1
    with self.assertRaises(ValueError):read_movie_pak(bytes(corrupt))
  finally:app.CATALOG=original_catalog

if __name__=='__main__':unittest.main()
