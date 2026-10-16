import json, collections, re

load = json.load(open('/opt/spine-viewer/tools/resdownloader-re/loader-symbols.json'))
methods = json.load(open('/tmp/methods.json'))

# --- 1) qualified names from loader.* ---
top_fn   = collections.OrderedDict()   # module-level funcs
classes  = collections.OrderedDict()   # class -> [methods]
for s in load:
    p = s.split('.')
    if len(p) == 2:                    # loader.<fn>
        top_fn[p[1]] = True
    elif len(p) >= 3:                  # loader.<Class>.<method...>
        classes.setdefault(p[1], []).append('.'.join(p[2:]))

print(f"# module-level functions : {len(top_fn)}")
print(f"# classes               : {len(classes)}")
print(f"# total loader.* symbols : {len(load)}")
print(f"# PyMethodDef entries    : {len(methods)}")

# --- 2) classify classes: downloader vs unpacker vs login vs helper ---
def kind(c):
    cl = c.lower()
    if 'login' in cl or cl in ('logiaeero','logiaeop','logiwzzyop','userloginself','loginspinegoods'):
        return 'AUTH/LOGIN'
    if 'unpack' in cl or cl in ('nmunpack','lsnunpack','wyunpack','luunpack','thbjunpack','xqautounpack','Burstautounpack'.lower()):
        return 'UNPACK'
    if cl.endswith('diff') or 'diff' in cl:
        return 'DIFF/UPDATE'
    if 'download' in cl or 'downloder' in cl or 'downloader' in cl:
        return 'DOWNLOAD'
    return 'OTHER'

groups = collections.defaultdict(list)
for c in classes:
    groups[kind(c)].append(c)

for g in ('AUTH/LOGIN','DOWNLOAD','DIFF/UPDATE','UNPACK','OTHER'):
    print(f"\n=== {g} ({len(groups[g])}) ===")
    print("  " + ", ".join(groups[g]))

# --- 3) module-level funcs, JSON dump ---
json.dump({'module_funcs': list(top_fn), 'classes': {k: v for k, v in classes.items()},
           'groups': {k: v for k, v in groups.items()}},
          open('/tmp/func_inventory.json','w'), ensure_ascii=False, indent=1)
print("\nsaved /tmp/func_inventory.json")
