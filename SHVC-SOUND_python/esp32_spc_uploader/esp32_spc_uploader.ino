// SHVC-SOUND-ESP32 r0.4 / ESP32 DevKit V1: PC spc_play.py compatible uploader.
// Binary serial at 500000 baud. Do not print debug text on this connection.
#include <Arduino.h>
#include "spc_bus.h"
using spc::readPort;
using spc::writePort;
using spc::waitForPort;
const uint8_t PIN_RESET = spc::PIN_RESET;
const uint8_t PIN_VOLUME = 33;
const uint8_t CMD_WRITEPORT = 0x0B;
const uint8_t CMD_BUS_DIAG = 0x0C;
const uint8_t CMD_WRITE_TRACE = 0x0D;
const uint8_t CMD_WRITE_TIMING = 0x0E;
const uint8_t CMD_PAD_SWEEP = 0x0F;
const uint8_t CMD_HOLD_WR = 0x10;
const uint8_t CMD_HOLD_DATA = 0x11;
// シリアルコマンド (PC -> Arduino)
const uint8_t CMD_RESET = 0x01;
const uint8_t CMD_SETADDR = 0x02;
const uint8_t CMD_SENDBYTES = 0x03;
const uint8_t CMD_READPORT = 0x04;
const uint8_t CMD_SETVOLUME = 0x05; // 1バイト引数(PWMデューティ比 0-255)

// シリアル応答 (Arduino -> PC)
const uint8_t ACK_RESET = 0x01;
const uint8_t ACK_SETADDR = 0x02;
const uint8_t ACK_CHUNK = 0x10; // (未使用: byte単位マーカーは0xCD)
const uint8_t ACK_SENDBYTES = 0x03;
const uint8_t MARKER_BYTE_OK = 0xCD;
const uint8_t MARKER_TIMEOUT = 0xEE;

uint8_t transferIndex = 0;  // ブロック内のバイトカウンタ(port0へ書く値)
bool firstBlock = true;     // リセット直後の最初のブロックか(0xCCキック要否の判定)

// 1バイトをブロッキングで読む。タイムアウトしたら-1を返す。
int16_t serialReadByteBlocking(uint32_t timeoutMs) {
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    if (Serial.available() > 0) return Serial.read();
    delay(1);
  }
  return -1;
}

// タイムアウトなしで1バイト待つ(コマンド待ち受け用)
uint8_t serialReadByteForever() {
  while (Serial.available() <= 0) { delay(1); }
  return (uint8_t)Serial.read();
}

bool readSerialExact(uint8_t *buf, uint8_t len, uint32_t timeoutMs) {
  for (uint8_t i = 0; i < len; i++) {
    int16_t b = serialReadByteBlocking(timeoutMs);
    if (b < 0) return false;
    buf[i] = (uint8_t)b;
  }
  return true;
}

void handleReset() {
  spc::setMute(true);
  digitalWrite(PIN_RESET, LOW);
  delay(10);
  digitalWrite(PIN_RESET, HIGH);

  // ブート後、IPL ROMは port0=0xAA, port1=0xBB をセットしてホストからの
  // 転送要求を待つ状態になる。
  uint32_t start = millis();
  bool ready = false;
  while (millis() - start < 2000) {
    if (readPort(0) == 0xAA && readPort(1) == 0xBB) {
      ready = true;
      break;
    }
  }

  transferIndex = 0;
  firstBlock = true;

  if (ready) {
    Serial.write(ACK_RESET);
  } else {
    Serial.write((uint8_t)0x00); // readAckが期待値と食い違い、PC側でエラーになる
  }
}

void handleSetAddr() {
  uint8_t buf[3];
  if (!readSerialExact(buf, 3, 5000)) return; // タイムアウト時は無応答(PC側もタイムアウトする)
  uint8_t addrLo = buf[0];
  uint8_t addrHi = buf[1];
  bool cont = buf[2] != 0;

  // 転送先/ジャンプ先アドレスは常にport2(下位)/port3(上位)へ先に置く
  writePort(2, addrLo);
  writePort(3, addrHi);

  if (cont) {
    // --- データブロックの開始 ---
    // port1に非ゼロ = 「続けてデータブロックを送る」の意味
    writePort(1, 0x01);

    if (firstBlock) {
      // リセット直後の最初のブロックだけは 0xCC をキックとしてport0へ書き、
      // port0が0xCCをエコーするのを待つ。
      writePort(0, 0xCC);
      if (!waitForPort(0, 0xCC, 1000)) {
        Serial.write(MARKER_TIMEOUT);
        Serial.write((uint8_t)0xFF);
        Serial.write((uint8_t)0xFF);
        Serial.write((uint8_t)0x00);
        Serial.write(readPort(0));
        return;
      }
      firstBlock = false;
    } else {
      // 2ブロック目以降は「直前にport0へ書いた値 + 2」を書くとブロックが切り替わる。
      // port0は直前に書いた値をエコーしているので、それを読んで+2すれば確実。
      // 継続転送の場合、この値は0であってはならない(IPL ROMの内部処理の都合)。
      uint8_t kick = (uint8_t)(readPort(0) + 2);
      if (kick == 0) kick++;
      writePort(0, kick);
      if (!waitForPort(0, kick, 1000)) {
        Serial.write(MARKER_TIMEOUT);
        Serial.write((uint8_t)0xFF);
        Serial.write((uint8_t)0xFF);
        Serial.write(kick);
        Serial.write(readPort(0));
        return;
      }
    }

    // ブロック先頭からバイトカウンタは0で振り直す
    transferIndex = 0;
    Serial.write(ACK_SETADDR);

  } else {
    // --- 転送終了・指定アドレスへジャンプ ---
    // port1に0x00 = 「転送を終えてport2/port3のアドレスを実行せよ」の意味。
    // その上で port0 に「直前の値+2」を書いて初めて実行に移る。
    // (ジャンプ時は0でも構わないので0回避は不要)
    writePort(1, 0x00);
    uint8_t kick = (uint8_t)(readPort(0) + 2);
    writePort(0, kick);
    // ジャンプ後はIPL ROMを抜けるためエコーは返らない。待たずに完了応答する。
    firstBlock = true;
    spc::setMute(false);
    Serial.write(ACK_SETADDR);
  }
}

// PC側は PING_INTERVAL バイト書いてから1回だけ応答を待つ(バックプレッシャー
// 兼進捗確認)。1バイトごとに往復していた旧方式はUSBシリアルの往復遅延が
// 支配的になり65216バイトの転送に40秒近くかかっていたため、この単位で
// まとめることで往復回数を1/64に減らす。Arduinoの受信バッファ(64バイト)を
// 超えない値にしておくこと。
const uint16_t PING_INTERVAL = 64;

void handleSendBytes() {
  uint8_t lenBuf[2];
  if (!readSerialExact(lenBuf, 2, 5000)) return;
  uint16_t length = lenBuf[0] | (lenBuf[1] << 8);

  Serial.write((uint8_t)0xAB);
  Serial.write((uint8_t)(length & 0xFF));
  Serial.write((uint8_t)((length >> 8) & 0xFF));

  for (uint16_t pos = 0; pos < length; pos++) {
    int16_t vb = serialReadByteBlocking(3000);
    if (vb < 0) {
      Serial.write(MARKER_TIMEOUT);
      Serial.write((uint8_t)(pos & 0xFF));
      Serial.write((uint8_t)((pos >> 8) & 0xFF));
      Serial.write((uint8_t)0x00);
      Serial.write((uint8_t)0x00);
      return;
    }
    uint8_t value = (uint8_t)vb;

    writePort(1, value);
    writePort(0, transferIndex);

    if (!waitForPort(0, transferIndex, 200)) {
      uint8_t actual = readPort(0);
      Serial.write(MARKER_TIMEOUT);
      Serial.write((uint8_t)(pos & 0xFF));
      Serial.write((uint8_t)((pos >> 8) & 0xFF));
      Serial.write(value);
      Serial.write(actual);
      return;
    }

    transferIndex = (uint8_t)(transferIndex + 1);

    // PING_INTERVALバイトごと(と末尾)にだけ確認応答を1バイト返す。
    bool isLast = (pos == length - 1);
    bool isBoundary = ((pos % PING_INTERVAL) == (PING_INTERVAL - 1));
    if (isBoundary || isLast) {
      Serial.write(MARKER_BYTE_OK);
    }
  }

  Serial.write(ACK_SENDBYTES);
}

void handleReadPort() {
  int16_t portB = serialReadByteBlocking(3000);
  if (portB < 0) return;
  uint8_t val = readPort((uint8_t)portB);
  Serial.write((uint8_t)0x04);
  Serial.write(val);
}

void handleSetVolume() {
  int16_t dutyB = serialReadByteBlocking(3000);
  if (dutyB < 0) return;
  ledcWrite(PIN_VOLUME, (uint8_t)dutyB);
  Serial.write(CMD_SETVOLUME);
  Serial.write((uint8_t)dutyB);
}

void handleWritePort() {
  uint8_t args[2];
  if (!readSerialExact(args, 2, 3000)) return;
  writePort(args[0] & 3, args[1]);
  Serial.write(CMD_WRITEPORT);
}

// Call only in reset/IPL-ready state. Ports 2/3 can change without kicking IPL.
// Response: 0C, flags, mismatching reads (LE16), eight bit counters (LE16).
void handleBusDiag() {
  const uint8_t patterns[] = {0x00, 0xFF, 0x55, 0xAA, 0x80, 0x7F, 0x10, 0x01};
  uint16_t failures = 0, bits[8] = {};
  uint8_t flags = 0;
  for (uint8_t pattern : patterns) {
    for (int n = 0; n < 32; n++) {
      writePort(2, pattern);
      writePort(3, (uint8_t)~pattern);
      for (uint8_t port = 0; port < 2; port++) {
        uint8_t value = readPort(port);
        if (REG_READ(GPIO_ENABLE_REG) & spc::dataMask) flags |= 1;
        uint32_t outputs = REG_READ(GPIO_OUT_REG);
        if (!(outputs & (1UL << spc::PIN_OE_W)) &&
            !(outputs & (1UL << spc::PIN_OE_R))) flags |= 2;
        uint8_t difference = value ^ (port == 0 ? 0xAA : 0xBB);
        if (difference) failures++;
        for (int bit = 0; bit < 8; bit++) if (difference & (1 << bit)) bits[bit]++;
      }
    }
  }
  Serial.write(CMD_BUS_DIAG);
  Serial.write(flags);
  Serial.write((uint8_t)(failures & 0xFF));
  Serial.write((uint8_t)(failures >> 8));
  for (uint16_t count : bits) {
    Serial.write((uint8_t)(count & 0xFF));
    Serial.write((uint8_t)(count >> 8));
  }
}

// Run from IPL-ready state. Start transfer at $1000 but do not execute code.
// 0D, ready, echoed, ports[4], 4 writes * 4 stages * (OUT, IN, ENABLE) LE32.
void handleWriteTrace() {
  bool ready = readPort(0) == 0xAA && readPort(1) == 0xBB;
  for (uint8_t p : {spc::PIN_A0, spc::PIN_A1, spc::PIN_WR, spc::PIN_RD,
                    spc::PIN_OE_W, spc::PIN_OE_R}) gpio_input_enable((gpio_num_t)p);
  memset(spc::writeTrace, 0, sizeof(spc::writeTrace));
  spc::traceCount = 0;
  spc::traceWrites = true;
  if (ready) {
    writePort(2, 0x00);
    writePort(3, 0x10);
    writePort(1, 0x01);
    writePort(0, 0xCC);
  }
  spc::traceWrites = false;
  bool echoed = ready && waitForPort(0, 0xCC, 1000);
  Serial.write(CMD_WRITE_TRACE);
  Serial.write((uint8_t)ready);
  Serial.write((uint8_t)echoed);
  for (uint8_t p = 0; p < 4; p++) Serial.write(readPort(p));
  Serial.write((const uint8_t *)spc::writeTrace, sizeof(spc::writeTrace));
}

void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(500000);
  spc::begin();
  ledcAttach(PIN_VOLUME, 20000, 8);
  ledcWrite(PIN_VOLUME, 0);
}
void loop() {
  uint8_t cmd = serialReadByteForever();

  switch (cmd) {
    case CMD_HOLD_DATA: {
      int16_t value = serialReadByteBlocking(3000);
      if (value < 0) break;
      spc::setMute(true);
      ledcWrite(PIN_VOLUME, 0);
      digitalWrite(PIN_RESET, LOW);
      spc::enterWrite();
      spc::selectPort(2);
      for (uint8_t bit = 0; bit < 8; bit++) {
        digitalWrite(spc::DATA_PINS[bit], (value & (1 << bit)) ? HIGH : LOW);
        gpio_input_enable((gpio_num_t)spc::DATA_PINS[bit]);
      }
      delay(1);
      digitalWrite(spc::PIN_OE_W, LOW);
      delay(1);
      uint32_t latch = REG_READ(GPIO_OUT_REG), pads = REG_READ(GPIO_IN_REG);
      uint8_t latchData = 0, padData = 0;
      for (uint8_t bit = 0; bit < 8; bit++) {
        if (latch & (1UL << spc::DATA_PINS[bit])) latchData |= 1 << bit;
        if (pads & (1UL << spc::DATA_PINS[bit])) padData |= 1 << bit;
      }
      Serial.write(CMD_HOLD_DATA);
      Serial.write((uint8_t)value);
      Serial.write(latchData);
      Serial.write(padData);
      break;
    }
    case CMD_HOLD_WR: {
      int16_t level = serialReadByteBlocking(3000);
      if (level < 0) break;
      // Static meter test: mute/reset asserted, both data buffers disabled.
      spc::setMute(true);
      ledcWrite(PIN_VOLUME, 0);
      digitalWrite(PIN_RESET, LOW);
      digitalWrite(spc::PIN_OE_W, HIGH);
      digitalWrite(spc::PIN_OE_R, HIGH);
      digitalWrite(spc::PIN_RD, HIGH);
      for (uint8_t pin : spc::DATA_PINS) pinMode(pin, INPUT);
      gpio_input_enable((gpio_num_t)spc::PIN_WR);
      digitalWrite(spc::PIN_WR, level ? HIGH : LOW);
      delay(1);
      Serial.write(CMD_HOLD_WR);
      Serial.write((uint8_t)(level != 0));
      Serial.write((uint8_t)((REG_READ(GPIO_OUT_REG) >> spc::PIN_WR) & 1));
      Serial.write((uint8_t)((REG_READ(GPIO_IN_REG) >> spc::PIN_WR) & 1));
      break;
    }
    case CMD_WRITE_TIMING: {
      uint8_t args[2];
      if (readSerialExact(args, 2, 3000)) {
        uint16_t us = args[0] | (args[1] << 8);
        spc::diagnosticWriteUs = constrain(us, 1, 1000);
        Serial.write(CMD_WRITE_TIMING);
        Serial.write((uint8_t)spc::diagnosticWriteUs);
        Serial.write((uint8_t)(spc::diagnosticWriteUs >> 8));
      }
      break;
    }
    case CMD_PAD_SWEEP: {
      // Writes only input port2; never sends the IPL kick or executes code.
      for (uint8_t p : {spc::PIN_A0, spc::PIN_A1, spc::PIN_WR, spc::PIN_RD,
                        spc::PIN_OE_W, spc::PIN_OE_R}) gpio_input_enable((gpio_num_t)p);
      Serial.write(CMD_PAD_SWEEP);
      for (uint16_t value = 0; value < 256; value++) {
        spc::traceCount = 0;
        spc::traceWrites = true;
        writePort(2, (uint8_t)value);
        spc::traceWrites = false;
        // Capture while /WR LOW and U2 enabled: OUT, IN, ENABLE (12 bytes).
        Serial.write((const uint8_t *)spc::writeTrace[0][1], 12);
      }
      break;
    }
    case CMD_WRITE_TRACE:
      handleWriteTrace();
      break;
    case CMD_BUS_DIAG:
      handleBusDiag();
      break;
    case CMD_WRITEPORT:
      handleWritePort();
      break;
    case CMD_RESET:
      handleReset();
      break;
    case CMD_SETADDR:
      handleSetAddr();
      break;
    case CMD_SENDBYTES:
      handleSendBytes();
      break;
    case CMD_READPORT:
      handleReadPort();
      break;
    case CMD_SETVOLUME:
      handleSetVolume();
      break;
    default:
      // 未知コマンドは無視 (PC側はACK待ちでタイムアウトする)
      break;
  }
}
