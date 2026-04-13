#include <acl/acl.h>
#include <pthread.h>
#include <sched.h>

#include <chrono>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

struct Config {
    std::string mode = "h2d";
    std::vector<int> devices;
    std::vector<std::string> affinity_lists;
    size_t bytes = 1024ULL * 1024ULL * 1024ULL;
    int warmup_iters = 5;
    int iters = 20;
};

struct WorkerResult {
    int device = -1;
    double seconds = 0.0;
    double gbps = 0.0;
    std::string error;
};

[[noreturn]] void usage(const char *prog) {
    std::cerr
        << "Usage: " << prog
        << " --mode <h2d|d2h> --devices <id[,id...]> [--affinity-lists <cpu-list[/cpu-list...]>]"
        << " [--size-mb <mb>] [--warmup <iters>] [--iters <iters>]\n";
    std::exit(1);
}

std::vector<std::string> split(const std::string &value, char delim) {
    std::vector<std::string> out;
    std::stringstream stream(value);
    std::string part;
    while (std::getline(stream, part, delim)) {
        if (!part.empty()) {
            out.push_back(part);
        }
    }
    return out;
}

std::vector<int> parse_int_list(const std::string &value) {
    std::vector<int> result;
    for (const auto &item : split(value, ',')) {
        result.push_back(std::stoi(item));
    }
    return result;
}

cpu_set_t parse_cpu_set(const std::string &value) {
    cpu_set_t set;
    CPU_ZERO(&set);
    for (const auto &token : split(value, ',')) {
        auto dash = token.find('-');
        if (dash == std::string::npos) {
            CPU_SET(std::stoi(token), &set);
            continue;
        }
        int begin = std::stoi(token.substr(0, dash));
        int end = std::stoi(token.substr(dash + 1));
        for (int cpu = begin; cpu <= end; ++cpu) {
            CPU_SET(cpu, &set);
        }
    }
    return set;
}

void check_acl(aclError rc, const char *expr) {
    if (rc != ACL_SUCCESS) {
        std::ostringstream stream;
        stream << expr << " failed with aclError=" << rc;
        throw std::runtime_error(stream.str());
    }
}

Config parse_args(int argc, char **argv) {
    Config config;
    for (int index = 1; index < argc; ++index) {
        std::string arg = argv[index];
        auto need_value = [&](const std::string &name) -> std::string {
            if (index + 1 >= argc) {
                std::cerr << "Missing value for " << name << "\n";
                usage(argv[0]);
            }
            return argv[++index];
        };

        if (arg == "--mode") {
            config.mode = need_value(arg);
        } else if (arg == "--devices") {
            config.devices = parse_int_list(need_value(arg));
        } else if (arg == "--affinity-lists") {
            config.affinity_lists = split(need_value(arg), '/');
        } else if (arg == "--size-mb") {
            config.bytes = static_cast<size_t>(std::stoull(need_value(arg))) * 1024ULL * 1024ULL;
        } else if (arg == "--warmup") {
            config.warmup_iters = std::stoi(need_value(arg));
        } else if (arg == "--iters") {
            config.iters = std::stoi(need_value(arg));
        } else {
            usage(argv[0]);
        }
    }

    if (config.devices.empty()) {
        std::cerr << "At least one device is required\n";
        usage(argv[0]);
    }
    if (config.mode != "h2d" && config.mode != "d2h") {
        std::cerr << "Unsupported mode: " << config.mode << "\n";
        usage(argv[0]);
    }
    if (!config.affinity_lists.empty() && config.affinity_lists.size() != config.devices.size()) {
        std::cerr << "Affinity list count must match device count\n";
        usage(argv[0]);
    }
    return config;
}

void run_worker(const Config &config, size_t worker_index, WorkerResult *result) {
    const int device = config.devices.at(worker_index);
    result->device = device;

    aclrtContext context = nullptr;
    aclrtStream stream = nullptr;
    void *host_buffer = nullptr;
    void *device_buffer = nullptr;

    try {
        if (!config.affinity_lists.empty()) {
            cpu_set_t set = parse_cpu_set(config.affinity_lists.at(worker_index));
            if (pthread_setaffinity_np(pthread_self(), sizeof(set), &set) != 0) {
                throw std::runtime_error("pthread_setaffinity_np failed");
            }
        }

        check_acl(aclrtSetDevice(device), "aclrtSetDevice");
        check_acl(aclrtCreateContext(&context, device), "aclrtCreateContext");
        check_acl(aclrtSetCurrentContext(context), "aclrtSetCurrentContext");
        check_acl(aclrtCreateStream(&stream), "aclrtCreateStream");

        check_acl(aclrtMallocHost(&host_buffer, config.bytes), "aclrtMallocHost");
        check_acl(aclrtMalloc(&device_buffer, config.bytes, ACL_MEM_MALLOC_HUGE_FIRST), "aclrtMalloc");

        std::memset(host_buffer, 0x5A, config.bytes);
        check_acl(aclrtMemset(device_buffer, config.bytes, 0, config.bytes), "aclrtMemset");

        for (int iter = 0; iter < config.warmup_iters; ++iter) {
            if (config.mode == "h2d") {
                check_acl(
                    aclrtMemcpyAsync(device_buffer, config.bytes, host_buffer, config.bytes, ACL_MEMCPY_HOST_TO_DEVICE, stream),
                    "aclrtMemcpyAsync(H2D)");
            } else {
                check_acl(
                    aclrtMemcpyAsync(host_buffer, config.bytes, device_buffer, config.bytes, ACL_MEMCPY_DEVICE_TO_HOST, stream),
                    "aclrtMemcpyAsync(D2H)");
            }
        }
        check_acl(aclrtSynchronizeStream(stream), "aclrtSynchronizeStream(warmup)");

        auto begin = std::chrono::steady_clock::now();
        for (int iter = 0; iter < config.iters; ++iter) {
            if (config.mode == "h2d") {
                check_acl(
                    aclrtMemcpyAsync(device_buffer, config.bytes, host_buffer, config.bytes, ACL_MEMCPY_HOST_TO_DEVICE, stream),
                    "aclrtMemcpyAsync(H2D)");
            } else {
                check_acl(
                    aclrtMemcpyAsync(host_buffer, config.bytes, device_buffer, config.bytes, ACL_MEMCPY_DEVICE_TO_HOST, stream),
                    "aclrtMemcpyAsync(D2H)");
            }
        }
        check_acl(aclrtSynchronizeStream(stream), "aclrtSynchronizeStream(measure)");
        auto end = std::chrono::steady_clock::now();

        result->seconds = std::chrono::duration<double>(end - begin).count();
        result->gbps = (static_cast<double>(config.bytes) * static_cast<double>(config.iters)) /
                       result->seconds / 1e9;
    } catch (const std::exception &ex) {
        result->error = ex.what();
    }

    if (device_buffer != nullptr) {
        aclrtFree(device_buffer);
    }
    if (host_buffer != nullptr) {
        aclrtFreeHost(host_buffer);
    }
    if (stream != nullptr) {
        aclrtDestroyStream(stream);
    }
    if (context != nullptr) {
        aclrtDestroyContext(context);
    }
}

}  // namespace

int main(int argc, char **argv) {
    const Config config = parse_args(argc, argv);
    check_acl(aclInit(nullptr), "aclInit");

    std::vector<WorkerResult> results(config.devices.size());
    std::vector<std::thread> workers;
    workers.reserve(config.devices.size());
    for (size_t index = 0; index < config.devices.size(); ++index) {
        workers.emplace_back(run_worker, std::cref(config), index, &results[index]);
    }
    for (auto &worker : workers) {
        worker.join();
    }

    aclFinalize();

    bool has_error = false;
    double aggregate_gbps = 0.0;
    double max_seconds = 0.0;
    for (const auto &result : results) {
        if (!result.error.empty()) {
            has_error = true;
            std::cerr << "device=" << result.device << " error=" << result.error << "\n";
            continue;
        }
        aggregate_gbps += result.gbps;
        if (result.seconds > max_seconds) {
            max_seconds = result.seconds;
        }
    }

    std::cout << std::fixed << std::setprecision(2);
    std::cout << "mode=" << config.mode << " bytes_per_device=" << config.bytes << " iters=" << config.iters
              << " devices=";
    for (size_t index = 0; index < config.devices.size(); ++index) {
        if (index != 0) {
            std::cout << ",";
        }
        std::cout << config.devices[index];
    }
    std::cout << "\n";

    for (const auto &result : results) {
        if (!result.error.empty()) {
            continue;
        }
        std::cout << "per_device device=" << result.device << " seconds=" << result.seconds
                  << " bandwidth_GBps=" << result.gbps << "\n";
    }

    if (!has_error) {
        const double total_bytes = static_cast<double>(config.bytes) * static_cast<double>(config.iters) *
                                   static_cast<double>(config.devices.size());
        const double aggregate_wall_gbps = total_bytes / max_seconds / 1e9;
        std::cout << "aggregate_sum_GBps=" << aggregate_gbps << "\n";
        std::cout << "aggregate_wall_GBps=" << aggregate_wall_gbps << "\n";
    }

    return has_error ? 1 : 0;
}