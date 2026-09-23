#!/bin/bash
set -e

# 每次提交代码,请将版本号加1
VER="1.1.2"

SRV_NAME="hexai_pdf_parser"

echo "CURRENT_BRANCH: $1"
echo "CURRENT_PYTHON_VERSION: $2"
TIMESTAMP=""

echo $VER > version

if [[ $1 != "refs/tags/release"* ]]; then
    TIMESTAMP="-$(date +%Y%m%d.%H%M%S)"
fi

mkdir -p dist
maturin build --release --out dist
maturin sdist --out dist

shopt -s nullglob
WHEELS=("dist/${SRV_NAME}-${VER}-cp37-abi3-"*.whl)
if [ ${#WHEELS[@]} -ne 1 ]; then
    echo "Expected one cp37-abi3 wheel for ${SRV_NAME} ${VER}; found ${#WHEELS[@]}" >&2
    exit 1
fi

RELEASE_FILE=$(basename "${WHEELS[0]}")
echo "$RELEASE_FILE"
cp "${WHEELS[0]}" .

echo "$RELEASE_FILE" > "release_filename"
