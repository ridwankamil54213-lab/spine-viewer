// Dekripsi XXTEA cepat (cocos2d-x, little-endian), dipanggil dari Python
// lewat ctypes. Implementasi Python murni ~1 MB/detik; ini ~100x lebih cepat
// sehingga 7 GB aset bisa diproses dalam menit, bukan jam.
//
// Build:
//   gcc -O3 -shared -fPIC -o libxxtea_fast.so xxtea_fast.c
//
// Pakai dari Python:
//   lib.xxtea_decrypt(buf_in, len, key, buf_out)

#include <stdint.h>
#include <string.h>

#define DELTA 0x9E3779B9u
#define MX ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (k[(p & 3) ^ e] ^ z)))

static inline uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static inline void put32(uint8_t *p, uint32_t v) {
    p[0] = v & 0xFF;
    p[1] = (v >> 8) & 0xFF;
    p[2] = (v >> 16) & 0xFF;
    p[3] = (v >> 24) & 0xFF;
}

// Mengembalikan jumlah byte hasil (kelipatan 4), atau 0 kalau gagal.
int xxtea_decrypt(const uint8_t *data, int len, const uint8_t *key, uint8_t *out) {
    if (len < 8) return 0;
    int n = len / 4;
    if (n < 2) return 0;

    uint32_t k[4];
    for (int i = 0; i < 4; i++) k[i] = le32(key + i * 4);

    uint32_t v[n];
    for (int i = 0; i < n; i++) v[i] = le32(data + i * 4);

    uint32_t rounds = 6 + 52 / n;
    uint32_t sum = rounds * DELTA;
    uint32_t y = v[0];
    uint32_t z, e, p;
    uint32_t mx;

    while (sum) {
        e = (sum >> 2) & 3;
        for (p = (uint32_t)n - 1; p != 0xFFFFFFFFu; p--) {
            z = (p > 0) ? v[p - 1] : v[n - 1];
            mx = MX;
            v[p] -= mx;
            y = v[p];
        }
        sum -= DELTA;
    }

    for (int i = 0; i < n; i++) put32(out + i * 4, v[i]);
    return n * 4;
}
