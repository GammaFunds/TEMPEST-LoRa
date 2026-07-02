#include "tempest_lora/receiver_contract.hpp"

#include <iostream>

int main() {
    using namespace tempest_lora::contract;

    static_assert(kFrequencyMhz == 915.0F);
    static_assert(kBandwidthKhz == 500.0F);
    static_assert(kSpreadingFactor == 7);
    static_assert(kCodingRateDenominator == 5);
    static_assert(kSyncWord == 0x12);
    static_assert(kPreambleSymbols == 4);
    static_assert(kCrcBytes == 2);
    static_assert(!kIqInverted);
    static_assert(kDio2RfSwitch);
    static_assert(kTcxoVoltage == 1.8F);
    static_assert(!kUseRegulatorLdo);

    static_assert(kSpiDeviceIndex == 1);
    static_assert(kSpiChannelIndex == 0);
    static_assert(kSpiSpeedHz == 2'000'000);

    static_assert(kGpioChipIndex == 0);
    static_assert(kDio1Gpio == 26);
    static_assert(kResetGpio == 25);
    static_assert(kBusyGpio == 24);
    static_assert(kMaximumPacketLength == 255);

    if (kSchema != "tempest-lora.rx.v1") {
        std::cerr << "unexpected schema\n";
        return 1;
    }

    if (
        kContractText.find("tcxo_voltage=1.8") ==
        std::string_view::npos
    ) {
        std::cerr << "contract text lacks TCXO evidence\n";
        return 1;
    }

    return 0;
}
