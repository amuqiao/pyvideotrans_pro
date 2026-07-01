#!/usr/bin/env bash

set -u

section() {
  printf '\n===== %s =====\n' "$1"
}

run_cmd() {
  local label="$1"
  shift

  printf '\n# %s\n$ %s\n' "$label" "$*"
  if command -v "$1" >/dev/null 2>&1; then
    "$@" 2>&1
  else
    printf 'MISSING: command not found: %s\n' "$1"
  fi
}

run_cmd_head() {
  local label="$1"
  local lines="$2"
  shift 2

  printf '\n# %s\n$ %s | head -%s\n' "$label" "$*" "$lines"
  if command -v "$1" >/dev/null 2>&1; then
    "$@" 2>&1 | head -"${lines}"
  else
    printf 'MISSING: command not found: %s\n' "$1"
  fi
}

print_kv() {
  printf '%-22s %s\n' "$1:" "$2"
}

bytes_to_gib() {
  awk -v bytes="$1" 'BEGIN { printf "%.1f GiB", bytes / 1024 / 1024 / 1024 }'
}

section "SUMMARY"
print_kv "生成时间 Generated at" "$(date '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date)"
print_kv "主机名 Hostname" "$(hostname 2>/dev/null || printf 'UNKNOWN')"
print_kv "当前用户 User" "$(id -un 2>/dev/null || whoami 2>/dev/null || printf 'UNKNOWN')"
print_kv "内核架构 Kernel arch" "$(uname -m 2>/dev/null || printf 'UNKNOWN')"

section "系统 / 内核 / 架构 OS / KERNEL / ARCH"
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  print_kv "发行版 Distribution" "${PRETTY_NAME:-UNKNOWN}"
  print_kv "ID" "${ID:-UNKNOWN}"
  print_kv "版本 Version ID" "${VERSION_ID:-UNKNOWN}"
else
  printf 'MISSING: /etc/os-release 不存在或不可读\n'
fi
run_cmd "内核信息 kernel" uname -a
run_cmd "CPU 架构 cpu arch" arch

section "显卡 / NVIDIA / CUDA GPU / NVIDIA / CUDA"
if command -v nvidia-smi >/dev/null 2>&1; then
  run_cmd "NVIDIA 完整信息 nvidia full" nvidia-smi
  run_cmd "NVIDIA 简洁信息 nvidia compact" nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

  driver_cuda="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: \([^ |]*\).*/\1/p' | head -1)"
  if [ -n "${driver_cuda}" ]; then
    print_kv "驱动支持 Driver CUDA max" "${driver_cuda}"
    if awk -v version="${driver_cuda}" 'BEGIN {
      split(version, parts, ".")
      major = parts[1] + 0
      minor = parts[2] + 0
      exit !((major > 12) || (major == 12 && minor >= 8))
    }'; then
      print_kv "Torch cu128 匹配" "OK: 驱动支持 CUDA >= 12.8"
    else
      print_kv "Torch cu128 匹配" "CHECK: 驱动支持的 CUDA 低于 12.8"
    fi
  else
    print_kv "驱动支持 Driver CUDA max" "UNKNOWN: 无法从 nvidia-smi 输出解析"
  fi
else
  printf '\n$ nvidia-smi\n'
  printf 'MISSING: command not found: nvidia-smi\n'
  printf '含义 Meaning: 可能没装 NVIDIA 驱动、PATH 不完整，或服务器没有 NVIDIA GPU。\n'
fi

if command -v lspci >/dev/null 2>&1; then
  printf '\n$ lspci | grep -i -E "vga|3d|nvidia"\n'
  lspci | grep -i -E "vga|3d|nvidia" 2>&1 || printf 'NO MATCH: lspci 没看到 VGA/3D/NVIDIA 设备行\n'
else
  printf '\n$ lspci | grep -i -E "vga|3d|nvidia"\n'
  printf 'MISSING: command not found: lspci\n'
fi

run_cmd "CUDA 编译器 nvcc" nvcc --version

section "CPU / 内存 / 磁盘 CPU / MEMORY / DISK"
run_cmd "CPU 核心数 cpu cores" nproc
run_cmd "内存 memory" free -h
run_cmd "根分区磁盘 root disk" df -h /
if [ -d "$PWD" ]; then
  run_cmd "当前目录磁盘 current dir disk" df -h "$PWD"
fi

if [ -r /proc/meminfo ]; then
  mem_kib="$(awk '/MemTotal:/ { print $2 }' /proc/meminfo)"
  if [ -n "${mem_kib}" ]; then
    mem_bytes=$((mem_kib * 1024))
    print_kv "内存总量 Memory total" "$(bytes_to_gib "${mem_bytes}")"
  fi
fi

section "Python / 项目工具 PROJECT TOOLS"
run_cmd "python3" python3 --version
run_cmd "python" python --version
run_cmd "pip3" pip3 --version
run_cmd "uv" uv --version
run_cmd "git" git --version
run_cmd "curl" curl --version
run_cmd_head "ffmpeg" 8 ffmpeg -version

section "PyTorch CUDA 检查 PYTORCH CUDA CHECK"
if command -v python3 >/dev/null 2>&1; then
  PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
try:
    import torch
except Exception as exc:
    print(f"torch import: MISSING/FAILED 缺失或导入失败: {exc}")
else:
    print(f"torch version 版本: {torch.__version__}")
    print(f"torch cuda available CUDA 是否可用: {torch.cuda.is_available()}")
    print(f"torch cuda build 编译 CUDA 版本: {torch.version.cuda}")
    if torch.cuda.is_available():
        print(f"torch gpu count GPU 数量: {torch.cuda.device_count()}")
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            total_gib = props.total_memory / 1024 / 1024 / 1024
            print(f"torch gpu {index}: {props.name}, {total_gib:.1f} GiB")
PY
else
  printf 'MISSING: command not found: python3\n'
fi

section "容器 / 服务工具 CONTAINER / SERVICE TOOLS"
run_cmd "docker" docker --version
if command -v docker >/dev/null 2>&1; then
  run_cmd "docker compose" docker compose version
fi
run_cmd "systemd" systemctl --version

section "网络快速检查 NETWORK QUICK CHECK"
if command -v curl >/dev/null 2>&1; then
  printf '\n$ curl -sS -I --max-time 8 https://pypi.org/simple/\n'
  curl -sS -I --max-time 8 https://pypi.org/simple/ 2>&1 | head -20
else
  printf 'MISSING: command not found: curl\n'
fi

section "解读提示 INTERPRETATION HINTS"
cat <<'EOF'
- nvidia-smi 有输出：说明 NVIDIA 驱动可见；显存足够时优先走 CUDA 部署。
- nvidia-smi 里的 CUDA Version：是当前驱动支持的最高 CUDA runtime 版本。
- nvcc --version：是 CUDA toolkit 编译器版本；只用 PyTorch wheel 时可以没有 nvcc。
- 本项目如果使用 torch CUDA 12.8 wheel，Driver CUDA max 建议 >= 12.8。
- 如果 nvidia-smi 缺失但 lspci 能看到 NVIDIA，通常是驱动未安装或未正确加载。
- 跑 Whisper/视频大模型时，要同时看 GPU 显存、系统内存和磁盘剩余空间。
EOF
