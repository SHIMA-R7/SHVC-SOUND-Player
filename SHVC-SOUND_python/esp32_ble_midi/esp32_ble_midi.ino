/*
 * esp32_ble_midi.ino - BLE MIDI で SHVC-SOUND をリアルタイム演奏する(ESP32 DevKit V1 / SHVC-SOUND-ESP32 r0.4 基板)
 *
 * ■ できること
 *   ・BLE MIDI 鍵盤に自分から接続する(セントラル)。MIDIサービスを広告している機器を見つけ次第つなぐ
 *   ・スマホ/PCのアプリから "SHVC-SOUND" に接続してもらう(ペリフェラル)
 *   ・USBシリアル(115200bps)に生のMIDIバイトを流しても鳴る(tools/serial_midi.py でテスト用)
 *   受けたMIDIは synth.h で8ボイスに割り当て、SHVC-SOUND の S-DSP をその場で鳴らす。
 *   音色は midi2spc と同じ(tools/export_esp32_bank.py で bank_data.h を作る)。
 *
 * ■ 起動の流れ
 *   1. 両方のバッファを切り離し、MUTE=L(消音)で起動
 *   2. SHVC-SOUND をリセット → 音色(BRR)・ディレクトリ・常駐ドライバを転送 → DSP初期化 → MUTE=H
 *   3. SHVC-SOUND が見つからないときは「ドライラン」: DSPへの書き込み内容をシリアルに表示する
 *      (基板が無くても、素の DevKit で BLE 接続と発音ロジックを確かめられる)
 *
 * ■ 特別なMIDI(チャンネル16)
 *   CC7  : アンプ(TDA7053A)の音量。PWM(GPIO33)のデューティになる
 *   CC119: 127でシリアルへの発音ログ ON、0で OFF
 *
 * ■ ビルド
 *   arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 esp32_ble_midi
 *   (BLEを使うためプログラムが大きい。入らない場合は --build-property build.partitions=huge_app)
 */
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>

#include "bank_data.h"
#include "midi_parser.h"
#include "spc_bus.h"
#include "synth.h"

static const char *DEVICE_NAME = "SHVC-SOUND";
static BLEUUID MIDI_SERVICE_UUID("03b80e5a-ede8-4b33-a751-6ce34ec4c700");
static BLEUUID MIDI_CHAR_UUID("7772e5db-3868-4112-a1a9-f2669d106bf3");

const uint8_t PIN_LED = 2;          // DevKit のオンボードLED: BLEでつながっている間点灯
const uint8_t PIN_AMP_VOLUME = 33;  // TDA7053A の音量(PWM → RC平滑)
const uint32_t AMP_PWM_HZ = 20000;
static uint8_t ampVolume = 180;     // 0-255

// ---- BLE側(BLEタスク)→ loop() へメッセージを渡すキュー。バス操作は loop() だけで行う ----
struct Msg {
    uint8_t status, d1, d2;
};
static QueueHandle_t midiQueue;

static void enqueueMessage(uint8_t status, uint8_t d1, uint8_t d2) {
    Msg m{status, d1, d2};
    xQueueSend(midiQueue, &m, 0);   // あふれたら捨てる(演奏が詰まるよりまし)
}
static MidiStream bleStream(enqueueMessage);   // BLEパケットの組み立て(BLEタスクからだけ触る)

static void handleNow(uint8_t status, uint8_t d1, uint8_t d2);
static MidiStream serialStream(handleNow);     // USBシリアルからの生MIDI(loop からだけ触る)

static volatile bool allOffRequest = false;
static volatile int appConnections = 0;       // アプリ(ペリフェラルとして受けた接続)の数
static volatile bool keyboardConnected = false;

// ---- ペリフェラル: アプリから接続してもらう ----
class ServerCallbacks : public BLEServerCallbacks {
    void onConnect(BLEServer *server, esp_ble_gatts_cb_param_t *param) override {
        appConnections = appConnections + 1;
        // 接続間隔を短く(7.5-15ms)して遅れを減らす
        server->requestConnParams(param->connect.remote_bda, 0x06, 0x0C, 0, 400);
        BLEDevice::startAdvertising();   // 複数台から同時につなげるように広告を続ける
    }
    void onDisconnect(BLEServer *) override {
        if (appConnections > 0) appConnections = appConnections - 1;
        allOffRequest = true;
        BLEDevice::startAdvertising();
    }
};

class MidiCharCallbacks : public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *c) override {
        String v = c->getValue();
        parseBleMidiPacket((const uint8_t *)v.c_str(), v.length(), bleStream);
    }
};

// ---- セントラル: BLE MIDI 鍵盤を探して自分から接続する ----
static BLEAdvertisedDevice *keyboardCandidate = nullptr;
static volatile bool connectRequest = false;
static volatile bool scanning = false;
static BLEClient *keyboardClient = nullptr;
static uint32_t nextScanMs = 0;

class ScanCallbacks : public BLEAdvertisedDeviceCallbacks {
    void onResult(BLEAdvertisedDevice dev) override {
        if (connectRequest || keyboardClient) return;
        if (dev.haveServiceUUID() && dev.isAdvertisingService(MIDI_SERVICE_UUID)) {
            Serial.printf("BLE MIDI 機器を発見: %s (%s)\n", dev.getName().c_str(), dev.getAddress().toString().c_str());
            BLEDevice::getScan()->stop();
            delete keyboardCandidate;
            keyboardCandidate = new BLEAdvertisedDevice(dev);
            connectRequest = true;
        }
    }
};

static void scanComplete(BLEScanResults) { scanning = false; }

class ClientCallbacks : public BLEClientCallbacks {
    void onConnect(BLEClient *) override {}
    void onDisconnect(BLEClient *) override {
        if (keyboardConnected) Serial.println("鍵盤との接続が切れました。探し直します");
        keyboardConnected = false;
        allOffRequest = true;
        keyboardClient = nullptr;   // 実体の解放は loop 側で行わない(Bluedroid がまだ使っている場合がある)
        nextScanMs = millis() + 2000;
    }
};

static void keyboardNotify(BLERemoteCharacteristic *, uint8_t *data, size_t length, bool) {
    parseBleMidiPacket(data, length, bleStream);
}

static void connectToKeyboard() {
    connectRequest = false;
    if (!keyboardCandidate) return;
    BLEClient *client = BLEDevice::createClient();
    client->setClientCallbacks(new ClientCallbacks());
    Serial.println("鍵盤に接続中...");
    if (!client->connect(keyboardCandidate)) {
        Serial.println("接続できませんでした");
        nextScanMs = millis() + 3000;
        return;
    }
    BLERemoteService *svc = client->getService(MIDI_SERVICE_UUID);
    BLERemoteCharacteristic *ch = svc ? svc->getCharacteristic(MIDI_CHAR_UUID) : nullptr;
    if (!ch || !ch->canNotify()) {
        Serial.println("MIDIの受信口が見つかりません。切断します");
        client->disconnect();
        return;
    }
    ch->registerForNotify(keyboardNotify);
    keyboardClient = client;
    keyboardConnected = true;
    Serial.println("鍵盤とつながりました。弾けます");
}

static void startScan() {
    if (scanning || keyboardClient || connectRequest) return;
    BLEScan *scan = BLEDevice::getScan();
    scanning = true;
    scan->start(5, scanComplete, false);   // 5秒探して、見つからなければ loop が少し置いてまた探す
}

// ---- SHVC-SOUND の立ち上げ ----
static bool bringUpSpc() {
    spc::setMute(true);
    spc::dryRun = false;
    if (!spc::reset()) return false;
    if (!spc::uploadBlock(SPC_DIR_ADDR, SPC_DIR, sizeof(SPC_DIR), true)) return false;
    if (!spc::uploadBlock(SPC_SAMPLE_ADDR, SPC_BRR, sizeof(SPC_BRR), false)) return false;
    if (!spc::uploadBlock(SPC_DRIVER_ADDR, SPC_DRIVER, sizeof(SPC_DRIVER), false)) return false;
    spc::jumpTo(SPC_DRIVER_ADDR);
    synth::driverError = false;
    synth::initDsp();
    if (synth::driverError) return false;
    spc::setMute(false);
    return true;
}

static void setAmpVolume(uint8_t v) {
    ampVolume = v;
    ledcWrite(PIN_AMP_VOLUME, ampVolume);
}

static void handleNow(uint8_t status, uint8_t d1, uint8_t d2) {
    if ((status & 0xF0) == 0xB0 && (status & 0x0F) == 15) {   // チャンネル16は本機の設定用
        if (d1 == 7) {
            setAmpVolume((uint8_t)min(255, d2 * 2 + (d2 >> 6)));
            return;
        }
        if (d1 == 119) {
            synth::verbose = d2 >= 64;
            return;
        }
    }
    synth::handleMessage(status, d1, d2);
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\nSHVC-SOUND BLE MIDI");

    pinMode(PIN_LED, OUTPUT);
    digitalWrite(PIN_LED, LOW);
    ledcAttach(PIN_AMP_VOLUME, AMP_PWM_HZ, 8);
    setAmpVolume(ampVolume);

    midiQueue = xQueueCreate(256, sizeof(Msg));
    spc::begin();

    Serial.print("SHVC-SOUND を初期化中... ");
    uint32_t t0 = millis();
    if (bringUpSpc()) {
        Serial.printf("OK (%lu ms)\n", (unsigned long)(millis() - t0));
    } else {
        Serial.println("見つかりません → ドライラン(DSPへの書き込みをここに表示します)");
        spc::setMute(true);
        spc::dryRun = true;
        synth::verbose = true;
        synth::initDsp();
    }

    BLEDevice::init(DEVICE_NAME);
    BLEServer *server = BLEDevice::createServer();
    server->setCallbacks(new ServerCallbacks());
    BLEService *service = server->createService(MIDI_SERVICE_UUID);
    BLECharacteristic *ch = service->createCharacteristic(
        MIDI_CHAR_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_WRITE_NR |
                            BLECharacteristic::PROPERTY_NOTIFY);
    ch->setCallbacks(new MidiCharCallbacks());
    ch->addDescriptor(new BLE2902());
    service->start();
    BLEAdvertising *adv = BLEDevice::getAdvertising();
    adv->addServiceUUID(MIDI_SERVICE_UUID);
    adv->setScanResponse(true);
    BLEDevice::startAdvertising();

    BLEScan *scan = BLEDevice::getScan();
    scan->setAdvertisedDeviceCallbacks(new ScanCallbacks());
    scan->setActiveScan(true);
    scan->setInterval(100);
    scan->setWindow(99);
    Serial.printf("BLE: \"%s\" として待ち受け中。BLE MIDI 鍵盤も自動で探します\n", DEVICE_NAME);
}

void loop() {
    // BLEから届いたメッセージを鳴らす
    Msg m;
    while (xQueueReceive(midiQueue, &m, 0) == pdTRUE) handleNow(m.status, m.d1, m.d2);

    // USBシリアルからの生MIDI
    while (Serial.available() > 0) serialStream.feed((uint8_t)Serial.read());

    if (allOffRequest) {
        allOffRequest = false;
        synth::allNotesOff(-1);
    }

    // 常駐ドライバの応答が途絶えた(接触不良・電源瞬断など)ら、転送からやり直す
    if (synth::driverError && !spc::dryRun) {
        Serial.println("SHVC-SOUND の応答がありません。初期化し直します");
        spc::setMute(true);
        delay(200);
        if (bringUpSpc()) Serial.println("復帰しました");
        else delay(2000);
    }

    // 鍵盤の自動接続
    if (connectRequest) connectToKeyboard();
    if (!keyboardClient && !connectRequest && !scanning && millis() >= nextScanMs) {
        startScan();
        nextScanMs = millis() + 6000;
    }

    digitalWrite(PIN_LED, (appConnections > 0 || keyboardConnected) ? HIGH : LOW);
    delay(1);
}
