#pragma once

#include <cstddef>
#include <cstdint>
#include <string_view>

namespace tempest_lora::contract {

inline constexpr std::string_view kSchema = "tempest-lora.rx.v1";

inline constexpr float kFrequencyMhz = 915.0F;
inline constexpr float kBandwidthKhz = 500.0F;
inline constexpr std::uint8_t kSpreadingFactor = 7;
inline constexpr std::uint8_t kCodingRateDenominator = 5;
inline constexpr std::uint8_t kSyncWord = 0x12;
inline constexpr std::int8_t kOutputPowerDbm = 10;
inline constexpr std::uint16_t kPreambleSymbols = 4;

inline constexpr std::uint8_t kCrcBytes = 2;
inline constexpr bool kIqInverted = false;
inline constexpr bool kDio2RfSwitch = true;
inline constexpr float kTcxoVoltage = 1.8F;
inline constexpr bool kUseRegulatorLdo = false;

inline constexpr std::uint8_t kSpiDeviceIndex = 1;
inline constexpr std::uint8_t kSpiChannelIndex = 0;
inline constexpr std::uint32_t kSpiSpeedHz = 2'000'000;

inline constexpr std::uint8_t kGpioChipIndex = 0;
inline constexpr std::uint32_t kDio1Gpio = 26;
inline constexpr std::uint32_t kResetGpio = 25;
inline constexpr std::uint32_t kBusyGpio = 24;

inline constexpr std::size_t kMaximumPacketLength = 255;

inline constexpr int kExitSuccess = 0;
inline constexpr int kExitInvalidCommandLine = 2;
inline constexpr int kExitHalOpenFailure = 10;
inline constexpr int kExitRadioConfigurationFailure = 11;
inline constexpr int kExitInitialReceiveFailure = 12;
inline constexpr int kExitPacketReadFailure = 13;
inline constexpr int kExitRestartReceiveFailure = 14;
inline constexpr int kExitOutputFailure = 15;
inline constexpr int kExitCleanupFailure = 16;
inline constexpr int kExitContractViolation = 17;

inline constexpr std::string_view kContractText = R"CONTRACT(
schema=tempest-lora.rx.v1
radio=SX1262
frequency_mhz=915.0
bandwidth_khz=500.0
spreading_factor=7
coding_rate=4/5
sync_word_api=0x12
preamble_symbols=4
header_mode=explicit
crc_bytes=2
iq_inverted=false
dio2_rf_switch=true
tcxo_voltage=1.8
use_regulator_ldo=false
spi_device=/dev/spidev1.0
spi_device_index=1
spi_channel_index=0
spi_speed_hz=2000000
gpiochip_index=0
dio1_gpio=26
reset_gpio=25
busy_gpio=24
maximum_packet_length=255
)CONTRACT";

}  // namespace tempest_lora::contract
