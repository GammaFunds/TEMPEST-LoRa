#ifndef TEMPEST_LORA_NATIVE_ATOMIC_PREFLIGHT_HPP
#define TEMPEST_LORA_NATIVE_ATOMIC_PREFLIGHT_HPP

#include <cstdint>
#include <string>
#include <vector>
#include <cstddef>
#include <array>

#include "tempest_lora/native_display_bundle.hpp"

namespace tempest_lora {

enum class DrmObjectClass : uint8_t {
    Connector = 0,
    Crtc = 1,
    Plane = 2
};

enum class SymbolicValueSource : uint8_t {
    None = 0,
    FutureModeBlobId = 1,
    FutureFramebufferId = 2
};

struct PropertySnapshot {
    uint32_t id{};
    std::string name;
    uint64_t value{};
};

struct FormatModifierTuple {
    uint32_t fourcc{};
    uint64_t modifier{};
};

struct ConnectorSnapshot {
    uint32_t connector_id{};
    bool connected{};
    std::vector<uint32_t> possible_crtc_ids;
    std::vector<PropertySnapshot> properties;
};

struct CrtcSnapshot {
    uint32_t crtc_id{};
    std::vector<PropertySnapshot> properties;
};

struct PlaneSnapshot {
    uint32_t plane_id{};
    bool is_primary{};
    std::vector<uint32_t> possible_crtc_ids;
    std::vector<FormatModifierTuple> supported_formats;
    std::vector<PropertySnapshot> properties;
};

struct IdentityGates {
    bool rotation{true};
    bool scaling{true};
    bool color_pipeline{true};
};

struct KmsTopologySnapshot {
    std::string device_identity;
    std::string edid_sha256;
    std::string topology_token;
    ConnectorSnapshot connector;
    CrtcSnapshot crtc;
    PlaneSnapshot plane;
    IdentityGates identity_gates;
    uint32_t mode_clock_khz{148500};
    uint32_t mode_hdisplay{1920};
    uint32_t mode_hsync_start{2008};
    uint32_t mode_hsync_end{2052};
    uint32_t mode_htotal{2200};
    uint32_t mode_vdisplay{1080};
    uint32_t mode_vsync_start{1084};
    uint32_t mode_vsync_end{1089};
    uint32_t mode_vtotal{1125};
    bool mode_hsync_positive{true};
    bool mode_vsync_positive{true};
    bool mode_interlaced{false};
    bool mode_doublescan{false};
};

struct PropertyAssignment {
    uint32_t object_id{};
    DrmObjectClass object_class{};
    uint32_t property_id{};
    std::string property_name;
    uint64_t immediate_value{};
    SymbolicValueSource symbolic_source{SymbolicValueSource::None};
    bool is_symbolic{};
};

struct PreparedAtomicRequest {
    std::vector<PropertyAssignment> assignments;
    bool test_only_before_live_required{true};
    bool allow_modeset_required{true};
    bool async_flip_forbidden{true};
    uint32_t max_outstanding_commits{1};
};

struct PreflightResult {
    bool success{};
    std::string error;
    PreparedAtomicRequest request;
};

PreflightResult prepare_atomic_request(
    const AtomicDisplayPlan& plan,
    const KmsTopologySnapshot& snapshot);

} // namespace tempest_lora

#endif
