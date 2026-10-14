#!/usr/bin/env bash
# Build the AgentCore Runtime code package (arm64 / Python 3.12) into build/agent.zip.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf build/pkg && mkdir -p build/pkg
uv pip install -q --target build/pkg --python-platform aarch64-manylinux_2_28 --python-version 3.12 \
  --only-binary=:all: -r agents/requirements.txt
cp agents/*.py build/pkg/
find build/pkg -name '__pycache__' -prune -exec rm -rf {} +
(cd build/pkg && rm -f ../agent.zip && zip -qr9 ../agent.zip .)
echo "build/agent.zip $(du -h build/agent.zip | cut -f1) (unzipped $(du -sh build/pkg | cut -f1))"
