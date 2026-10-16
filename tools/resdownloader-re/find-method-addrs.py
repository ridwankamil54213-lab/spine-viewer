import struct, re, json

img = open('/tmp/390_mem.bin','rb').read()
REAL = 0x7ff9ff870000          # actual load base in the process (ASLR)
LO, HI = REAL, REAL + len(img)
BASE = 0x180000000             # header ImageBase (for reporting RVAs)

def str_at_p(p):
    if not (LO <= p < HI-1): return None
    off = p - REAL
    e = img.find(b'\x00', off, off+64)
    if e < 0: return None
    raw = img[off:e]
    if not raw or not all(32 <= c < 127 for c in raw): return None
    return raw.decode('ascii')

# find every 8-byte pointer to a string
ptrs = {}
for off in range(0, len(img)-8, 8):
    v = struct.unpack_from('<Q', img, off)[0]
    s = str_at_p(v)
    if s and 1 <= len(s) <= 48:
        ptrs[off] = s
print("string ptrs:", len(ptrs))

# PyMethodDef: [name_ptr][func_ptr][flags(int32)][pad/doc_ptr]
methods = {}
for off, s in ptrs.items():
    fo = off + 8
    if fo+8 > len(img): continue
    v2 = struct.unpack_from('<Q', img, fo)[0]
    rva2 = v2 - REAL
    if 0x1000 <= rva2 < 0xD6A000:      # points into code/data (a function)
        methods.setdefault(s, []).append((hex(BASE+off), hex(BASE+rva2)))
print("methods:", len(methods))

WANT = ['parse_manifest','load_manifest_from_bytes','getversion','checkself_for_update','update_games',
        'is_newer_version','getCatalogversion','download_and_parse_manifest','generate_download_urls',
        'fetch_secret_data','update_download_list','main','run','get_game_url','export_aria2_txt',
        'get_version_info_from_manifest','get_latest_android_build','process_json_file','fetch_json',
        'patchupdate','decrypt_version_json','get_index_content','get_ablist','get_url_list','getosapi',
        'getpasswd','decrypt_files_in_folder','extract_all_zips','unpackmain','geterolabtoken','login']
for w in WANT:
    if w in methods:
        for nv, fv in methods[w][:3]:
            print(f"  {w:32} name@{nv}  func@{fv}")
    else:
        print(f"  {w:32} (not found)")

json.dump(methods, open('/tmp/methods.json','w'))
print("\nsaved /tmp/methods.json entries:", len(methods))
