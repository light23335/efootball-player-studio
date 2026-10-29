import ctypes
import struct
import unittest
import types
from unittest.mock import Mock
from personal_binding import _BindingCtypes,guard_module_reads


class DiagnosticReadTests(unittest.TestCase):
    def test_camera_and_fps_reader_keep_checks_and_turn_unmap_into_error(self):
        module=types.SimpleNamespace(ctypes=ctypes)
        reader=Mock(return_value=b'x'*32);self.assertTrue(guard_module_reads(module,reader))
        self.assertIs(module.ctypes.c_uint32,ctypes.c_uint32)
        self.assertEqual(module.ctypes.string_at(123,32),b'x'*32)
        reader.side_effect=OSError(14,'unmapped')
        with self.assertRaises(OSError):module.ctypes.string_at(123,32)
        self.assertFalse(guard_module_reads(module,reader))
    def test_ring_counters_and_rows_use_checked_reader(self):
        binding=_BindingCtypes(ctypes,{'writable_data_bytes':0})
        memory=struct.pack('<8Q',*range(10,18));calls=[]
        def read(address,size):
            calls.append((address,size))
            if not 1000<=address<=1000+len(memory)-size:raise OSError(5,'unmapped')
            return memory[address-1000:address-1000+size]
        binding._guard_reads(read)
        self.assertEqual([binding.c_uint64.from_address(1000+i*8).value for i in range(4)],list(range(10,14)))
        self.assertEqual(struct.unpack('<4Q',binding.string_at(1032,32)),(14,15,16,17))
        self.assertEqual(len(calls),5)

    def test_engine_unmap_between_view_creation_and_read_is_an_exception(self):
        binding=_BindingCtypes(ctypes,{'writable_data_bytes':0})
        live=Mock(return_value=struct.pack('<Q',42));binding._guard_reads(live)
        view=binding.c_uint64.from_address(1000);self.assertEqual(view.value,42)
        live.side_effect=OSError(14,'engine unmapped')
        with self.assertRaises(OSError):_ = view.value
        with self.assertRaises(OSError):binding.string_at(1000,32)
        with self.assertRaises(AttributeError):view.value=7

    def test_guarded_integer_still_has_original_eight_byte_abi(self):
        binding=_BindingCtypes(ctypes,{'writable_data_bytes':0});binding._guard_reads(lambda a,n:bytes(n))
        self.assertEqual(ctypes.sizeof(binding.c_uint64),8)
        self.assertEqual(binding.c_uint64(123).value,123)
