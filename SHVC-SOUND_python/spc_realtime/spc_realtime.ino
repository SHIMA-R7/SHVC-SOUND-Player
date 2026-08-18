/*
 * spc_realtime.ino - SHVC-SOUND リアルタイム演奏対応ファームウェア (Arduino Uno R3 / Nano)
 *
 * spc_uploader.ino の上位互換。従来の .spc 転送コマンド(CMD_RESET/SETADDR/
 * SENDBYTES/READPORT/SETVOLUME)はそのまま残してあるので、spc_gui.py /
 * spc_play.py はこのファームでも今までどおり動く。
 *
 * 追加したのはMIDIリアルタイム演奏(midi2spc/hardware.py)用の3コマンド:
 *
 *   CMD_DSPWRITE (0x07) [reg][val]
 *       SPC700側の常駐ドライバ経由でDSPレジスタを1個書く。
 *
 *   CMD_STREAM (0x08)
 *       以後、4バイトのイベントレコードを連続で受け取る。
 *         [待ち時間LE16 (100µs単位)][DSPレジスタ番号][値]
 *       レコードはリングバッファに積まれ、指定の時刻どおりに実行される。
 *       レジスタ番号 0xFF は「DSPには書かず待つだけ」のNOP。
 *       FF FF FF FF を受け取るとストリーム終了。
 *       1レコード消化するごとにクレジットバイト(0x5A)を返すので、
 *       PC側はそれを数えて送りすぎを防ぐ(フロー制御)。
 *
 *   CMD_PANIC (0x09)
 *       全ボイスをキーオフしてマスター音量を0にする(緊急停止)。
 *
 * ■ なぜSPC700側にドライバが必要か
 *   S-DSPのレジスタはSPC700からしか触れない。ホスト(Arduino)から見えるのは
 *   $F4-$F7の4バイトの窓だけ。そこで「$F5のレジスタ番号と$F6の値をDSPへ
 *   書き写すだけ」の23バイトの常駐ループをSPC700に置き、Arduinoはその窓越しに
 *   指示を出す。曲の解釈はすべてPC側に残るので、SPC700側はこれで足りる。
 *   ドライバ本体は midi2spc/hardware.py の DRIVER_CODE にある。
 *
 * ピン配置は spc_uploader.ino と同一(PROJECT_BRIEF.md 3.1節)。
 */

const uint8_t DATA_PINS[8] = {2, 3, 4, 5, 6, 7, 8, 9};
const uint8_t ARD_A0 = A0;
const uint8_t ARD_A1 = A1;
const uint8_t PIN_WR = A2;
const uint8_t PIN_RD = A3;
const uint8_t PIN_RESET = A4;
const uint8_t PIN_VOLUME = 10;

// シリアルコマンド (PC -> Arduino)
const uint8_t CMD_RESET = 0x01;
const uint8_t CMD_SETADDR = 0x02;
const uint8_t CMD_SENDBYTES = 0x03;
const uint8_t CMD_READPORT = 0x04;
const uint8_t CMD_SETVOLUME = 0x05;
const uint8_t CMD_DSPWRITE = 0x07;
const uint8_t CMD_STREAM = 0x08;
const uint8_t CMD_PANIC = 0x09;
const uint8_t CMD_PING = 0x0A;

// PING応答。PC側はこれでファームの種類とバージョンを確認する。
// 旧 spc_uploader.ino は未知のコマンドを黙って捨てるため、
// PINGに無反応 = 旧ファームが載っている、と判別できる。
const uint8_t PING_MAGIC = 0xA5;
const uint8_t FIRMWARE_VERSION = 1;

// シリアル応答 (Arduino -> PC)
const uint8_t ACK_RESET = 0x01;
const uint8_t ACK_SETADDR = 0x02;
const uint8_t ACK_SENDBYTES = 0x03;
const uint8_t ACK_DSPWRITE = 0x07;
const uint8_t ACK_STREAM_DONE = 0x08;
const uint8_t ACK_PANIC = 0x09;
const uint8_t MARKER_BYTE_OK = 0xCD;
const uint8_t MARKER_TIMEOUT = 0xEE;
const uint8_t CREDIT_BYTE = 0x5A;
const uint8_t ERR_DRIVER_TIMEOUT = 0xE7;

uint8_t transferIndex = 0;
bool firstBlock = true;
uint8_t driverSeq = 0;   // 常駐ドライバとのハンドシェイク用シーケンス値

// ==================== 高速バスI/O(AVRポートレジスタ直叩き) ====================
// 詳細は spc_uploader.ino のコメント参照。1バイトあたりの処理を
// ポート書き込み数回まで削るための直接操作。

const uint8_t DATA_LOW_MASK = 0b11111100;   // PORTD bit2-7 (D2-D7)
const uint8_t DATA_HIGH_MASK = 0b00000011;  // PORTB bit0-1 (D8-D9)

void setDataBusOutput() {
  DDRD |= DATA_LOW_MASK;
  DDRB |= DATA_HIGH_MASK;
}

void setDataBusInput() {
  DDRD &= ~DATA_LOW_MASK;
  DDRB &= ~DATA_HIGH_MASK;
}

inline void busWriteData(uint8_t v) {
  PORTD = (PORTD & ~DATA_LOW_MASK) | ((v << 2) & DATA_LOW_MASK);
  PORTB = (PORTB & ~DATA_HIGH_MASK) | ((v >> 6) & DATA_HIGH_MASK);
}

inline uint8_t busReadData() {
  uint8_t low = (PIND & DATA_LOW_MASK) >> 2;
  uint8_t high = (PINB & DATA_HIGH_MASK) << 6;
  return low | high;
}

inline void selectAddr(uint8_t port) {
  PORTC = (PORTC & ~0b00000011) | (port & 0b00000011);
}

const uint8_t BUS_DELAY_US = 3;

void writePort(uint8_t port, uint8_t val) {
  setDataBusOutput();
  selectAddr(port);
  busWriteData(val);
  delayMicroseconds(BUS_DELAY_US);
  PORTC &= ~(1 << 2);
  delayMicroseconds(BUS_DELAY_US);
  PORTC |= (1 << 2);
  delayMicroseconds(BUS_DELAY_US);
}

uint8_t readPort(uint8_t port) {
  setDataBusInput();
  selectAddr(port);
  PORTC &= ~(1 << 3);
  delayMicroseconds(BUS_DELAY_US);
  uint8_t v = busReadData();
  PORTC |= (1 << 3);
  delayMicroseconds(BUS_DELAY_US);
  return v;
}

bool waitForPort(uint8_t port, uint8_t expected, uint32_t timeoutMs) {
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    if (readPort(port) == expected) return true;
  }
  return false;
}

int16_t serialReadByteBlocking(uint32_t timeoutMs) {
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    if (Serial.available() > 0) return Serial.read();
  }
  return -1;
}

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

// ==================== SPC700常駐ドライバとのやり取り ====================
//
// ドライバは $F4 の値が変わるのを待っている。
// $F5 にレジスタ番号、$F6 に値を置いてから $F4 に新しいシーケンス値を
// 書くと、DSPへ書き写して $F4 に同じ値を返してくる。
//
// ドライバのループは十数サイクル(約5µs)なので、待ち時間はごく短い。
// 応答が来ない = ドライバが動いていない、ということなのでタイムアウトは短くてよい。

const uint32_t DRIVER_TIMEOUT_MS = 20;

bool dspWrite(uint8_t reg, uint8_t val) {
  writePort(1, reg);
  writePort(2, val);
  driverSeq++;
  writePort(0, driverSeq);
  return waitForPort(0, driverSeq, DRIVER_TIMEOUT_MS);
}

void handleDspWrite() {
  uint8_t buf[2];
  if (!readSerialExact(buf, 2, 3000)) return;
  if (dspWrite(buf[0], buf[1])) {
    Serial.write(ACK_DSPWRITE);
  } else {
    Serial.write(ERR_DRIVER_TIMEOUT);
  }
}

void handlePing() {
  Serial.write(PING_MAGIC);
  Serial.write(FIRMWARE_VERSION);
}

void handlePanic() {
  dspWrite(0x5C, 0xFF);  // KOF: 全ボイスをキーオフ
  dspWrite(0x5C, 0x00);
  dspWrite(0x0C, 0x00);  // MVOLL
  dspWrite(0x1C, 0x00);  // MVOLR
  Serial.write(ACK_PANIC);
}

// ==================== イベントストリーム ====================
//
// 4バイトのレコードをリングバッファに積み、待ち時間どおりに実行する。
// PC側は「クレジット」の数だけ先行して送ってよい。1レコード消化ごとに
// クレジットバイトを1つ返す。
//
// EVENT_SLOTS はPC側 hardware.py の STREAM_CREDITS より大きくしておくこと
// (PCが先行送信できる量をリングバッファが必ず受けきれるようにするため)。

// 和音のキーオンは1音あたり11レジスタ書き込みになるため、8音同時だと
// 88レコードが一気に来る。段数が少ないとそのたびPCとの往復待ちが入って
// 発音が滲むので、余裕を持たせてある(96段でRAM384バイト)。
const uint8_t EVENT_SLOTS = 96;

// リングバッファは構造体ではなく並列配列で持つ。
// Arduinoのスケッチはビルド時に関数プロトタイプが自動挿入されるが、
// その挿入位置は自作の型定義より前になるため、構造体を引数や戻り値に
// 使うと 'Event' does not name a type でコンパイルが通らない。
uint16_t ringDelay[EVENT_SLOTS];  // 直前のイベントからの待ち時間(100µs単位)
uint8_t ringReg[EVENT_SLOTS];     // DSPレジスタ番号 (0xFF = 待つだけのNOP)
uint8_t ringVal[EVENT_SLOTS];
uint8_t ringHead = 0;
uint8_t ringTail = 0;
uint8_t ringCount = 0;

// PCからの供給が途絶えたと判断するまでの時間
const uint32_t STREAM_STARVE_TIMEOUT_MS = 5000;

void handleStream() {
  ringHead = ringTail = ringCount = 0;

  bool inputDone = false;
  bool driverLost = false;
  uint32_t dueTime = micros();     // 次に実行すべきイベントの絶対時刻
  bool dueValid = false;
  uint32_t lastActivity = millis();

  while (true) {
    // --- 1. 受信: 空きがある限り4バイト単位で取り込む ---
    while (!inputDone && ringCount < EVENT_SLOTS && Serial.available() >= 4) {
      uint8_t lo = Serial.read();
      uint8_t hi = Serial.read();
      uint8_t reg = Serial.read();
      uint8_t val = Serial.read();

      if (lo == 0xFF && hi == 0xFF && reg == 0xFF && val == 0xFF) {
        inputDone = true;   // 終端マーカー
        break;
      }

      ringDelay[ringTail] = (uint16_t)lo | ((uint16_t)hi << 8);
      ringReg[ringTail] = reg;
      ringVal[ringTail] = val;
      ringTail = (uint8_t)((ringTail + 1) % EVENT_SLOTS);
      ringCount++;
      lastActivity = millis();
    }

    // --- 2. 実行: 待ち時間が来たイベントを処理する ---
    if (ringCount > 0) {
      if (!dueValid) {
        // 次のイベントの実行時刻を、前のイベントの予定時刻から積み上げる。
        // micros()を都度基準にすると誤差が累積してテンポがずれるため。
        dueTime += (uint32_t)ringDelay[ringHead] * 100UL;
        dueValid = true;
      }
      if ((int32_t)(micros() - dueTime) >= 0) {
        uint8_t reg = ringReg[ringHead];
        uint8_t val = ringVal[ringHead];
        ringHead = (uint8_t)((ringHead + 1) % EVENT_SLOTS);
        ringCount--;
        dueValid = false;

        if (reg != 0xFF) {
          if (!dspWrite(reg, val)) {
            driverLost = true;
            break;
          }
        }
        Serial.write(CREDIT_BYTE);
        lastActivity = millis();
      }
    } else if (inputDone) {
      break;
    } else if (millis() - lastActivity > STREAM_STARVE_TIMEOUT_MS) {
      // PC側が落ちた等。鳴りっぱなしを避けて抜ける。
      break;
    }
  }

  if (driverLost) {
    Serial.write(ERR_DRIVER_TIMEOUT);
  } else {
    Serial.write(ACK_STREAM_DONE);
  }
}

// ==================== 従来の .spc 転送コマンド ====================

void handleReset() {
  digitalWrite(PIN_RESET, LOW);
  delay(10);
  digitalWrite(PIN_RESET, HIGH);

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
  driverSeq = 0;

  if (ready) {
    Serial.write(ACK_RESET);
  } else {
    Serial.write((uint8_t)0x00);
  }
}

void handleSetAddr() {
  uint8_t buf[3];
  if (!readSerialExact(buf, 3, 5000)) return;
  uint8_t addrLo = buf[0];
  uint8_t addrHi = buf[1];
  bool cont = buf[2] != 0;

  writePort(2, addrLo);
  writePort(3, addrHi);

  if (cont) {
    writePort(1, 0x01);

    if (firstBlock) {
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

    transferIndex = 0;
    Serial.write(ACK_SETADDR);

  } else {
    writePort(1, 0x00);
    uint8_t kick = (uint8_t)(readPort(0) + 2);
    writePort(0, kick);
    firstBlock = true;
    // ジャンプ先が常駐ドライバの場合、ドライバはACKラッチを0に初期化する。
    // 次のdspWrite()はdriverSeq=1から始まるので必ず値が変わる。
    driverSeq = 0;
    Serial.write(ACK_SETADDR);
  }
}

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
  analogWrite(PIN_VOLUME, (uint8_t)dutyB);
  Serial.write(CMD_SETVOLUME);
  Serial.write((uint8_t)dutyB);
}

void setup() {
  Serial.begin(500000);

  pinMode(ARD_A0, OUTPUT);
  pinMode(ARD_A1, OUTPUT);
  pinMode(PIN_WR, OUTPUT);
  pinMode(PIN_RD, OUTPUT);
  pinMode(PIN_RESET, OUTPUT);
  pinMode(PIN_VOLUME, OUTPUT);

  digitalWrite(PIN_WR, HIGH);
  digitalWrite(PIN_RD, HIGH);
  digitalWrite(PIN_RESET, HIGH);
  analogWrite(PIN_VOLUME, 0);

  setDataBusInput();
}

void loop() {
  uint8_t cmd = serialReadByteForever();

  switch (cmd) {
    case CMD_RESET:     handleReset();     break;
    case CMD_SETADDR:   handleSetAddr();   break;
    case CMD_SENDBYTES: handleSendBytes(); break;
    case CMD_READPORT:  handleReadPort();  break;
    case CMD_SETVOLUME: handleSetVolume(); break;
    case CMD_DSPWRITE:  handleDspWrite();  break;
    case CMD_STREAM:    handleStream();    break;
    case CMD_PANIC:     handlePanic();     break;
    case CMD_PING:      handlePing();      break;
    default: break;
  }
}
