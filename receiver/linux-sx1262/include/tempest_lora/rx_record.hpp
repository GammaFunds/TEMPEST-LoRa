#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace tempest_lora {

struct RxEvent {
    std::string type;
    std::uint64_t sequence = 0;
    std::string time_utc;
    std::uint64_t monotonic_ns = 0;
    std::vector<std::uint8_t> payload;
    float rssi_dbm = 0.0F;
    float snr_db = 0.0F;
    std::string crc;
    int radiolib_state = 0;
};

std::string bytes_to_hex(const std::vector<std::uint8_t>& bytes);
std::string bytes_to_ascii(const std::vector<std::uint8_t>& bytes);
std::string json_escape(const std::string& value);
std::string serialize_rx_event(const RxEvent& event);

}  // namespace tempest_lora
