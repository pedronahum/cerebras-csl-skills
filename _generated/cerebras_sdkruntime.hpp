// ===========================================================================
//  cerebras_sdkruntime.hpp — RECONSTRUCTED FROM SDK 2.10.0
//  =====================  NOT CEREBRAS-AUTHORITATIVE  =====================
//
//  This header is a documentation artifact. Cerebras does not ship it.
//  Treat it as the readable form of the SDK runtime's symbol surface, not
//  as something you can build against.
//
//  Pinned to:
//    SDK version : 2.10.0
//    Build       : 202604101435
//    Git short   : 4586d3f0d8
//    SIF         : sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
//    SIF sha256  : 4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
//    Extracted   : 2026-05-26T14:14:52Z
//
//  Sources used to reconstruct:
//    (a) `nm -D --demangle` against 10 .so libraries in /cbcore/lib/ — for
//        every member-function signature (parameter types, const-ness,
//        overload set). See _generated/sdkruntime-symbols.txt.
//    (b) pybind11 introspection of cerebras.sdk.runtime.sdkruntimepybind —
//        for enum names+values, the user-facing-method subset, and the
//        kwarg names that pybind splats from `MemcpyOptions`. See
//        _generated/sdkruntime-surface.json.
//
//  Things this header DOES NOT recover:
//    - Return types (nm carries the mangled parameter types but not the
//      return; we use `auto` everywhere as a placeholder).
//    - Default argument values (mangled symbols don't preserve them).
//    - Struct field layouts (`MemcpyOptions`, internal helpers) —
//      the field set is inferred from pybind kwargs; the ORDER is a
//      best guess and may not match the actual ABI.
//    - Member visibility (everything appears as `public`).
//    - `virtual` / `final` / `inline` / `template` qualifiers.
//    - Templates and inline functions that never produced a symbol.
//
//  Regenerate via `scripts/generate_cpp_header.py` after the dump is
//  refreshed with `scripts/refresh_sdk_surface.sh`.
// ===========================================================================


#pragma once

#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

// Forward declarations for types referenced in signatures but whose
// definitions never make it into the .so symbol table (templates,
// internal headers, etc.). Documented opaquely.
namespace cerebras {
    template <typename T> struct Point;
    template <typename T> struct AbstractRectangle;
    struct IntVector;       // (x, y) pair; from das_common
    struct IntRectangle;    // ((x0,y0),(x1,y1)) rect; from das_common
    class  MemcpyTask;      // internal — Task holds shared_ptr<MemcpyTask>

    // RECONSTRUCTED. The field SET is inferred from pybind kwargs that
    // get splatted into this struct on every memcpy_*/call call. The
    // field ORDER and any padding/alignment is a GUESS — do not
    // construct directly until layout is probed against a real SIF.
    struct MemcpyOptions {
        bool                  streaming;    // pybind kwarg
        /*MemcpyOrder*/ int   order;        // pybind kwarg
        /*MemcpyDataType*/ int data_type;   // pybind kwarg
        bool                  nonblock;     // pybind kwarg
    };
} // namespace cerebras

namespace nlohmann { class json; } // forward decl for SdkCompileArtifacts ctor

namespace cerebras {

enum class SdkTarget : int {
    WSE2 = 0,
    WSE3 = 1,
};

enum class MemcpyDataType : int {
    MEMCPY_32BIT = 0,
    MEMCPY_16BIT = 1,
};

enum class MemcpyOrder : int {
    ROW_MAJOR = 0,
    COL_MAJOR = 1,
};

// ---- cerebras::SimfabConfig (fields from pybind; no nm signature) ----
struct SimfabConfig {
    int  num_threads     = 16;     // pybind default
    bool suppress_trace  = false;  // pybind default
    bool dump_core       = false;  // pybind default
    std::optional<std::filesystem::path> core_path = std::nullopt;
};

// ---- cerebras::SdkExecutionPlatform ------------------------------
class SdkExecutionPlatform {
public:
    SdkExecutionPlatform(std::string const&);
    auto load_fabric_config() const  /* internal — not in pybind */;
};

// ---- cerebras::SdkCompileArtifacts -------------------------------
class SdkCompileArtifacts {
public:
    SdkCompileArtifacts(std::string const&);
    SdkCompileArtifacts(std::string const&, nlohmann::json const&);
    auto add_port_mapping(std::string const&);
};

// ---- cerebras::SdkRuntime ----------------------------------------
class SdkRuntime {
public:
    SdkRuntime(cerebras::SdkCompileArtifacts const&, cerebras::SdkExecutionPlatform const&, std::string, bool, bool, bool, std::string, std::string);
    auto call(std::string const&, std::vector<unsigned int> const&, cerebras::MemcpyOptions const&);
    auto check_rpc_api(std::string, std::vector<std::string>&)  /* internal — not in pybind */;
    auto coord_logical_to_physical(int, int, int*, int*);
    auto dump_core(std::string);
    auto dump_elf_core(std::string);
    auto get_id(std::string const&) const;
    auto get_port_id(std::string const&);
    auto is_task_done(cerebras::SdkRuntime::Task const&);
    auto load();
    auto memcpy_d2h(void*, unsigned short, int, int, int, int, int, cerebras::MemcpyOptions const&);
    auto memcpy_h2d(unsigned short, void*, int, int, int, int, int, cerebras::MemcpyOptions const&);
    auto memcpy_h2d_colbcast(unsigned short, void*, int, int, int, int, int, cerebras::MemcpyOptions const&);
    auto memcpy_h2d_rowbcast(unsigned short, void*, int, int, int, int, int, cerebras::MemcpyOptions const&);
    auto memcpy_h2d_stride(unsigned short, void*, int, int, int, int, int, int, int, cerebras::MemcpyOptions const&);
    auto read_symbol(int, int, std::string const&) const;
    auto receive(std::string const&, void*, unsigned long, bool);
    auto receive(unsigned short, void*, unsigned long, bool);
    auto receive_tofile(std::string const&, std::string const&, bool);
    auto receive_tofile(unsigned short, std::string const&, bool);
    auto report_port_infos();
    auto run();
    auto send(std::string const&, void const*, unsigned long, bool);
    auto send(unsigned short, void const*, unsigned long, bool);
    auto stop();
    auto task_wait(cerebras::SdkRuntime::Task const&);
    ~SdkRuntime();
};

// ---- cerebras::SdkRuntime::Task ----------------------------------
class SdkRuntime::Task {
public:
    Task(cerebras::SdkRuntime::Task const&);
    Task(cerebras::SdkRuntime::Task&&);
    Task(std::shared_ptr<cerebras::MemcpyTask>);
    auto get_mtask() const  /* internal — not in pybind */;
    auto operator=(cerebras::SdkRuntime::Task const&);
    auto operator=(cerebras::SdkRuntime::Task&&);
    ~Task();
};

// ---- cerebras::SdkLayout -----------------------------------------
class SdkLayout {
public:
    enum class Edge : int {
        TOP = 0,
        BOTTOM = 1,
        LEFT = 2,
        RIGHT = 3,
    };

    enum class Route : int {
        RAMP = 0,
        EAST = 1,
        WEST = 2,
        NORTH = 3,
        SOUTH = 4,
    };

    enum class FP16TYPE : int {
        F16 = 0,
        BF16 = 1,
        CB16 = 2,
    };

    class Color;
    class RoutingPosition;
    class EdgeRouteInfo;
    class PortHandle;
    class CodeRegion;

    SdkLayout(cerebras::SdkExecutionPlatform const&, std::string);
    SdkLayout(cerebras::SdkTarget const&, std::string);
    SdkLayout(std::filesystem::path const&, std::string);
    auto compile(std::string const&, std::vector<std::string> const&, std::string const&, bool, cerebras::SdkLayout::FP16TYPE) const;
    auto connect(cerebras::SdkLayout::PortHandle&, cerebras::SdkLayout::PortHandle&);
    auto create_code_region(std::string const&, std::string const&, int, int);
    auto create_input_stream(cerebras::SdkLayout::PortHandle&, std::optional<cerebras::IntVector> const&, unsigned short);
    auto create_input_stream_from_loc(cerebras::IntVector const&, cerebras::SdkLayout::Color const&, std::string const&);
    auto create_output_stream(cerebras::SdkLayout::PortHandle&, std::optional<cerebras::IntVector> const&, unsigned short);
    auto create_output_stream_from_loc(cerebras::IntVector const&, cerebras::SdkLayout::Color const&, std::string const&);
    auto hstack(std::vector<cerebras::SdkLayout::CodeRegion> const&);
    auto hstack(std::vector<cerebras::SdkLayout::CodeRegion> const&, cerebras::IntVector const&);
    auto vstack(std::vector<cerebras::SdkLayout::CodeRegion> const&);
    auto vstack(std::vector<cerebras::SdkLayout::CodeRegion> const&, cerebras::IntVector const&);
    ~SdkLayout();
};

// ---- cerebras::SdkLayout::Color ----------------------------------
class SdkLayout::Color {
public:
    // No C++ symbols for this class in the .so dump.
    // The class is either header-only / inline or the runtime
    // never emits standalone symbols for its members. Below are
    // the methods pybind11 exposes — return types and arg names
    // come from the pybind signature, not from C++ truth.
    //   __init__             __init__(self: cerebras.sdk.runtime.sdkruntimepybind.Color, name: str, value: Optional[int] = None) -> None
    //   get_global_name      get_global_name(self: cerebras.sdk.runtime.sdkruntimepybind.Color) -> str
    //   get_local_param_name get_local_param_name(self: cerebras.sdk.runtime.sdkruntimepybind.Color) -> str
    //   get_value            get_value(self: cerebras.sdk.runtime.sdkruntimepybind.Color) -> Optional[int]
};

// ---- cerebras::SdkLayout::RoutingPosition ------------------------
class SdkLayout::RoutingPosition {
public:
    // No C++ symbols for this class in the .so dump.
    // The class is either header-only / inline or the runtime
    // never emits standalone symbols for its members. Below are
    // the methods pybind11 exposes — return types and arg names
    // come from the pybind signature, not from C++ truth.
    //   __init__             __init__(self: cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition) -> None
    //   add_input            add_input(self: cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition, arg0: cerebras.sdk.runtime.sdkruntimepybind.Route) -> cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition
    //   add_output           add_output(self: cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition, arg0: cerebras.sdk.runtime.sdkruntimepybind.Route) -> cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition
    //   get_input            get_input(self: cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition) -> List[cerebras.sdk.runtime.sdkruntimepybind.Route]
    //   get_output           get_output(self: cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition) -> List[cerebras.sdk.runtime.sdkruntimepybind.Route]
    //   set_input            set_input(self: cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition, arg0: List[cerebras.sdk.runtime.sdkruntimepybind.Route]) -> cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition
    //   set_output           set_output(self: cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition, arg0: List[cerebras.sdk.runtime.sdkruntimepybind.Route]) -> cerebras.sdk.runtime.sdkruntimepybind.RoutingPosition
};

// ---- cerebras::SdkLayout::EdgeRouteInfo --------------------------
class SdkLayout::EdgeRouteInfo {
public:
    // No C++ symbols for this class in the .so dump.
    // The class is either header-only / inline or the runtime
    // never emits standalone symbols for its members. Below are
    // the methods pybind11 exposes — return types and arg names
    // come from the pybind signature, not from C++ truth.
    //   __init__             
};

// ---- cerebras::SdkLayout::PortHandle -----------------------------
class SdkLayout::PortHandle {
public:
    // No C++ symbols for this class in the .so dump.
    // The class is either header-only / inline or the runtime
    // never emits standalone symbols for its members. Below are
    // the methods pybind11 exposes — return types and arg names
    // come from the pybind signature, not from C++ truth.
    //   __init__             
};

// ---- cerebras::SdkLayout::CodeRegion -----------------------------
class SdkLayout::CodeRegion {
public:
    auto create_input_port(cerebras::SdkLayout::Color const&, cerebras::SdkLayout::Edge, std::vector<cerebras::SdkLayout::RoutingPosition> const&, unsigned long, std::string const&);
    auto create_output_port(cerebras::SdkLayout::Color const&, cerebras::SdkLayout::Edge, std::vector<cerebras::SdkLayout::RoutingPosition> const&, unsigned long, std::string const&);
    auto paint(cerebras::IntVector const&, cerebras::SdkLayout::Color const&, std::vector<cerebras::SdkLayout::RoutingPosition> const&);
    auto paint_all(cerebras::SdkLayout::Color const&, std::vector<cerebras::SdkLayout::RoutingPosition> const&);
    auto paint_all(cerebras::SdkLayout::Color const&, std::vector<cerebras::SdkLayout::RoutingPosition> const&, std::vector<cerebras::SdkLayout::EdgeRouteInfo> const&);
    auto paint_range(cerebras::IntRectangle const&, cerebras::SdkLayout::Color const&, std::vector<cerebras::SdkLayout::RoutingPosition> const&);
    auto place(int, int);
    auto set_param(cerebras::IntVector const&, cerebras::SdkLayout::Color const&);
    auto set_param(cerebras::IntVector const&, std::string const&, cerebras::SdkLayout::Color const&);
    auto set_param(cerebras::IntVector const&, std::string const&, int);
    auto set_param_all(cerebras::SdkLayout::Color const&);
    auto set_param_all(std::string const&, cerebras::SdkLayout::Color const&);
    auto set_param_all(std::string const&, int);
    auto set_param_range(cerebras::IntRectangle const&, cerebras::SdkLayout::Color const&);
    auto set_param_range(cerebras::IntRectangle const&, std::string const&, cerebras::SdkLayout::Color const&);
    auto set_param_range(cerebras::IntRectangle const&, std::string const&, int);
    auto set_symbol_impl(std::string const&, std::vector<unsigned short> const&, int, int, int)  /* internal — not in pybind */;
};

// ---- pybind-only free functions -----------------------------------
// These appear in cerebras.sdk.runtime.sdkruntimepybind but have no
// corresponding C++ symbols in the runtime .so libs — they exist only
// inside the pybind binding code. Listed here for reference; they are
// not part of the C++ API.
//
//   SdkExecutionPlatform get_platform(
//       std::optional<std::string> addr = std::nullopt,
//       SimfabConfig config = {},
//       SdkTarget target = SdkTarget::WSE3);
//   SdkExecutionPlatform get_simulator(
//       SimfabConfig config = {},
//       SdkTarget target = SdkTarget::WSE3);
//   SdkExecutionPlatform get_system(std::string addr);
//   SdkLayout::EdgeRouteInfo get_edge_routing(
//       SdkLayout::Edge edge,
//       std::vector<SdkLayout::RoutingPosition> routes);

} // namespace cerebras
