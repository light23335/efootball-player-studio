"""Real codec roundtrip and seek-table checks for the experimental importer."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / '.work/movie-lab-deps'))
from card_movie_import import encode, mux_ivf
from native_movie import extract_ivf


class CardMovieTests(unittest.TestCase):
    def test_real_codec_roundtrip_and_seek_offsets(self):
        from wannacri.usm import Usm
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ff = ROOT / 'tools/video/ffmpeg.exe'
            source = folder / 'input.mp4'
            subprocess.run([str(ff), '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=182x256:rate=30', '-t', '0.5',
                            '-c:v', 'libx264', str(source)], check=True, capture_output=True)
            ivf, usm = folder / 'video.ivf', folder / 'video.usm'
            encode(source, ivf, ff, 182, 256, 30, .5)
            report = mux_ivf(ivf, usm)
            self.assertEqual(report['frames'], 15)
            self.assertEqual(extract_ivf(usm.read_bytes()), ivf.read_bytes())
            # The parser retains its input without a close API. Metadata is
            # eager, so supply a context-managed handle for this inspection.
            with usm.open('rb') as handle, patch('builtins.open', return_value=handle):
                parsed = Usm.open(str(usm))
            self.assertEqual(parsed.usm_crid_page()['filesize'].val, usm.stat().st_size)
            data = usm.read_bytes()
            pos, metadata_bytes = 0, 0
            while pos < len(data):
                size = 8 + struct.unpack_from('>I', data, pos + 4)[0]
                if data[pos:pos + 4] == b'@SFV' and data[pos + 15] == 3:
                    metadata_bytes += size
                pos += size
            self.assertEqual(parsed.videos[0].header_page['metadata_size'].val, metadata_bytes)
            for page in parsed.videos[0].metadata_pages:
                offset = page['ofs_byte'].val
                self.assertEqual(data[offset:offset + 4], b'@SFV')
                self.assertEqual(data[offset + 15], 0)
            def hashes(path):
                result = subprocess.run([str(ff), '-v', 'error', '-i', str(path),
                                         '-f', 'framemd5', '-'], check=True, capture_output=True)
                return [row.split(b',')[-1] for row in result.stdout.splitlines()
                        if row and not row.startswith(b'#')]
            self.assertEqual(hashes(ivf), hashes(usm.with_suffix('.webm')))
            before = usm.read_bytes()
            with self.assertRaises(ValueError):
                mux_ivf(ivf, usm)
            self.assertEqual(usm.read_bytes(), before)

    def test_unsupported_contract_does_not_start_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'out.ivf'
            with self.assertRaises(ValueError):
                encode('missing.mp4', target, 'missing.exe', 512, 512, 30, 5)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
