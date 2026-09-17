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
const uint32_t WRITE_SETUP_US = 4;
const uint32_t WRITE_PULSE_US = 4;
const uint32_t WRITE_HOLD_US = 2;
const uint32_t READ_US = 15;
const uint32_t OE_SETTLE_US = 5;
const uint32_t DRIVER_TIMEOUT_MS = 100;

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
    if (mode == BusMode::Write) return;
    pinHigh(PIN_OE_R);                          // 読み出しバッファを切り離す
    esp_rom_delay_us(OE_SETTLE_US);
    REG_WRITE(GPIO_ENABLE_W1TS_REG, dataMask);  // ESP32側を出力に
    pinLow(PIN_OE_W);                           // 書き込みバッファを有効に
    esp_rom_delay_us(OE_SETTLE_US);
    mode = BusMode::Write;
}

inline void enterRead() {
    if (mode == BusMode::Read) return;
    pinHigh(PIN_OE_W);                          // 書き込みバッファを切り離す
    REG_WRITE(GPIO_ENABLE_W1TC_REG, dataMask);  // ESP32側を入力に
    esp_rom_delay_us(OE_SETTLE_US);
    pinLow(PIN_OE_R);                           // 読み出しバッファを有効に
    esp_rom_delay_us(OE_SETTLE_US);
    mode = BusMode::Read;
}

inline void selectPort(uint8_t port) {
    uint32_t set = ((port & 1) ? (1UL << PIN_A0) : 0) | ((port & 2) ? (1UL << PIN_A1) : 0);
    REG_WRITE(GPIO_OUT_W1TC_REG, ADDR_MASK & ~set);
    REG_WRITE(GPIO_OUT_W1TS_REG, set);
}

inline void writePort(uint8_t port, uint8_t val) {
    enterWrite();
    selectPort(port);
    REG_WRITE(GPIO_OUT_W1TC_REG, dataMask & ~outMask[val]);
    REG_WRITE(GPIO_OUT_W1TS_REG, outMask[val]);
    esp_rom_delay_us(WRITE_SETUP_US);
    pinLow(PIN_WR);
    esp_rom_delay_us(WRITE_PULSE_US);
    pinHigh(PIN_WR);
    esp_rom_delay_us(WRITE_HOLD_US);
}

inline uint8_t readPort(uint8_t port) {
    enterRead();
    selectPort(port);
    pinLow(PIN_RD);
    esp_rom_delay_us(READ_US);
    uint32_t in = REG_READ(GPIO_IN_REG);
    pinHigh(PIN_RD);
    uint8_t v = 0;
    for (uint8_t i = 0; i < 8; i++)
        if (in & (1UL << DATA_PINS[i])) v |= 1 << i;
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
