// midi_parser.h - バイト列からMIDIメッセージを組み立てる(ランニングステータス対応)と、BLE MIDIパケットの分解
#pragma once
#include <Arduino.h>

// 完成したメッセージを受け取る関数
using MidiHandler = void (*)(uint8_t status, uint8_t d1, uint8_t d2);

class MidiStream {
   public:
    explicit MidiStream(MidiHandler h) : handler(h) {}

    void feed(uint8_t b) {
        if (b >= 0xF8) return;               // リアルタイムメッセージ(クロック等)は無視。途中に挟まっても状態は保つ
        if (b & 0x80) {
            if (b == 0xF0) { inSysex = true; status = 0; return; }
            if (b == 0xF7) { inSysex = false; return; }
            inSysex = false;
            if (b >= 0xF0) { status = 0; return; }   // その他のシステムコモンは使わない
            status = b;
            count = 0;
            expected = dataLength(b);
            return;
        }
        if (inSysex || status == 0) return;
        data[count++] = b;
        if (count >= expected) {
            handler(status, data[0], expected > 1 ? data[1] : 0);
            count = 0;                        // ランニングステータス: 次のデータバイトは同じステータスで続く
        }
    }

    bool betweenMessages() const { return count == 0 && !inSysex; }
    bool sysex() const { return inSysex; }

   private:
    static uint8_t dataLength(uint8_t status) {
        uint8_t t = status & 0xF0;
        return (t == 0xC0 || t == 0xD0) ? 1 : 2;
    }
    MidiHandler handler;
    uint8_t status = 0;
    uint8_t data[2] = {0, 0};
    uint8_t count = 0;
    uint8_t expected = 2;
    bool inSysex = false;
};

// BLE MIDI のパケット: [ヘッダ(bit7=1)] [タイムスタンプ(bit7=1)] [ステータス] [データ...] ...
// タイムスタンプはメッセージの切れ目にだけ現れる。ランニングステータスのときは
// 「タイムスタンプ + データ」または「データだけ」が続くことがある。
inline void parseBleMidiPacket(const uint8_t *p, size_t len, MidiStream &stream) {
    if (len < 2 || !(p[0] & 0x80)) return;
    bool expectTimestamp = true;
    for (size_t i = 1; i < len; i++) {
        uint8_t b = p[i];
        if (b & 0x80) {
            if (stream.sysex()) {
                // SysEx 中の bit7=1 はタイムスタンプか終端(F7)。終端の直前には必ずタイムスタンプが来る
                if (b == 0xF7) {
                    stream.feed(b);
                    expectTimestamp = true;
                }
                continue;
            }
            if (expectTimestamp && stream.betweenMessages()) {
                expectTimestamp = false;      // タイムスタンプ(音の出るタイミングは受信した瞬間で扱う)
                continue;
            }
            stream.feed(b);                   // ステータス
            // データを持たないメッセージ(リアルタイム系など)の後には、次のタイムスタンプが来る
            expectTimestamp = (b >= 0xF4 && b != 0xF0);
        } else {
            stream.feed(b);
            if (stream.betweenMessages()) expectTimestamp = true;
        }
    }
}
