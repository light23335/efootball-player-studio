import importlib.util,unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'app/src/main/python/android_card_movie.py'
spec=importlib.util.spec_from_file_location('android_card_movie',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class CardMoviePlanesTests(unittest.TestCase):
    def test_planar_padding_and_interleaved_chroma_keep_every_pixel(self):
        raw=bytes(range(12))
        for row,pixel in ((4,1),(8,1),(8,2)):
            packed=module.plane_bytes(raw,4,3,row,pixel)
            restored=bytes(packed[y*row+x*pixel]for y in range(3)for x in range(4))
            self.assertEqual(restored,raw)
        with self.assertRaises(ValueError):module.plane_bytes(raw,4,3,4,2)

if __name__=='__main__':unittest.main()
