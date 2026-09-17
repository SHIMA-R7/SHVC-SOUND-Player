// synth.h - MIDIメッセージを受けて S-DSP の8ボイスをその場で鳴らす
//
// midi2spc/engine.py の Sequencer(曲ファイル向け)を、演奏向けに1メッセージずつ即時処理する形へ移したもの。
// 音色の割り当て(GM/ドラム)・ベロシティ/CC7/CC11/パン・サステインペダル・ピッチベンドの扱いは同じ。
#pragma once
#include <Arduino.h>
#include <math.h>
#include "bank_data.h"
#include "spc_bus.h"

namespace synth {

const uint8_t NUM_VOICES = 8;
const uint8_t DRUM_CHANNEL = 9;   // MIDIチャンネル10
const uint16_t PITCH_MAX = 16383;
const uint16_t PITCH_UNITY = 4096;

// DSPレジスタ
const uint8_t V_VOLL = 0, V_VOLR = 1, V_PITCHL = 2, V_PITCHH = 3, V_SRCN = 4, V_ADSR1 = 5, V_ADSR2 = 6;
const uint8_t DSP_MVOLL = 0x0C, DSP_MVOLR = 0x1C, DSP_EVOLL = 0x2C, DSP_EVOLR = 0x3C;
const uint8_t DSP_KON = 0x4C, DSP_KOF = 0x5C, DSP_FLG = 0x6C;
const uint8_t DSP_EFB = 0x0D, DSP_PMON = 0x2D, DSP_NON = 0x3D, DSP_EON = 0x4D;
const uint8_t DSP_DIR = 0x5D, DSP_ESA = 0x6D, DSP_EDL = 0x7D;

// KON/KOF を書いてから 0 に戻すまでの待ち。S-DSP は2サンプル(約63µs)ごとにしか見ないので、
// それより早く戻すとキーオン/キーオフを取りこぼす
const uint32_t KEY_LATCH_US = 150;

struct Channel {
    uint8_t program = 0;
    uint8_t volume = 100;      // CC7
    uint8_t expression = 127;  // CC11
    uint8_t pan = 64;          // CC10
    int16_t bend = 0;          // -8192..8191
    float bendRange = 2.0f;    // 半音
    bool sustain = false;      // CC64
    bool drum = false;
};

struct Voice {
    bool active = false;
    int8_t channel = -1;
    uint8_t note = 0;
    uint8_t velocity = 0;
    uint8_t inst = 0;
    bool heldByPedal = false;
    uint32_t startMs = 0;
    uint32_t order = 0;        // 鳴り始めた順番(同じミリ秒でも区別するため)
    uint16_t lastPitch = 0;
    int8_t lastVolL = 0, lastVolR = 0;
};

static Channel channels[16];
static Voice voices[NUM_VOICES];
static float masterVolume = 0.7f;   // 同時発音で飽和しないよう全体を絞る(engine.py の既定は曲向けに0.55)
static uint32_t noteCounter = 0;
static bool verbose = false;        // ドライラン時などにシリアルへ発音の様子を出す
static bool driverError = false;

inline uint8_t reg(uint8_t voice, uint8_t offset) { return (voice << 4) | offset; }

inline void write(uint8_t r, uint8_t v) {
    if (!spc::dspWrite(r, v)) driverError = true;
}

inline void resetChannels() {
    for (uint8_t c = 0; c < 16; c++) {
        channels[c] = Channel();
        channels[c].drum = (c == DRUM_CHANNEL);
    }
}

// 演奏前に一度だけ書く初期設定(midi2spc/hardware.py の initial_dsp_writes と同じ)
inline void initDsp() {
    write(DSP_FLG, 0x20);      // ミュート解除・リセット解除・エコー書き込み禁止(BRRを壊さないため)
    write(DSP_KOF, 0xFF);
    delayMicroseconds(KEY_LATCH_US);
    write(DSP_KOF, 0x00);
    write(DSP_KON, 0x00);
    write(DSP_MVOLL, 0x7F);
    write(DSP_MVOLR, 0x7F);
    write(DSP_EVOLL, 0x00);
    write(DSP_EVOLR, 0x00);
    write(DSP_EFB, 0x00);
    write(DSP_PMON, 0x00);
    write(DSP_NON, 0x00);
    write(DSP_EON, 0x00);
    write(DSP_DIR, SPC_DIR_ADDR >> 8);
    write(DSP_ESA, 0xFF);
    write(DSP_EDL, 0x00);
    for (uint8_t i = 0; i < 8; i++) write((i << 4) | 0x0F, 0x00);   // エコーFIR係数
    for (uint8_t v = 0; v < NUM_VOICES; v++) {
        write(reg(v, V_VOLL), 0);
        write(reg(v, V_VOLR), 0);
        voices[v] = Voice();
    }
    resetChannels();
}

inline float noteToHz(float note) { return 440.0f * powf(2.0f, (note - 69.0f) / 12.0f); }

inline uint16_t pitchRegister(float hz, float naturalHz) {
    long v = lroundf(PITCH_UNITY * hz / naturalHz);
    if (v < 1) v = 1;
    if (v > PITCH_MAX) v = PITCH_MAX;
    return (uint16_t)v;
}

inline void volumePair(uint8_t velocity, const Channel &ch, int8_t &l, int8_t &r) {
    float amp = (velocity / 127.0f) * (ch.volume / 127.0f) * (ch.expression / 127.0f) * masterVolume;
    amp = constrain(amp, 0.0f, 1.0f);
    float pan = constrain(ch.pan, 0, 127) / 127.0f;       // 等パワーパン
    l = (int8_t)constrain(lroundf(127 * amp * sqrtf(1.0f - pan)), -128, 127);
    r = (int8_t)constrain(lroundf(127 * amp * sqrtf(pan)), -128, 127);
}

inline void keyOffVoice(uint8_t v) {
    write(DSP_KOF, 1 << v);
    delayMicroseconds(KEY_LATCH_US);
    write(DSP_KOF, 0x00);
    voices[v].active = false;
}

// 空きボイスを探す。全部鳴っていたら一番古く鳴り始めたものを止めて使う
inline uint8_t allocate() {
    for (uint8_t v = 0; v < NUM_VOICES; v++)
        if (!voices[v].active) return v;
    uint8_t oldest = 0;
    for (uint8_t v = 1; v < NUM_VOICES; v++)
        if (voices[v].order < voices[oldest].order) oldest = v;
    keyOffVoice(oldest);
    return oldest;
}

inline int findVoice(uint8_t channel, uint8_t note) {
    for (uint8_t v = 0; v < NUM_VOICES; v++)
        if (voices[v].active && voices[v].channel == channel && voices[v].note == note) return v;
    return -1;
}

inline void noteOff(uint8_t channel, uint8_t note) {
    int v = findVoice(channel, note);
    if (v < 0) return;
    if (channels[channel].sustain) {
        voices[v].heldByPedal = true;   // ペダル中は離鍵しても鳴らし続ける
        return;
    }
    keyOffVoice(v);
}

inline void noteOn(uint8_t channel, uint8_t note, uint8_t velocity) {
    if (velocity == 0) {
        noteOff(channel, note);
        return;
    }
    Channel &ch = channels[channel];
    uint8_t instIndex;
    float baseHz;
    if (ch.drum) {
        instIndex = DRUM_NOTE_TO_INST[note & 0x7F];
        const InstrumentDef &inst = INSTRUMENTS[instIndex];
        // 打楽器はサンプルそのままの速さ。タムだけノート番号で音程を変える
        baseHz = (instIndex == TOM_INST) ? inst.naturalHz * powf(2.0f, (note - 45) / 24.0f) : inst.naturalHz;
    } else {
        instIndex = GM_PROGRAM_TO_INST[ch.program & 0x7F];
        baseHz = noteToHz(note + (ch.bend / 8192.0f) * ch.bendRange);
    }
    const InstrumentDef &inst = INSTRUMENTS[instIndex];

    int existing = findVoice(channel, note);
    if (existing >= 0) keyOffVoice(existing);
    uint8_t v = allocate();

    uint16_t pitch = pitchRegister(baseHz, inst.naturalHz);
    int8_t vl, vr;
    volumePair(velocity, ch, vl, vr);

    // 念のため一度切ってから鳴らし直す(直前まで別の音が鳴っていたボイスでも確実に立ち上がる)
    write(DSP_KOF, 1 << v);
    delayMicroseconds(KEY_LATCH_US);
    write(DSP_KOF, 0x00);
    write(reg(v, V_SRCN), inst.srcn);
    write(reg(v, V_ADSR1), inst.adsr1);
    write(reg(v, V_ADSR2), inst.adsr2);
    write(reg(v, V_PITCHL), pitch & 0xFF);
    write(reg(v, V_PITCHH), (pitch >> 8) & 0x3F);
    write(reg(v, V_VOLL), (uint8_t)vl);
    write(reg(v, V_VOLR), (uint8_t)vr);
    write(DSP_KON, 1 << v);
    delayMicroseconds(KEY_LATCH_US);
    write(DSP_KON, 0x00);

    Voice &vs = voices[v];
    vs.active = true;
    vs.channel = channel;
    vs.note = note;
    vs.velocity = velocity;
    vs.inst = instIndex;
    vs.heldByPedal = false;
    vs.startMs = millis();
    vs.order = ++noteCounter;
    vs.lastPitch = pitch;
    vs.lastVolL = vl;
    vs.lastVolR = vr;
    if (verbose)
        Serial.printf("ON  ch%d note%d vel%d -> voice%d %s pitch=%u vol=%d/%d\n", channel + 1, note, velocity, v,
                      inst.name, pitch, vl, vr);
}

inline void refreshVolumes(uint8_t channel) {
    Channel &ch = channels[channel];
    for (uint8_t v = 0; v < NUM_VOICES; v++) {
        Voice &vs = voices[v];
        if (!vs.active || vs.channel != channel) continue;
        int8_t l, r;
        volumePair(vs.velocity, ch, l, r);
        if (l != vs.lastVolL || r != vs.lastVolR) {
            write(reg(v, V_VOLL), (uint8_t)l);
            write(reg(v, V_VOLR), (uint8_t)r);
            vs.lastVolL = l;
            vs.lastVolR = r;
        }
    }
}

inline void allNotesOff(int channel) {   // channel<0 なら全チャンネル
    for (uint8_t v = 0; v < NUM_VOICES; v++)
        if (voices[v].active && (channel < 0 || voices[v].channel == channel)) keyOffVoice(v);
}

inline void controlChange(uint8_t channel, uint8_t controller, uint8_t value) {
    Channel &ch = channels[channel];
    switch (controller) {
        case 0:   // バンクセレクトMSB。127 は XG/GS のドラムキット
            if (value == 127) ch.drum = true;
            else if (channel != DRUM_CHANNEL) ch.drum = false;
            break;
        case 7:
            ch.volume = value;
            refreshVolumes(channel);
            break;
        case 10:
            ch.pan = value;
            refreshVolumes(channel);
            break;
        case 11:
            ch.expression = value;
            refreshVolumes(channel);
            break;
        case 64: {
            bool was = ch.sustain;
            ch.sustain = value >= 64;
            if (was && !ch.sustain) {   // ペダルを離したら保留していた音を止める
                for (uint8_t v = 0; v < NUM_VOICES; v++)
                    if (voices[v].active && voices[v].channel == channel && voices[v].heldByPedal) keyOffVoice(v);
            }
            break;
        }
        case 120:   // All Sound Off
        case 123:   // All Notes Off
            allNotesOff(channel);
            break;
        case 121:   // Reset All Controllers
            ch.volume = 100;
            ch.expression = 127;
            ch.pan = 64;
            ch.bend = 0;
            ch.sustain = false;
            refreshVolumes(channel);
            break;
    }
}

inline void programChange(uint8_t channel, uint8_t program) {
    channels[channel].program = program & 0x7F;
    if (verbose) Serial.printf("PROG ch%d -> %d (%s)\n", channel + 1, program, INSTRUMENTS[GM_PROGRAM_TO_INST[program & 0x7F]].name);
}

inline void pitchBend(uint8_t channel, int16_t value) {
    Channel &ch = channels[channel];
    ch.bend = value;
    if (ch.drum) return;
    float semis = (value / 8192.0f) * ch.bendRange;
    for (uint8_t v = 0; v < NUM_VOICES; v++) {
        Voice &vs = voices[v];
        if (!vs.active || vs.channel != channel) continue;
        uint16_t pitch = pitchRegister(noteToHz(vs.note + semis), INSTRUMENTS[vs.inst].naturalHz);
        if (pitch != vs.lastPitch) {
            write(reg(v, V_PITCHL), pitch & 0xFF);
            write(reg(v, V_PITCHH), (pitch >> 8) & 0x3F);
            vs.lastPitch = pitch;
        }
    }
}

// 完成した MIDI メッセージ(ステータス + データ最大2バイト)を処理する
inline void handleMessage(uint8_t status, uint8_t d1, uint8_t d2) {
    uint8_t type = status & 0xF0;
    uint8_t channel = status & 0x0F;
    switch (type) {
        case 0x80: noteOff(channel, d1); break;
        case 0x90: noteOn(channel, d1, d2); break;
        case 0xB0: controlChange(channel, d1, d2); break;
        case 0xC0: programChange(channel, d1); break;
        case 0xE0: pitchBend(channel, (int16_t)(((uint16_t)d2 << 7) | d1) - 8192); break;
        default: break;   // ポリフォニックキープレッシャー・チャンネルプレッシャーは使わない
    }
}

}  // namespace synth
