import struct, json

disk = open('/tmp/rdpshare/app_390.pyd', 'rb').read()
img  = bytearray(open('/tmp/390_mem.bin', 'rb').read())   # carved, identity RVA layout

# --- PE header ---
e_lfanew = struct.unpack_from('<I', img, 0x3C)[0]
print("e_lfanew:", hex(e_lfanew), img[e_lfanew:e_lfanew+4])
filehdr = e_lfanew + 4
nsec, = struct.unpack_from('<H', img, filehdr + 2)
size_opt, = struct.unpack_from('<H', img, filehdr + 16)
opt = filehdr + 20
magic, = struct.unpack_from('<H', img, opt)
print("magic:", hex(magic), "sections:", nsec, "opt size:", size_opt)

sa, = struct.unpack_from('<I', img, opt + 32)
fa, = struct.unpack_from('<I', img, opt + 36)
sizeimg, = struct.unpack_from('<I', img, opt + 56)
print(f"SectionAlign={sa:#x} FileAlign={fa:#x} SizeOfImage={sizeimg:#x}")

sec0 = opt + size_opt
secs = []
for i in range(nsec):
    o = sec0 + i*40
    name = img[o:o+8].rstrip(b'\x00').decode('latin1')
    vsize, va, rsize, raddr = struct.unpack_from('<IIII', img, o+8)
    chars, = struct.unpack_from('<I', img, o+36)
    secs.append((name, va, vsize, rsize, raddr, chars, o))
    print(f"  {name:8} VA={va:#x} VSize={vsize:#x} rawsize={rsize:#x} rawaddr={raddr:#x} char={chars:#x}")

# --- fix up for identity mapping (file offset == RVA) ---
struct.pack_into('<I', img, opt + 36, sa)     # FileAlignment = SectionAlignment
for name, va, vsize, rsize, raddr, chars, o in secs:
    newraw = (vsize + sa - 1)//sa*sa
    struct.pack_into('<I', img, o + 8, newraw)  # SizeOfRawData
    struct.pack_into('<I', img, o + 20, va)     # PointerToRawData
    print(f"  patched {name}: raw->{va:#x} size->{newraw:#x}")

# zero-fill anything beyond current length up to SizeOfImage
if len(img) < sizeimg:
    img += b'\x00' * (sizeimg - len(img))
open('/tmp/390_unpacked.pyd', 'wb').write(img)
print("wrote /tmp/390_unpacked.pyd", f"{len(img):,}")

# verify with pefile
import pefile
pe = pefile.PE('/tmp/390_unpacked.pyd', fast_load=True)
print("pefile OK: machine", hex(pe.FILE_HEADER.Machine), "ts", pe.FILE_HEADER.TimeDateStamp,
      "nsec", pe.FILE_HEADER.NumberOfSections)
print("entry:", hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint))
try:
    for e in pe.DIRECTORY_ENTRY_EXPORT.symbols[:5]:
        print("  export:", e.name)
except Exception as ex:
    print("  exports:", ex)
