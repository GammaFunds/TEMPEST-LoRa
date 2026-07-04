#ifndef TEMPEST_LORA_NATIVE_DISPLAY_BUNDLE_HPP
#define TEMPEST_LORA_NATIVE_DISPLAY_BUNDLE_HPP

#include <cstdint>
#include <cstddef>
#include <string>
#include <vector>
#include <array>
#include <memory>

#include <xf86drmMode.h>
#include <libdrm/drm_fourcc.h>

namespace tempest_lora {

// Bundle format constants
inline constexpr std::string_view  kMagic = "TLORABND";
inline constexpr uint32_t          kVersion = 1;
inline constexpr uint32_t          kByteOrderMarker = 0x01020304;
inline constexpr uint32_t          kModeClockKHz = 148500;
inline constexpr uint32_t          kModeHDisplay = 1920;
inline constexpr uint32_t          kModeHSyncStart = 2008;
inline constexpr uint32_t          kModeHSyncEnd = 2052;
inline constexpr uint32_t          kModeHTotal = 2200;
inline constexpr uint32_t          kModeVDisplay = 1080;
inline constexpr uint32_t          kModeVSyncStart = 1084;
inline constexpr uint32_t          kModeVSyncEnd = 1089;
inline constexpr uint32_t          kModeVTotal = 1125;
inline constexpr uint32_t          kModeFlagsPosH = 1;
inline constexpr uint32_t          kModeFlagsPosV = 2;
inline constexpr uint32_t          kModeFlagsInterlaced = 4;
inline constexpr uint32_t          kModeFlagsDoublescan = 8;
inline constexpr uint32_t          kModeFlagsExpected = 3;  // posH | posV

inline constexpr std::string_view  kFourccXRGB8888 = "XRGB8888";
inline constexpr uint64_t          kModifierLinear = 0;

inline constexpr uint32_t          kSrcX = 0;
inline constexpr uint32_t          kSrcY = 0;
inline constexpr uint32_t          kSrcW = 1920 << 16;   // 125829120
inline constexpr uint32_t          kSrcH = 1080 << 16;   // 70778880
inline constexpr uint32_t          kDstX = 0;
inline constexpr uint32_t          kDstY = 0;
inline constexpr uint32_t          kDstW = 1920;
inline constexpr uint32_t          kDstH = 1080;

inline constexpr uint32_t          kFrameWidth = 1920;
inline constexpr uint32_t          kFrameHeight = 1080;
inline constexpr uint32_t          kFrameByteSize = 1920 * 1080 * 4;  // 8294400
inline constexpr uint32_t          kMinFrameCount = 1;
inline constexpr uint32_t          kMaxFrameCount = 16;

// Record kind values
inline constexpr uint32_t          kRecordKindGuard = 0;
inline constexpr uint32_t          kRecordKindData = 1;

// R2E.1 contract SHA-256 hex
inline constexpr std::string_view  kR2E1ContractSha256 =
    "d6b06815ea9e4e077170067c742a87d347766bd484d63fcb1996564524a739c4";

// Design basis
inline constexpr std::string_view  kDesignBasisCommit =
    "f05f7ded6c062852a08214523edf7c991b9493b1";
inline constexpr std::string_view  kDesignBasisTree =
    "d6a6c1f0a9b495a51a2be0ca38c5c00fc9062c77";

// Fixed offsets
inline constexpr size_t kOffMagic = 0;
inline constexpr size_t kOffVersion = 8;
inline constexpr size_t kOffBom = 12;
inline constexpr size_t kOffR2e1Hash = 16;
inline constexpr size_t kOffDesignCommit = 48;
inline constexpr size_t kOffDesignTree = 68;
inline constexpr size_t kOffCheckoutCommit = 88;
inline constexpr size_t kOffCheckoutTree = 108;
inline constexpr size_t kOffModeStart = 128;
inline constexpr size_t kOffFormatStart = 168;
inline constexpr size_t kOffFourcc = 168;
inline constexpr size_t kOffModifier = 176;
inline constexpr size_t kOffGeometryStart = 184;
inline constexpr size_t kOffSrcRect = 184;
inline constexpr size_t kOffDstRect = 200;
inline constexpr size_t kOffIdentityStart = 216;
inline constexpr size_t kOffDeviceIdentity = 216;
inline constexpr size_t kOffConnectorId = 232;
inline constexpr size_t kOffCrtcId = 236;
inline constexpr size_t kOffPlaneId = 240;
inline constexpr size_t kOffEdidSha256 = 244;
inline constexpr size_t kOffTopologyToken = 276;
inline constexpr size_t kOffFormatGate = 340;
inline constexpr size_t kOffModifierGate = 344;

inline constexpr size_t kFieldSizeMagic = 8;
inline constexpr size_t kFieldSizeVersion = 4;
inline constexpr size_t kFieldSizeBom = 4;
inline constexpr size_t kFieldSizeR2e1Hash = 32;
inline constexpr size_t kFieldSizeSha1 = 20;
inline constexpr size_t kFieldSizeSha256 = 32;
inline constexpr size_t kFieldSizeModeEntry = 4;
inline constexpr size_t kFieldSizeModeEntries = 10;
inline constexpr size_t kFieldSizeMode = 40;
inline constexpr size_t kFieldSizeFourcc = 8;
inline constexpr size_t kFieldSizeModifier = 8;
inline constexpr size_t kFieldSizeFormat = 16;
inline constexpr size_t kFieldSizeRectEntry = 4;
inline constexpr size_t kFieldSizeRectEntries = 4;
inline constexpr size_t kFieldSizeRect = 16;
inline constexpr size_t kFieldSizeGeometry = 32;
inline constexpr size_t kFieldSizeDeviceIdentity = 16;
inline constexpr size_t kFieldSizeId = 4;
inline constexpr size_t kFieldSizeEdidSha256 = 32;
inline constexpr size_t kFieldSizeTopologyToken = 64;
inline constexpr size_t kFieldSizeGate = 4;
inline constexpr size_t kFieldSizeIdentity =
    kFieldSizeDeviceIdentity + 3 * kFieldSizeId +
    kFieldSizeEdidSha256 + kFieldSizeTopologyToken + 2 * kFieldSizeGate;

inline constexpr size_t kFixedMetaSize =
    kFieldSizeMagic + kFieldSizeVersion + kFieldSizeBom +
    kFieldSizeR2e1Hash + 4 * kFieldSizeSha1 +
    kFieldSizeMode + kFieldSizeFormat + kFieldSizeGeometry +
    kFieldSizeIdentity;  // 348

inline constexpr size_t kFrameRecordHashEntry = 4 + 4 + 32;   // kind + ordinal + sha256
inline constexpr size_t kFrameRecordSizeEntry = 4 + 4 + 4;    // kind + ordinal + size
inline constexpr size_t kFrameHashRecordSectionFixed = 4 + 4 + 32 + 4 + 4 + 4 + 32;  // guard_before(40) + count(4) + guard_after(40) = 84
inline constexpr size_t kFrameSizeRecordSectionFixed = 4 + 4 + 4 + 4 + 4 + 4;  // guard_before(12) + guard_after(12) = 24


// In-memory frame descriptor
struct FrameDescriptor {
    std::array<uint8_t, 32> sha256{};
    std::vector<uint8_t>    data;
};

// In-memory immutable scanout/atomic property plan
struct AtomicDisplayPlan {
    // Identity
    uint32_t connector_id{};
    uint32_t crtc_id{};
    uint32_t plane_id{};

    // Mode
    drmModeModeInfo mode{};

    // Pixel format and modifier
    uint32_t fourcc{};      // DRM_FORMAT_XRGB8888
    uint64_t modifier{};    // DRM_FORMAT_MOD_LINEAR

    // Source/destination rectangles
    uint32_t src_x{}, src_y{}, src_w{}, src_h{};
    uint32_t dst_x{}, dst_y{}, dst_w{}, dst_h{};

    // Guard before frame (black)
    FrameDescriptor guard_before;

    // Data frames (1..16)
    std::vector<FrameDescriptor> data_frames;

    // Guard after frame (black)
    FrameDescriptor guard_after;

    // Metadata
    std::string device_identity;
    std::string edid_sha256;
    std::string topology_token;
    std::string design_basis_commit;
    std::string design_basis_tree;
    std::string current_checkout_commit;
    std::string current_checkout_tree;

    // Nonclaim marker (no live DRM operation occurred)
    bool no_live_drm_operation = true;
    bool test_only_before_live_semantics = true;
    bool async_flip = false;
    uint32_t max_outstanding_commits = 1;
};


// Result of bundle validation
struct ValidateResult {
    bool success{};
    std::string error;
    std::unique_ptr<AtomicDisplayPlan> plan;
};


// Public hex encoding utility
std::string hex_encode(const uint8_t* data, size_t len);

// Parse and validate a native display bundle from raw bytes.
// Returns nullptr in result.plan on failure.
ValidateResult parse_native_display_bundle(const uint8_t* data, size_t size);

// Print contract metadata to stdout (machine-readable).
void print_contract(const AtomicDisplayPlan& plan);

// Print bundle plan to stdout (machine-readable).
void print_plan(const AtomicDisplayPlan& plan);

// Read an entire file into a byte vector.
std::vector<uint8_t> read_entire_file(const char* path);

}  // namespace tempest_lora

#endif  // TEMPEST_LORA_NATIVE_DISPLAY_BUNDLE_HPP
