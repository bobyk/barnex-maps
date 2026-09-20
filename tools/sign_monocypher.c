/* sign_monocypher.c — sign a 32-byte digest with Monocypher EdDSA (BLAKE2b).
 *
 * Firmware verifies with crypto_eddsa_check (curve25519 + BLAKE2b), NOT
 * PyNaCl/libsodium Ed25519 (SHA-512). Same 32-byte seed yields a different
 * public key under each scheme — keep sign + verify on the same primitive.
 *
 * Usage:
 *   sign_monocypher <seed.hex> <sha256.hex>
 * Prints: public_key_hex, signature_hex, signature_b64
 */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "monocypher.h"

/* -1 for a non-hex nibble. Not sscanf("%2x", ...): that format means
 * "match up to 2 hex digits", not "exactly 2" — a truncated/corrupted hex
 * string (e.g. one bad trailing character) would silently decode from
 * whatever valid digit came before it instead of failing outright. Found
 * and fixed the same bug in esp32_coordinator's src/ChargerMap/
 * ChargerMapSignature.cpp while writing this file's sibling — see that
 * repo's docs/charger-discovery-decisions.md. */
static int hex_nibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static int hex_decode(const char* hex, uint8_t* out, size_t outlen) {
  size_t n = strlen(hex);
  while (n && (hex[n - 1] == '\n' || hex[n - 1] == '\r' || hex[n - 1] == ' ')) n--;
  if (n != outlen * 2) return -1;
  for (size_t i = 0; i < outlen; i++) {
    int hi = hex_nibble(hex[i * 2]);
    int lo = hex_nibble(hex[i * 2 + 1]);
    if (hi < 0 || lo < 0) return -1;
    out[i] = (uint8_t)((hi << 4) | lo);
  }
  return 0;
}

static void hex_print(const uint8_t* b, size_t n) {
  for (size_t i = 0; i < n; i++) printf("%02x", b[i]);
}

static void b64_print(const uint8_t* b, size_t n) {
  static const char T[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  for (size_t i = 0; i < n; i += 3) {
    uint32_t v = ((uint32_t)b[i] << 16);
    int rem = (int)(n - i);
    if (rem > 1) v |= ((uint32_t)b[i + 1] << 8);
    if (rem > 2) v |= (uint32_t)b[i + 2];
    putchar(T[(v >> 18) & 63]);
    putchar(T[(v >> 12) & 63]);
    putchar(rem > 1 ? T[(v >> 6) & 63] : '=');
    putchar(rem > 2 ? T[v & 63] : '=');
  }
}

int main(int argc, char** argv) {
  if (argc != 3) {
    fprintf(stderr, "usage: %s seed.hex sha256.hex\n", argv[0]);
    return 2;
  }
  FILE* f = fopen(argv[1], "r");
  if (!f) { perror(argv[1]); return 2; }
  char seedhex[96] = {0};
  if (!fgets(seedhex, sizeof(seedhex), f)) { fclose(f); return 2; }
  fclose(f);

  uint8_t seed[32], sk[64], pk[32], digest[32], sig[64];
  if (hex_decode(seedhex, seed, 32)) {
    fprintf(stderr, "bad seed hex\n");
    return 2;
  }
  if (hex_decode(argv[2], digest, 32)) {
    fprintf(stderr, "bad sha256 hex (want 64 hex chars)\n");
    return 2;
  }

  uint8_t seed_copy[32];
  memcpy(seed_copy, seed, 32);
  crypto_eddsa_key_pair(sk, pk, seed_copy);
  crypto_eddsa_sign(sig, sk, digest, 32);
  if (crypto_eddsa_check(sig, pk, digest, 32) != 0) {
    fprintf(stderr, "self-check failed\n");
    return 1;
  }

  printf("public_key_hex=");
  hex_print(pk, 32);
  printf("\nsignature_hex=");
  hex_print(sig, 64);
  printf("\nsignature_b64=");
  b64_print(sig, 64);
  printf("\n");
  return 0;
}
