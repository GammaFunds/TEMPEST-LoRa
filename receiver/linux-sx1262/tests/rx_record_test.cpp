#include "tempest_lora/rx_record.hpp"

#include <iostream>
#include <string>
#include <vector>

int main() {
    const std::vector<std::uint8_t> payload{
        0x00,
        0x20,
        0x22,
        0x5c,
        0x7e,
        0x7f,
        0xff,
    };

    if (
        tempest_lora::bytes_to_hex(payload) !=
        "0020225c7e7fff"
    ) {
        std::cerr << "hex conversion mismatch\n";
        return 1;
    }

    if (
        tempest_lora::bytes_to_ascii(payload) !=
        ". \"\\~.."
    ) {
        std::cerr << "ASCII conversion mismatch\n";
        return 1;
    }

    if (
        tempest_lora::json_escape("\"\\\n") !=
        "\\\"\\\\\\n"
    ) {
        std::cerr << "JSON escaping mismatch\n";
        return 1;
    }

    tempest_lora::RxEvent event;
    event.type = "packet";
    event.sequence = 7;
    event.time_utc = "2026-07-02T12:00:00.123456Z";
    event.monotonic_ns = 42;
    event.payload = payload;
    event.rssi_dbm = -70.25F;
    event.snr_db = 7.5F;
    event.crc = "ok";
    event.radiolib_state = 0;

    const std::string json =
        tempest_lora::serialize_rx_event(event);

    const std::vector<std::string> required{
        "\"schema\":\"tempest-lora.rx.v1\"",
        "\"type\":\"packet\"",
        "\"sequence\":7",
        "\"monotonic_ns\":42",
        "\"length\":7",
        "\"payload_hex\":\"0020225c7e7fff\"",
        "\"rssi_dbm\":-70.25",
        "\"snr_db\":7.50",
        "\"crc\":\"ok\"",
        "\"radiolib_state\":0",
    };

    for (const std::string& token : required) {
        if (json.find(token) == std::string::npos) {
            std::cerr
                << "serialized record lacks token: "
                << token
                << '\n';

            return 1;
        }
    }

    return 0;
}
