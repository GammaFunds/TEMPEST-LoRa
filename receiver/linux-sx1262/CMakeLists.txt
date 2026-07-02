cmake_minimum_required(VERSION 3.16)

project(
    tempest_lora_linux_sx1262
    VERSION 1.0.0
    LANGUAGES CXX
)

option(
    TEMPEST_LORA_BUILD_HARDWARE_RECEIVER
    "Build the lgpio-backed SX1262 hardware receiver"
    OFF
)

option(
    TEMPEST_LORA_BUILD_CONTRACT_TESTS
    "Build hardware-independent receiver contract tests"
    ON
)

add_library(
    tempest_lora_rx_record
    STATIC
    src/rx_record.cpp
)

target_include_directories(
    tempest_lora_rx_record
    PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)

set_target_properties(
    tempest_lora_rx_record
    PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED YES
    CXX_EXTENSIONS NO
)

target_compile_options(
    tempest_lora_rx_record
    PRIVATE
    -Wall
    -Wextra
    -Wpedantic
    -Werror
)

if(TEMPEST_LORA_BUILD_CONTRACT_TESTS)
    enable_testing()

    add_executable(
        receiver_contract_test
        tests/receiver_contract_test.cpp
    )

    target_include_directories(
        receiver_contract_test
        PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/include"
    )

    set_target_properties(
        receiver_contract_test
        PROPERTIES
        CXX_STANDARD 17
        CXX_STANDARD_REQUIRED YES
        CXX_EXTENSIONS NO
    )

    target_compile_options(
        receiver_contract_test
        PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Werror
    )

    add_test(
        NAME receiver_contract_test
        COMMAND receiver_contract_test
    )

    add_executable(
        rx_record_test
        tests/rx_record_test.cpp
    )

    target_link_libraries(
        rx_record_test
        PRIVATE
        tempest_lora_rx_record
    )

    set_target_properties(
        rx_record_test
        PROPERTIES
        CXX_STANDARD 17
        CXX_STANDARD_REQUIRED YES
        CXX_EXTENSIONS NO
    )

    target_compile_options(
        rx_record_test
        PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Werror
    )

    add_test(
        NAME rx_record_test
        COMMAND rx_record_test
    )
endif()

if(TEMPEST_LORA_BUILD_HARDWARE_RECEIVER)
    set(
        RADIOLIB_SOURCE_DIR
        "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/RadioLib"
    )

    if(NOT EXISTS "${RADIOLIB_SOURCE_DIR}/CMakeLists.txt")
        message(
            FATAL_ERROR
            "Pinned RadioLib submodule is missing. "
            "Initialize third_party/RadioLib explicitly."
        )
    endif()

    add_subdirectory(
        "${RADIOLIB_SOURCE_DIR}"
        "${CMAKE_CURRENT_BINARY_DIR}/RadioLib"
    )

    find_path(
        LGPIO_INCLUDE_DIR
        NAMES lgpio.h
        REQUIRED
    )

    find_library(
        LGPIO_LIBRARY
        NAMES lgpio
        REQUIRED
    )

    find_package(Threads REQUIRED)

    add_executable(
        tempest-lora-sx1262-receiver
        src/main.cpp
        src/lab_pi_hal.cpp
    )

    target_include_directories(
        tempest-lora-sx1262-receiver
        PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/include"
        "${LGPIO_INCLUDE_DIR}"
    )

    target_link_libraries(
        tempest-lora-sx1262-receiver
        PRIVATE
        tempest_lora_rx_record
        RadioLib
        "${LGPIO_LIBRARY}"
        Threads::Threads
    )

    set_target_properties(
        tempest-lora-sx1262-receiver
        PROPERTIES
        CXX_STANDARD 20
        CXX_STANDARD_REQUIRED YES
        CXX_EXTENSIONS NO
    )

    target_compile_options(
        tempest-lora-sx1262-receiver
        PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Werror
    )
endif()
