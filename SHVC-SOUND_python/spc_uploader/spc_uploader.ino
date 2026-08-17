/*
 * spc_uploader.ino - SHVC-SOUND (SPC700 IPL ROM) 転送用ファームウェア (Arduino Uno R3 / Nano)
 *
 * PC側 spc_play.py とシリアル(115200bps)でやり取りし、そのコマンドを
 * SHVC-SOUNDのパラレルバス(D0-D7, A0/A1, /WR, /RD, /RESET)経由で
 * SPC700標準IPL ROMアップロードプロトコルに変換して実行する。
 *
 * Uno R3とNanoはどちらもATmega328P・16MHz・5Vロジックなので、
 * 下記ピン名はそのまま共通で使える。
 *
 * ピン配置 (PROJECT_BRIEF.md 3.1節と一致させること):
 *   D2-D9  -> SHVC-SOUND D0-D7
 *   Nano A0     -> SHVC-SOUND A0
 *   Nano A1     -> SHVC-SOUND A1
 *   Nano A2     -> SHVC-SOUND /WR
 *   Nano A3     -> SHVC-SOUND /RD
 *   Nano A4     -> SHVC-SOUND /RESET
 *   D10         -> TDA7053A VC1/VC2への音量制御PWM出力
 *                  (R6=10kΩ経由でノードへ、ノード-R5-GND、ノード-C5-GND、
 *                   ノードをVC1/VC2に接続。PROJECT_BRIEF.md 3.4節)
 *
 * /MUTE(SHVC-SOUND pin20)はD10を使わず基板側で+5V直結に固定する
 * (このスケッチではD10をPWM音量出力として使うため)。
 *
 * ポートマップ (SPC700 IPL ROM):
 *   port0 = $F4 (A1A0=00)  port1 = $F5 (A1A0=01)
 *   port2 = $F6 (A1A0=10)  port3 = $F7 (A1A0=11)
 */

const uint8_t DATA_PINS[8] = {2, 3, 4, 5, 6, 7, 8, 9};
const uint8_t ARD_A0 = A0;
const uint8_t ARD_A1 = A1;
const uint8_t PIN_WR = A2;
const uint8_t PIN_RD = A3;
const uint8_t PIN_RESET = A4;
const uint8_t PIN_VOLUME = 10; // TDA7053A VC1/VC2への音量制御PWM出力

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

// ==================== 高速バスI/O(AVRポートレジスタ直叩き) ====================
//
// digitalWrite()/digitalRead()は1回あたり数マイクロ秒かかる重い実装で、
// 1バイト転送するたびに8〜16回呼ぶと合計38秒もかかっていた(実測)。
// ここではATmega328Pのポートレジスタを直接操作し、1バイトあたりの
// 処理をポート書き込み数回(各1〜2クロック)まで削る。
//
// DATA_PINS = {2,3,4,5,6,7,8,9} のピン配置(Uno/Nano共通)は
//   D2-D7 -> PORTD bit2-7 (上位6bit分がここに乗る形)
//   D8-D9 -> PORTB bit0-1
// という2ポートにまたがった配置なので、データバイトを
// 下位6bit(D2-D7側)と上位2bit(D8-D9側)に分けて書く。
//
// A0/A1/WR/RD/RESET は ARD_A0=A0(PC0), ARD_A1=A1(PC1),
// PIN_WR=A2(PC2), PIN_RD=A3(PC3), PIN_RESET=A4(PC4) と
// すべてPORTC上に収まっているので、アドレス選択とWR/RDの
// トグルはPORTCのビット操作だけで完結する。
//
// pinMode()自体は起動時とデータバスの入出力切り替え時にしか
// 呼ばないので(1バイトごとには呼ばない)、そこは従来通りの
// DDR直接操作に留め、速度が問題になる箇所だけを最適化する。

const uint8_t DATA_LOW_MASK = 0b11111100;   // PORTD bit2-7 (D2-D7)
const uint8_t DATA_HIGH_MASK = 0b00000011;  // PORTB bit0-1 (D8-D9)

void setDataBusOutput() {
  DDRD |= DATA_LOW_MASK;
  DDRB |= DATA_HIGH_MASK;
}

void setDataBusInput() {
  DDRD &= ~DATA_LOW_MASK;
  DDRB &= ~DATA_HIGH_MASK;
  // 入力時のプルアップは付けない(バスは常にどちらかがHIGH/LOWを
  // 明示的に駆動する前提のため、フローティング入力にしても
  // readPort()を呼ぶ瞬間は必ずSHVC-SOUND側が駆動している)。
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

// digitalWrite()版は1回の呼び出しだけで数マイクロ秒かかっていたため、
// 明示的な delayMicroseconds(1) 以上の「余分な余裕」がバスタイミングに
// 意図せず乗っていた。直接ポート操作にした際にそのマージンが消え、
// ACK(カウンタの一致だけを見る仕組みのため、データが化けていても
// 成功と報告されてしまう)は通るのに実際のデータが化ける不具合が起きた。
// そのため明示的なディレイを増やし、確実なマージンを確保する。
const uint8_t BUS_DELAY_US = 3;

void writePort(uint8_t port, uint8_t val) {
  setDataBusOutput();
  selectAddr(port);
  busWriteData(val);
  delayMicroseconds(BUS_DELAY_US);
  PORTC &= ~(1 << 2);  // /WR = A2 = PC2 を LOW
  delayMicroseconds(BUS_DELAY_US);
  PORTC |= (1 << 2);   // /WR を HIGH に戻す
  delayMicroseconds(BUS_DELAY_US);
}

uint8_t readPort(uint8_t port) {
  setDataBusInput();
  selectAddr(port);
  PORTC &= ~(1 << 3);  // /RD = A3 = PC3 を LOW
  delayMicroseconds(BUS_DELAY_US);
  uint8_t v = busReadData();
  PORTC |= (1 << 3);   // /RD を HIGH に戻す
  delayMicroseconds(BUS_DELAY_US);
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
  analogWrite(PIN_VOLUME, (uint8_t)dutyB);
  Serial.write(CMD_SETVOLUME);
  Serial.write((uint8_t)dutyB);
}

void setup() {
  // spc_play.py側と揃えること。115200から500000へ引き上げ、
  // 65216バイトの曲データ転送にかかる時間を短縮している。
  Serial.begin(500000);

  pinMode(ARD_A0, OUTPUT);
  pinMode(ARD_A1, OUTPUT);
  pinMode(PIN_WR, OUTPUT);
  pinMode(PIN_RD, OUTPUT);
  pinMode(PIN_RESET, OUTPUT);
  pinMode(PIN_VOLUME, OUTPUT);

  digitalWrite(PIN_WR, HIGH);
  digitalWrite(PIN_RD, HIGH);
  digitalWrite(PIN_RESET, HIGH); // SHVC-SOUNDを動作状態に(初期化はCMD_RESETで行う)
  analogWrite(PIN_VOLUME, 0);    // 起動直後は無音側(未校正のR5/R6分圧に対する安全側の初期値)

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
    case CMD_SETVOLUME:
      handleSetVolume();
      break;
    default:
      // 未知コマンドは無視 (PC側はACK待ちでタイムアウトする)
      break;
  }
}
