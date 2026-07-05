#include "tempest_lora/native_atomic_preflight.hpp"

#include <iostream>
#include <sstream>
#include <cstdlib>
#include <cstring>
#include <vector>

#include <libdrm/drm_fourcc.h>

static int tests_run = 0;
static int tests_failed = 0;

#define TEST(name)                                                    \
    do {                                                              \
        ++tests_run;                                                  \
        try {                                                         \
            test_##name();                                            \
            std::cout << "  PASS: " #name << "\n";                   \
        } catch (const std::exception& e) {                           \
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

tempest_lora::PropertySnapshot make_prop(uint32_t id, const std::string& name, uint64_t val = 0) {
    PropertySnapshot p;
    p.id = id;
    p.name = name;
    p.value = val;
    return p;
}

AtomicDisplayPlan make_valid_plan() {
    AtomicDisplayPlan plan;
    plan.connector_id = 31;
    plan.crtc_id = 41;
    plan.plane_id = 51;
    plan.device_identity = "226:0";
    plan.edid_sha256 = "ab00000000000000000000000000000000000000000000000000000000000000";
    plan.topology_token = "topology-v1";
    plan.fourcc = DRM_FORMAT_XRGB8888;
    plan.modifier = DRM_FORMAT_MOD_LINEAR;
    plan.mode.clock = 148500;
    plan.mode.hdisplay = 1920;
    plan.mode.hsync_start = 2008;
    plan.mode.hsync_end = 2052;
    plan.mode.htotal = 2200;
    plan.mode.vdisplay = 1080;
    plan.mode.vsync_start = 1084;
    plan.mode.vsync_end = 1089;
    plan.mode.vtotal = 1125;
    plan.mode.vrefresh = 60;
    plan.mode.flags = DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC;
    plan.mode.type = DRM_MODE_TYPE_DRIVER;
    plan.src_x = kSrcX;
    plan.src_y = kSrcY;
    plan.src_w = kSrcW;
    plan.src_h = kSrcH;
    plan.dst_x = kDstX;
    plan.dst_y = kDstY;
    plan.dst_w = kDstW;
    plan.dst_h = kDstH;
    return plan;
}

KmsTopologySnapshot make_valid_snapshot(const AtomicDisplayPlan& plan) {
    KmsTopologySnapshot snap;
    snap.device_identity = plan.device_identity;
    snap.edid_sha256 = plan.edid_sha256;
    snap.topology_token = plan.topology_token;

    snap.connector.connector_id = plan.connector_id;
    snap.connector.connected = true;
    snap.connector.possible_crtc_ids = {plan.crtc_id};
    snap.connector.properties = {
        make_prop(101, "CRTC_ID")
    };

    snap.crtc.crtc_id = plan.crtc_id;
    snap.crtc.properties = {
        make_prop(201, "MODE_ID"),
        make_prop(202, "ACTIVE")
    };

    snap.plane.plane_id = plan.plane_id;
    snap.plane.is_primary = true;
    snap.plane.possible_crtc_ids = {plan.crtc_id};
    snap.plane.supported_formats = {
        {DRM_FORMAT_XRGB8888, DRM_FORMAT_MOD_LINEAR}
    };
    snap.plane.properties = {
        make_prop(301, "FB_ID"),
        make_prop(302, "CRTC_ID"),
        make_prop(303, "SRC_X"),
        make_prop(304, "SRC_Y"),
        make_prop(305, "SRC_W"),
        make_prop(306, "SRC_H"),
        make_prop(307, "CRTC_X"),
        make_prop(308, "CRTC_Y"),
        make_prop(309, "CRTC_W"),
        make_prop(310, "CRTC_H")
    };

    snap.identity_gates.rotation = true;
    snap.identity_gates.scaling = true;
    snap.identity_gates.color_pipeline = true;

    snap.mode_clock_khz = 148500;
    snap.mode_hdisplay = 1920;
    snap.mode_hsync_start = 2008;
    snap.mode_hsync_end = 2052;
    snap.mode_htotal = 2200;
    snap.mode_vdisplay = 1080;
    snap.mode_vsync_start = 1084;
    snap.mode_vsync_end = 1089;
    snap.mode_vtotal = 1125;
    snap.mode_hsync_positive = true;
    snap.mode_vsync_positive = true;
    snap.mode_interlaced = false;
    snap.mode_doublescan = false;

    return snap;
}

void require_failure(const PreflightResult& result,
                     const std::string& expected_error) {
    REQUIRE(!result.success, "expected failure");
    REQUIRE(result.error == expected_error,
            "expected error '" + expected_error + "', got '" + result.error + "'");
}

} // namespace

static void test_valid_exact_snapshot() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(result.success, "valid snapshot should succeed");
    REQUIRE(result.request.assignments.size() == 13,
            "should have 13 assignments, got " + std::to_string(result.request.assignments.size()));
}

static void test_deterministic_assignment_order() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(result.success, "should succeed");

    REQUIRE(result.request.assignments.size() == 13, "13 assignments");

    const char* expected_names[13] = {
        "CRTC_ID",    // connector
        "MODE_ID",    // CRTC
        "ACTIVE",     // CRTC
        "FB_ID",      // plane
        "CRTC_ID",    // plane
        "SRC_X",      // plane
        "SRC_Y",      // plane
        "SRC_W",      // plane
        "SRC_H",      // plane
        "CRTC_X",     // plane
        "CRTC_Y",     // plane
        "CRTC_W",     // plane
        "CRTC_H"      // plane
    };

    DrmObjectClass expected_classes[13] = {
        DrmObjectClass::Connector,
        DrmObjectClass::Crtc,
        DrmObjectClass::Crtc,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane,
        DrmObjectClass::Plane
    };

    for (size_t i = 0; i < 13; ++i) {
        REQUIRE(result.request.assignments[i].property_name == expected_names[i],
                "assignment " + std::to_string(i) + " name mismatch: expected " +
                expected_names[i] + ", got " + result.request.assignments[i].property_name);
        REQUIRE(result.request.assignments[i].object_class == expected_classes[i],
                "assignment " + std::to_string(i) + " class mismatch");
    }
}

static void test_symbolic_mode_id() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(result.success, "should succeed");
    REQUIRE(result.request.assignments.size() >= 2, "at least 2 assignments");
    REQUIRE(result.request.assignments[1].property_name == "MODE_ID",
            "second assignment should be MODE_ID");
    REQUIRE(result.request.assignments[1].is_symbolic == true,
            "MODE_ID should be symbolic");
    REQUIRE(result.request.assignments[1].symbolic_source == SymbolicValueSource::FutureModeBlobId,
            "MODE_ID source should be FutureModeBlobId");
}

static void test_symbolic_fb_id() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(result.success, "should succeed");
    REQUIRE(result.request.assignments.size() >= 4, "at least 4 assignments");
    REQUIRE(result.request.assignments[3].property_name == "FB_ID",
            "fourth assignment should be FB_ID");
    REQUIRE(result.request.assignments[3].is_symbolic == true,
            "FB_ID should be symbolic");
    REQUIRE(result.request.assignments[3].symbolic_source == SymbolicValueSource::FutureFramebufferId,
            "FB_ID source should be FutureFramebufferId");
}

static void test_prepared_request_values_and_markers() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(result.success, "should succeed");
    REQUIRE(result.request.test_only_before_live_required,
            "TEST_ONLY-before-live marker must be true");
    REQUIRE(result.request.allow_modeset_required,
            "ALLOW_MODESET marker must be true");
    REQUIRE(result.request.async_flip_forbidden,
            "asynchronous flip must be forbidden");
    REQUIRE(result.request.max_outstanding_commits == 1,
            "maximum outstanding commits must be one");

    const uint32_t expected_object_ids[13] = {
        plan.connector_id,
        plan.crtc_id, plan.crtc_id,
        plan.plane_id, plan.plane_id, plan.plane_id, plan.plane_id,
        plan.plane_id, plan.plane_id, plan.plane_id, plan.plane_id,
        plan.plane_id, plan.plane_id
    };
    const uint32_t expected_property_ids[13] = {
        101, 201, 202, 301, 302, 303, 304,
        305, 306, 307, 308, 309, 310
    };
    const uint64_t expected_immediate_values[13] = {
        plan.crtc_id, 0, 1, 0, plan.crtc_id,
        plan.src_x, plan.src_y, plan.src_w, plan.src_h,
        plan.dst_x, plan.dst_y, plan.dst_w, plan.dst_h
    };

    for (size_t i = 0; i < 13; ++i) {
        const auto& assignment = result.request.assignments[i];
        REQUIRE(assignment.object_id == expected_object_ids[i],
                "assignment object ID mismatch at index " + std::to_string(i));
        REQUIRE(assignment.property_id == expected_property_ids[i],
                "assignment property ID mismatch at index " + std::to_string(i));
        REQUIRE(assignment.immediate_value == expected_immediate_values[i],
                "assignment immediate value mismatch at index " + std::to_string(i));
    }

    for (size_t i : {size_t{1}, size_t{3}}) {
        REQUIRE(result.request.assignments[i].is_symbolic,
                "symbolic assignment expected at index " + std::to_string(i));
    }
    for (size_t i = 0; i < 13; ++i) {
        if (i == 1 || i == 3) continue;
        REQUIRE(!result.request.assignments[i].is_symbolic,
                "immediate assignment expected at index " + std::to_string(i));
        REQUIRE(result.request.assignments[i].symbolic_source == SymbolicValueSource::None,
                "immediate assignment must have no symbolic source");
    }
}

static void test_missing_connector_property() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.connector.properties.clear();
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "missing connector CRTC_ID should fail");
}

static void test_missing_crtc_property() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.crtc.properties.clear();
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "missing CRTC properties should fail");
}

static void test_missing_plane_property() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.plane.properties.clear();
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "missing plane properties should fail");
}

static void test_duplicate_property_name() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.connector.properties.push_back(make_prop(999, "CRTC_ID"));
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "duplicate property name should fail");
}

static void test_duplicate_property_id() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.connector.properties.push_back(make_prop(101, "DUPLICATE_ID"));
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "duplicate property ID should fail");
}

static void test_zero_property_id() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.connector.properties.clear();
    snap.connector.properties.push_back(make_prop(0, "CRTC_ID"));
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "zero property ID should fail");
}

static void test_extra_zero_property_id() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.connector.properties.push_back(make_prop(0, "UNRELATED"));
    auto result = prepare_atomic_request(plan, snap);
    require_failure(result, "zero property ID");
}

static void test_plan_mode_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    plan.mode.clock = 74250;
    auto result = prepare_atomic_request(plan, snap);
    require_failure(result, "plan exact mode mismatch");
}

static void test_plan_fourcc_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    plan.fourcc = DRM_FORMAT_ARGB8888;
    auto result = prepare_atomic_request(plan, snap);
    require_failure(result, "plan XRGB8888/linear mismatch");
}

static void test_plan_modifier_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    plan.modifier = 1;
    auto result = prepare_atomic_request(plan, snap);
    require_failure(result, "plan XRGB8888/linear mismatch");
}

static void test_connector_id_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.connector.connector_id = 999;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "connector ID mismatch should fail");
}

static void test_crtc_id_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.crtc.crtc_id = 999;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "CRTC ID mismatch should fail");
}

static void test_plane_id_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.plane.plane_id = 999;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "plane ID mismatch should fail");
}

static void test_edid_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.edid_sha256 = "bb00000000000000000000000000000000000000000000000000000000000000";
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "EDID mismatch should fail");
}

static void test_topology_token_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.topology_token = "wrong-token";
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "topology token mismatch should fail");
}

static void test_device_identity_mismatch() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.device_identity = "999:999";
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "device identity mismatch should fail");
}

static void test_disconnected_connector() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.connector.connected = false;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "disconnected connector should fail");
}

static void test_incompatible_crtc() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.connector.possible_crtc_ids = {42};
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "incompatible CRTC should fail");
}

static void test_incompatible_plane_crtc() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.plane.possible_crtc_ids = {42};
    auto result = prepare_atomic_request(plan, snap);
    require_failure(result, "plane does not support selected CRTC");
}

static void test_nonprimary_plane() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.plane.is_primary = false;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "non-primary plane should fail");
}

static void test_wrong_pixel_clock() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.mode_clock_khz = 148500;
    snap.mode_hdisplay = 1920;
    snap.mode_hsync_start = 2008;
    snap.mode_hsync_end = 2052;
    snap.mode_htotal = 2200;
    snap.mode_vdisplay = 1080;
    snap.mode_vsync_start = 1084;
    snap.mode_vsync_end = 1089;
    snap.mode_vtotal = 1125;
    snap.mode_hsync_positive = true;
    snap.mode_vsync_positive = true;
    snap.mode_interlaced = false;
    snap.mode_doublescan = false;
    snap.mode_clock_khz = 74250;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "wrong pixel clock should fail");
}

static void test_wrong_sync_flag() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.mode_hsync_positive = false;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "wrong sync flag should fail");
}

static void test_unsupported_xrgb8888() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.plane.supported_formats.clear();
    snap.plane.supported_formats.push_back({DRM_FORMAT_ARGB8888, DRM_FORMAT_MOD_LINEAR});
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "unsupported XRGB8888 should fail");
}

static void test_unsupported_linear_modifier() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.plane.supported_formats.clear();
    snap.plane.supported_formats.push_back({DRM_FORMAT_XRGB8888, 1});
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "unsupported LINEAR modifier should fail");
}

static void test_nonidentity_rotation() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.identity_gates.rotation = false;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "nonidentity rotation should fail");
}

static void test_nonidentity_scaling() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.identity_gates.scaling = false;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "nonidentity scaling should fail");
}

static void test_nonidentity_color_path() {
    auto plan = make_valid_plan();
    auto snap = make_valid_snapshot(plan);
    snap.identity_gates.color_pipeline = false;
    auto result = prepare_atomic_request(plan, snap);
    REQUIRE(!result.success, "nonidentity color path should fail");
}

static void test_scaled_destination_geometry() {
    auto plan = make_valid_plan();
    plan.dst_w = 960;
    plan.dst_h = 540;
    auto snap = make_valid_snapshot(plan);
    auto result = prepare_atomic_request(plan, snap);
    require_failure(result, "scaling present in geometry");
}

int main() {
    std::cout << "native_atomic_preflight_test\n";

    TEST(valid_exact_snapshot);
    TEST(deterministic_assignment_order);
    TEST(symbolic_mode_id);
    TEST(symbolic_fb_id);
    TEST(prepared_request_values_and_markers);
    TEST(missing_connector_property);
    TEST(missing_crtc_property);
    TEST(missing_plane_property);
    TEST(duplicate_property_name);
    TEST(duplicate_property_id);
    TEST(zero_property_id);
    TEST(extra_zero_property_id);
    TEST(plan_mode_mismatch);
    TEST(plan_fourcc_mismatch);
    TEST(plan_modifier_mismatch);
    TEST(connector_id_mismatch);
    TEST(crtc_id_mismatch);
    TEST(plane_id_mismatch);
    TEST(edid_mismatch);
    TEST(topology_token_mismatch);
    TEST(device_identity_mismatch);
    TEST(disconnected_connector);
    TEST(incompatible_crtc);
    TEST(incompatible_plane_crtc);
    TEST(nonprimary_plane);
    TEST(wrong_pixel_clock);
    TEST(wrong_sync_flag);
    TEST(unsupported_xrgb8888);
    TEST(unsupported_linear_modifier);
    TEST(nonidentity_rotation);
    TEST(nonidentity_scaling);
    TEST(nonidentity_color_path);
    TEST(scaled_destination_geometry);

    std::cout << "\n" << tests_run << " tests, "
              << tests_failed << " failed\n";

    return tests_failed > 0 ? 1 : 0;
}
