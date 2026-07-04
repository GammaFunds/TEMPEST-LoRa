#include "tempest_lora/native_display_bundle.hpp"

#include <cstring>
#include <iostream>
#include <cstdlib>

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage:\n"
                  << "  " << argv[0] << " --print-contract\n"
                  << "  " << argv[0] << " --validate-bundle PATH\n"
                  << "\n"
                  << "This is a compile-only libdrm-linked validator.\n"
                  << "No live DRM operation occurs.\n"
                  << "No /dev/dri access or display output.\n";
        return 1;
    }

    std::string cmd = argv[1];

    if (cmd == "--print-contract") {
        tempest_lora::AtomicDisplayPlan plan;
        plan.design_basis_commit = std::string(tempest_lora::kDesignBasisCommit);
        plan.design_basis_tree = std::string(tempest_lora::kDesignBasisTree);
        plan.current_checkout_commit = "none";
        plan.current_checkout_tree = "none";
        plan.device_identity = "none";
        plan.connector_id = 0;
        plan.crtc_id = 0;
        plan.plane_id = 0;
        plan.mode.clock = tempest_lora::kModeClockKHz;
        plan.mode.hdisplay = tempest_lora::kModeHDisplay;
        plan.mode.hsync_start = tempest_lora::kModeHSyncStart;
        plan.mode.hsync_end = tempest_lora::kModeHSyncEnd;
        plan.mode.htotal = tempest_lora::kModeHTotal;
        plan.mode.vdisplay = tempest_lora::kModeVDisplay;
        plan.mode.vsync_start = tempest_lora::kModeVSyncStart;
        plan.mode.vsync_end = tempest_lora::kModeVSyncEnd;
        plan.mode.vtotal = tempest_lora::kModeVTotal;
        plan.src_x = tempest_lora::kSrcX;
        plan.src_y = tempest_lora::kSrcY;
        plan.src_w = tempest_lora::kSrcW;
        plan.src_h = tempest_lora::kSrcH;
        plan.dst_x = tempest_lora::kDstX;
        plan.dst_y = tempest_lora::kDstY;
        plan.dst_w = tempest_lora::kDstW;
        plan.dst_h = tempest_lora::kDstH;
        tempest_lora::print_contract(plan);
        return 0;
    }

    if (cmd == "--validate-bundle") {
        if (argc < 3) {
            std::cerr << "error: --validate-bundle requires a PATH argument\n";
            return 1;
        }
        const char* path = argv[2];

        std::vector<uint8_t> bundle_data;
        try {
            bundle_data = tempest_lora::read_entire_file(path);
        } catch (const std::exception& e) {
            std::cerr << "error: " << e.what() << "\n";
            return 1;
        }

        auto result = tempest_lora::parse_native_display_bundle(
            bundle_data.data(), bundle_data.size());

        if (!result.success) {
            std::cerr << "VALIDATION FAILED: " << result.error << "\n";
            return 2;
        }

        std::cout << "VALIDATION SUCCESS\n";
        std::cout << "connector_id=" << result.plan->connector_id << "\n";
        std::cout << "crtc_id=" << result.plan->crtc_id << "\n";
        std::cout << "plane_id=" << result.plan->plane_id << "\n";
        std::cout << "data_frame_count=" << result.plan->data_frames.size() << "\n";
        std::cout << "guard_before_sha256="
                  << tempest_lora::hex_encode(
                      result.plan->guard_before.sha256.data(), 32) << "\n";
        std::cout << "guard_after_sha256="
                  << tempest_lora::hex_encode(
                      result.plan->guard_after.sha256.data(), 32) << "\n";
        for (size_t i = 0; i < result.plan->data_frames.size(); ++i) {
            std::cout << "data_frame_" << i << "_sha256="
                      << tempest_lora::hex_encode(
                          result.plan->data_frames[i].sha256.data(), 32) << "\n";
        }
        std::cout << "no_live_drm_operation="
                  << (result.plan->no_live_drm_operation ? "true" : "false") << "\n";
        std::cout << "async_flip="
                  << (result.plan->async_flip ? "true" : "false") << "\n";
        std::cout << "max_outstanding_commits="
                  << result.plan->max_outstanding_commits << "\n";
        return 0;
    }

    std::cerr << "error: unknown command '" << cmd << "'\n"
              << "valid commands: --print-contract, --validate-bundle PATH\n";
    return 1;
}
