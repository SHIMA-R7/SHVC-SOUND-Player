/*
 * spc_uploader.ino - SHVC-SOUND (SPC700 IPL ROM) 転送用ファームウェア (Arduino Nano)
 *
 * PC側 spc_play.py とシリアル(115200bps)でやり取りし、そのコマンドを
 * SHVC-SOUNDのパラレルバス(D0-D7, A0/A1, /WR, /RD, /RESET)経由で
 * SPC700標準IPL ROMアップロードプロトコルに変換して実行する。
 *
 * ピン配置 (PROJECT_BRIEF.md 3.1節と一致させること):
 *   Nano D2-D9  -> SHVC-SOUND D0-D7
 *   Nano A0     -> SHVC-SOUND A0
 *   Nano A1     -> SHVC-SOUND A1
 *   Nano A2     -> SHVC-SOUND /WR
 *   Nano A3     -> SHVC-SOUND /RD
 *   Nano A4     -> SHVC-SOUND /RESET
 *   (D10 = /MUTE は基板側で常時HIGH固定、本スケッチでは未使用)
 *
 * ポートマップ (SPC700 IPL ROM):
 *   port0 = $F4 (A1A0=00)  port1 = $F5 (A1A0=01)
 *   port2 = $F6 (A1A0=10)  port3 = $F7 (A1A0=11)
 */

const uint8_t DATA_PINS[8] = {2, 3, 4, 5, 6, 7, 8, 9};
const uint8_t PIN_A0 = A0;
const uint8_t PIN_A1 = A1;
const uint8_t PIN_WR = A2;
const uint8_t PIN_RD = A3;
const uint8_t PIN_RESET = A4;
const uint8_t PIN_MUTE = 10; // SHVC-SOUND pin20 (/MUTE) 常時HIGH固定

// シリアルコマンド (PC -> Arduino)
const uint8_t CMD_RESET = 0x01;
const uint8_t CMD_SETADDR = 0x02;
const uint8_t CMD_SENDBYTES = 0x03;
const uint8_t CMD_READPORT = 0x04;

// シリアル応答 (Arduino -> PC)
const uint8_t ACK_RESET = 0x01;
const uint8_t ACK_SETADDR = 0x02;
const uint8_t ACK_CHUNK = 0x10; // (未使用: byte単位マーカーは0xCD)
const uint8_t ACK_SENDBYTES = 0x03;
const uint8_t MARKER_BYTE_OK = 0xCD;
const uint8_t MARKER_TIMEOUT = 0xEE;

uint8_t transferIndex = 0;  // ブロック内のバイトカウンタ(port0へ書く値)
bool firstBlock = true;     // リセット直後の最初のブロックか(0xCCキック要否の判定)

void setDataBusOutput() {
  for (uint8_t i = 0; i < 8; i++) pinMode(DATA_PINS[i], OUTPUT);
}

void setDataBusInput() {
  for (uint8_t i = 0; i < 8; i++) pinMode(DATA_PINS[i], INPUT);
}

void busWriteData(uint8_t v) {
  for (uint8_t i = 0; i < 8; i++) digitalWrite(DATA_PINS[i], (v >> i) & 1);
}

uint8_t busReadData() {
  uint8_t v = 0;
  for (uint8_t i = 0; i < 8; i++) v |= (digitalRead(DATA_PINS[i]) << i);
  return v;
}

void selectAddr(uint8_t port) {
  digitalWrite(PIN_A0, port & 1);
  digitalWrite(PIN_A1, (port >> 1) & 1);
}

void writePort(uint8_t port, uint8_t val) {
  setDataBusOutput();
  selectAddr(port);
  busWriteData(val);
  delayMicroseconds(1);
  digitalWrite(PIN_WR, LOW);
  delayMicroseconds(1);
  digitalWrite(PIN_WR, HIGH);
  delayMicroseconds(1);
}

uint8_t readPort(uint8_t port) {
  setDataBusInput();
  selectAddr(port);
  digitalWrite(PIN_RD, LOW);
  delayMicroseconds(1);
  uint8_t v = busReadData();
  digitalWrite(PIN_RD, HIGH);
  delayMicroseconds(1);
  return v;
}

// timeoutMs 以内に readPort(port)==expected になるのを待つ。成功でtrue。
bool waitForPort(uint8_t port, uint8_t expected, uint32_t timeoutMs) {
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    if (readPort(port) == expected) return true;
  }
  return false;
}

// 1バイトをブロッキングで読む。タイムアウトしたら-1を返す。
int16_t serialReadByteBlocking(uint32_t timeoutMs) {
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    if (Serial.available() > 0) return Serial.read();
  }
  return -1;
}

// タイムアウトなしで1バイト待つ(コマンド待ち受け用)
uint8_t serialReadByteForever() {
  while (Serial.available() <= 0) { /* spin */ }
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
    Serial.write(ACK_SETADDR);
  }
}

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

    Serial.write(MARKER_BYTE_OK);
    Serial.write(transferIndex);
    transferIndex = (uint8_t)(transferIndex + 1);
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

void setup() {
  Serial.begin(115200);

  pinMode(PIN_A0, OUTPUT);
  pinMode(PIN_A1, OUTPUT);
  pinMode(PIN_WR, OUTPUT);
  pinMode(PIN_RD, OUTPUT);
  pinMode(PIN_RESET, OUTPUT);
  pinMode(PIN_MUTE, OUTPUT);

  digitalWrite(PIN_WR, HIGH);
  digitalWrite(PIN_RD, HIGH);
  digitalWrite(PIN_RESET, HIGH); // SHVC-SOUNDを動作状態に(初期化はCMD_RESETで行う)
  digitalWrite(PIN_MUTE, HIGH); // /MUTE常時HIGH固定

  setDataBusInput();
}

void loop() {
  uint8_t cmd = serialReadByteForever();

  switch (cmd) {
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
    default:
      // 未知コマンドは無視 (PC側はACK待ちでタイムアウトする)
      break;
  }
}
