#pragma once

#include <RadioLib.h>
#include <lgpio.h>

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>
#include <string_view>

namespace tempest_lora {

class LabPiHal final : public RadioLibHal {
  public:
    using Isr = void (*)(void);

    static constexpr std::uint32_t kMaximumGpio = 31;

    LabPiHal(
        std::uint8_t spi_channel,
        std::uint32_t spi_speed,
        std::uint8_t spi_device,
        std::uint8_t gpio_device
    );

    ~LabPiHal() override;

    LabPiHal(const LabPiHal&) = delete;
    LabPiHal& operator=(const LabPiHal&) = delete;
    LabPiHal(LabPiHal&&) = delete;
    LabPiHal& operator=(LabPiHal&&) = delete;

    bool open() noexcept;
    bool close() noexcept;

    [[nodiscard]] bool ready() const noexcept;
    [[nodiscard]] bool is_open() const noexcept;
    [[nodiscard]] int last_error() const noexcept;
    [[nodiscard]] std::string last_operation() const;

    void init() override;
    void term() override;

    void pinMode(std::uint32_t pin, std::uint32_t mode) override;
    void digitalWrite(std::uint32_t pin, std::uint32_t value) override;
    std::uint32_t digitalRead(std::uint32_t pin) override;

    void attachInterrupt(
        std::uint32_t interrupt_num,
        Isr interrupt_callback,
        std::uint32_t mode
    ) override;

    void detachInterrupt(std::uint32_t interrupt_num) override;

    void delay(RadioLibTime_t milliseconds) override;
    void delayMicroseconds(RadioLibTime_t microseconds) override;
    RadioLibTime_t millis() override;
    RadioLibTime_t micros() override;

    long pulseIn(
        std::uint32_t pin,
        std::uint32_t state,
        RadioLibTime_t timeout
    ) override;

    void spiBegin() override;
    void spiBeginTransaction() override;
    void spiTransfer(
        std::uint8_t* output,
        std::size_t length,
        std::uint8_t* input
    ) override;
    void spiEndTransaction() override;
    void spiEnd() override;

    void tone(
        std::uint32_t pin,
        unsigned int frequency,
        RadioLibTime_t duration = 0
    ) override;

    void noTone(std::uint32_t pin) override;

    void pullUpDown(
        std::uint32_t pin,
        bool enable,
        bool pull_up
    ) override;

    void yield() override;

  private:
    static void alert_handler(
        int alert_count,
        lgGpioAlert_p alerts,
        void* user_data
    );

    void record_error(
        std::string_view operation,
        int error_code
    ) noexcept;

    [[nodiscard]] bool valid_pin(std::uint32_t pin) const noexcept;
    bool release_line(std::uint32_t pin) noexcept;

    const std::uint8_t gpio_device_;
    const std::uint8_t spi_device_;
    const std::uint32_t spi_speed_;
    const std::uint8_t spi_channel_;

    int gpio_handle_ = -1;
    int spi_handle_ = -1;

    std::array<int, kMaximumGpio + 1> pin_flags_{};
    std::array<bool, kMaximumGpio + 1> claimed_lines_{};
    std::array<bool, kMaximumGpio + 1> alert_lines_{};

    std::array<std::atomic<bool>, kMaximumGpio + 1>
        interrupt_enabled_{};

    std::array<std::atomic<std::uint32_t>, kMaximumGpio + 1>
        interrupt_modes_{};

    std::array<std::atomic<Isr>, kMaximumGpio + 1>
        interrupt_callbacks_{};

    std::atomic<int> last_error_{0};
    mutable std::mutex error_mutex_;
    std::string last_operation_;
};

}  // namespace tempest_lora
