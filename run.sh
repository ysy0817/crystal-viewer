#!/usr/bin/env bash
# 不安装也能直接运行：把 src 加入 PYTHONPATH 后调用模块入口。
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m crystal_viewer "$@"
