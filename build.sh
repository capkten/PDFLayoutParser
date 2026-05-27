#!/bin/bash
set -e

ARCH=$(uname -m)

# 每次提交代码,请将版本号加1
VER="0.1.0"

SRV_NAME="hexai_pdf_parser"

echo "CURRENT_BRANCH: $1"
echo "CURRENT_PYTHON_VERSION: $2"

echo $VER > version

TIMESTAMP=""
if [[ $1 != "refs/tags/release"* ]]; then
    TIMESTAMP="-$(date +%Y%m%d.%H%M%S)"
fi

# 更新 pyproject.toml 中的版本号
sed -i "s/^version = .*/version = \"${VER}\"/" pyproject.toml

RELEASE_FILE="${SRV_NAME}-${VER}-py3-none-any.whl"
echo "Building: ${RELEASE_FILE}"

# 清理旧构建产物
rm -rf build dist *.egg-info src/*.egg-info

# 构建 wheel
python -m build --wheel

cd dist
ls -lh
cd ..

# 复制 wheel 到项目根目录（CI 产物收集用）
cp dist/${RELEASE_FILE} .

echo ${RELEASE_FILE} > "release_filename"

echo "Build complete: ${RELEASE_FILE}"
