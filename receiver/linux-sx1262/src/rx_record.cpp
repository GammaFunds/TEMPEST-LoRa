#include "tempest_lora/rx_record.hpp"

#include "tempest_lora/receiver_contract.hpp"

#include <cmath>
#include <iomanip>
#include <locale>
#include <sstream>

namespace tempest_lora {

std::string bytes_to_hex(const std::vector<std::uint8_t>& bytes) {
    static constexpr char digits[] = "0123456789abcdef";

    std::string result;
    result.reserve(bytes.size() * 2);

    for (const std::uint8_t byte : bytes) {
        result.push_back(digits[(byte >> 4U) & 0x0FU]);
        result.push_back(digits[byte & 0x0FU]);
    }

    return result;
}

std::string bytes_to_ascii(const std::vector<std::uint8_t>& bytes) {
    std::string result;
    result.reserve(bytes.size());

    for (const std::uint8_t byte : bytes) {
        if (byte >= 0x20U && byte <= 0x7EU) {
            result.push_back(static_cast<char>(byte));
        } else {
            result.push_back('.');
        }
    }

    return result;
}

std::string json_escape(const std::string& value) {
    static constexpr char digits[] = "0123456789abcdef";

    std::string result;

    for (const unsigned char character : value) {
        switch (character) {
            case '"':
                result += "\\\"";
                break;
            case '\\':
                result += "\\\\";
                break;
            case '\b':
                result += "\\b";
                break;
            case '\f':
                result += "\\f";
                break;
            case '\n':
                result += "\\n";
                break;
            case '\r':
                result += "\\r";
                break;
            case '\t':
                result += "\\t";
                break;
            default:
                if (character < 0x20U) {
                    result += "\\u00";
                    result.push_back(digits[(character >> 4U) & 0x0FU]);
                    result.push_back(digits[character & 0x0FU]);
                } else {
                    result.push_back(static_cast<char>(character));
                }
                break;
        }
    }

    return result;
}

namespace {

void append_float_or_null(
    std::ostringstream& output,
    const float value
) {
    if (std::isfinite(value)) {
        output << std::fixed << std::setprecision(2) << value;
    } else {
        output << "null";
    }
}

}  // namespace

std::string serialize_rx_event(const RxEvent& event) {
    std::ostringstream output;
    output.imbue(std::locale::classic());

    output
        << "{\"schema\":\""
        << json_escape(std::string(contract::kSchema))
        << "\",\"type\":\""
        << json_escape(event.type)
        << "\",\"sequence\":"
        << event.sequence
        << ",\"time_utc\":\""
        << json_escape(event.time_utc)
        << "\",\"monotonic_ns\":"
        << event.monotonic_ns
        << ",\"length\":"
        << event.payload.size()
        << ",\"payload_hex\":\""
        << bytes_to_hex(event.payload)
        << "\",\"payload_ascii\":\""
        << json_escape(bytes_to_ascii(event.payload))
        << "\",\"rssi_dbm\":";

    append_float_or_null(output, event.rssi_dbm);

    output << ",\"snr_db\":";
    append_float_or_null(output, event.snr_db);

    output
        << ",\"crc\":\""
        << json_escape(event.crc)
        << "\",\"radiolib_state\":"
        << event.radiolib_state
        << '}';

    return output.str();
}

}  // namespace tempest_lora
