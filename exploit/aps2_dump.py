"""Robust APS2 (Android packed RELA) decode + command-table discovery.

AOSP packed format (bionic linker_reloc_iterators.h):
  header: 'APS2', sleb relocation_count, sleb initial_offset
  groups:  sleb group_size, sleb group_flags
           flags bit0 GROUPED_BY_INFO, bit1 GROUPED_BY_OFFSET,
                 bit2 GROUPED_BY_ADDEND, bit3 GROUP_HAS_ADDEND
           read group_offset_delta if bit1, group_info if bit0,
           group_addend if bit2
  then per relocation in group:
     r_offset += grouped_offset ? group_offset_delta : sleb_delta
     r_info    = grouped_info   ? group_info        : r_info + sleb_delta
     if HAS_ADDEND:
        if GROUPED_BY_ADDEND: r_addend = group_addend
        else:                 r_addend += sleb_delta
"""
import bisect
import io
import lzma
import struct
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from elftools.elf.elffile import ELFFile

PATH = sys.argv[1] if len(sys.argv) > 1 else r're\bin\dji_sys'
FILTER = sys.argv[2].lower() if len(sys.argv) > 2 else ''

elf = ELFFile(open(PATH, 'rb'))
data = open(PATH, 'rb').read()
loads = [(s['p_vaddr'], s['p_offset'], s['p_filesz'])
         for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
maxva = max(v + s for v, o, s in loads)


def va2off(va):
    for v, o, sz in loads:
        if v <= va < v + sz:
            return o + (va - v)
    return None


def rd(va, n):
    o = va2off(va)
    return data[o:o + n] if o is not None else b''


def sleb(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7f) << shift
        shift += 7
        if not (b & 0x80):
            break
    if b & 0x40:
        result -= (1 << shift)
    return result, pos


rel = {}
for s in elf.iter_sections():
    if s.header['sh_type'] == 'SHT_RELA':
        for r in s.iter_relocations():
            rel[r['r_offset']] = r['r_addend']

tags = {str(t.entry.d_tag): t.entry.d_val
        for t in elf.get_section_by_name('.dynamic').iter_tags()}
apsec = 0
if 'DT_ANDROID_RELA' in tags:
    off = va2off(tags['DT_ANDROID_RELA'])
    assert data[off:off + 4] == b'APS2', data[off:off + 4]
    pos = off + 4
    count, pos = sleb(data, pos)
    r_offset, pos = sleb(data, pos)   # initial offset
    r_info = 0
    r_addend = 0
    done = 0
    while done < count:
        gsize, pos = sleb(data, pos)
        gflags, pos = sleb(data, pos)
        g_off = g_add = 0
        g_info = 0
        if gflags & 2:
            g_off, pos = sleb(data, pos)
        if gflags & 1:
            g_info, pos = sleb(data, pos)
        if gflags & 4:
            g_add, pos = sleb(data, pos)
        for _ in range(gsize):
            if gflags & 2:
                r_offset += g_off
            else:
                d, pos = sleb(data, pos)
                r_offset += d
            if gflags & 1:
                r_info = g_info
            else:
                d, pos = sleb(data, pos)
                r_info += d
            if gflags & 8:
                if gflags & 4:
                    r_addend = g_add
                else:
                    d, pos = sleb(data, pos)
                    r_addend += d
            rel[r_offset] = r_addend
            done += 1
    apsec = count

print('%s: %d reloc entries (%d from APS2)' % (PATH, len(rel), apsec))

ds = elf.get_section_by_name('.gnu_debugdata')
st = ELFFile(io.BytesIO(lzma.decompress(ds.data()))).get_section_by_name('.symtab')
fns = []
for s in st.iter_symbols():
    try:
        if s['st_info']['type'] == 'STT_FUNC' and s['st_size'] and s.name:
            fns.append((s['st_value'], s['st_size'], s.name))
    except Exception:
        pass
fns.sort()
starts = {v: n for v, sz, n in fns}
start_list = sorted(starts)


def fn_at(va):
    i = bisect.bisect_right(start_list, va) - 1
    if i >= 0:
        v = start_list[i]
        # find size
        for v2, sz, n in fns:
            if v2 == v:
                if v <= va < v + sz:
                    return n if va == v else '%s+0x%x' % (n, va - v)
                break
    return 'sub_%x' % va


# collect relocations whose addend is exactly a function start, plus nearby msg id
rows = []
for slot, add in rel.items():
    if add in starts:
        rows.append((slot, add, starts[add]))
rows.sort()

print('%d slots point at function starts' % len(rows))
out = 0
for slot, add, nm in rows:
    if FILTER and FILTER not in nm.lower():
        continue
    # scan backwards for a plausible msg id at any 4-byte alignment
    tags2 = []
    for back in range(4, 0x60, 4):
        w = rd(slot - back, 4)
        if len(w) < 4:
            continue
        w32 = struct.unpack('<I', w)[0]
        set2, cid = w32 >> 16, w32 & 0xFFFF
        if w32 and set2 <= 0x60 and cid < 0x400:
            tags2.append((back, '%04x/%04x' % (set2, cid)))
    print('  slot 0x%06x -> %-44s back=%s' % (slot, nm, tags2[:3]))
    out += 1
    if out > 400:
        print('  ... (truncated)')
        break
