#!/bin/bash
set -e

ARCH=$(uname -m)

# 每次提交代码,请将版本号加1
VER="1.1.0"

SRV_NAME="hexai_pdf_parser"

echo "CURRENT_BRANCH: $1"
echo "CURRENT_PYTHON_VERSION: $2"
TIMESTAMP=""

echo $VER > version

if [[ $1 != "refs/tags/release"* ]]; then
    TIMESTAMP="-$(date +%Y%m%d.%H%M%S)"
fi

PYVER="37m"
if [ "py36" = "$2" ];then
    PYVER="36m"
elif [ "py37" = "$2" ]; then
    PYVER="37m"
elif [ "py38" = "$2" ]; then
    PYVER="38m"
fi

RELEASE_FILE="${SRV_NAME}-${VER}-py3-none-any.whl"
echo $RELEASE_FILE

mkdir -p dist
VER=${VER} python setup.py sdist bdist_wheel
cd dist
ls -lh
cd ..

cp dist/${SRV_NAME}-${VER}-py3-none-any.whl .

echo ${RELEASE_FILE} > "release_filename"
