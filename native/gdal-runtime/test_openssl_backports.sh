#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="${BUILD_ROOT:?BUILD_ROOT is required}"
PREFIX="${PREFIX:-/opt/haste}"
JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN)}"
TEST_ROOT="$BUILD_ROOT/work/openssl-regression"
SOURCE="$TEST_ROOT/openssl-3.5.9"

mkdir -p "$TEST_ROOT"
python3 "$ROOT/fetch_sources.py" --dest "$BUILD_ROOT/sources"
tar -xf "$BUILD_ROOT/sources/openssl-3.5.9.tar.gz" -C "$TEST_ROOT"
python3 "$ROOT/apply_openssl_patches.py" \
  --source-dir "$SOURCE" \
  --cache-dir "$BUILD_ROOT/sources/openssl-patches" \
  --report "$TEST_ROOT/applied-patches.json"
(
  cd "$SOURCE"
  ./Configure linux-x86_64 no-shared no-docs no-module \
    no-legacy no-engine no-dso no-autoload-config
  make -j"$JOBS"
  make test TESTS='test_evp_extra test_evp test_ec test_quic_stream'
)

cc -Wall -Wextra -Werror \
  -I"$PREFIX/include" "$ROOT/tests/openssl_peer_address.c" \
  -L"$PREFIX/lib" -Wl,-rpath,"$PREFIX/lib" -lcrypto \
  -o "$TEST_ROOT/openssl-peer-address"
"$TEST_ROOT/openssl-peer-address"
