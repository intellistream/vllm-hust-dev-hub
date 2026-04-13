#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
RUN_ID=${1:-$(date +%Y%m%d_%H%M%S)}
OUT_DIR="$ROOT_DIR/results/$RUN_ID"
BUILD_DIR="$ROOT_DIR/build"
HCCL_BUILD_DIR="$BUILD_DIR/hccl_test"
ACL_BENCH_BIN="$BUILD_DIR/acl_copy_bench"
NUMA_MEMCPY_BIN="$BUILD_DIR/numa_memcpy_bench"
FIO_FILE=${FIO_FILE:-/data/ascend_machine_nvme_bw.bin}
MPI_HOME=${MPI_HOME:-}
MPI_INC_DIR=${MPI_INC_DIR:-}
MPI_LIB_DIR=${MPI_LIB_DIR:-}
ASCEND_TOOLKIT_HOME=${ASCEND_TOOLKIT_HOME:-/usr/local/Ascend/ascend-toolkit/latest}
ASCEND_HCCL_SRC=${ASCEND_HCCL_SRC:-$ASCEND_TOOLKIT_HOME/tools/hccl_test}
NPU_SMI_BIN=${NPU_SMI_BIN:-}
CLEAN_ENV_PATH="$ASCEND_TOOLKIT_HOME/bin:$ASCEND_TOOLKIT_HOME/compiler/ccec_compiler/bin:$ASCEND_TOOLKIT_HOME/tools/ccec_compiler/bin:/usr/bin:/usr/sbin:/bin:/sbin"
CLEAN_ENV_LD_LIBRARY_PATH="$ASCEND_TOOLKIT_HOME/lib64:$ASCEND_TOOLKIT_HOME/lib64/plugin/opskernel:$ASCEND_TOOLKIT_HOME/lib64/plugin/nnengine:$ASCEND_TOOLKIT_HOME/opp/built-in/op_impl/ai_core/tbe/op_tiling/lib/linux/$(arch):$ASCEND_TOOLKIT_HOME/tools/aml/lib64:$ASCEND_TOOLKIT_HOME/tools/aml/lib64/plugin:/usr/local/Ascend/driver/lib64:/usr/local/Ascend/driver/lib64/common:/usr/local/Ascend/driver/lib64/driver"

mkdir -p "$OUT_DIR"
mkdir -p "$BUILD_DIR"
ln -sfn "$RUN_ID" "$ROOT_DIR/results/latest"

export ASCEND_TOOLKIT_HOME
export LD_LIBRARY_PATH="$ASCEND_TOOLKIT_HOME/lib64:$ASCEND_TOOLKIT_HOME/lib64/plugin/opskernel:$ASCEND_TOOLKIT_HOME/lib64/plugin/nnengine:$ASCEND_TOOLKIT_HOME/opp/built-in/op_impl/ai_core/tbe/op_tiling/lib/linux/$(arch):$ASCEND_TOOLKIT_HOME/tools/aml/lib64:$ASCEND_TOOLKIT_HOME/tools/aml/lib64/plugin:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$ASCEND_TOOLKIT_HOME/python/site-packages:$ASCEND_TOOLKIT_HOME/opp/built-in/op_impl/ai_core/tbe:${PYTHONPATH:-}"
export PATH="$ASCEND_TOOLKIT_HOME/bin:$ASCEND_TOOLKIT_HOME/compiler/ccec_compiler/bin:$ASCEND_TOOLKIT_HOME/tools/ccec_compiler/bin:${PATH}"
export ASCEND_AICPU_PATH="$ASCEND_TOOLKIT_HOME"
export ASCEND_OPP_PATH="$ASCEND_TOOLKIT_HOME/opp"
export TOOLCHAIN_HOME="$ASCEND_TOOLKIT_HOME/toolkit"
export ASCEND_HOME_PATH="$ASCEND_TOOLKIT_HOME"

log() {
    printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

resolve_npu_smi_bin() {
    if [[ -n "$NPU_SMI_BIN" ]]; then
        echo "$NPU_SMI_BIN"
        return 0
    fi
    if command -v npu-smi >/dev/null 2>&1; then
        command -v npu-smi
        return 0
    fi
    if [[ -x /home/shuhao/.local/bin/npu-smi ]]; then
        echo /home/shuhao/.local/bin/npu-smi
        return 0
    fi
    return 1
}

capture_best_effort() {
    local outfile=$1
    shift
    if "$@" > "$outfile" 2>&1; then
        return 0
    fi

    local rc=$?
    {
        echo "COMMAND_FAILED exit_code=$rc"
        echo "COMMAND: $*"
        echo
        cat "$outfile"
    } > "$outfile.tmp"
    mv "$outfile.tmp" "$outfile"
    return 0
}

run_with_privilege() {
    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
        return 0
    fi
    if [[ $(id -u) -eq 0 ]]; then
        "$@"
        return 0
    fi

    echo "sudo is required to run: $*" >&2
    return 1
}

resolve_mpi_layout() {
    local mpi_roots=()
    local root

    if [[ -n "$MPI_HOME" ]]; then
        mpi_roots+=("$MPI_HOME")
    fi

    mpi_roots+=(
        /usr/lib/aarch64-linux-gnu/openmpi
        /usr/lib/x86_64-linux-gnu/openmpi
        /usr/local/openmpi
        /opt/openmpi
    )

    for root in "${mpi_roots[@]}"; do
        if [[ -z "$MPI_INC_DIR" && -f "$root/include/mpi.h" ]]; then
            MPI_INC_DIR="$root/include"
        fi
        if [[ -z "$MPI_LIB_DIR" ]]; then
            if [[ -f "$root/lib/libmpi.so" || -f "$root/lib/libmpi.a" ]]; then
                MPI_LIB_DIR="$root/lib"
            elif [[ -f "$root/lib64/libmpi.so" || -f "$root/lib64/libmpi.a" ]]; then
                MPI_LIB_DIR="$root/lib64"
            fi
        fi
        if [[ -n "$MPI_INC_DIR" && -n "$MPI_LIB_DIR" ]]; then
            return 0
        fi
    done

    return 1
}

compile_hccl_binary() {
    local output_name=$1
    local source_name=$2

    g++ \
        -std=c++11 \
        -Werror \
        -fstack-protector-strong \
        -fPIE -pie \
        -O2 \
        -s \
        -Wl,-z,relro \
        -Wl,-z,now \
        -Wl,-z,noexecstack \
        -Wl,--copy-dt-needed-entries \
        "$HCCL_BUILD_DIR"/common/src/*.cc \
        "$HCCL_BUILD_DIR/opbase_test/$source_name" \
        -I"$HCCL_BUILD_DIR/common/src" \
        -I"$ASCEND_TOOLKIT_HOME/include" \
        -I"$MPI_INC_DIR" \
        -I"$HCCL_BUILD_DIR/opbase_test" \
        -L"$ASCEND_TOOLKIT_HOME/lib64" \
        -Wl,-rpath,"$ASCEND_TOOLKIT_HOME/lib64" \
        -L"$MPI_LIB_DIR" \
        -lhccl_v2 \
        -lacl_rt \
        -lmpi \
        -lmpi_cxx \
        -lmsprofiler \
        -o "$HCCL_BUILD_DIR/bin/$output_name"
}

run_clean_env() {
    env -i \
        HOME="$HOME" \
        USER="${USER:-shuhao}" \
        LOGNAME="${LOGNAME:-shuhao}" \
        SHELL=/bin/bash \
        TERM="${TERM:-xterm-256color}" \
        PATH="$CLEAN_ENV_PATH" \
        LD_LIBRARY_PATH="$CLEAN_ENV_LD_LIBRARY_PATH" \
        ASCEND_TOOLKIT_HOME="$ASCEND_TOOLKIT_HOME" \
        ASCEND_AICPU_PATH="$ASCEND_TOOLKIT_HOME" \
        ASCEND_OPP_PATH="$ASCEND_TOOLKIT_HOME/opp" \
        TOOLCHAIN_HOME="$ASCEND_TOOLKIT_HOME/toolkit" \
        ASCEND_HOME_PATH="$ASCEND_TOOLKIT_HOME" \
        OMPI_ALLOW_RUN_AS_ROOT=1 \
        OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
        "$@"
}

capture_static_inventory() {
    log "Capturing static inventory"
    local npu_smi_path
    uname -a > "$OUT_DIR/uname.txt"
    hostname > "$OUT_DIR/hostname.txt"
    lscpu > "$OUT_DIR/lscpu.txt"
    numactl -H > "$OUT_DIR/numactl-H.txt"
    free -h > "$OUT_DIR/free-h.txt"
    lsmem > "$OUT_DIR/lsmem.txt"
    lsblk -a -o NAME,MAJ:MIN,SIZE,ROTA,TYPE,MOUNTPOINT,MODEL,VENDOR,SERIAL > "$OUT_DIR/lsblk.txt"
    lspci -D > "$OUT_DIR/lspci.txt"
    if npu_smi_path=$(resolve_npu_smi_bin); then
        run_clean_env "$npu_smi_path" -v > "$OUT_DIR/npu-smi-version.txt"
        run_clean_env "$npu_smi_path" info > "$OUT_DIR/npu-smi-info.txt"
        capture_best_effort "$OUT_DIR/npu-smi-topo.txt" run_clean_env "$npu_smi_path" topo -m
    else
        printf 'npu-smi binary not found\n' > "$OUT_DIR/npu-smi-version.txt"
        printf 'npu-smi binary not found\n' > "$OUT_DIR/npu-smi-info.txt"
        printf 'npu-smi topo not collected because npu-smi binary was not found\n' > "$OUT_DIR/npu-smi-topo.txt"
    fi
    ip -br link > "$OUT_DIR/ip-link.txt"
    ip -br addr > "$OUT_DIR/ip-addr.txt"
    for nic in enp189s0f0 enp189s0f1 enp189s0f2 enp189s0f3 enp195s0f0np0 enp195s0f1np1 enp61s0f0 enp61s0f1 enp61s0f2 enp61s0f3 enp67s0f0np0 enp67s0f1np1; do
        {
            echo "=== $nic ==="
            ethtool "$nic" | grep -E 'Speed|Duplex|Port|Link detected' || true
            echo
        }
    done > "$OUT_DIR/ethtool-summary.txt"
}

build_numa_memcpy_bench() {
    log "Building numa_memcpy_bench"
    g++ -O3 -std=c++17 "$SCRIPT_DIR/numa_memcpy_bench.cpp" -lpthread -o "$NUMA_MEMCPY_BIN"
}

run_memcpy_case() {
    local name=$1
    local cpu_node=$2
    local mem_node=$3
    log "Running memcpy case $name"
    numactl --cpunodebind="$cpu_node" --membind="$mem_node" "$NUMA_MEMCPY_BIN" --threads 24 --size-mb 256 --warmup 3 --iters 20 > "$OUT_DIR/$name.memcpy.txt"
}

run_mbw_case() {
    local name=$1
    local cpu_node=$2
    local mem_node=$3
    local size_mb=$4
    log "Running mbw case $name"
    numactl --cpunodebind="$cpu_node" --membind="$mem_node" mbw -n 3 "$size_mb" > "$OUT_DIR/$name.mbw.txt"
}

prepare_fio_file() {
    log "Preparing fio file at $FIO_FILE"
    mkdir -p "$(dirname -- "$FIO_FILE")"
    run_with_privilege /usr/bin/fio \
        --name=prepare \
        --filename="$FIO_FILE" \
        --rw=write \
        --bs=1M \
        --iodepth=32 \
        --ioengine=libaio \
        --direct=1 \
        --size=16G \
        --numjobs=1 \
        --group_reporting \
        --output-format=json \
        > "$OUT_DIR/fio-prepare.json"
}

run_fio_read() {
    log "Running fio sequential read"
    run_with_privilege numactl --cpunodebind=4 --membind=4 /usr/bin/fio \
        --name=seqread \
        --filename="$FIO_FILE" \
        --rw=read \
        --bs=1M \
        --iodepth=32 \
        --ioengine=libaio \
        --direct=1 \
        --size=16G \
        --runtime=20 \
        --time_based=1 \
        --numjobs=1 \
        --group_reporting \
        --output-format=json \
        > "$OUT_DIR/fio-seqread.json"
}

build_acl_copy_bench() {
    log "Building acl_copy_bench"
    g++ -O2 -std=c++17 \
        "$SCRIPT_DIR/acl_copy_bench.cpp" \
        -I"$ASCEND_TOOLKIT_HOME/include" \
        -L"$ASCEND_TOOLKIT_HOME/lib64" \
        -Wl,-rpath,"$ASCEND_TOOLKIT_HOME/lib64" \
        -lascendcl -lpthread \
        -o "$ACL_BENCH_BIN"
}

run_acl_copy_cases() {
    log "Running ACL H2D/D2H cases"
    run_clean_env "$ACL_BENCH_BIN" --mode d2h --devices 4 --size-mb 1024 --warmup 5 --iters 20 --affinity-lists 0-23 > "$OUT_DIR/acl-copy-single-d2h.txt"
    run_clean_env "$ACL_BENCH_BIN" --mode h2d --devices 4 --size-mb 1024 --warmup 5 --iters 20 --affinity-lists 0-23 > "$OUT_DIR/acl-copy-single-h2d.txt"
    run_clean_env "$ACL_BENCH_BIN" --mode h2d --devices 4,5 --size-mb 1024 --warmup 5 --iters 20 --affinity-lists 0-23/0-23 > "$OUT_DIR/acl-copy-dual-h2d.txt"
    run_clean_env "$ACL_BENCH_BIN" --mode h2d --devices 0,1,2,3,4,5,6,7 --size-mb 512 --warmup 5 --iters 20 --affinity-lists 144-167/144-167/96-119/96-119/0-23/0-23/48-71/48-71 > "$OUT_DIR/acl-copy-all8-h2d.txt"
}

build_hccl_test() {
    log "Building hccl_test"

    if ! resolve_mpi_layout; then
        cat > "$OUT_DIR/hccl-build.txt" <<EOF
HCCL_BUILD_FAILED exit_code=127
reason=OpenMPI headers or libraries were not found
MPI_HOME=${MPI_HOME:-unset}
MPI_INC_DIR=${MPI_INC_DIR:-unset}
MPI_LIB_DIR=${MPI_LIB_DIR:-unset}
expected_one_of=/usr/lib/aarch64-linux-gnu/openmpi,/usr/lib/x86_64-linux-gnu/openmpi,/usr/local/openmpi,/opt/openmpi
EOF
        return 1
    fi

    rm -rf "$HCCL_BUILD_DIR"
    cp -rL "$ASCEND_HCCL_SRC" "$HCCL_BUILD_DIR"

    if {
        cp "$SCRIPT_DIR/hccl_compat.h" "$HCCL_BUILD_DIR/common/src/hccl_compat.h"
        cp "$SCRIPT_DIR/hccl_compat.cc" "$HCCL_BUILD_DIR/common/src/hccl_compat.cc"
        sed -i 's|#include "hccl/hccl.h"|#include "hccl_compat.h"|' "$HCCL_BUILD_DIR/common/src/hccl_test_common.h"
        sed -i 's|strcmp(reinterpret_cast<const char *>(&comm_id), "invalid") == 0|memcmp(&comm_id, "invalid", sizeof("invalid") - 1) == 0|' "$HCCL_BUILD_DIR/common/src/hccl_test_common.cc"
        mkdir -p "$HCCL_BUILD_DIR/bin"
        compile_hccl_binary all_gather_test hccl_allgather_rootinfo_test.cc
        compile_hccl_binary all_reduce_test hccl_allreduce_rootinfo_test.cc
        compile_hccl_binary alltoall_test hccl_alltoall_rootinfo_test.cc
        compile_hccl_binary broadcast_test hccl_brocast_rootinfo_test.cc
        compile_hccl_binary reduce_scatter_test hccl_reducescatter_rootinfo_test.cc
        compile_hccl_binary reduce_test hccl_reduce_rootinfo_test.cc
        compile_hccl_binary scatter_test hccl_scatter_rootinfo_test.cc
    } > "$OUT_DIR/hccl-build.txt" 2>&1; then
        return 0
    else
        local rc=$?
        {
            echo "HCCL_BUILD_FAILED exit_code=$rc"
            echo "ASCEND_HCCL_SRC=$ASCEND_HCCL_SRC"
            echo "ASCEND_TOOLKIT_HOME=$ASCEND_TOOLKIT_HOME"
            echo "MPI_INC_DIR=$MPI_INC_DIR"
            echo "MPI_LIB_DIR=$MPI_LIB_DIR"
            echo
            cat "$OUT_DIR/hccl-build.txt"
        } > "$OUT_DIR/hccl-build.txt.tmp"
        mv "$OUT_DIR/hccl-build.txt.tmp" "$OUT_DIR/hccl-build.txt"
        return 1
    fi
}

run_hccl_case() {
    local binary=$1
    local outfile=$2
    local extra_args=()
    shift 2
    if (($# > 0)); then
        extra_args=("$@")
    fi
    log "Running hccl case $binary"
    run_clean_env mpirun --bind-to none -n 8 "$HCCL_BUILD_DIR/bin/$binary" -b 64M -e 64M -i 0 -p 8 -d fp32 -n 5 -w 2 -c 0 "${extra_args[@]}" > "$OUT_DIR/$outfile"
}

run_hccl_cases() {
    run_hccl_case all_gather_test hccl-all-gather.txt
    run_hccl_case reduce_scatter_test hccl-reduce-scatter.txt
    run_hccl_case scatter_test hccl-scatter.txt -r 0
    run_hccl_case alltoall_test hccl-alltoall.txt
    run_hccl_case all_reduce_test hccl-all-reduce.txt -o sum
    run_hccl_case broadcast_test hccl-broadcast.txt -r 1
    run_hccl_case reduce_test hccl-reduce.txt -r 1 -o sum
}

main() {
    capture_static_inventory
    build_numa_memcpy_bench
    run_memcpy_case local-ddr-node0 0 0
    run_memcpy_case same-socket-remote-node1 0 1
    run_memcpy_case cross-socket-remote-node4 0 4
    run_mbw_case local-ddr-node0 0 0 4096
    run_mbw_case same-socket-remote-node1 0 1 4096
    run_mbw_case cross-socket-remote-node4 0 4 4096
    prepare_fio_file
    run_fio_read
    build_acl_copy_bench
    run_acl_copy_cases
    if build_hccl_test; then
        run_hccl_cases
    else
        log "Skipping HCCL cases because hccl_test build failed; see $OUT_DIR/hccl-build.txt"
    fi
    log "Results written to $OUT_DIR"
}

main "$@"