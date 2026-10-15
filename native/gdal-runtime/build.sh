#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="${BUILD_ROOT:-$ROOT/build}"
PREFIX="${PREFIX:-/opt/haste}"
PYTHON="${PYTHON:-/opt/python/cp311-cp311/bin/python}"
JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN)}"
SOURCES="$BUILD_ROOT/sources"
WORK="$BUILD_ROOT/work"
WHEELS="$BUILD_ROOT/wheels"
TOOL_VENV="$BUILD_ROOT/venv"
FIONA_VENV="$BUILD_ROOT/venv-fiona"

if [[ -z "${PIP_INDEX_URL:-}" ]]; then
  echo "PIP_INDEX_URL must point to the approved internal package feed" >&2
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "CPython 3.11 interpreter not found: $PYTHON" >&2
  exit 2
fi

# Preserve the verified source cache, but rebuild generated state from scratch.
rm -rf "$WORK" "$WHEELS" "$TOOL_VENV" "$FIONA_VENV" \
  "$BUILD_ROOT/dist" "$BUILD_ROOT/package/haste_gdal_runtime"
mkdir -p "$SOURCES" "$WORK" "$WHEELS"
export PYTHON
export PATH="$PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export CMAKE_PREFIX_PATH="$PREFIX${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
export CFLAGS="-I$PREFIX/include ${CFLAGS:-}"
export CPPFLAGS="-I$PREFIX/include ${CPPFLAGS:-}"
export LDFLAGS="-L$PREFIX/lib -Wl,-rpath,$PREFIX/lib ${LDFLAGS:-}"
export OPENSSL_CONF=/dev/null
export OPENSSL_MODULES="$PREFIX/lib/ossl-modules"
export PYTHON

python3 "$ROOT/fetch_sources.py" --dest "$SOURCES"
bash "$ROOT/install_build_tools.sh" "$TOOL_VENV"
bash "$ROOT/install_build_tools.sh" "$FIONA_VENV" \
  "$ROOT/requirements-fiona-build.txt"

extract() {
  local name="$1"
  local archive
  archive="$(find "$SOURCES" -maxdepth 1 -type f -name "$name-*.tar.gz" -print -quit)"
  if [[ -z "$archive" ]]; then
    echo "locked archive for $name not found" >&2
    return 1
  fi
  tar -xf "$archive" -C "$WORK"
}

extract zlib
(
  cd "$WORK"/zlib-*/
  ./configure --prefix="$PREFIX" --shared
  make -j"$JOBS"
  make install
)

extract libdeflate
cmake -S "$WORK"/libdeflate-*/ -B "$WORK/libdeflate-build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DBUILD_SHARED_LIBS=ON \
  -DLIBDEFLATE_BUILD_GZIP=OFF \
  -DLIBDEFLATE_BUILD_TESTS=OFF
cmake --build "$WORK/libdeflate-build" --parallel "$JOBS"
cmake --install "$WORK/libdeflate-build"

extract zstd
cmake -S "$WORK"/zstd-*/build/cmake -B "$WORK/zstd-build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DZSTD_BUILD_SHARED=ON \
  -DZSTD_BUILD_STATIC=OFF \
  -DZSTD_BUILD_PROGRAMS=OFF \
  -DZSTD_BUILD_TESTS=OFF
cmake --build "$WORK/zstd-build" --parallel "$JOBS"
cmake --install "$WORK/zstd-build"

extract libjpeg-turbo
cmake -S "$WORK"/libjpeg-turbo-*/ -B "$WORK/libjpeg-build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DENABLE_SHARED=ON \
  -DENABLE_STATIC=OFF \
  -DWITH_TURBOJPEG=OFF \
  -DWITH_TESTS=OFF \
  -DWITH_TOOLS=OFF
cmake --build "$WORK/libjpeg-build" --parallel "$JOBS"
cmake --install "$WORK/libjpeg-build"

extract openssl
(
  cd "$WORK"/openssl-*/
  ./Configure linux-x86_64 shared no-tests no-apps no-docs no-module \
    no-legacy no-engine no-dso no-autoload-config \
    --prefix="$PREFIX" --openssldir="$PREFIX/ssl"
  make -j"$JOBS"
  make install_sw
)

extract curl
(
  cd "$WORK"/curl-*/
  ./configure \
    --prefix="$PREFIX" \
    --with-openssl="$PREFIX" \
    --with-zlib="$PREFIX" \
    --with-ca-fallback \
    --without-ca-bundle \
    --without-ca-path \
    --disable-file \
    --disable-ftp \
    --disable-ipfs \
    --disable-ldap \
    --disable-ldaps \
    --disable-rtsp \
    --disable-dict \
    --disable-telnet \
    --disable-tftp \
    --disable-pop3 \
    --disable-imap \
    --disable-smb \
    --disable-smtp \
    --disable-gopher \
    --disable-mqtt \
    --disable-websockets \
    --disable-netrc \
    --disable-docs \
    --disable-manual \
    --disable-unix-sockets \
    --disable-alt-svc \
    --disable-hsts \
    --disable-ech \
    --disable-aws \
    --disable-httpsrr \
    --disable-ares \
    --disable-threaded-resolver \
    --disable-sspi \
    --disable-kerberos-auth \
    --disable-negotiate-auth \
    --disable-ntlm \
    --disable-cookies \
    --without-libpsl \
    --without-libidn2 \
    --without-nghttp2 \
    --without-brotli \
    --without-zstd \
    --without-ngtcp2 \
    --without-nghttp3
  make -j"$JOBS"
  make install
)

extract sqlite
(
  cd "$WORK"/sqlite-autoconf-*/
  CFLAGS="-O2 -fPIC -DSQLITE_ENABLE_RTREE=1 \
    -DSQLITE_ENABLE_COLUMN_METADATA=1 -DSQLITE_THREADSAFE=1 \
    -DSQLITE_OMIT_LOAD_EXTENSION=1" \
    ./configure --prefix="$PREFIX" --enable-shared --disable-static
  make -j"$JOBS"
  make install
)

PROJ_VERSION="$(python3 "$ROOT/fetch_sources.py" --print-version proj)"
extract proj
cmake -S "$WORK"/proj-*/ -B "$WORK/proj-build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_PREFIX_PATH="$PREFIX" \
  -DSQLite3_INCLUDE_DIR="$PREFIX/include" \
  -DSQLite3_LIBRARY="$PREFIX/lib/libsqlite3.so" \
  -DBUILD_APPS=OFF \
  -DBUILD_TESTING=OFF \
  -DBUILD_EXAMPLES=OFF \
  -DENABLE_TIFF=OFF \
  -DENABLE_CURL=OFF \
  -DEMBED_PROJ_DATA_PATH=OFF \
  -DUSE_ONLY_EMBEDDED_RESOURCE_FILES=OFF
cmake --build "$WORK/proj-build" --parallel "$JOBS"
cmake --install "$WORK/proj-build"

extract gdal
GDAL_SOURCE="$(find "$WORK" -maxdepth 1 -type d -name 'gdal-*' -print -quit)"
cmake -S "$GDAL_SOURCE" -B "$WORK/gdal-build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_PREFIX_PATH="$PREFIX" \
  -DBUILD_SHARED_LIBS=ON \
  -DBUILD_APPS=OFF \
  -DBUILD_TESTING=OFF \
  -DGDAL_BUILD_OPTIONAL_DRIVERS=OFF \
  -DOGR_BUILD_OPTIONAL_DRIVERS=OFF \
  -DGDAL_ENABLE_DRIVER_GTIFF=ON \
  -DGDAL_ENABLE_DRIVER_VRT=ON \
  -DGDAL_VRT_ENABLE_RAWRASTERBAND=OFF \
  -DGDAL_AUTOLOAD_PLUGINS=OFF \
  -DGDAL_USE_EXTERNAL_LIBS=OFF \
  -DGDAL_USE_INTERNAL_LIBS=OFF \
  -DGDAL_USE_CURL=ON \
  -DGDAL_USE_SQLITE3=ON \
  -DGDAL_USE_ZLIB=ON \
  -DGDAL_USE_DEFLATE=ON \
  -DGDAL_USE_ZSTD=ON \
  -DGDAL_USE_JPEG=ON \
  -DGDAL_USE_TIFF_INTERNAL=ON \
  -DGDAL_USE_GEOTIFF_INTERNAL=ON \
  -DGDAL_USE_PNG_INTERNAL=ON \
  -DGDAL_USE_JSONC_INTERNAL=ON \
  -DGDAL_USE_GEOS=OFF \
  -DGDAL_USE_LERC=OFF \
  -DGDAL_USE_QHULL=OFF \
  -DGDAL_USE_OPENSSL=OFF \
  -DGDAL_ENABLE_DRIVER_PNG=ON \
  -DGDAL_ENABLE_DRIVER_JPEG=ON \
  -DOGR_ENABLE_DRIVER_GEOJSON=ON \
  -DOGR_ENABLE_DRIVER_GPKG=ON \
  -DOGR_ENABLE_DRIVER_SQLITE=ON \
  -DOGR_ENABLE_DRIVER_SHAPE=OFF \
  -DCMAKE_CXX_FLAGS=-DGDAL_VRT_DISABLE_PYTHON\ -DCPL_VSIL_CURL_HEADER_FILE_KVP_DISABLED \
  2>&1 | tee "$BUILD_ROOT/gdal-configure.log"

# Fail if this source release silently ignores a security-critical CMake
# option. The GDAL configure step also audits every unconsumed cache entry.
cmake -LAH -N "$WORK/gdal-build" > "$BUILD_ROOT/gdal-cmake-cache.txt"
for option in GDAL_VRT_ENABLE_RAWRASTERBAND GDAL_AUTOLOAD_PLUGINS; do
  grep -q "^${option}:BOOL=OFF$" "$BUILD_ROOT/gdal-cmake-cache.txt"
done
grep -q '^CMAKE_CXX_FLAGS:STRING=.*GDAL_VRT_DISABLE_PYTHON.*CPL_VSIL_CURL_HEADER_FILE_KVP_DISABLED' \
  "$BUILD_ROOT/gdal-cmake-cache.txt"
if grep -q 'Manually-specified variables were not used' \
  "$BUILD_ROOT/gdal-configure.log"; then
  echo "GDAL CMake ignored a manually specified build option" >&2
  exit 1
fi

cmake --build "$WORK/gdal-build" --parallel "$JOBS"
cmake --install "$WORK/gdal-build"

# BUILD_APPS=OFF intentionally omits gdal-config. Generate its build-time
# metadata script with apps enabled, but do not build or install GDAL utilities.
cmake -S "$GDAL_SOURCE" -B "$WORK/gdal-build" -DBUILD_APPS=ON
install -D -m 755 "$WORK/gdal-build/apps/gdal-config" \
  "$PREFIX/bin/gdal-config"
config_version="$("$PREFIX/bin/gdal-config" --version)"
if [[ "$config_version" != "3.13.3" ]]; then
  echo "gdal-config reports $config_version, expected 3.13.3" >&2
  exit 1
fi
ln -sfn "$PREFIX/bin/gdal-config" /usr/local/bin/gdal-config
command -v gdal-config
gdal-config --version

export GDAL_CONFIG="$PREFIX/bin/gdal-config"
export PROJ_DIR="$PREFIX"
export PROJ_VERSION
export GDAL_DATA="$PREFIX/share/gdal"
export PROJ_DATA="$PREFIX/share/proj"

# pip inspects GDAL's PEP 517 metadata while downloading its sdist. That
# metadata step runs gdal-config, so resolve binding sdists only after the
# native runtime and its build-only config tool are available.
bash "$ROOT/fetch_binding_sdists.sh" "$SOURCES/bindings"

mkdir -p "$BUILD_ROOT/package/haste_gdal_runtime/share/gdal"
mkdir -p "$BUILD_ROOT/package/haste_gdal_runtime/share/proj"
cp "$ROOT/haste_gdal_runtime/"*.py "$ROOT/haste_gdal_runtime/gdalrc" \
  "$BUILD_ROOT/package/haste_gdal_runtime/"
cp -a "$PREFIX/share/gdal/." \
  "$BUILD_ROOT/package/haste_gdal_runtime/share/gdal/"
cp -a "$PREFIX/share/proj/." \
  "$BUILD_ROOT/package/haste_gdal_runtime/share/proj/"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" -m haste_gdal_runtime manifest \
    --library "$PREFIX/lib/libgdal.so" \
    --output "$BUILD_ROOT/package/haste_gdal_runtime/manifest.json"
python3 "$ROOT/verify_build_manifest.py" \
  "$BUILD_ROOT/package/haste_gdal_runtime/manifest.json"

python3 "$ROOT/build_bindings.py" \
  --python "$PYTHON" \
  --prefix "$PREFIX" \
  --sdist-dir "$SOURCES/bindings" \
  --wheel-dir "$WHEELS" \
  --common-venv "$TOOL_VENV" \
  --fiona-venv "$FIONA_VENV"

python3 "$ROOT/assemble_wheels.py" \
  --wheel-dir "$WHEELS" \
  --runtime-package "$BUILD_ROOT/package/haste_gdal_runtime" \
  --output-dir "$BUILD_ROOT/dist" \
  --build "$(python3 "$ROOT/fetch_sources.py" --print-build)" \
  --gdal-version 3.13.3 \
  --prefix "$PREFIX"

echo "Native runtime and binding wheels built under $BUILD_ROOT/dist"
