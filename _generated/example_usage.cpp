// example_usage.cpp — Demonstrates the reconstructed cerebras_sdkruntime.hpp.
//
// Documentation, not buildable. This file does not link against anything;
// it just shows how the reconstructed API would be used and proves the
// header is well-formed C++. Validate with:
//
//     clang++ -std=c++20 -fsyntax-only _generated/example_usage.cpp
//
// Note: real linking would require:
//   1. The SDK's .so files on LD_LIBRARY_PATH or as -l flags
//   2. A C++ toolchain matching GLIBCXX_3.4.32 / CXXABI_1.3.14 (GCC 13.x)
//   3. Resolved declarations for the forward-declared support types
//      (pybind11::object, nlohmann::json, real IntVector, etc.)
//
// See SKILL-SDKRUNTIME-CPP.md for the toolchain-reality discussion.

#include "cerebras_sdkruntime.hpp"

#include <iostream>
#include <numeric>
#include <stdexcept>
#include <vector>

namespace cb = cerebras;

// -----------------------------------------------------------------------------
//  Scenario 1: memcpy-style host script (CSL layout.csl on the device side).
//  Equivalent of the Python: rt = SdkRuntime("out"); rt.load(); rt.run(); ...
// -----------------------------------------------------------------------------
void run_memcpy_demo(cb::SdkRuntime& rt) {
    constexpr int N = 64;

    // 1. Host-side input.
    std::vector<float> host_in(N);
    std::iota(host_in.begin(), host_in.end(), 0.0f);

    // 2. Memcpy options. RECOVERED FIELD ORDER: streaming, data_type, order, nonblock.
    //    static_assert(sizeof(MemcpyOptions) == 16) in the header guards this.
    const cb::MemcpyOptions h2d_opts{
        /* streaming = */ false,
        /* data_type = */ cb::MemcpyDataType::MEMCPY_32BIT,
        /* order     = */ cb::MemcpyOrder::ROW_MAJOR,
        /* nonblock  = */ false,
    };

    // 3. Resolve the symbol id (host-visible name "A" was @export_name'd in the
    //    CSL layout block + @export_symbol'd in the PE program).
    auto a_id_opt = rt.get_id("A");
    if (!a_id_opt.has_value()) {
        throw std::runtime_error("symbol 'A' not exported by the layout");
    }
    const unsigned short a_id = static_cast<unsigned short>(*a_id_opt);

    // 4. Push to device. C++ signature mirrors the Python kwargs splat.
    auto task = rt.memcpy_h2d(
        a_id,
        host_in.data(),
        /*px=*/0, /*py=*/0,
        /*w=*/1,  /*h=*/1,
        /*elem_per_pe=*/N,
        h2d_opts);
    rt.task_wait(task);

    // 5. RPC into the kernel function.
    auto launch_task = rt.call(
        "compute",
        /*args_u32=*/std::vector<unsigned int>{},   // no args
        h2d_opts);                                  // MemcpyOptions surface
    rt.task_wait(launch_task);

    // 6. Pull result.
    std::vector<float> host_out(N, 0.0f);
    cb::MemcpyOptions d2h_opts = h2d_opts;  // same options for the readback
    auto d2h_task = rt.memcpy_d2h(
        host_out.data(),
        a_id,
        0, 0, 1, 1, N,
        d2h_opts);
    rt.task_wait(d2h_task);
}

// -----------------------------------------------------------------------------
//  Scenario 2: SdkLayout-driven (Python-side fabric layout, but in C++).
//  Mirrors SKILL-SDKLAYOUT.md's worked example.
// -----------------------------------------------------------------------------
cb::SdkCompileArtifacts build_layout(cb::SdkExecutionPlatform const& platform) {
    cb::SdkLayout layout(platform);

    auto region = layout.create_code_region("./add1.csl", "a1", 2, 1);
    region.set_param_all("size", 64);

    // Color/RoutingPosition/EdgeRouteInfo/PortHandle constructors are inline
    // in the SDK and emit no symbols, so the reconstructed header documents
    // their members as comments only. To get a Color value in code that can
    // actually compile against this header, use a factory method that IS
    // recoverable. For Color specifically, that's not in our header either —
    // the example below demonstrates the recoverable subset and notes the
    // gap explicitly. A real C++ user would need the Cerebras-internal
    // headers for these inline classes.

    region.set_param_all("size_extra", 32);   // (name, int) overload IS recoverable

    region.place(4, 4);
    return layout.compile("out");
}

// -----------------------------------------------------------------------------
//  Compile-time invariants the header asserts.
// -----------------------------------------------------------------------------
static_assert(sizeof(cb::MemcpyOptions) == 16,
              "MemcpyOptions layout drift — re-run scripts/refresh_sdk_surface.sh");
static_assert(static_cast<int>(cb::SdkTarget::WSE3) == 1, "SdkTarget enum drift");
static_assert(static_cast<int>(cb::MemcpyDataType::MEMCPY_32BIT) == 0,
              "MemcpyDataType enum drift");
static_assert(static_cast<int>(cb::MemcpyOrder::ROW_MAJOR) == 0, "MemcpyOrder enum drift");

// -----------------------------------------------------------------------------
//  Entry point (proves the file compiles end-to-end).
// -----------------------------------------------------------------------------
int main() {
    // We don't actually construct the runtime here — that would need a real
    // SdkCompileArtifacts + SdkExecutionPlatform built by the SDK's
    // (pybind-only) factory functions. This file proves the *shape* of the
    // API, not its runtime behavior.
    std::cout << "reconstructed cerebras_sdkruntime.hpp parses; "
              << "sizeof(MemcpyOptions) = " << sizeof(cb::MemcpyOptions) << "\n";
    return 0;
}
