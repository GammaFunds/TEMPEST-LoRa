#include "tempest_lora/lab_pi_hal.hpp"

#include <algorithm>
#include <cerrno>
#include <sched.h>
#include <utility>

namespace tempest_lora {

LabPiHal::LabPiHal(
    const std::uint8_t spi_channel,
    const std::uint32_t spi_speed,
    const std::uint8_t spi_device,
    const std::uint8_t gpio_device
)
    : RadioLibHal(
          0,
          1,
          LG_LOW,
          LG_HIGH,
          LG_RISING_EDGE,
          LG_FALLING_EDGE
      ),
      gpio_device_(gpio_device),
      spi_device_(spi_device),
      spi_speed_(spi_speed),
      spi_channel_(spi_channel) {
    for (std::size_t index = 0; index < interrupt_enabled_.size(); ++index) {
        interrupt_enabled_[index].store(false);
        interrupt_modes_[index].store(0);
        interrupt_callbacks_[index].store(nullptr);
    }
}

LabPiHal::~LabPiHal() {
    static_cast<void>(close());
}

bool LabPiHal::valid_pin(const std::uint32_t pin) const noexcept {
    return pin <= kMaximumGpio;
}

void LabPiHal::record_error(
    const std::string_view operation,
    const int error_code
) noexcept {
    if (error_code >= 0) {
        return;
    }

    int expected = 0;

    if (last_error_.compare_exchange_strong(expected, error_code)) {
        try {
            std::lock_guard<std::mutex> lock(error_mutex_);
            last_operation_.assign(operation.begin(), operation.end());
        } catch (...) {
            // The numeric error remains sticky even if allocating the
            // diagnostic operation name fails.
        }
    }
}

bool LabPiHal::open() noexcept {
    if (last_error() != 0) {
        return false;
    }

    if (gpio_handle_ < 0) {
        gpio_handle_ = lgGpiochipOpen(gpio_device_);

        if (gpio_handle_ < 0) {
            record_error("lgGpiochipOpen", gpio_handle_);
            gpio_handle_ = -1;
            return false;
        }
    }

    if (spi_handle_ < 0) {
        spi_handle_ = lgSpiOpen(
            spi_device_,
            spi_channel_,
            spi_speed_,
            0
        );

        if (spi_handle_ < 0) {
            const int spi_error = spi_handle_;
            spi_handle_ = -1;
            record_error("lgSpiOpen", spi_error);

            const int close_result = lgGpiochipClose(gpio_handle_);
            gpio_handle_ = -1;

            if (close_result < 0) {
                record_error(
                    "lgGpiochipClose-after-lgSpiOpen-failure",
                    close_result
                );
            }

            return false;
        }
    }

    return ready();
}

bool LabPiHal::release_line(const std::uint32_t pin) noexcept {
    if (!valid_pin(pin) || gpio_handle_ < 0) {
        return true;
    }

    bool success = true;

    interrupt_enabled_[pin].store(false);
    interrupt_modes_[pin].store(0);
    interrupt_callbacks_[pin].store(nullptr);

    if (alert_lines_[pin]) {
        const int callback_result = lgGpioSetAlertsFunc(
            gpio_handle_,
            static_cast<int>(pin),
            nullptr,
            nullptr
        );

        if (callback_result < 0) {
            record_error("lgGpioSetAlertsFunc-clear", callback_result);
            success = false;
        }
    }

    if (claimed_lines_[pin] || alert_lines_[pin]) {
        const int free_result = lgGpioFree(
            gpio_handle_,
            static_cast<int>(pin)
        );

        if (free_result < 0) {
            record_error("lgGpioFree", free_result);
            success = false;
        }
    }

    claimed_lines_[pin] = false;
    alert_lines_[pin] = false;

    return success;
}

bool LabPiHal::close() noexcept {
    bool success = true;

    if (gpio_handle_ >= 0) {
        for (std::uint32_t pin = 0; pin <= kMaximumGpio; ++pin) {
            if (!release_line(pin)) {
                success = false;
            }
        }
    }

    if (spi_handle_ >= 0) {
        const int spi_close_result = lgSpiClose(spi_handle_);
        spi_handle_ = -1;

        if (spi_close_result < 0) {
            record_error("lgSpiClose", spi_close_result);
            success = false;
        }
    }

    if (gpio_handle_ >= 0) {
        const int gpio_close_result = lgGpiochipClose(gpio_handle_);
        gpio_handle_ = -1;

        if (gpio_close_result < 0) {
            record_error("lgGpiochipClose", gpio_close_result);
            success = false;
        }
    }

    return success && last_error() == 0;
}

bool LabPiHal::ready() const noexcept {
    return (
        last_error() == 0 &&
        gpio_handle_ >= 0 &&
        spi_handle_ >= 0
    );
}

bool LabPiHal::is_open() const noexcept {
    return gpio_handle_ >= 0 || spi_handle_ >= 0;
}

int LabPiHal::last_error() const noexcept {
    return last_error_.load();
}

std::string LabPiHal::last_operation() const {
    std::lock_guard<std::mutex> lock(error_mutex_);
    return last_operation_;
}

void LabPiHal::init() {
    static_cast<void>(open());
}

void LabPiHal::term() {
    static_cast<void>(close());
}

void LabPiHal::pinMode(
    const std::uint32_t pin,
    const std::uint32_t mode
) {
    if (pin == RADIOLIB_NC || last_error() != 0) {
        return;
    }

    if (!valid_pin(pin)) {
        record_error("pinMode-invalid-pin", -ERANGE);
        return;
    }

    if (gpio_handle_ < 0) {
        record_error("pinMode-without-gpiochip", -ENODEV);
        return;
    }

    if (!release_line(pin) || last_error() != 0) {
        return;
    }

    int result = 0;

    if (mode == GpioModeInput) {
        result = lgGpioClaimInput(
            gpio_handle_,
            pin_flags_[pin],
            static_cast<int>(pin)
        );
    } else if (mode == GpioModeOutput) {
        result = lgGpioClaimOutput(
            gpio_handle_,
            pin_flags_[pin],
            static_cast<int>(pin),
            LG_HIGH
        );
    } else {
        record_error("pinMode-invalid-mode", -EINVAL);
        return;
    }

    if (result < 0) {
        record_error("lgGpioClaim", result);
        return;
    }

    claimed_lines_[pin] = true;
}

void LabPiHal::digitalWrite(
    const std::uint32_t pin,
    const std::uint32_t value
) {
    if (pin == RADIOLIB_NC || last_error() != 0) {
        return;
    }

    if (!valid_pin(pin) || gpio_handle_ < 0) {
        record_error("digitalWrite-invalid-state", -ENODEV);
        return;
    }

    const int result = lgGpioWrite(
        gpio_handle_,
        static_cast<int>(pin),
        static_cast<int>(value)
    );

    if (result < 0) {
        record_error("lgGpioWrite", result);
    }
}

std::uint32_t LabPiHal::digitalRead(const std::uint32_t pin) {
    if (pin == RADIOLIB_NC || last_error() != 0) {
        return GpioLevelLow;
    }

    if (!valid_pin(pin) || gpio_handle_ < 0) {
        record_error("digitalRead-invalid-state", -ENODEV);
        return GpioLevelLow;
    }

    const int result = lgGpioRead(
        gpio_handle_,
        static_cast<int>(pin)
    );

    if (result < 0) {
        record_error("lgGpioRead", result);
        return GpioLevelLow;
    }

    return static_cast<std::uint32_t>(result);
}

void LabPiHal::attachInterrupt(
    const std::uint32_t interrupt_num,
    const Isr interrupt_callback,
    const std::uint32_t mode
) {
    if (interrupt_num == RADIOLIB_NC || last_error() != 0) {
        return;
    }

    if (
        !valid_pin(interrupt_num) ||
        interrupt_callback == nullptr ||
        gpio_handle_ < 0
    ) {
        record_error("attachInterrupt-invalid-state", -EINVAL);
        return;
    }

    if (!release_line(interrupt_num) || last_error() != 0) {
        return;
    }

    const int claim_result = lgGpioClaimAlert(
        gpio_handle_,
        0,
        static_cast<int>(mode),
        static_cast<int>(interrupt_num),
        -1
    );

    if (claim_result < 0) {
        record_error("lgGpioClaimAlert", claim_result);
        return;
    }

    claimed_lines_[interrupt_num] = true;
    alert_lines_[interrupt_num] = true;

    interrupt_modes_[interrupt_num].store(
        mode == GpioInterruptFalling ? LG_LOW : LG_HIGH
    );

    interrupt_callbacks_[interrupt_num].store(interrupt_callback);
    interrupt_enabled_[interrupt_num].store(true);

    const int callback_result = lgGpioSetAlertsFunc(
        gpio_handle_,
        static_cast<int>(interrupt_num),
        &LabPiHal::alert_handler,
        this
    );

    if (callback_result < 0) {
        record_error("lgGpioSetAlertsFunc", callback_result);
        static_cast<void>(release_line(interrupt_num));
    }
}

void LabPiHal::detachInterrupt(const std::uint32_t interrupt_num) {
    if (interrupt_num == RADIOLIB_NC || !valid_pin(interrupt_num)) {
        return;
    }

    static_cast<void>(release_line(interrupt_num));
}

void LabPiHal::delay(const RadioLibTime_t milliseconds) {
    if (milliseconds == 0) {
        sched_yield();
        return;
    }

    lguSleep(static_cast<double>(milliseconds) / 1000.0);
}

void LabPiHal::delayMicroseconds(const RadioLibTime_t microseconds) {
    if (microseconds == 0) {
        sched_yield();
        return;
    }

    lguSleep(static_cast<double>(microseconds) / 1'000'000.0);
}

RadioLibTime_t LabPiHal::millis() {
    return static_cast<RadioLibTime_t>(
        lguTimestamp() / 1'000'000ULL
    );
}

RadioLibTime_t LabPiHal::micros() {
    return static_cast<RadioLibTime_t>(
        lguTimestamp() / 1'000ULL
    );
}

long LabPiHal::pulseIn(
    const std::uint32_t pin,
    const std::uint32_t state,
    const RadioLibTime_t timeout
) {
    if (pin == RADIOLIB_NC || last_error() != 0) {
        return 0;
    }

    pinMode(pin, GpioModeInput);

    if (last_error() != 0) {
        return 0;
    }

    const RadioLibTime_t start = micros();
    RadioLibTime_t current = start;

    while (digitalRead(pin) == state) {
        if (last_error() != 0) {
            return 0;
        }

        current = micros();

        if ((current - start) > timeout) {
            return 0;
        }

        sched_yield();
    }

    return static_cast<long>(micros() - start);
}

void LabPiHal::spiBegin() {
    if (spi_handle_ >= 0 || last_error() != 0) {
        return;
    }

    static_cast<void>(open());
}

void LabPiHal::spiBeginTransaction() {
}

void LabPiHal::spiTransfer(
    std::uint8_t* output,
    const std::size_t length,
    std::uint8_t* input
) {
    if (input != nullptr) {
        std::fill(input, input + length, 0);
    }

    if (
        last_error() != 0 ||
        spi_handle_ < 0 ||
        output == nullptr ||
        input == nullptr
    ) {
        if (last_error() == 0) {
            record_error("spiTransfer-invalid-state", -EINVAL);
        }

        return;
    }

    const int result = lgSpiXfer(
        spi_handle_,
        reinterpret_cast<char*>(output),
        reinterpret_cast<char*>(input),
        length
    );

    if (result < 0) {
        record_error("lgSpiXfer", result);
        return;
    }

    if (static_cast<std::size_t>(result) != length) {
        record_error("lgSpiXfer-short-transfer", -EIO);
    }
}

void LabPiHal::spiEndTransaction() {
}

void LabPiHal::spiEnd() {
    if (spi_handle_ < 0) {
        return;
    }

    const int result = lgSpiClose(spi_handle_);
    spi_handle_ = -1;

    if (result < 0) {
        record_error("lgSpiClose", result);
    }
}

void LabPiHal::tone(
    const std::uint32_t pin,
    const unsigned int frequency,
    const RadioLibTime_t duration
) {
    if (
        pin == RADIOLIB_NC ||
        !valid_pin(pin) ||
        gpio_handle_ < 0 ||
        last_error() != 0
    ) {
        return;
    }

    const int result = lgTxPwm(
        gpio_handle_,
        static_cast<int>(pin),
        static_cast<float>(frequency),
        50.0F,
        0,
        static_cast<int>(duration)
    );

    if (result < 0) {
        record_error("lgTxPwm-tone", result);
    }
}

void LabPiHal::noTone(const std::uint32_t pin) {
    if (
        pin == RADIOLIB_NC ||
        !valid_pin(pin) ||
        gpio_handle_ < 0
    ) {
        return;
    }

    const int result = lgTxPwm(
        gpio_handle_,
        static_cast<int>(pin),
        0.0F,
        0.0F,
        0,
        0
    );

    if (result < 0) {
        record_error("lgTxPwm-stop", result);
    }
}

void LabPiHal::pullUpDown(
    const std::uint32_t pin,
    const bool enable,
    const bool pull_up
) {
    if (pin == RADIOLIB_NC || !valid_pin(pin)) {
        return;
    }

    pin_flags_[pin] = enable
        ? (pull_up ? LG_SET_PULL_UP : LG_SET_PULL_DOWN)
        : LG_SET_PULL_NONE;
}

void LabPiHal::yield() {
    sched_yield();
}

void LabPiHal::alert_handler(
    const int alert_count,
    lgGpioAlert_p alerts,
    void* user_data
) {
    if (
        alert_count <= 0 ||
        alerts == nullptr ||
        user_data == nullptr
    ) {
        return;
    }

    auto* hal = static_cast<LabPiHal*>(user_data);

    for (int index = 0; index < alert_count; ++index) {
        const int gpio = alerts[index].report.gpio;

        if (
            gpio < 0 ||
            gpio > static_cast<int>(kMaximumGpio)
        ) {
            continue;
        }

        const auto pin = static_cast<std::size_t>(gpio);

        if (!hal->interrupt_enabled_[pin].load()) {
            continue;
        }

        if (
            hal->interrupt_modes_[pin].load() !=
            alerts[index].report.level
        ) {
            continue;
        }

        const Isr callback =
            hal->interrupt_callbacks_[pin].load();

        if (callback != nullptr) {
            callback();
        }
    }
}

}  // namespace tempest_lora
