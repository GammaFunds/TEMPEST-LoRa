cmake_minimum_required(VERSION 3.20)
project(tempest_lora_native_bundle LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Treat warnings as errors
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -Wpedantic -Werror)
endif()

# Find dependencies via pkg-config imported targets
find_package(PkgConfig REQUIRED)
pkg_check_modules(DRM REQUIRED IMPORTED_TARGET libdrm)
pkg_check_modules(OPENSSL REQUIRED IMPORTED_TARGET openssl)

# Library
add_library(tempest_lora_native_bundle
    src/native_display_bundle.cpp
)
target_include_directories(tempest_lora_native_bundle
    PUBLIC include
)
target_link_libraries(tempest_lora_native_bundle
    PUBLIC PkgConfig::OPENSSL PkgConfig::DRM
)

# CLI tool
add_executable(tempest_lora_bundle_cli
    src/main.cpp
)
target_link_libraries(tempest_lora_bundle_cli
    PRIVATE tempest_lora_native_bundle
)
# Force libdrm DT_NEEDED via --no-as-needed (no live DRM function called)
target_link_options(tempest_lora_bundle_cli
    PRIVATE -Wl,--no-as-needed
)
target_link_libraries(tempest_lora_bundle_cli
    PRIVATE PkgConfig::DRM
)

# Tests
enable_testing()
add_executable(native_display_bundle_test
    tests/native_display_bundle_test.cpp
)
target_link_libraries(native_display_bundle_test
    PRIVATE tempest_lora_native_bundle
)
add_test(NAME native_display_bundle_test
    COMMAND native_display_bundle_test
)
