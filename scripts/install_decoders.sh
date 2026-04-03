#!/usr/bin/env bash
set -euo pipefail

# SignalDeck decoder installation script
# Builds and installs decoders that aren't available via apt

INSTALL_DIR="${HOME}/signaldeck-tools"
mkdir -p "$INSTALL_DIR/src"

echo "=== SignalDeck Decoder Installer ==="
echo "Install directory: $INSTALL_DIR"
echo ""

# ---- Common build dependencies ----
echo "[1/5] Installing build dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    build-essential cmake pkg-config git \
    libsndfile1-dev libpng-dev libfftw3-dev \
    libpulse-dev libncurses-dev libncurses6 \
    libcodec2-dev librtlsdr-dev libusb-1.0-0-dev \
    liblapack-dev socat \
    gnuradio-dev gr-osmosdr python3-pybind11 \
    python3-numpy python3-waitress python3-requests \
    libspdlog-dev liborc-dev doxygen \
    2>&1 | tail -1

# ---- acarsdec ----
echo ""
echo "[2/5] Building acarsdec..."
cd "$INSTALL_DIR/src"
if [ ! -d "acarsdec" ]; then
    git clone --depth 1 https://github.com/f00b4r0/acarsdec.git
fi
cd acarsdec

# Try to install libacars from apt, fall back to source
if ! dpkg -s libacars-dev &>/dev/null; then
    echo "  Building libacars from source..."
    cd "$INSTALL_DIR/src"
    if [ ! -d "libacars" ]; then
        git clone --depth 1 https://github.com/szpajder/libacars.git
    fi
    cd libacars
    cmake -B build -DCMAKE_BUILD_TYPE=Release
    cmake --build build -j "$(nproc)"
    sudo cmake --install build
    sudo ldconfig
    cd "$INSTALL_DIR/src/acarsdec"
fi

# Install libcjson if needed
if ! dpkg -s libcjson-dev &>/dev/null; then
    sudo apt-get install -y -qq libcjson-dev 2>/dev/null || true
fi

cmake -B build -DCMAKE_BUILD_TYPE=Release \
    -DRTLSDR=ON -DSOAPYSDR=OFF -DAIRSPY=OFF -DALSA=OFF
cmake --build build -j "$(nproc)"
sudo cmake --install build
sudo ldconfig
echo "  acarsdec installed: $(which acarsdec)"

# ---- libmbe (required by DSD-FME) ----
echo ""
echo "[3/6] Building libmbe..."
cd "$INSTALL_DIR/src"
if [ ! -d "mbelib" ]; then
    git clone --depth 1 https://github.com/szechyjs/mbelib.git
fi
cd mbelib
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j "$(nproc)"
sudo cmake --install build
sudo ldconfig

# ---- DSD-FME ----
echo ""
echo "[4/6] Building DSD-FME..."
cd "$INSTALL_DIR/src"
if [ ! -d "dsd-fme" ]; then
    git clone --depth 1 https://github.com/lwvmobile/dsd-fme.git
fi
cd dsd-fme
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j "$(nproc)"
sudo make install
sudo ldconfig
echo "  DSD-FME installed: $(which dsd-fme)"

# ---- OP25 ----
echo ""
echo "[5/6] Building OP25..."
cd "$INSTALL_DIR/src"
if [ ! -d "op25" ]; then
    git clone --depth 1 https://github.com/boatbod/op25.git
fi
cd op25
if [ -f install.sh ]; then
    echo "  Running OP25 install.sh (this may take a while)..."
    yes | ./install.sh 2>&1 | tail -5
else
    mkdir -p build && cd build
    cmake ../
    make -j "$(nproc)"
    sudo make install
    sudo ldconfig
fi
echo "  OP25 installed"

# ---- aptdec ----
echo ""
echo "[6/6] Building aptdec..."
cd "$INSTALL_DIR/src"
if [ ! -d "aptdec" ]; then
    git clone --recursive --depth 1 https://github.com/Xerbo/aptdec.git
fi
cd aptdec
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j "$(nproc)"
sudo cmake --install build
sudo ldconfig
echo "  aptdec installed: $(which aptdec)"

echo ""
echo "=== Installation complete ==="
echo "Installed tools:"
for tool in acarsdec dsd-fme aptdec; do
    if which "$tool" &>/dev/null; then
        echo "  ✓ $tool: $(which $tool)"
    else
        echo "  ✗ $tool: NOT FOUND"
    fi
done
if [ -f "$INSTALL_DIR/src/op25/op25/gr-op25_repeater/apps/rx.py" ]; then
    echo "  ✓ op25: $INSTALL_DIR/src/op25/op25/gr-op25_repeater/apps/rx.py"
else
    echo "  ✗ op25: NOT FOUND"
fi
