import pefile, capstone, struct, re, sys

PATH = '/tmp/390_unpacked.pyd'
pe = pefile.PE(PATH, fast_load=False)
IMG = pe.OPTIONAL_HEADER.ImageBase
raw = open(PATH, 'rb').read()

# section map (rva -> file offset)
secs = [(s.VirtualAddress, s.Misc_VirtualSize or s.SizeOfRawData, s.PointerToRawData) for s in pe.sections]
def rva2off(rva):
    for va, vs, pr in secs:
        if va <= rva < va + max(vs,1):
            return pr + (rva - va)
    return None
def off2rva(off):
    for va, vs, pr in secs:
        if pr <= off < pr + max(vs,1):
            return va + (off - pr)
    return None
def read_va(va, n=64):
    rva = va - IMG
    o = rva2off(rva)
    return raw[o:o+n] if o is not None else None
def cstr(va, maxn=200):
    b = read_va(va, maxn)
    if not b: return None
    e = b.find(b'\x00')
    if e < 0: e = len(b)
    s = b[:e]
    if len(s) < 2: return None
    try: t = s.decode('utf-8')
    except Exception: return None
    if all(32 <= ord(c) < 127 for c in t): return t
    return t

# imports: IAT VA -> name
iat = {}
if hasattr(pe, 'DIRECTORY_ENTRY_IMPORT'):
    for mod in pe.DIRECTORY_ENTRY_IMPORT:
        dll = mod.dll.decode()
        for imp in mod.imports:
            if imp.name:
                iat[imp.address] = f"{dll}!{imp.name.decode()}"
            else:
                iat[imp.address] = f"{dll}!#{imp.ordinal}"

print(f"ImageBase={IMG:#x}  imports={len(iat)}")

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
md.detail = True

def disasm(func_rva, max_insn=600):
    va = IMG + func_rva
    o = rva2off(func_rva)
    if o is None:
        print(f"  !! no rva for {func_rva:#x}"); return
    code = raw[o:o+ 0x4000]     # up to 16KB window
    print(f"\n########## func rva={func_rva:#x} va={va:#x} ##########")
    n = 0
    for ins in md.disasm(code, va):
        line = f"  {ins.address:#012x}  {ins.mnemonic:8} {ins.op_str}"
        ann = ""
        # annotate RIP-relative memory operands
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                tgt = ins.address + ins.size + op.mem.disp
                nm = iat.get(tgt)
                if nm:
                    ann = f"   ; {nm}"
                else:
                    st = cstr(tgt, 160)
                    if st:
                        ann = f"   ; \"{st}\""
                    else:
                        ann = f"   ; [mem {tgt:#x}]"
            if op.type == capstone.x86.X86_OP_IMM and ins.mnemonic == 'call':
                ann = f"   ; -> {op.imm:#x} (rva {op.imm-IMG:#x})"
        print(line + ann)
        n += 1
        if n >= max_insn: 
            print("  ... (truncated)")
            break
        if ins.mnemonic == 'ret' and n > 4:
            break

for rva in [int(a,16) for a in sys.argv[1:]]:
    disasm(rva)
