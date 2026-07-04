#include "tempest_lora/native_display_bundle.hpp"

#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>
#include <set>

#include <openssl/sha.h>

namespace tempest_lora {

// -------------------------------------------------------------------
// Public hex encoding utility
// -------------------------------------------------------------------

std::string hex_encode(const uint8_t* data, size_t len) {
    std::ostringstream os;
    os << std::hex << std::setfill('0');
    for (size_t i = 0; i < len; ++i) {
        os << std::setw(2) << static_cast<int>(data[i]);
    }
    return os.str();
}


namespace {

// -------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------

[[noreturn]] void fail(std::string msg) {
    throw std::runtime_error(std::move(msg));
}

void require(bool cond, const std::string& msg) {
    if (!cond) fail(msg);
}

std::array<uint8_t, 32> hex_decode_sha256(const std::string& hex) {
    require(hex.size() == 64, "SHA-256 hex must be exactly 64 chars");
    std::array<uint8_t, 32> out{};
    for (size_t i = 0; i < 32; ++i) {
        auto byte_str = hex.substr(i * 2, 2);
        out[i] = static_cast<uint8_t>(std::stoul(byte_str, nullptr, 16));
    }
    return out;
}

std::array<uint8_t, 20> hex_decode_sha1(const std::string& hex) {
    require(hex.size() == 40, "SHA-1 hex must be exactly 40 chars");
    std::array<uint8_t, 20> out{};
    for (size_t i = 0; i < 20; ++i) {
        auto byte_str = hex.substr(i * 2, 2);
        out[i] = static_cast<uint8_t>(std::stoul(byte_str, nullptr, 16));
    }
    return out;
}

std::array<uint8_t, 32> compute_sha256(const uint8_t* data, size_t len) {
    std::array<uint8_t, 32> hash{};
    SHA256(data, len, hash.data());
    return hash;
}

bool is_decimal_digits(const std::string& value) {
    if (value.empty()) return false;
    for (unsigned char ch : value) {
        if (ch < '0' || ch > '9') return false;
    }
    return true;
}

void require_canonical_device_identity(const std::string& value) {
    auto colon = value.find(':');
    require(colon != std::string::npos, "device_identity must be canonical decimal-major:decimal-minor");
    require(value.find(':', colon + 1) == std::string::npos,
            "device_identity must be canonical decimal-major:decimal-minor");
    auto major = value.substr(0, colon);
    auto minor = value.substr(colon + 1);
    require(is_decimal_digits(major) && is_decimal_digits(minor),
            "device_identity must be canonical decimal-major:decimal-minor");
}

uint32_t read_u32_be(const uint8_t* buf) {
    return (static_cast<uint32_t>(buf[0]) << 24) |
           (static_cast<uint32_t>(buf[1]) << 16) |
           (static_cast<uint32_t>(buf[2]) << 8)  |
           (static_cast<uint32_t>(buf[3]));
}

uint64_t read_u64_be(const uint8_t* buf) {
    return (static_cast<uint64_t>(buf[0]) << 56) |
           (static_cast<uint64_t>(buf[1]) << 48) |
           (static_cast<uint64_t>(buf[2]) << 40) |
           (static_cast<uint64_t>(buf[3]) << 32) |
           (static_cast<uint64_t>(buf[4]) << 24) |
           (static_cast<uint64_t>(buf[5]) << 16) |
           (static_cast<uint64_t>(buf[6]) << 8)  |
           (static_cast<uint64_t>(buf[7]));
}

void require_remaining(size_t size,
                       size_t offset, size_t needed,
                       const std::string& label) {
    if (offset + needed > size) {
        std::ostringstream os;
        os << "truncated bundle at " << label
           << ": need " << needed << " bytes at offset " << offset
           << ", have " << (size - offset);
        fail(os.str());
    }
}

std::string read_fixed_string(const uint8_t* buf, size_t len) {
    size_t real_len = 0;
    while (real_len < len && buf[real_len] != 0) ++real_len;
    for (size_t i = real_len + 1; i < len; ++i) {
        if (buf[i] != 0) {
            fail("nonzero bytes after NUL in fixed string");
        }
    }
    for (size_t i = 0; i < real_len; ++i) {
        if (buf[i] >= 128) {
            fail("non-ASCII bytes in fixed string");
        }
    }
    require(real_len > 0, "empty fixed string field");
    return std::string(reinterpret_cast<const char*>(buf), real_len);
}

void read_sha256_field(const uint8_t* data, size_t offset,
                       std::array<uint8_t, 32>& out) {
    std::memcpy(out.data(), data + offset, 32);
}

void read_sha1_field(const uint8_t* data, size_t offset,
                     std::array<uint8_t, 20>& out) {
    std::memcpy(out.data(), data + offset, 20);
}

bool sha256_arrays_equal(const std::array<uint8_t, 32>& a,
                         const std::array<uint8_t, 32>& b) {
    return std::memcmp(a.data(), b.data(), 32) == 0;
}

void read_record_kind_and_ordinal(const uint8_t* data, size_t offset,
                                  uint32_t expected_kind,
                                  uint32_t expected_ordinal,
                                  const std::string& label) {
    uint32_t kind = read_u32_be(data + offset);
    if (kind != expected_kind) {
        fail(label + " record kind mismatch: expected " +
             std::to_string(expected_kind) + ", got " + std::to_string(kind));
    }
    uint32_t ordinal = read_u32_be(data + offset + 4);
    if (ordinal != expected_ordinal) {
        fail(label + " record ordinal mismatch: expected " +
             std::to_string(expected_ordinal) + ", got " + std::to_string(ordinal));
    }
}

// -------------------------------------------------------------------
// Bundle Parsing
// -------------------------------------------------------------------

std::unique_ptr<AtomicDisplayPlan> parse_impl(const uint8_t* data, size_t size) {
    auto plan = std::make_unique<AtomicDisplayPlan>();
    size_t off = 0;

    // ---- Header (128 bytes) ----
    require_remaining(size, off, kFieldSizeMagic, "magic");
    if (std::memcmp(data + off, kMagic.data(), kFieldSizeMagic) != 0) {
        fail("bad magic: expected " + std::string(kMagic));
    }
    off += kFieldSizeMagic;

    require_remaining(size, off, kFieldSizeVersion, "version");
    uint32_t version = read_u32_be(data + off);
    off += kFieldSizeVersion;
    require(version == kVersion,
            "bad version: expected " + std::to_string(kVersion) +
            ", got " + std::to_string(version));

    require_remaining(size, off, kFieldSizeBom, "byte_order_marker");
    uint32_t bom = read_u32_be(data + off);
    off += kFieldSizeBom;
    require(bom == kByteOrderMarker,
            "bad byte order marker: expected 0x" +
            hex_encode(reinterpret_cast<const uint8_t*>(&kByteOrderMarker), 4) +
            ", got 0x" + hex_encode(reinterpret_cast<const uint8_t*>(&bom), 4));

    // R2E.1 contract SHA-256
    require_remaining(size, off, kFieldSizeR2e1Hash, "r2e1_sha256");
    auto expected_r2e1 = hex_decode_sha256(std::string(kR2E1ContractSha256));
    std::array<uint8_t, 32> stored_r2e1{};
    read_sha256_field(data, off, stored_r2e1);
    off += kFieldSizeR2e1Hash;
    require(sha256_arrays_equal(stored_r2e1, expected_r2e1),
            "R2E.1 contract SHA-256 mismatch");

    // Design basis commit/tree
    require_remaining(size, off, kFieldSizeSha1, "design_commit");
    auto expected_dc = hex_decode_sha1(std::string(kDesignBasisCommit));
    std::array<uint8_t, 20> actual_dc{};
    read_sha1_field(data, off, actual_dc);
    require(std::memcmp(actual_dc.data(), expected_dc.data(), 20) == 0,
            "design_basis_commit mismatch");
    plan->design_basis_commit = std::string(kDesignBasisCommit);
    off += kFieldSizeSha1;

    require_remaining(size, off, kFieldSizeSha1, "design_tree");
    auto expected_dt = hex_decode_sha1(std::string(kDesignBasisTree));
    std::array<uint8_t, 20> actual_dt{};
    read_sha1_field(data, off, actual_dt);
    require(std::memcmp(actual_dt.data(), expected_dt.data(), 20) == 0,
            "design_basis_tree mismatch");
    plan->design_basis_tree = std::string(kDesignBasisTree);
    off += kFieldSizeSha1;

    // Current checkout commit/tree
    require_remaining(size, off, kFieldSizeSha1, "checkout_commit");
    plan->current_checkout_commit = hex_encode(data + off, 20);
    off += kFieldSizeSha1;

    require_remaining(size, off, kFieldSizeSha1, "checkout_tree");
    plan->current_checkout_tree = hex_encode(data + off, 20);
    off += kFieldSizeSha1;

    // ---- Mode (40 bytes) ----
    require_remaining(size, off, kFieldSizeMode, "mode");
    uint32_t clock_khz   = read_u32_be(data + off + 0);
    uint32_t hdisplay    = read_u32_be(data + off + 4);
    uint32_t hsync_start = read_u32_be(data + off + 8);
    uint32_t hsync_end   = read_u32_be(data + off + 12);
    uint32_t htotal      = read_u32_be(data + off + 16);
    uint32_t vdisplay    = read_u32_be(data + off + 20);
    uint32_t vsync_start = read_u32_be(data + off + 24);
    uint32_t vsync_end   = read_u32_be(data + off + 28);
    uint32_t vtotal      = read_u32_be(data + off + 32);
    uint32_t mode_flags  = read_u32_be(data + off + 36);
    off += kFieldSizeMode;

    require(clock_khz   == kModeClockKHz,   "mode clock mismatch");
    require(hdisplay    == kModeHDisplay,    "mode hdisplay mismatch");
    require(hsync_start == kModeHSyncStart,  "mode hsync_start mismatch");
    require(hsync_end   == kModeHSyncEnd,    "mode hsync_end mismatch");
    require(htotal      == kModeHTotal,      "mode htotal mismatch");
    require(vdisplay    == kModeVDisplay,    "mode vdisplay mismatch");
    require(vsync_start == kModeVSyncStart,  "mode vsync_start mismatch");
    require(vsync_end   == kModeVSyncEnd,    "mode vsync_end mismatch");
    require(vtotal      == kModeVTotal,      "mode vtotal mismatch");
    require(mode_flags  == kModeFlagsExpected, "mode flags mismatch");

    plan->mode.clock      = clock_khz;
    plan->mode.hdisplay   = hdisplay;
    plan->mode.hsync_start = hsync_start;
    plan->mode.hsync_end   = hsync_end;
    plan->mode.htotal     = htotal;
    plan->mode.vdisplay   = vdisplay;
    plan->mode.vsync_start = vsync_start;
    plan->mode.vsync_end   = vsync_end;
    plan->mode.vtotal     = vtotal;
    plan->mode.vrefresh   = 60;
    plan->mode.flags      = DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC;
    plan->mode.type       = DRM_MODE_TYPE_DRIVER;

    // ---- Format (16 bytes) ----
    require_remaining(size, off, kFieldSizeFormat, "format");
    if (std::memcmp(data + off, kFourccXRGB8888.data(), 8) != 0) {
        std::string got(reinterpret_cast<const char*>(data + off), 8);
        got = got.substr(0, got.find('\0'));
        fail("expected XRGB8888 fourcc, got " + got);
    }
    plan->fourcc = DRM_FORMAT_XRGB8888;
    off += kFieldSizeFourcc;

    uint64_t modifier = read_u64_be(data + off);
    off += kFieldSizeModifier;
    require(modifier == kModifierLinear, "expected LINEAR modifier (0)");

    plan->modifier = DRM_FORMAT_MOD_LINEAR;

    // ---- Geometry (32 bytes) ----
    require_remaining(size, off, kFieldSizeGeometry, "geometry");
    plan->src_x = read_u32_be(data + off + 0);
    plan->src_y = read_u32_be(data + off + 4);
    plan->src_w = read_u32_be(data + off + 8);
    plan->src_h = read_u32_be(data + off + 12);
    plan->dst_x = read_u32_be(data + off + 16);
    plan->dst_y = read_u32_be(data + off + 20);
    plan->dst_w = read_u32_be(data + off + 24);
    plan->dst_h = read_u32_be(data + off + 28);
    off += kFieldSizeGeometry;

    require(plan->src_x == kSrcX, "src_x mismatch");
    require(plan->src_y == kSrcY, "src_y mismatch");
    require(plan->src_w == kSrcW, "src_w mismatch");
    require(plan->src_h == kSrcH, "src_h mismatch");
    require(plan->dst_x == kDstX, "dst_x mismatch");
    require(plan->dst_y == kDstY, "dst_y mismatch");
    require(plan->dst_w == kDstW, "dst_w mismatch");
    require(plan->dst_h == kDstH, "dst_h mismatch");

    // ---- Identity (132 bytes) ----
    require_remaining(size, off, kFieldSizeIdentity, "identity");
    plan->device_identity = read_fixed_string(data + off, kFieldSizeDeviceIdentity);
    off += kFieldSizeDeviceIdentity;

    plan->connector_id = read_u32_be(data + off); off += kFieldSizeId;
    plan->crtc_id      = read_u32_be(data + off); off += kFieldSizeId;
    plan->plane_id     = read_u32_be(data + off); off += kFieldSizeId;

    plan->edid_sha256 = hex_encode(data + off, kFieldSizeEdidSha256);
    off += kFieldSizeEdidSha256;

    plan->topology_token = read_fixed_string(data + off, kFieldSizeTopologyToken);
    off += kFieldSizeTopologyToken;

    uint32_t fmt_gate = read_u32_be(data + off); off += kFieldSizeGate;
    uint32_t mod_gate = read_u32_be(data + off); off += kFieldSizeGate;

    require(fmt_gate == 1, "format_gate must be 1 (XRGB8888 present)");
    require(mod_gate == 1, "modifier_gate must be 1 (LINEAR present)");
    require(plan->connector_id > 0, "connector_id must be positive");
    require(plan->crtc_id > 0, "crtc_id must be positive");
    require(plan->plane_id > 0, "plane_id must be positive");
    require_canonical_device_identity(plan->device_identity);

    // ---- Frame hash records (variable) ----
    // Guard-before record
    require_remaining(size, off, kFrameRecordHashEntry, "guard_before_hash_record");
    read_record_kind_and_ordinal(data, off, kRecordKindGuard, 0, "guard-before");
    off += 8;  // skip kind + ordinal
    std::array<uint8_t, 32> guard_before_hash{};
    read_sha256_field(data, off, guard_before_hash);
    off += kFieldSizeSha256;

    // Frame count
    require_remaining(size, off, kFieldSizeId, "frame_count");
    uint32_t frame_count = read_u32_be(data + off);
    off += kFieldSizeId;
    require(frame_count >= kMinFrameCount && frame_count <= kMaxFrameCount,
            "frame_count " + std::to_string(frame_count) +
            " outside " + std::to_string(kMinFrameCount) +
            ".." + std::to_string(kMaxFrameCount));

    // Data frame records
    std::vector<std::array<uint8_t, 32>> data_hashes(frame_count);
    std::set<uint32_t> seen_data_ordinals;
    for (uint32_t i = 0; i < frame_count; ++i) {
        require_remaining(size, off, kFrameRecordHashEntry, "data_hash_record");
        read_record_kind_and_ordinal(data, off, kRecordKindData, i,
                                     "data frame " + std::to_string(i));
        off += 8;
        read_sha256_field(data, off, data_hashes[i]);
        off += kFieldSizeSha256;
        if (!seen_data_ordinals.insert(i).second) {
            fail("duplicate data ordinal " + std::to_string(i));
        }
    }

    // Guard-after record
    require_remaining(size, off, kFrameRecordHashEntry, "guard_after_hash_record");
    read_record_kind_and_ordinal(data, off, kRecordKindGuard, frame_count,
                                 "guard-after");
    off += 8;
    std::array<uint8_t, 32> guard_after_hash{};
    read_sha256_field(data, off, guard_after_hash);
    off += kFieldSizeSha256;

    // Guard-after must match guard-before
    require(sha256_arrays_equal(guard_after_hash, guard_before_hash),
            "guard-after SHA-256 must match guard-before");

    // ---- Frame size records (variable) ----
    // Guard-before size record
    require_remaining(size, off, kFrameRecordSizeEntry, "guard_before_size_record");
    read_record_kind_and_ordinal(data, off, kRecordKindGuard, 0, "guard-before-size");
    off += 8;
    uint32_t guard_before_size = read_u32_be(data + off);
    off += kFieldSizeId;
    require(guard_before_size == kFrameByteSize,
            "guard_before_byte_size mismatch");

    // Data frame size records
    std::set<uint32_t> seen_size_ordinals;
    for (uint32_t i = 0; i < frame_count; ++i) {
        require_remaining(size, off, kFrameRecordSizeEntry, "data_size_record");
        read_record_kind_and_ordinal(data, off, kRecordKindData, i,
                                     "data frame " + std::to_string(i) + " size");
        off += 8;
        uint32_t frame_size = read_u32_be(data + off);
        off += kFieldSizeId;
        require(frame_size == kFrameByteSize,
                "data_frame_byte_size [" + std::to_string(i) +
                "] mismatch");
        if (!seen_size_ordinals.insert(i).second) {
            fail("duplicate data size ordinal " + std::to_string(i));
        }
    }

    // Guard-after size record
    require_remaining(size, off, kFrameRecordSizeEntry, "guard_after_size_record");
    read_record_kind_and_ordinal(data, off, kRecordKindGuard, frame_count,
                                 "guard-after-size");
    off += 8;
    uint32_t guard_after_size = read_u32_be(data + off);
    off += kFieldSizeId;
    require(guard_after_size == kFrameByteSize,
            "guard_after_byte_size mismatch");

    // ---- Frame payloads (variable) ----
    auto read_frame_payload = [&](const std::array<uint8_t, 32>& expected_hash)
            -> FrameDescriptor {
        require_remaining(size, off, kFrameByteSize, "frame_payload");
        FrameDescriptor fd;
        fd.data.assign(data + off, data + off + kFrameByteSize);
        off += kFrameByteSize;

        auto computed = compute_sha256(fd.data.data(), fd.data.size());
        fd.sha256 = computed;
        require(sha256_arrays_equal(computed, expected_hash),
                "frame payload SHA-256 mismatch (expected " +
                hex_encode(expected_hash.data(), 32) +
                ", computed " + hex_encode(computed.data(), 32) + ")");
        return fd;
    };

    // Guard before
    plan->guard_before = read_frame_payload(guard_before_hash);

    // Data frames
    plan->data_frames.reserve(frame_count);
    for (uint32_t i = 0; i < frame_count; ++i) {
        plan->data_frames.push_back(read_frame_payload(data_hashes[i]));
    }

    // Guard after
    plan->guard_after = read_frame_payload(guard_after_hash);

    // Check for trailing data
    require(off == size,
            "unexpected trailing data: " +
            std::to_string(size - off) + " extra bytes");

    return plan;
}

}  // anonymous namespace


// -------------------------------------------------------------------
// Public API
// -------------------------------------------------------------------

ValidateResult parse_native_display_bundle(const uint8_t* data, size_t size) {
    ValidateResult result;
    try {
        result.plan = parse_impl(data, size);
        result.success = true;
    } catch (const std::exception& e) {
        result.success = false;
        result.error = e.what();
    }
    return result;
}


void print_contract(const AtomicDisplayPlan& plan) {
    std::cout << "{\n"
              << "  \"schema\": \"tempest-lora.compile-only-bundle-plan.v1\",\n"
              << "  \"no_live_drm_operation\": true,\n"
              << "  \"test_only_before_live_semantics\": true,\n"
              << "  \"async_flip\": false,\n"
              << "  \"max_outstanding_commits\": 1,\n"
              << "  \"design_basis_commit\": \""
              << plan.design_basis_commit << "\",\n"
              << "  \"design_basis_tree\": \""
              << plan.design_basis_tree << "\",\n"
              << "  \"current_checkout_commit\": \""
              << plan.current_checkout_commit << "\",\n"
              << "  \"current_checkout_tree\": \""
              << plan.current_checkout_tree << "\",\n"
              << "  \"device_identity\": \""
              << plan.device_identity << "\",\n"
              << "  \"connector_id\": " << plan.connector_id << ",\n"
              << "  \"crtc_id\": " << plan.crtc_id << ",\n"
              << "  \"plane_id\": " << plan.plane_id << ",\n"
              << "  \"fourcc\": \"DRM_FORMAT_XRGB8888\",\n"
              << "  \"modifier\": \"DRM_FORMAT_MOD_LINEAR\",\n"
              << "  \"mode\": {\n"
              << "    \"clock_khz\": " << plan.mode.clock << ",\n"
              << "    \"hdisplay\": " << plan.mode.hdisplay << ",\n"
              << "    \"hsync_start\": " << plan.mode.hsync_start << ",\n"
              << "    \"hsync_end\": " << plan.mode.hsync_end << ",\n"
              << "    \"htotal\": " << plan.mode.htotal << ",\n"
              << "    \"vdisplay\": " << plan.mode.vdisplay << ",\n"
              << "    \"vsync_start\": " << plan.mode.vsync_start << ",\n"
              << "    \"vsync_end\": " << plan.mode.vsync_end << ",\n"
              << "    \"vtotal\": " << plan.mode.vtotal << "\n"
              << "  },\n"
              << "  \"src_rect\": ["
              << plan.src_x << "," << plan.src_y << ","
              << plan.src_w << "," << plan.src_h << "],\n"
              << "  \"dst_rect\": ["
              << plan.dst_x << "," << plan.dst_y << ","
              << plan.dst_w << "," << plan.dst_h << "],\n"
              << "  \"guard_before_sha256\": \""
              << hex_encode(plan.guard_before.sha256.data(), 32) << "\",\n"
              << "  \"data_frame_count\": "
              << plan.data_frames.size() << ",\n"
              << "  \"guard_after_sha256\": \""
              << hex_encode(plan.guard_after.sha256.data(), 32) << "\",\n"
              << "  \"nonclaims\": [\n"
              << "    \"no live DRM/KMS access\",\n"
              << "    \"no physical pixel-clock accuracy proof\",\n"
              << "    \"no RF emission or LoRa decodability proof\",\n"
              << "    \"no protected MATLAB/P-code equivalence claim\"\n"
              << "  ],\n"
              << "  \"B1_remaining_open\": true,\n"
              << "  \"no_dev_dri_access\": true,\n"
              << "  \"no_display_output\": true\n"
              << "}\n";
}


void print_plan(const AtomicDisplayPlan& plan) {
    print_contract(plan);
}


std::vector<uint8_t> read_entire_file(const char* path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) {
        fail(std::string("cannot open file: ") + path);
    }
    auto size = f.tellg();
    f.seekg(0);
    std::vector<uint8_t> buf(static_cast<size_t>(size));
    if (size > 0) {
        f.read(reinterpret_cast<char*>(buf.data()), size);
    }
    return buf;
}

}  // namespace tempest_lora
