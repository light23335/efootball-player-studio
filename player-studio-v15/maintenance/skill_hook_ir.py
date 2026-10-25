"""Small, relocatable AArch64 hook builder used by native skill maintenance.

Only explicit absolute literal references are rebased at installation. Code is
assembled with a zero origin so internal branches remain position independent.
This module never reads or modifies an APK by itself.
"""
import struct
import re
from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN


class Hooks:
    def __init__(self, engine):
        self.engine = engine
        self.rows = []
        self.helpers = []
        self.assembler = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)

    def assemble(self, name, code, functions=None, constants=None, evidence=()):
        functions = dict(functions or {})
        constants = dict(constants or {})
        defined=set(re.findall(r'^([A-Za-z_]\w*):',code,re.M))
        unresolved=sorted(set(re.findall(r'\b(?:bl|b)\s+(shared_\w+)',code))-defined)
        # Helpers may refer to one another before the final bundle is linked.
        # Standalone probes trap on such references; the linked bundle resolves
        # them to real helper entries, never an external process-global pointer.
        probes='\n'.join(label+': brk #4095' for label in unresolved)
        pool = '\n.align 3\n'
        pool += '\n'.join(f'{key}: .quad {value}' for key, value in functions.items())
        pool += '\n' + '\n'.join(f'{key}: .word {bits(value)}' for key, value in constants.items())
        assembly = code + '\n' + probes + pool
        body = bytes(self.assembler.asm(assembly)[0])
        fixups = []
        for key, value in functions.items():
            needle = struct.pack('<Q', value)
            at = body.find(needle)
            if at < 0 or body.find(needle, at + 1) >= 0 or at % 8:
                raise ValueError(f'Non-unique or unaligned literal: {name}/{key}')
            fixups.append([at, value])
        return {'name': name, 'body_hex': body.hex(), 'absolute_fixups': fixups,
               'assembly': assembly, 'code': code, 'functions': functions,
               'constants': constants, 'deferred_shared_refs': unresolved,
               'evidence': list(evidence)}

    def add(self, name, address, code, functions=None, constants=None, evidence=()):
        row = self.assemble(name, code, functions, constants, evidence)
        row.update(address=address, file_offset=address - 16384,
                   expected_hex=self.engine[address - 16384:address - 16384 + 64].hex())
        self.rows.append(row)
        return row

    def helper(self, name, code, functions=None, constants=None, evidence=()):
        row = self.assemble(name, code, functions, constants, evidence)
        self.helpers.append(row)
        return row

    def bundle(self, name, rows):
        """Link hook entries and shared helpers without process-global pointers.

        PC-relative internal references keep working when the installer splits
        its nearby branch stubs from extension code on native-bridge emulators.
        """
        imports, constants, fragments, entries, evidence = {}, {}, [], [], []
        for index, row in enumerate(rows):
            entry = 'shared_' + row['name'] if 'address' not in row else 'entry_' + row['name']
            substitutions = {label: f'local_{index}_{label}' for label in
                             re.findall(r'^([A-Za-z_]\w*):', row['code'], re.M)}
            for label, value in row['functions'].items():
                target = 'native_' + hex(value)[2:]
                imports[target] = value
                substitutions[label] = target
            for label, value in row['constants'].items():
                target = 'float_' + hex(bits(value))[2:]
                constants[target] = value
                substitutions[label] = target
            pattern = r'\b(' + '|'.join(map(re.escape, sorted(substitutions, key=len, reverse=True))) + r')\b'
            code = re.sub(pattern, lambda match: substitutions[match[0]], row['code']) if substitutions else row['code']
            fragments.append(entry + ':\n' + code + '\n.align 3\n')
            entries.append((entry, row))
            evidence += row.get('evidence', [])
        marker = 0x53545544494f4d32
        fragments.append(f'.quad {marker}\n' + '\n'.join('.quad ' + entry for entry, _ in entries))
        linked = self.assemble(name, '\n'.join(fragments), imports, constants, evidence)
        body = bytes.fromhex(linked['body_hex'])
        at = body.find(struct.pack('<Q', marker))
        if at < 0 or body.find(struct.pack('<Q', marker), at + 1) >= 0:
            raise ValueError('Bundle entry metadata is not unique')
        offsets = struct.unpack_from('<' + 'Q' * len(entries), body, at + 8)
        hooks, helpers = [], {}
        for (entry, row), offset in zip(entries, offsets):
            if offset % 4 or offset >= len(body):
                raise ValueError('Bundle entry outside assembled code')
            if 'address' in row:
                hooks.append({'name': row['name'], 'address': row['address'],
                              'file_offset': row['file_offset'], 'expected_hex': row['expected_hex'],
                              'entry_offset': offset})
            else:
                helpers[entry] = offset
        if not hooks:
            raise ValueError('Bundle needs at least one native hook entry')
        linked.update(hooks[0])
        linked['name'] = name
        linked['extra_entries'] = hooks[1:]
        linked['helper_entries'] = helpers
        return linked


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def call(name):
    return f'ldr x16,{name}\nblr x16'


def jump(name):
    return f'ldr x16,{name}\nbr x16'


FRAME = 800
SIMD = 256
NZCV = 768


def save_all():
    code = [f'sub sp,sp,#{FRAME}']
    code += [f'stp x{i},x{i+1},[sp,#{i*8}]' for i in range(0, 30, 2)]
    code += ['str x30,[sp,#240]']
    code += [f'stp q{i},q{i+1},[sp,#{SIMD+i*16}]' for i in range(0, 32, 2)]
    return '\n'.join(code + ['mrs x17,nzcv', f'str x17,[sp,#{NZCV}]']) + '\n'


def restore_all():
    code = [f'ldr x17,[sp,#{NZCV}]', 'msr nzcv,x17']
    code += [f'ldp q{i},q{i+1},[sp,#{SIMD+i*16}]' for i in range(0, 32, 2)]
    code += [f'ldp x{i},x{i+1},[sp,#{i*8}]' for i in range(0, 30, 2)]
    return '\n'.join(code + ['ldr x30,[sp,#240]', f'add sp,sp,#{FRAME}']) + '\n'
