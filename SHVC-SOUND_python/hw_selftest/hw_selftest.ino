/*
 * hw_selftest.ino - SHVC-SOUND 最小構成ハードウェア自己診断 (Arduino Nano)
 *
 * PCのPythonを使わず、Arduino単体でSHVC-SOUNDからノイズ音を出す。
 * 「ハードの配線が悪いのか、spc_play.pyの転送が悪いのか」を切り分けるための道具。
 *
 * 使い方:
 *   1. このスケッチをNanoに書き込む
 *   2. Arduino IDEのシリアルモニタを 115200bps で開く
 *   3. 自動でテストが走る。何かキーを送ると再実行。
 *
 * 期待する結果:
 *   [OK] が並び、最後に「ザーッ」というノイズが鳴り続ける。
 *   どこで [NG] が出たかで原因が分かる(下のトラブルシュートを参照)。
 *
 * ピン配置は spc_uploader.ino と同一。
 */

const uint8_t DATA_PINS[8] = {2, 3, 4, 5, 6, 7, 8, 9};
const uint8_t PIN_A0 = A0;
const uint8_t PIN_A1 = A1;
const uint8_t PIN_WR = A2;
const uint8_t PIN_RD = A3;
const uint8_t PIN_RESET = A4;
const uint8_t PIN_MUTE = 10;

// ---------------- 低レベルバス操作 ----------------

void setDataBusOutput() { for (uint8_t i = 0; i < 8; i++) pinMode(DATA_PINS[i], OUTPUT); }
void setDataBusInput()  { for (uint8_t i = 0; i < 8; i++) pinMode(DATA_PINS[i], INPUT); }

void selectAddr(uint8_t port) {
  digitalWrite(PIN_A0, port & 1);
  digitalWrite(PIN_A1, (port >> 1) & 1);
}

void writePort(uint8_t port, uint8_t val) {
  setDataBusOutput();
  selectAddr(port);
  for (uint8_t i = 0; i < 8; i++) digitalWrite(DATA_PINS[i], (val >> i) & 1);
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
  uint8_t v = 0;
  for (uint8_t i = 0; i < 8; i++) v |= ((uint8_t)digitalRead(DATA_PINS[i]) << i);
  digitalWrite(PIN_RD, HIGH);
  delayMicroseconds(1);
  return v;
}

bool waitForPort(uint8_t port, uint8_t expected, uint32_t timeoutMs) {
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    if (readPort(port) == expected) return true;
  }
  return false;
}

void printHex(uint8_t v) {
  if (v < 0x10) Serial.print('0');
  Serial.print(v, HEX);
}

// ---------------- IPL ROM 転送プロトコル ----------------

uint8_t g_index = 0;
bool g_firstBlock = true;

// SHVC-SOUNDをリセットし、IPL ROMがready($AA/$BB)になるのを待つ
bool apuReset() {
  digitalWrite(PIN_RESET, LOW);
  delay(10);
  digitalWrite(PIN_RESET, HIGH);

  g_index = 0;
  g_firstBlock = true;

  uint32_t start = millis();
  while (millis() - start < 2000) {
    if (readPort(0) == 0xAA && readPort(1) == 0xBB) return true;
  }
  return false;
}

// データブロックの開始(転送先アドレスを指定する)
bool apuBeginBlock(uint16_t addr) {
  writePort(2, addr & 0xFF);
  writePort(3, (addr >> 8) & 0xFF);
  writePort(1, 0x01);          // 非ゼロ = データブロックを続ける

  uint8_t kick;
  if (g_firstBlock) {
    kick = 0xCC;               // 最初のブロックだけ$CCがキック
    g_firstBlock = false;
  } else {
    kick = (uint8_t)(readPort(0) + 2);   // 2ブロック目以降は直前値+2
    if (kick == 0) kick++;               // ゼロは禁止(IPLがバイト0待ちと誤認する)
  }
  writePort(0, kick);
  if (!waitForPort(0, kick, 1000)) return false;

  g_index = 0;               // バイトカウンタはブロックごとに0から
  return true;
}

bool apuSendByte(uint8_t value) {
  writePort(1, value);
  writePort(0, g_index);
  if (!waitForPort(0, g_index, 200)) return false;
  g_index++;
  return true;
}

bool apuWriteBlock(uint16_t addr, const uint8_t *data, uint16_t len) {
  if (!apuBeginBlock(addr)) return false;
  for (uint16_t i = 0; i < len; i++) {
    if (!apuSendByte(data[i])) return false;
  }
  return true;
}

// 転送を終えて指定アドレスから実行させる
void apuJump(uint16_t addr) {
  writePort(2, addr & 0xFF);
  writePort(3, (addr >> 8) & 0xFF);
  writePort(1, 0x00);                    // ゼロ = 実行せよ
  writePort(0, (uint8_t)(readPort(0) + 2));
}

// ---------------- 転送する内容 ----------------

// BRRサンプル1ブロック($0300)。
// ヘッダ$03 = END|LOOP なので、無限にループして勝手にキーオフされない。
// データは全ゼロ(無音)だが、NONでノイズを有効にするので音はノイズになる。
const uint8_t BRR_SAMPLE[9] = {0x03, 0, 0, 0, 0, 0, 0, 0, 0};

// サンプルディレクトリ($0400)。エントリ0 = 開始$0300 / ループ$0300
const uint8_t SAMPLE_DIR[4] = {0x00, 0x03, 0x00, 0x03};

// DSPレジスタへ書く値の並び (レジスタ番号, 値)。
// SPC700に「mov $F2,#idx / mov $F3,#val」を実行させる形で書く。
const uint8_t DSP_SETUP[] = {
  0x6C, 0x3A,   // FLG:  soft reset解除/mute解除/エコー書き込み禁止/ノイズクロック$1A
  0x5D, 0x04,   // DIR:  サンプルディレクトリは$0400
  0x5C, 0x00,   // KOFF: キーオフ解除
  0x4D, 0x00,   // EON:  エコー無効
  0x2C, 0x00,   // EVOLL
  0x3C, 0x00,   // EVOLR
  0x7D, 0x00,   // EDL
  0x6D, 0xF0,   // ESA (エコー書き込み禁止中なので実害なし)
  0x0C, 0x60,   // MVOLL: マスター音量L
  0x1C, 0x60,   // MVOLR: マスター音量R
  0x00, 0x7F,   // V0 VOLL
  0x01, 0x7F,   // V0 VOLR
  0x02, 0x00,   // V0 PITCH L
  0x03, 0x10,   // V0 PITCH H (1.0倍)
  0x04, 0x00,   // V0 SRCN: サンプル番号0
  0x05, 0x00,   // V0 ADSR1: bit7=0 → GAIN直接モード
  0x07, 0x7F,   // V0 GAIN: 最大
  0x3D, 0x01,   // NON:  ボイス0をノイズ出力に
  0x4C, 0x01,   // KON:  ボイス0キーオン
};

// $0200に置く実行コードを組み立てる
uint16_t buildProgram(uint8_t *out) {
  uint16_t n = 0;
  out[n++] = 0x8F; out[n++] = 0x99; out[n++] = 0xF4;  // mov $F4,#$99 (実行開始マーカー)

  for (uint16_t i = 0; i < sizeof(DSP_SETUP); i += 2) {
    out[n++] = 0x8F; out[n++] = DSP_SETUP[i];     out[n++] = 0xF2;  // mov $F2,#idx
    out[n++] = 0x8F; out[n++] = DSP_SETUP[i + 1]; out[n++] = 0xF3;  // mov $F3,#val
  }

  out[n++] = 0x2F; out[n++] = 0xFE;  // bra 自分自身(ここで停止して鳴らし続ける)
  return n;
}

// ---------------- テスト本体 ----------------

// 文字列はすべてフラッシュに置く(NanoのRAMは2KBしかないため)
void ok(const __FlashStringHelper *msg) { Serial.print(F("  [OK] ")); Serial.println(msg); }
void ng(const __FlashStringHelper *msg) { Serial.print(F("  [NG] ")); Serial.println(msg); }

void runSelfTest() {
  Serial.println();
  Serial.println(F("=== SHVC-SOUND 自己診断 ==="));

  // --- テスト1: リセットしてIPL ROMが起動するか ---
  Serial.println(F("[1] リセットしてIPL ROMの起動を待つ..."));
  if (!apuReset()) {
    ng(F("port0/port1 が $AA/$BB になりません。"));
    Serial.print(F("       実際に読めた値: port0=$")); printHex(readPort(0));
    Serial.print(F(" port1=$"));                       printHex(readPort(1));
    Serial.println();
    Serial.println();
    Serial.println(F("  --- ここで止まる場合に疑う所 ---"));
    Serial.println(F("   $FF が読める → モジュールが応答していない。"));
    Serial.println(F("      ・VCC(18番)とVS(24番)の両方に+5Vが来ているか"));
    Serial.println(F("      ・GND(19番,23番)とNanoのGNDが繋がっているか"));
    Serial.println(F("      ・/CS(1番)=GND, CS(2番)=+5V になっているか"));
    Serial.println(F("      ・/RESET(15番)がNanoのA4に繋がっているか"));
    Serial.println(F("   $00 が読める → データバスがGNDに落ちている。D0-D7(7-14番)の配線を確認。"));
    Serial.println(F("   毎回違う値 → /RD(A3)か/WRの配線ミス、または結線が浮いている。"));
    return;
  }
  ok(F("IPL ROM 起動確認 (port0=$AA, port1=$BB)"));

  // --- テスト2: サンプルディレクトリを転送 (最初のブロック=$CCキック) ---
  Serial.println(F("[2] サンプルディレクトリを $0400 へ転送..."));
  if (!apuWriteBlock(0x0400, SAMPLE_DIR, sizeof(SAMPLE_DIR))) {
    ng(F("転送に失敗。最初のブロック($CCキック)が通っていません。"));
    Serial.print(F("       port0=$")); printHex(readPort(0)); Serial.println();
    return;
  }
  ok(F("ディレクトリ転送成功 → データバスの書き込みは正常"));

  // --- テスト3: 2ブロック目 (直前値+2 のキック) ---
  Serial.println(F("[3] BRRサンプルを $0300 へ転送 (2ブロック目)..."));
  if (!apuWriteBlock(0x0300, BRR_SAMPLE, sizeof(BRR_SAMPLE))) {
    ng(F("2ブロック目の転送に失敗。ブロック切り替えが通っていません。"));
    return;
  }
  ok(F("2ブロック目成功 → ブロック切り替えプロトコルは正常"));

  // --- テスト4: 実行コードを転送 ---
  Serial.println(F("[4] ノイズ再生コードを $0200 へ転送..."));
  uint8_t program[160];
  uint16_t progLen = buildProgram(program);
  if (!apuWriteBlock(0x0200, program, progLen)) {
    ng(F("実行コードの転送に失敗。"));
    return;
  }
  Serial.print(F("  [OK] ")); Serial.print(progLen); Serial.println(F(" バイト転送完了"));

  // --- テスト5: 実行 ---
  Serial.println(F("[5] $0200 から実行..."));
  apuJump(0x0200);
  delay(100);

  uint8_t marker = readPort(0);
  if (marker == 0x99) {
    ok(F("実行開始マーカー $99 を確認 → SPC700はコードを実行中"));
  } else {
    Serial.print(F("  [NG] マーカーが $99 ではなく $")); printHex(marker);
    Serial.println(F(" でした。ジャンプが失敗した可能性があります。"));
  }

  Serial.println();
  Serial.println(F("=== 転送は全部通りました ==="));
  Serial.println(F("この状態で「ザーッ」というノイズが鳴っていれば、ハードは全て正常です。"));
  Serial.println();
  Serial.println(F("  ここまで [OK] なのに音が出ない場合、原因は音声出力側だけです:"));
  Serial.println(F("   ・Audio-L(21番)/Audio-R(22番) から音を取れているか"));
  Serial.println(F("   ・DCカット用のコンデンサを挟んでいるか(直結は避ける)"));
  Serial.println(F("   ・/MUTE(20番)がHIGHになっているか(D10、または+5V直結)"));
  Serial.println(F("   ・アンプを繋いでいる場合は一旦外し、アンプ付きスピーカーで直接聴く"));
  Serial.println();
  Serial.println(F("  逆にノイズが鳴るなら、ハードは完動です。"));
  Serial.println(F("  音が出ない原因は spc_play.py 側にあります。"));
  Serial.println();
  Serial.println(F("(何かキーを送ると再実行します)"));
}

void setup() {
  Serial.begin(115200);
  while (!Serial) { /* USB接続待ち(Nanoでは即座に抜ける) */ }

  pinMode(PIN_A0, OUTPUT);
  pinMode(PIN_A1, OUTPUT);
  pinMode(PIN_WR, OUTPUT);
  pinMode(PIN_RD, OUTPUT);
  pinMode(PIN_RESET, OUTPUT);
  pinMode(PIN_MUTE, OUTPUT);

  digitalWrite(PIN_WR, HIGH);
  digitalWrite(PIN_RD, HIGH);
  digitalWrite(PIN_RESET, HIGH);
  digitalWrite(PIN_MUTE, HIGH);   // /MUTE解除
  setDataBusInput();

  delay(500);
  runSelfTest();
}

void loop() {
  if (Serial.available()) {
    while (Serial.available()) Serial.read();
    runSelfTest();
  }
}
