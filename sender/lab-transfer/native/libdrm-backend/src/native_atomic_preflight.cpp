#include "tempest_lora/native_atomic_preflight.hpp"

#include <algorithm>
#include <set>
#include <string>
#include <vector>

#include <libdrm/drm_fourcc.h>

namespace tempest_lora {

namespace {

const PropertySnapshot* find_property(
    const std::vector<PropertySnapshot>& props,
    const std::string& name) {
    for (const auto& p : props) {
        if (p.name == name) return &p;
    }
    return nullptr;
}

bool has_dup_ids(const std::vector<PropertySnapshot>& props) {
    std::set<uint32_t> ids;
    for (const auto& p : props) {
        if (!ids.insert(p.id).second) return true;
    }
    return false;
}

bool has_dup_names(const std::vector<PropertySnapshot>& props) {
    std::set<std::string> names;
    for (const auto& p : props) {
        if (!names.insert(p.name).second) return true;
    }
    return false;
}

bool all_property_ids_nonzero(const std::vector<PropertySnapshot>& props) {
    return std::all_of(props.begin(), props.end(),
                       [](const PropertySnapshot& prop) {
                           return prop.id != 0;
                       });
}

} // namespace

PreflightResult prepare_atomic_request(
    const AtomicDisplayPlan& plan,
    const KmsTopologySnapshot& snapshot)
{
    PreflightResult result;

    auto reject = [&](const std::string& msg) {
        result.success = false;
        result.error = msg;
    };

    if (plan.connector_id == 0 || plan.crtc_id == 0 || plan.plane_id == 0) {
        reject("plan connector/CRTC/plane IDs must be nonzero");
        return result;
    }

    if (snapshot.connector.connector_id != plan.connector_id) {
        reject("connector ID mismatch");
        return result;
    }
    if (snapshot.crtc.crtc_id != plan.crtc_id) {
        reject("CRTC ID mismatch");
        return result;
    }
    if (snapshot.plane.plane_id != plan.plane_id) {
        reject("plane ID mismatch");
        return result;
    }

    if (plan.mode.clock != kModeClockKHz ||
        plan.mode.hdisplay != kModeHDisplay ||
        plan.mode.hsync_start != kModeHSyncStart ||
        plan.mode.hsync_end != kModeHSyncEnd ||
        plan.mode.htotal != kModeHTotal ||
        plan.mode.vdisplay != kModeVDisplay ||
        plan.mode.vsync_start != kModeVSyncStart ||
        plan.mode.vsync_end != kModeVSyncEnd ||
        plan.mode.vtotal != kModeVTotal ||
        plan.mode.flags != (DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC)) {
        reject("plan exact mode mismatch");
        return result;
    }

    if (plan.fourcc != DRM_FORMAT_XRGB8888 ||
        plan.modifier != DRM_FORMAT_MOD_LINEAR) {
        reject("plan XRGB8888/linear mismatch");
        return result;
    }

    if (snapshot.device_identity != plan.device_identity) {
        reject("device identity mismatch");
        return result;
    }

    if (snapshot.edid_sha256 != plan.edid_sha256) {
        reject("EDID SHA-256 mismatch");
        return result;
    }

    if (snapshot.topology_token != plan.topology_token) {
        reject("topology token mismatch");
        return result;
    }

    if (!snapshot.connector.connected) {
        reject("connector is not connected");
        return result;
    }

    {
        auto it = std::find(snapshot.connector.possible_crtc_ids.begin(),
                            snapshot.connector.possible_crtc_ids.end(),
                            plan.crtc_id);
        if (it == snapshot.connector.possible_crtc_ids.end()) {
            reject("connector does not support selected CRTC");
            return result;
        }
    }

    if (!snapshot.plane.is_primary) {
        reject("plane is not a primary plane");
        return result;
    }

    {
        auto it = std::find(snapshot.plane.possible_crtc_ids.begin(),
                            snapshot.plane.possible_crtc_ids.end(),
                            plan.crtc_id);
        if (it == snapshot.plane.possible_crtc_ids.end()) {
            reject("plane does not support selected CRTC");
            return result;
        }
    }

    if (snapshot.mode_clock_khz != 148500 ||
        snapshot.mode_hdisplay != 1920 ||
        snapshot.mode_hsync_start != 2008 ||
        snapshot.mode_hsync_end != 2052 ||
        snapshot.mode_htotal != 2200 ||
        snapshot.mode_vdisplay != 1080 ||
        snapshot.mode_vsync_start != 1084 ||
        snapshot.mode_vsync_end != 1089 ||
        snapshot.mode_vtotal != 1125 ||
        !snapshot.mode_hsync_positive ||
        !snapshot.mode_vsync_positive ||
        snapshot.mode_interlaced ||
        snapshot.mode_doublescan) {
        reject("exact mode mismatch");
        return result;
    }

    {
        uint32_t src_w_int = plan.src_w >> 16;
        uint32_t src_h_int = plan.src_h >> 16;
        if (src_w_int != plan.dst_w || src_h_int != plan.dst_h) {
            reject("scaling present in geometry");
            return result;
        }
    }

    if (plan.src_x != kSrcX || plan.src_y != kSrcY ||
        plan.src_w != kSrcW || plan.src_h != kSrcH ||
        plan.dst_x != kDstX || plan.dst_y != kDstY ||
        plan.dst_w != kDstW || plan.dst_h != kDstH) {
        reject("source/destination rectangle mismatch");
        return result;
    }

    bool xrgb8888_linear = false;
    for (const auto& fmt : snapshot.plane.supported_formats) {
        if (fmt.fourcc == DRM_FORMAT_XRGB8888 &&
            fmt.modifier == DRM_FORMAT_MOD_LINEAR) {
            xrgb8888_linear = true;
            break;
        }
    }
    if (!xrgb8888_linear) {
        reject("XRGB8888/linear not supported");
        return result;
    }

    if (!snapshot.identity_gates.rotation) {
        reject("rotation identity gate not true");
        return result;
    }
    if (!snapshot.identity_gates.scaling) {
        reject("scaling identity gate not true");
        return result;
    }
    if (!snapshot.identity_gates.color_pipeline) {
        reject("color pipeline identity gate not true");
        return result;
    }

    auto* conn_crtc_id = find_property(snapshot.connector.properties, "CRTC_ID");
    if (!conn_crtc_id) {
        reject("missing connector CRTC_ID property");
        return result;
    }

    auto* crtc_mode_id = find_property(snapshot.crtc.properties, "MODE_ID");
    auto* crtc_active = find_property(snapshot.crtc.properties, "ACTIVE");
    if (!crtc_mode_id) {
        reject("missing CRTC MODE_ID property");
        return result;
    }
    if (!crtc_active) {
        reject("missing CRTC ACTIVE property");
        return result;
    }

    auto* plane_fb_id = find_property(snapshot.plane.properties, "FB_ID");
    auto* plane_crtc_id = find_property(snapshot.plane.properties, "CRTC_ID");
    auto* plane_src_x = find_property(snapshot.plane.properties, "SRC_X");
    auto* plane_src_y = find_property(snapshot.plane.properties, "SRC_Y");
    auto* plane_src_w = find_property(snapshot.plane.properties, "SRC_W");
    auto* plane_src_h = find_property(snapshot.plane.properties, "SRC_H");
    auto* plane_crtc_x = find_property(snapshot.plane.properties, "CRTC_X");
    auto* plane_crtc_y = find_property(snapshot.plane.properties, "CRTC_Y");
    auto* plane_crtc_w = find_property(snapshot.plane.properties, "CRTC_W");
    auto* plane_crtc_h = find_property(snapshot.plane.properties, "CRTC_H");

    if (!plane_fb_id) { reject("missing plane FB_ID property"); return result; }
    if (!plane_crtc_id) { reject("missing plane CRTC_ID property"); return result; }
    if (!plane_src_x) { reject("missing plane SRC_X property"); return result; }
    if (!plane_src_y) { reject("missing plane SRC_Y property"); return result; }
    if (!plane_src_w) { reject("missing plane SRC_W property"); return result; }
    if (!plane_src_h) { reject("missing plane SRC_H property"); return result; }
    if (!plane_crtc_x) { reject("missing plane CRTC_X property"); return result; }
    if (!plane_crtc_y) { reject("missing plane CRTC_Y property"); return result; }
    if (!plane_crtc_w) { reject("missing plane CRTC_W property"); return result; }
    if (!plane_crtc_h) { reject("missing plane CRTC_H property"); return result; }

    if (!all_property_ids_nonzero(snapshot.connector.properties) ||
        !all_property_ids_nonzero(snapshot.crtc.properties) ||
        !all_property_ids_nonzero(snapshot.plane.properties)) {
        reject("zero property ID");
        return result;
    }

    if (has_dup_ids(snapshot.connector.properties)) {
        reject("duplicate property ID in connector");
        return result;
    }
    if (has_dup_names(snapshot.connector.properties)) {
        reject("duplicate property name in connector");
        return result;
    }
    if (has_dup_ids(snapshot.crtc.properties)) {
        reject("duplicate property ID in CRTC");
        return result;
    }
    if (has_dup_names(snapshot.crtc.properties)) {
        reject("duplicate property name in CRTC");
        return result;
    }
    if (has_dup_ids(snapshot.plane.properties)) {
        reject("duplicate property ID in plane");
        return result;
    }
    if (has_dup_names(snapshot.plane.properties)) {
        reject("duplicate property name in plane");
        return result;
    }

    PreparedAtomicRequest req;
    req.test_only_before_live_required = true;
    req.allow_modeset_required = true;
    req.async_flip_forbidden = true;
    req.max_outstanding_commits = 1;

    auto add_imm = [&](uint32_t oid, DrmObjectClass cls,
                       const PropertySnapshot& prop, uint64_t val) {
        PropertyAssignment a;
        a.object_id = oid;
        a.object_class = cls;
        a.property_id = prop.id;
        a.property_name = prop.name;
        a.immediate_value = val;
        a.is_symbolic = false;
        a.symbolic_source = SymbolicValueSource::None;
        req.assignments.push_back(std::move(a));
    };

    auto add_sym = [&](uint32_t oid, DrmObjectClass cls,
                       const PropertySnapshot& prop,
                       SymbolicValueSource src) {
        PropertyAssignment a;
        a.object_id = oid;
        a.object_class = cls;
        a.property_id = prop.id;
        a.property_name = prop.name;
        a.immediate_value = 0;
        a.is_symbolic = true;
        a.symbolic_source = src;
        req.assignments.push_back(std::move(a));
    };

    add_imm(snapshot.connector.connector_id,
            DrmObjectClass::Connector, *conn_crtc_id, plan.crtc_id);

    add_sym(snapshot.crtc.crtc_id,
            DrmObjectClass::Crtc, *crtc_mode_id,
            SymbolicValueSource::FutureModeBlobId);

    add_imm(snapshot.crtc.crtc_id,
            DrmObjectClass::Crtc, *crtc_active, 1);

    add_sym(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_fb_id,
            SymbolicValueSource::FutureFramebufferId);

    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_crtc_id, plan.crtc_id);

    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_src_x, plan.src_x);
    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_src_y, plan.src_y);
    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_src_w, plan.src_w);
    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_src_h, plan.src_h);

    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_crtc_x, plan.dst_x);
    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_crtc_y, plan.dst_y);
    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_crtc_w, plan.dst_w);
    add_imm(snapshot.plane.plane_id,
            DrmObjectClass::Plane, *plane_crtc_h, plan.dst_h);

    result.success = true;
    result.request = std::move(req);
    return result;
}

} // namespace tempest_lora
