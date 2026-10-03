// spc_bus.h - ESP32版基板(SHVC-SOUND-ESP32 r0.4)のバス制御と、SPC700への転送・DSP書き込み
//
// ■ バスのつながり(回路図 SHVC-SOUND-ESP32-KiCad)
//   データ D0-D7 : GPIO13,14,16,17,18,19,21,22
//     書き込み  ESP32 → 74HCT541N(U2, OE_W=GPIO4 がLで出力) → SHVC-SOUND
//     読み出し  SHVC-SOUND → 74LVC245N(U4, OE_R=GPIO5 がLで出力) → ESP32
//   A0=GPIO26  A1=GPIO27  /WR=GPIO23  /RD=GPIO25  /RESET=GPIO32  (74HCT541N U3 経由で5Vに)
//   MUTE=GPIO15(U3経由で20番ピン。Hで音が出る。10kで引き下げ済み)
//
// ■ 絶対に守ること
//   OE_W と OE_R を同時に L にしない(2つのバッファの出力がデータ線上でぶつかる)。
//   切り替えは必ず「今出しているほうを H → ESP32側のピンの向きを変える → もう一方を L」の順。
#pragma once
#include <Arduino.h>
#include "soc/gpio_reg.h"
#include "soc/soc.h"
#include "esp_rom_sys.h"
#include "driver/gpio.h"

namespace spc {

const uint8_t DATA_PINS[8] = {13, 14, 16, 17, 18, 19, 21, 22};
const uint8_t PIN_A0 = 26;
const uint8_t PIN_A1 = 27;
const uint8_t PIN_WR = 23;
const uint8_t PIN_RD = 25;
const uint8_t PIN_RESET = 32;
const uint8_t PIN_OE_W = 4;
const uint8_t PIN_OE_R = 5;
const uint8_t PIN_MUTE = 15;

// 待ち時間(µs)。Uno版(書き3µs/読み15µs)を基準に、バッファ1段ぶんの余裕を足した値
const uint32_t WRITE_SETUP_US = 15;
const uint32_t WRITE_PULSE_US = 15;
const uint32_t WRITE_HOLD_US = 15;
const uint32_t READ_US = 30;
const uint32_t OE_SETTLE_US = 15;
const uint32_t DRIVER_TIMEOUT_MS = 100;
static uint16_t diagnosticWriteUs = WRITE_PULSE_US;

// GPIO0-31 はレジスタ1本で一括操作できる(digitalWrite より桁違いに速い)
static uint32_t dataMask = 0;
static uint32_t outMask[256];
static const uint32_t ADDR_MASK = (1UL << PIN_A0) | (1UL << PIN_A1);

inline void pinHigh(uint8_t p) { REG_WRITE(GPIO_OUT_W1TS_REG, 1UL << p); }
inline void pinLow(uint8_t p) { REG_WRITE(GPIO_OUT_W1TC_REG, 1UL << p); }

enum class BusMode : uint8_t { Idle, Write, Read };
static BusMode mode = BusMode::Idle;

// ドライランモード: SHVC-SOUND が見つからないときは、バスを触らずシリアルに書き込み内容を出す
static bool dryRun = false;
static uint8_t driverSeq = 0;
// Diagnostic-only snapshots: output latch, input pad, output enable.
static bool traceWrites = false;
static uint32_t writeTrace[4][4][3];
static uint8_t traceCount = 0;
inline void captureWrite(uint8_t stage) {
    if (!traceWrites || traceCount >= 4) return;
    writeTrace[traceCount][stage][0] = REG_READ(GPIO_OUT_REG);
    writeTrace[traceCount][stage][1] = REG_READ(GPIO_IN_REG);
    writeTrace[traceCount][stage][2] = REG_READ(GPIO_ENABLE_REG);
}

inline void begin() {
    // 起動直後は両方のバッファを切り離し、/RESET をかけておく
    pinMode(PIN_OE_W, OUTPUT);
    pinMode(PIN_OE_R, OUTPUT);
    digitalWrite(PIN_OE_W, HIGH);
    digitalWrite(PIN_OE_R, HIGH);
    pinMode(PIN_MUTE, OUTPUT);
    digitalWrite(PIN_MUTE, LOW);
    pinMode(PIN_RESET, OUTPUT);
    digitalWrite(PIN_RESET, LOW);
    for (uint8_t p : {PIN_A0, PIN_A1, PIN_WR, PIN_RD}) {
        pinMode(p, OUTPUT);
        digitalWrite(p, HIGH);
    }
    dataMask = 0;
    for (uint8_t i = 0; i < 8; i++) {
        pinMode(DATA_PINS[i], INPUT);   // 入力を有効にしたうえで、出力は下のレジスタで出し入れする
        dataMask |= 1UL << DATA_PINS[i];
    }
    for (int v = 0; v < 256; v++) {
        uint32_t m = 0;
        for (uint8_t i = 0; i < 8; i++)
            if (v & (1 << i)) m |= 1UL << DATA_PINS[i];
        outMask[v] = m;
    }
    mode = BusMode::Idle;
}

inline void setMute(bool muted) { digitalWrite(PIN_MUTE, muted ? LOW : HIGH); }

inline void enterWrite() {
    digitalWrite(PIN_WR, HIGH);
    digitalWrite(PIN_RD, HIGH);
    digitalWrite(PIN_OE_W, HIGH);
    digitalWrite(PIN_OE_R, HIGH);
    esp_rom_delay_us(OE_SETTLE_US);
    for (uint8_t p : DATA_PINS) pinMode(p, OUTPUT);
    if (traceWrites) for (uint8_t p : DATA_PINS) gpio_input_enable((gpio_num_t)p);
    // Keep U2 disabled until address and data are valid in writePort().
    mode = BusMode::Write;
}

inline void enterRead() {
    digitalWrite(PIN_WR, HIGH);
    digitalWrite(PIN_RD, HIGH);
    digitalWrite(PIN_OE_W, HIGH);
    digitalWrite(PIN_OE_R, HIGH);
    esp_rom_delay_us(OE_SETTLE_US);
    for (uint8_t p : DATA_PINS) pinMode(p, INPUT);
    esp_rom_delay_us(OE_SETTLE_US);
    mode = BusMode::Read;
}

inline void selectPort(uint8_t port) {
    digitalWrite(PIN_A0, (port & 1) ? HIGH : LOW);
    digitalWrite(PIN_A1, (port & 2) ? HIGH : LOW);
}

inline void writePort(uint8_t port, uint8_t val) {
    enterWrite();
    selectPort(port);
    for (uint8_t i = 0; i < 8; i++)
        digitalWrite(DATA_PINS[i], (val & (1 << i)) ? HIGH : LOW);
    esp_rom_delay_us(diagnosticWriteUs);
    digitalWrite(PIN_OE_W, LOW);
    esp_rom_delay_us(diagnosticWriteUs);
    captureWrite(0);
    digitalWrite(PIN_WR, LOW);
    esp_rom_delay_us(diagnosticWriteUs);
    captureWrite(1);
    digitalWrite(PIN_WR, HIGH);
    esp_rom_delay_us(diagnosticWriteUs);
    captureWrite(2);
    digitalWrite(PIN_OE_W, HIGH);
    if (traceWrites) esp_rom_delay_us(OE_SETTLE_US);
    captureWrite(3);
    if (traceWrites && traceCount < 4) traceCount++;
}

inline uint8_t readPort(uint8_t port) {
    enterRead();
    selectPort(port);
    esp_rom_delay_us(READ_US);
    digitalWrite(PIN_OE_R, LOW);
    esp_rom_delay_us(OE_SETTLE_US);
    digitalWrite(PIN_RD, LOW);
    esp_rom_delay_us(READ_US);
    uint8_t v = 0;
    for (uint8_t i = 0; i < 8; i++)
        if (digitalRead(DATA_PINS[i])) v |= 1 << i;
    digitalWrite(PIN_RD, HIGH);
    esp_rom_delay_us(READ_US);
    digitalWrite(PIN_OE_R, HIGH);
    return v;
}

inline bool waitForPort(uint8_t port, uint8_t expected, uint32_t timeoutMs) {
    uint32_t start = millis();
    do {
        if (readPort(port) == expected) return true;
    } while (millis() - start < timeoutMs);
    return false;
}

// ---- SPC700 のリセットと IPL ROM 経由の転送(spc_realtime.ino と同じ手順) ----

// リセットして IPL の準備完了($F4=$AA, $F5=$BB)を待つ。見つからなければ false
inline bool reset() {
    for (int attempt = 0; attempt < 3; attempt++) {
        digitalWrite(PIN_RESET, LOW);
        delay(100);
        digitalWrite(PIN_RESET, HIGH);
        uint32_t start = millis();
        while (millis() - start < 2500) {
            if (readPort(0) == 0xAA && readPort(1) == 0xBB) {
                driverSeq = 0;
                return true;
            }
            delay(1);
        }
    }
    return false;
}

// addr から data を書き込む。first=true はリセット後最初のブロック
inline bool uploadBlock(uint16_t addr, const uint8_t *data, size_t len, bool first) {
    writePort(2, addr & 0xFF);
    writePort(3, addr >> 8);
    writePort(1, 0x01);
    uint8_t kick;
    if (first) {
        kick = 0xCC;
    } else {
        kick = (uint8_t)(readPort(0) + 2);
        if (kick == 0) kick = 1;
    }
    writePort(0, kick);
    if (!waitForPort(0, kick, 1000)) return false;
    uint8_t idx = 0;
    for (size_t i = 0; i < len; i++) {
        writePort(1, data[i]);
        writePort(0, idx);
        if (!waitForPort(0, idx, 200)) return false;
        idx++;
    }
    return true;
}

// addr へジャンプして、常駐ドライバを走らせる
inline void jumpTo(uint16_t addr) {
    writePort(2, addr & 0xFF);
    writePort(3, addr >> 8);
    writePort(1, 0x00);
    uint8_t kick = (uint8_t)(readPort(0) + 2);
    writePort(0, kick);
    // ドライバは起動直後、$F4 に残っている kick を「新しい指示」と見なして1回処理し、kick を返す。
    // 次のシーケンス値を kick の次から始めれば、この空振りと値がかぶらない。
    delay(20);
    driverSeq = kick;
}

// 常駐ドライバ経由で DSP レジスタを1個書く
inline bool dspWrite(uint8_t reg, uint8_t val) {
    if (dryRun) {
        Serial.printf("  DSP $%02X = $%02X\n", reg, val);
        return true;
    }
    writePort(1, reg);
    writePort(2, val);
    driverSeq++;
    writePort(0, driverSeq);
    return waitForPort(0, driverSeq, DRIVER_TIMEOUT_MS);
}

}  // namespace spc
