#include "tempest_lora/native_display_bundle.hpp"

#include <cstring>
#include <iostream>
#include <sstream>
#include <cstdlib>
#include <set>

#include <openssl/sha.h>

// Minimal test framework
static int tests_run = 0;
static int tests_failed = 0;

#define TEST(name)                                                    \
    do {                                                              \
        ++tests_run;                                                  \
        try {                                                         \
            test_##name();                                            \
            std::cout << "  PASS: " #name << "\n";                   \
        } catch (const std::exception& e) {                            \
            ++tests_failed;                                           \
            std::cerr << "  FAIL: " #name ": " << e.what() << "\n";   \
        }                                                             \
    } while (0)

#define REQUIRE(cond, msg)                                            \
    do {                                                              \
        if (!(cond)) {                                                \
            std::ostringstream _os;                                   \
            _os << msg;                                               \
            throw std::runtime_error(_os.str());                      \
        }                                                             \
    } while (0)

using namespace tempest_lora;

namespace {

// Build a minimal valid bundle in memory (new format with record kinds/ordinals)
std::vector<uint8_t> build_minimal_bundle(uint32_t frame_count = 1) {
    std::vector<uint8_t> buf;

    auto append = [&](const uint8_t* d, size_t len) {
        buf.insert(buf.end(), d, d + len);
    };
    auto append_u32 = [&](uint32_t v) {
        uint8_t b[4] = {
            static_cast<uint8_t>((v >> 24) & 0xff),
            static_cast<uint8_t>((v >> 16) & 0xff),
            static_cast<uint8_t>((v >> 8) & 0xff),
            static_cast<uint8_t>(v & 0xff)
        };
        append(b, 4);
    };
    auto append_u64_be = [&](uint64_t v) {
        uint8_t b[8] = {
            static_cast<uint8_t>((v >> 56) & 0xff),
            static_cast<uint8_t>((v >> 48) & 0xff),
            static_cast<uint8_t>((v >> 40) & 0xff),
            static_cast<uint8_t>((v >> 32) & 0xff),
            static_cast<uint8_t>((v >> 24) & 0xff),
            static_cast<uint8_t>((v >> 16) & 0xff),
            static_cast<uint8_t>((v >> 8) & 0xff),
            static_cast<uint8_t>(v & 0xff)
        };
        append(b, 8);
    };
    auto append_hex = [&](const std::string& hex) {
        for (size_t i = 0; i < hex.size(); i += 2) {
            auto byte = static_cast<uint8_t>(
                std::stoul(hex.substr(i, 2), nullptr, 16));
            buf.push_back(byte);
        }
    };
    auto append_fixed_str = [&](const std::string& s, size_t size) {
        for (size_t i = 0; i < size; ++i) {
            buf.push_back(i < s.size() ? static_cast<uint8_t>(s[i]) : 0);
        }
    };
    auto append_zeros = [&](size_t n) {
        buf.insert(buf.end(), n, 0);
    };
    auto append_record = [&](uint32_t kind, uint32_t ordinal,
                             const uint8_t* sha_data) {
        append_u32(kind);
        append_u32(ordinal);
        append(sha_data, 32);
    };
    auto append_size_record = [&](uint32_t kind, uint32_t ordinal,
                                  uint32_t size_val) {
        append_u32(kind);
        append_u32(ordinal);
        append_u32(size_val);
    };

    // Magic
    append(reinterpret_cast<const uint8_t*>(kMagic.data()), 8);
    // Version
    append_u32(kVersion);
    // BOM
    append_u32(kByteOrderMarker);
    // R2E1 hash
    append_hex(std::string(kR2E1ContractSha256));
    // Design basis commit
    append_hex(std::string(kDesignBasisCommit));
    // Design basis tree
    append_hex(std::string(kDesignBasisTree));
    // Checkout commit (zeros placeholder)
    append_zeros(20);
    // Checkout tree (zeros placeholder)
    append_zeros(20);

    // Mode
    append_u32(kModeClockKHz);
    append_u32(kModeHDisplay);
    append_u32(kModeHSyncStart);
    append_u32(kModeHSyncEnd);
    append_u32(kModeHTotal);
    append_u32(kModeVDisplay);
    append_u32(kModeVSyncStart);
    append_u32(kModeVSyncEnd);
    append_u32(kModeVTotal);
    append_u32(kModeFlagsExpected);

    // Format
    append(reinterpret_cast<const uint8_t*>(kFourccXRGB8888.data()), 8);
    append_u64_be(kModifierLinear);

    // Geometry
    append_u32(kSrcX);
    append_u32(kSrcY);
    append_u32(kSrcW);
    append_u32(kSrcH);
    append_u32(kDstX);
    append_u32(kDstY);
    append_u32(kDstW);
    append_u32(kDstH);

    // Identity
    append_fixed_str("226:0", 16);
    append_u32(31);   // connector_id
    append_u32(41);   // crtc_id
    append_u32(51);   // plane_id
    append_hex("ab" + std::string(62, '0'));  // edid_sha256 (32 bytes)
    append_fixed_str("topology-v1", 64);
    append_u32(1);    // format_gate
    append_u32(1);    // modifier_gate

    // Build frame data and compute hashes
    auto compute_hash = [](const uint8_t* d, size_t len) -> std::vector<uint8_t> {
        std::vector<uint8_t> h(32);
        SHA256(d, len, h.data());
        return h;
    };

    // Black guard frame
    std::vector<uint8_t> guard_frame(kFrameByteSize, 0);
    // Data frames (slightly different content)
    std::vector<std::vector<uint8_t>> data_frames(frame_count);
    for (uint32_t i = 0; i < frame_count; ++i) {
        data_frames[i].resize(kFrameByteSize, 0);
        if (kFrameByteSize > 0) {
            data_frames[i][0] = 255;
            data_frames[i][kFrameByteSize - 4] = 255;
            data_frames[i][kFrameByteSize - 3] = 255;
            data_frames[i][kFrameByteSize - 2] = 255;
            data_frames[i][kFrameByteSize - 1] = 255;
            if (i > 0) {
                data_frames[i][4] = static_cast<uint8_t>(i);
            }
        }
    }

    // Guard frame hash
    auto guard_hash = compute_hash(guard_frame.data(), guard_frame.size());

    // ---- Frame hash records ----
    // Guard-before record
    append_record(kRecordKindGuard, 0, guard_hash.data());
    // Frame count
    append_u32(frame_count);
    // Data frame records
    for (uint32_t i = 0; i < frame_count; ++i) {
        auto dh = compute_hash(data_frames[i].data(), data_frames[i].size());
        append_record(kRecordKindData, i, dh.data());
    }
    // Guard-after record
    append_record(kRecordKindGuard, frame_count, guard_hash.data());

    // ---- Frame size records ----
    // Guard-before
    append_size_record(kRecordKindGuard, 0, kFrameByteSize);
    for (uint32_t i = 0; i < frame_count; ++i) {
        append_size_record(kRecordKindData, i, kFrameByteSize);
    }
    // Guard-after
    append_size_record(kRecordKindGuard, frame_count, kFrameByteSize);

    // ---- Frame payloads ----
    append(guard_frame.data(), guard_frame.size());
    for (uint32_t i = 0; i < frame_count; ++i) {
        append(data_frames[i].data(), data_frames[i].size());
    }
    append(guard_frame.data(), guard_frame.size());

    return buf;
}

}  // anonymous namespace

// --- Tests ---

static void test_valid_one_frame() {
    auto buf = build_minimal_bundle(1);
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(result.success, "valid one-frame bundle should succeed");
    REQUIRE(result.plan != nullptr, "plan should be non-null");
    REQUIRE(result.plan->connector_id == 31, "connector_id");
    REQUIRE(result.plan->crtc_id == 41, "crtc_id");
    REQUIRE(result.plan->plane_id == 51, "plane_id");
    REQUIRE(result.plan->data_frames.size() == 1, "one data frame");
    REQUIRE(result.plan->no_live_drm_operation == true, "no live drm");
    REQUIRE(result.plan->async_flip == false, "no async flip");
    REQUIRE(result.plan->max_outstanding_commits == 1, "max 1 outstanding");
}

static void test_valid_sixteen_frames() {
    auto buf = build_minimal_bundle(16);
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(result.success, "valid 16-frame bundle should succeed");
    REQUIRE(result.plan->data_frames.size() == 16, "16 data frames");
}

static void test_wrong_magic() {
    auto buf = build_minimal_bundle(1);
    buf[0] = 'B';
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "wrong magic should fail");
}

static void test_wrong_version() {
    auto buf = build_minimal_bundle(1);
    buf[8] = 0; buf[9] = 0; buf[10] = 0; buf[11] = 99;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "wrong version should fail");
}

static void test_wrong_bom() {
    auto buf = build_minimal_bundle(1);
    buf[15] = 0;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "wrong byte order marker should fail");
}

static void test_wrong_r2e1_hash() {
    auto buf = build_minimal_bundle(1);
    buf[16] ^= 1;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "wrong R2E.1 hash should fail");
}

static void test_wrong_mode_clock() {
    auto buf = build_minimal_bundle(1);
    buf[128] = 0; buf[129] = 0; buf[130] = 0; buf[131] = 1;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "wrong mode clock should fail");
}

static void test_wrong_format() {
    auto buf = build_minimal_bundle(1);
    buf[168] = 'X'; buf[169] = 'R'; buf[170] = 'G'; buf[171] = 'B';
    buf[172] = '0'; buf[173] = '0'; buf[174] = '0'; buf[175] = '0';
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "wrong format should fail");
}

static void test_wrong_modifier() {
    auto buf = build_minimal_bundle(1);
    buf[176] = 0; buf[177] = 0; buf[178] = 0; buf[179] = 0;
    buf[180] = 0; buf[181] = 0; buf[182] = 0; buf[183] = 1;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "wrong modifier should fail");
}

static void test_zero_connector_id() {
    auto buf = build_minimal_bundle(1);
    buf[232] = 0; buf[233] = 0; buf[234] = 0; buf[235] = 0;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "zero connector_id should fail");
}

static void test_zero_crtc_id() {
    auto buf = build_minimal_bundle(1);
    buf[236] = 0; buf[237] = 0; buf[238] = 0; buf[239] = 0;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "zero crtc_id should fail");
}

static void test_zero_plane_id() {
    auto buf = build_minimal_bundle(1);
    buf[240] = 0; buf[241] = 0; buf[242] = 0; buf[243] = 0;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "zero plane_id should fail");
}

static void test_truncated_bundle() {
    auto buf = build_minimal_bundle(1);
    buf.resize(buf.size() - 1);
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "truncated bundle should fail");
}

static void test_extended_bundle() {
    auto buf = build_minimal_bundle(1);
    buf.push_back(0x42);
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "extended bundle should fail");
}

static void test_frame_payload_hash_mismatch() {
    auto buf = build_minimal_bundle(1);
    size_t guard_before_size = 12;
    size_t data_size_per = 12;
    size_t hash_section_size = 4 + 4 + 32 + 4 + 1 * (4 + 4 + 32) + 4 + 4 + 32;
    size_t size_section_size = guard_before_size + data_size_per + guard_before_size;
    size_t payload_start = 348 + hash_section_size + size_section_size;
    size_t first_data_payload = payload_start + kFrameByteSize;
    buf[first_data_payload] ^= 0xff;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "payload hash mismatch should fail");
}

static void test_guard_after_mismatch() {
    auto buf = build_minimal_bundle(1);
    size_t guard_after_hash_off = 348 + 4 + 4 + 32 + 4 + 1 * (4 + 4 + 32) + 4 + 4;
    buf[guard_after_hash_off] ^= 1;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "guard-after hash mismatch should fail");
}

static void test_malformed_device_identity() {
    auto buf = build_minimal_bundle(1);
    const char malformed[16] = {'2', '2', '6', ':', '0', ':', '1', 0, 0, 0, 0, 0, 0, 0, 0, 0};
    std::memcpy(&buf[216], malformed, sizeof(malformed));
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "malformed device_identity should fail");
}

static void test_identical_payloads_distinct_ordinals() {
    // Build a bundle with two identical data frames but distinct ordinals
    uint32_t fc = 2;
    auto buf = build_minimal_bundle(fc);
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(result.success, "two-frame bundle should succeed");
    REQUIRE(result.plan->data_frames.size() == 2, "two data frames");
}

static void test_duplicate_frame_ordinal() {
    auto buf = build_minimal_bundle(2);
    // Corrupt data frame 1's ordinal to 0 (duplicate of data frame 0)
    size_t data1_ordinal_off = 348 + 4 + 4 + 32 + 4 + 4 + 4 + 32 + 4;
    buf[data1_ordinal_off] = 0; buf[data1_ordinal_off+1] = 0;
    buf[data1_ordinal_off+2] = 0; buf[data1_ordinal_off+3] = 0;
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "duplicate ordinal should fail");
}

static void test_reordered_frame_ordinals() {
    auto buf = build_minimal_bundle(2);
    size_t data0_ord_off = 348 + 4 + 4 + 32 + 4 + 4;
    size_t data1_ord_off = 348 + 4 + 4 + 32 + 4 + 4 + 4 + 32 + 4;
    // Swap ordinals
    uint8_t tmp[4];
    std::memcpy(tmp, &buf[data0_ord_off], 4);
    std::memcpy(&buf[data0_ord_off], &buf[data1_ord_off], 4);
    std::memcpy(&buf[data1_ord_off], tmp, 4);
    auto result = parse_native_display_bundle(buf.data(), buf.size());
    REQUIRE(!result.success, "reordered ordinals should fail");
}

static void test_print_contract() {
    AtomicDisplayPlan plan;
    plan.design_basis_commit = std::string(kDesignBasisCommit);
    plan.design_basis_tree = std::string(kDesignBasisTree);
    plan.connector_id = 31;
    plan.crtc_id = 41;
    plan.plane_id = 51;
    print_contract(plan);
}

int main() {
    std::cout << "native_display_bundle_test\n";

    TEST(valid_one_frame);
    TEST(valid_sixteen_frames);
    TEST(wrong_magic);
    TEST(wrong_version);
    TEST(wrong_bom);
    TEST(wrong_r2e1_hash);
    TEST(wrong_mode_clock);
    TEST(wrong_format);
    TEST(wrong_modifier);
    TEST(zero_connector_id);
    TEST(zero_crtc_id);
    TEST(zero_plane_id);
    TEST(truncated_bundle);
    TEST(extended_bundle);
    TEST(frame_payload_hash_mismatch);
    TEST(guard_after_mismatch);
    TEST(malformed_device_identity);
    TEST(identical_payloads_distinct_ordinals);
    TEST(duplicate_frame_ordinal);
    TEST(reordered_frame_ordinals);
    TEST(print_contract);

    std::cout << "\n" << tests_run << " tests, "
              << tests_failed << " failed\n";

    return tests_failed > 0 ? 1 : 0;
}
