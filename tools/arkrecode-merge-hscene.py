"""Gabungkan 3 model H-scene baru ke folder arkrecode/ (satu grup).

4 dari 7 model (H006_S, H016_S, H019, H060_S) SUDAH ADA di assets/arkrecode/
dengan .skel/.atlas identik dan PNG beresolusi sama tapi bitrate lebih tinggi.
Jadi yang benar-benar perlu ditambahkan hanya 3: H006, H009_S, H016.
"""
import os
import shutil

SRC = '/opt/spine-viewer/assets/arkrecode-h'
DST = '/opt/spine-viewer/assets/arkrecode'

NEW = ['H006', 'H009_S', 'H016']
DUP = ['H006_S', 'H016_S', 'H019', 'H060_S']

for m in NEW:
    s = os.path.join(SRC, m)
    d = os.path.join(DST, m)
    if not os.path.isdir(s):
        print(f'  LEWATI {m}: sumber tidak ada')
        continue
    if os.path.isdir(d):
        print(f'  LEWATI {m}: sudah ada di tujuan')
        continue
    shutil.copytree(s, d)
    print(f'  SALIN {m}: {len(os.listdir(d))} file')

print('\nverifikasi:')
for m in NEW + DUP:
    d = os.path.join(DST, m)
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    print(f'  {m}: {"ADA" if files else "TIDAK ADA"} ({len(files)} file) {files}')

# hapus folder sementara arkrecode-h (isinya duplikat semua)
shutil.rmtree(SRC, ignore_errors=True)
print('\nassets/arkrecode-h dihapus:', not os.path.exists(SRC))
