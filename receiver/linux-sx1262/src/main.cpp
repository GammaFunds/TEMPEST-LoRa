#include "tempest_lora/lab_pi_hal.hpp"
#include "tempest_lora/receiver_contract.hpp"
#include "tempest_lora/rx_record.hpp"

#include <RadioLib.h>

#include <atomic>
#include <charconv>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace {

std::atomic<bool> packet_received{false};
volatile std::sig_atomic_t stop_requested = 0;

void packet_received_callback() {
    packet_received.store(true, std::memory_order_release);
}

void signal_handler(int) {
    stop_requested = 1;
}

struct Options {
    bool help = false;
    bool print_contract = false;
    std::optional<std::uint64_t> max_packets;
};

bool parse_unsigned(
    const std::string_view text,
    std::uint64_t& value
) {
    if (text.empty()) {
        return false;
    }

    const char* begin = text.data();
    const char* end = begin + text.size();

    const auto result = std::from_chars(begin, end, value);

    return (
        result.ec == std::errc{} &&
        result.ptr == end
    );
}

std::optional<Options> parse_options(
    const int argument_count,
    char** arguments
) {
    Options options;

    for (int index = 1; index < argument_count; ++index) {
        const std::string_view argument(arguments[index]);

        if (argument == "--help") {
            if (options.help) {
                return std::nullopt;
            }

            options.help = true;
            continue;
        }

        if (argument == "--print-contract") {
            if (options.print_contract) {
                return std::nullopt;
            }

            options.print_contract = true;
            continue;
        }

        static constexpr std::string_view prefix =
            "--max-packets=";

        if (
            argument.size() >= prefix.size() &&
            argument.compare(0, prefix.size(), prefix) == 0
        ) {
            if (options.max_packets.has_value()) {
                return std::nullopt;
            }

            std::uint64_t parsed = 0;

            if (
                !parse_unsigned(argument.substr(prefix.size()), parsed) ||
                parsed == 0
            ) {
                return std::nullopt;
            }

            options.max_packets = parsed;
            continue;
        }

        return std::nullopt;
    }

    if (options.help && options.print_contract) {
        return std::nullopt;
    }

    return options;
}

void print_help() {
    std::cout
        << "Usage: tempest-lora-sx1262-receiver [OPTIONS]\n"
        << "\n"
        << "Options:\n"
        << "  --max-packets=N   Exit after N packet events\n"
        << "  --print-contract  Print the fixed receiver contract without hardware access\n"
        << "  --help            Show this help without hardware access\n";
}

std::optional<std::string> utc_now() {
    using namespace std::chrono;

    const system_clock::time_point now = system_clock::now();
    const auto whole_seconds = time_point_cast<seconds>(now);
    const auto microseconds_part =
        duration_cast<microseconds>(now - whole_seconds).count();

    const std::time_t timestamp =
        system_clock::to_time_t(now);

    std::tm utc{};

    if (gmtime_r(&timestamp, &utc) == nullptr) {
        return std::nullopt;
    }

    char date_buffer[32] = {};

    if (
        std::strftime(
            date_buffer,
            sizeof(date_buffer),
            "%Y-%m-%dT%H:%M:%S",
            &utc
        ) == 0
    ) {
        return std::nullopt;
    }

    std::ostringstream output;

    output
        << date_buffer
        << '.'
        << std::setw(6)
        << std::setfill('0')
        << microseconds_part
        << 'Z';

    return output.str();
}

std::uint64_t monotonic_now_ns() {
    using namespace std::chrono;

    return static_cast<std::uint64_t>(
        duration_cast<nanoseconds>(
            steady_clock::now().time_since_epoch()
        ).count()
    );
}

void set_first_exit_code(int& current, const int proposed) {
    if (current == tempest_lora::contract::kExitSuccess) {
        current = proposed;
    }
}

bool report_radio_failure(
    const std::string_view operation,
    const int state,
    const tempest_lora::LabPiHal& hal
) {
    if (
        state == RADIOLIB_ERR_NONE &&
        hal.ready()
    ) {
        return false;
    }

    std::cerr
        << "radio_step_failed operation="
        << operation
        << " radiolib_state="
        << state
        << " hal_error="
        << hal.last_error()
        << " hal_operation="
        << hal.last_operation()
        << '\n';

    return true;
}

bool write_event(const tempest_lora::RxEvent& event) {
    std::cout
        << tempest_lora::serialize_rx_event(event)
        << '\n';

    std::cout.flush();

    return std::cout.good();
}

}  // namespace

int main(int argc, char** argv) {
    const std::optional<Options> parsed =
        parse_options(argc, argv);

    if (!parsed.has_value()) {
        std::cerr << "invalid command line\n";
        return tempest_lora::contract::kExitInvalidCommandLine;
    }

    const Options options = *parsed;

    if (options.help) {
        print_help();
        std::cout.flush();

        return std::cout.good()
            ? tempest_lora::contract::kExitSuccess
            : tempest_lora::contract::kExitOutputFailure;
    }

    if (options.print_contract) {
        std::cout << tempest_lora::contract::kContractText;
        std::cout.flush();

        return std::cout.good()
            ? tempest_lora::contract::kExitSuccess
            : tempest_lora::contract::kExitOutputFailure;
    }

    const auto previous_sigint =
        std::signal(SIGINT, signal_handler);

    const auto previous_sigterm =
        std::signal(SIGTERM, signal_handler);

    if (
        previous_sigint == SIG_ERR ||
        previous_sigterm == SIG_ERR
    ) {
        std::cerr << "signal_handler_install_failed\n";
        return tempest_lora::contract::kExitContractViolation;
    }

    tempest_lora::LabPiHal hal(
        tempest_lora::contract::kSpiChannelIndex,
        tempest_lora::contract::kSpiSpeedHz,
        tempest_lora::contract::kSpiDeviceIndex,
        tempest_lora::contract::kGpioChipIndex
    );

    Module module(
        &hal,
        RADIOLIB_NC,
        tempest_lora::contract::kDio1Gpio,
        tempest_lora::contract::kResetGpio,
        tempest_lora::contract::kBusyGpio
    );

    SX1262 radio(&module);

    int exit_code = tempest_lora::contract::kExitSuccess;
    bool radio_initialized = false;
    bool callback_installed = false;
    bool application_processing = true;

    if (!hal.open()) {
        std::cerr
            << "hal_open_failed error="
            << hal.last_error()
            << " operation="
            << hal.last_operation()
            << '\n';

        return tempest_lora::contract::kExitHalOpenFailure;
    }

    radio.tcxoVoltage =
        tempest_lora::contract::kTcxoVoltage;

    radio.useRegulatorLDO =
        tempest_lora::contract::kUseRegulatorLdo;

    ConfigLoRa_t config;
    config.frequency =
        tempest_lora::contract::kFrequencyMhz;
    config.bandwidth =
        tempest_lora::contract::kBandwidthKhz;
    config.spreadingFactor =
        tempest_lora::contract::kSpreadingFactor;
    config.codingRate =
        tempest_lora::contract::kCodingRateDenominator;
    config.syncWord =
        tempest_lora::contract::kSyncWord;
    config.power =
        tempest_lora::contract::kOutputPowerDbm;
    config.preambleLength =
        tempest_lora::contract::kPreambleSymbols;

    int state = radio.begin(config);

    if (report_radio_failure("begin", state, hal)) {
        set_first_exit_code(
            exit_code,
            tempest_lora::contract::kExitRadioConfigurationFailure
        );
    } else {
        radio_initialized = true;
    }

    const auto configuration_step =
        [&](const std::string_view operation, const int result) {
            if (exit_code != tempest_lora::contract::kExitSuccess) {
                return;
            }

            if (report_radio_failure(operation, result, hal)) {
                set_first_exit_code(
                    exit_code,
                    tempest_lora::contract::kExitRadioConfigurationFailure
                );
            }
        };

    if (exit_code == tempest_lora::contract::kExitSuccess) {
        configuration_step(
            "setSyncWord",
            radio.setSyncWord(tempest_lora::contract::kSyncWord)
        );

        configuration_step(
            "setPreambleLength",
            radio.setPreambleLength(
                tempest_lora::contract::kPreambleSymbols
            )
        );

        configuration_step(
            "explicitHeader",
            radio.explicitHeader()
        );

        configuration_step(
            "setCRC",
            radio.setCRC(tempest_lora::contract::kCrcBytes)
        );

        configuration_step(
            "invertIQ",
            radio.invertIQ(tempest_lora::contract::kIqInverted)
        );

        configuration_step(
            "setDio2AsRfSwitch",
            radio.setDio2AsRfSwitch(
                tempest_lora::contract::kDio2RfSwitch
            )
        );
    }

    if (exit_code == tempest_lora::contract::kExitSuccess) {
        radio.setPacketReceivedAction(
            packet_received_callback
        );

        if (!hal.ready()) {
            std::cerr
                << "callback_install_failed hal_error="
                << hal.last_error()
                << " operation="
                << hal.last_operation()
                << '\n';

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitRadioConfigurationFailure
            );
        } else {
            callback_installed = true;
        }
    }

    if (exit_code == tempest_lora::contract::kExitSuccess) {
        packet_received.store(false);

        state = radio.startReceive();

        if (
            report_radio_failure(
                "initial-startReceive",
                state,
                hal
            )
        ) {
            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitInitialReceiveFailure
            );
        }
    }

    std::uint64_t sequence = 0;

    while (
        exit_code == tempest_lora::contract::kExitSuccess &&
        stop_requested == 0
    ) {
        if (!hal.ready()) {
            std::cerr
                << "hal_failed_while_receiving error="
                << hal.last_error()
                << " operation="
                << hal.last_operation()
                << '\n';

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitPacketReadFailure
            );
            break;
        }

        if (
            !packet_received.exchange(
                false,
                std::memory_order_acq_rel
            )
        ) {
            std::this_thread::sleep_for(
                std::chrono::milliseconds(10)
            );
            continue;
        }

        if (!application_processing) {
            continue;
        }

        const std::size_t length = radio.getPacketLength();

        if (!hal.ready()) {
            std::cerr
                << "getPacketLength_failed error="
                << hal.last_error()
                << " operation="
                << hal.last_operation()
                << '\n';

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitPacketReadFailure
            );
            break;
        }

        if (length > tempest_lora::contract::kMaximumPacketLength) {
            std::cerr
                << "packet_length_contract_violation length="
                << length
                << '\n';

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitContractViolation
            );
            break;
        }

        std::vector<std::uint8_t> payload(length);
        int read_state = RADIOLIB_ERR_NONE;

        if (length > 0) {
            read_state = radio.readData(
                payload.data(),
                payload.size()
            );
        }

        if (!hal.ready()) {
            std::cerr
                << "packet_read_hal_failed error="
                << hal.last_error()
                << " operation="
                << hal.last_operation()
                << '\n';

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitPacketReadFailure
            );
            break;
        }

        if (
            read_state != RADIOLIB_ERR_NONE &&
            read_state != RADIOLIB_ERR_CRC_MISMATCH
        ) {
            std::cerr
                << "packet_read_failed radiolib_state="
                << read_state
                << '\n';

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitPacketReadFailure
            );
            break;
        }

        const float rssi = radio.getRSSI();

        if (!hal.ready()) {
            std::cerr
                << "rssi_read_failed error="
                << hal.last_error()
                << " operation="
                << hal.last_operation()
                << '\n';

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitPacketReadFailure
            );
            break;
        }

        const float snr = radio.getSNR();

        if (!hal.ready()) {
            std::cerr
                << "snr_read_failed error="
                << hal.last_error()
                << " operation="
                << hal.last_operation()
                << '\n';

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitPacketReadFailure
            );
            break;
        }

        const std::optional<std::string> event_time_utc =
            utc_now();

        if (!event_time_utc.has_value()) {
            std::cerr << "timestamp_generation_failed\n";

            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitOutputFailure
            );
            break;
        }

        ++sequence;

        tempest_lora::RxEvent event;
        event.sequence = sequence;
        event.time_utc = *event_time_utc;
        event.monotonic_ns = monotonic_now_ns();
        event.payload = std::move(payload);
        event.rssi_dbm = rssi;
        event.snr_db = snr;
        event.radiolib_state = read_state;

        if (length == 0) {
            event.type = "packet_error";
            event.crc = "unknown";
        } else if (read_state == RADIOLIB_ERR_NONE) {
            event.type = "packet";
            event.crc = "ok";
        } else if (read_state == RADIOLIB_ERR_CRC_MISMATCH) {
            event.type = "packet_error";
            event.crc = "mismatch";
        } else {
            event.type = "packet_error";
            event.crc = "unknown";
        }

        if (!write_event(event)) {
            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitOutputFailure
            );
            break;
        }

        if (
            options.max_packets.has_value() &&
            sequence >= *options.max_packets
        ) {
            break;
        }

        state = radio.startReceive();

        if (
            report_radio_failure(
                "restart-startReceive",
                state,
                hal
            )
        ) {
            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitRestartReceiveFailure
            );
            break;
        }
    }

    application_processing = false;

    if (callback_installed) {
        radio.clearPacketReceivedAction();

        if (
            !hal.ready() &&
            exit_code == tempest_lora::contract::kExitSuccess
        ) {
            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitCleanupFailure
            );
        }
    }

    if (radio_initialized && hal.ready()) {
        const int standby_state = radio.standby();

        if (
            report_radio_failure(
                "cleanup-standby",
                standby_state,
                hal
            ) &&
            exit_code == tempest_lora::contract::kExitSuccess
        ) {
            set_first_exit_code(
                exit_code,
                tempest_lora::contract::kExitCleanupFailure
            );
        }
    }

    const bool close_success = hal.close();

    if (
        !close_success &&
        exit_code == tempest_lora::contract::kExitSuccess
    ) {
        std::cerr
            << "hal_cleanup_failed error="
            << hal.last_error()
            << " operation="
            << hal.last_operation()
            << '\n';

        set_first_exit_code(
            exit_code,
            tempest_lora::contract::kExitCleanupFailure
        );
    }

    std::cout.flush();

    if (
        !std::cout.good() &&
        exit_code == tempest_lora::contract::kExitSuccess
    ) {
        set_first_exit_code(
            exit_code,
            tempest_lora::contract::kExitCleanupFailure
        );
    }

    return exit_code;
}
