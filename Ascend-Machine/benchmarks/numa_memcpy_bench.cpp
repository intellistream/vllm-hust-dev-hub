#include <pthread.h>
#include <sched.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

struct Config {
    int threads = 24;
    size_t bytes_per_thread = 256ULL * 1024ULL * 1024ULL;
    int warmup_iters = 3;
    int iters = 10;
};

struct WorkerState {
    char *dst = nullptr;
    const char *src = nullptr;
    size_t bytes = 0;
};

[[noreturn]] void usage(const char *prog) {
    std::cerr << "Usage: " << prog << " [--threads N] [--size-mb N] [--warmup N] [--iters N]\n";
    std::exit(1);
}

Config parse_args(int argc, char **argv) {
    Config config;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto read_value = [&](const std::string &name) {
            if (i + 1 >= argc) {
                std::cerr << "Missing value for " << name << "\n";
                usage(argv[0]);
            }
            return std::string(argv[++i]);
        };
        if (arg == "--threads") {
            config.threads = std::stoi(read_value(arg));
        } else if (arg == "--size-mb") {
            config.bytes_per_thread = std::stoull(read_value(arg)) * 1024ULL * 1024ULL;
        } else if (arg == "--warmup") {
            config.warmup_iters = std::stoi(read_value(arg));
        } else if (arg == "--iters") {
            config.iters = std::stoi(read_value(arg));
        } else {
            usage(argv[0]);
        }
    }
    return config;
}

std::vector<int> current_allowed_cpus() {
    cpu_set_t cpu_set;
    CPU_ZERO(&cpu_set);
    if (sched_getaffinity(0, sizeof(cpu_set), &cpu_set) != 0) {
        throw std::runtime_error("sched_getaffinity failed");
    }
    std::vector<int> cpus;
    for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
        if (CPU_ISSET(cpu, &cpu_set)) {
            cpus.push_back(cpu);
        }
    }
    if (cpus.empty()) {
        throw std::runtime_error("No CPUs available in current affinity mask");
    }
    return cpus;
}

void pin_to_cpu(int cpu) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (pthread_setaffinity_np(pthread_self(), sizeof(set), &set) != 0) {
        throw std::runtime_error("pthread_setaffinity_np failed");
    }
}

}  // namespace

int main(int argc, char **argv) {
    const Config config = parse_args(argc, argv);
    const std::vector<int> cpus = current_allowed_cpus();

    const size_t total_bytes = config.bytes_per_thread * static_cast<size_t>(config.threads);
    std::vector<char> src(total_bytes);
    std::vector<char> dst(total_bytes);
    std::memset(src.data(), 0x5A, src.size());
    std::memset(dst.data(), 0, dst.size());

    std::vector<WorkerState> workers(config.threads);
    for (int tid = 0; tid < config.threads; ++tid) {
        workers[tid].src = src.data() + static_cast<size_t>(tid) * config.bytes_per_thread;
        workers[tid].dst = dst.data() + static_cast<size_t>(tid) * config.bytes_per_thread;
        workers[tid].bytes = config.bytes_per_thread;
    }

    std::atomic<int> ready{0};
    std::atomic<bool> start{false};
    std::vector<std::thread> threads;
    threads.reserve(config.threads);

    for (int tid = 0; tid < config.threads; ++tid) {
        threads.emplace_back([&, tid]() {
            pin_to_cpu(cpus[static_cast<size_t>(tid) % cpus.size()]);
            for (int iter = 0; iter < config.warmup_iters; ++iter) {
                std::memcpy(workers[tid].dst, workers[tid].src, workers[tid].bytes);
            }
            ready.fetch_add(1, std::memory_order_relaxed);
            while (!start.load(std::memory_order_acquire)) {
            }
            for (int iter = 0; iter < config.iters; ++iter) {
                std::memcpy(workers[tid].dst, workers[tid].src, workers[tid].bytes);
            }
        });
    }

    while (ready.load(std::memory_order_relaxed) != config.threads) {
    }
    auto begin = std::chrono::steady_clock::now();
    start.store(true, std::memory_order_release);
    for (auto &thread : threads) {
        thread.join();
    }
    auto end = std::chrono::steady_clock::now();

    const double seconds = std::chrono::duration<double>(end - begin).count();
    const double bandwidth_gbps = static_cast<double>(total_bytes) * static_cast<double>(config.iters) / seconds / 1e9;

    std::cout << std::fixed << std::setprecision(2);
    std::cout << "threads=" << config.threads << " bytes_per_thread=" << config.bytes_per_thread
              << " iters=" << config.iters << " seconds=" << seconds << " total_bandwidth_GBps=" << bandwidth_gbps
              << "\n";
    return 0;
}