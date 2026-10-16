import pefile, capstone, sys

PATH='/tmp/390_unpacked.pyd'
pe=pefile.PE(PATH, fast_load=True)
IMG=pe.OPTIONAL_HEADER.ImageBase
raw=open(PATH,'rb').read()
secs=[(s.VirtualAddress, s.Misc_VirtualSize or s.SizeOfRawData, s.PointerToRawData) for s in pe.sections]
def rva2off(rva):
    for va,vs,pr in secs:
        if va<=rva<va+max(vs,1): return pr+(rva-va)
def cstr(va,m=200):
    o=rva2off(va-IMG)
    if o is None: return None
    b=raw[o:o+m]; e=b.find(b'\x00')
    if e<0: e=len(b)
    s=b[:e]
    try: t=s.decode('utf-8')
    except Exception: return None
    if len(t)>=2 and all(32<=ord(c)<127 for c in t): return t
    return None
md=capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail=True

def scan(rva, win=0x3000):
    va=IMG+rva; o=rva2off(rva)
    code=raw[o:o+win]
    print(f"\n##### rva {rva:#x} (va {va:#x}) #####")
    seen=set()
    for ins in md.disasm(code, va):
        for op in ins.operands:
            if op.type==capstone.x86.X86_OP_MEM and op.mem.base==capstone.x86.X86_REG_RIP:
                tgt=ins.address+ins.size+op.mem.disp
                s=cstr(tgt)
                if s and s not in seen:
                    seen.add(s)
                    # keep interesting ones
                    if any(k in s for k in ('http','.json','.php','manifest','version','filelist',
                                            'secret','update','download','url','list','game','api',
                                            'catalog','hash','spine','Spine','.pyd','.txt','betasystem','1919810')):
                        print(f"   {ins.address:#x}  {s}")

import sys
for r in sys.argv[1:]:
    scan(int(r,16))
