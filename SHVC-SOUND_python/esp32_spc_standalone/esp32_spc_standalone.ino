// ESP32 r0.4: boot a locally supplied SPC from flash, without a PC.
#include <Arduino.h>
#include "spc_bus.h"
#include "spc_data.h"

static bool playing = false;
static uint32_t retryAt = 0;

bool upload(uint16_t addr, const uint8_t *data, size_t length, bool first) {
  spc::writePort(2, addr & 255);
  spc::writePort(3, addr >> 8);
  spc::writePort(1, 1);
  uint8_t kick = first ? 0xCC : (uint8_t)(spc::readPort(0) + 2);
  if (!first && !kick) kick = 1;
  spc::writePort(0, kick);
  if (!spc::waitForPort(0, kick, 1000)) {
    Serial.printf("ERROR start $%04X expected=%02X actual=%02X\n",addr,kick,spc::readPort(0));
    return false;
  }
  for (size_t i = 0; i < length; i++) {
    uint8_t index = (uint8_t)i;
    spc::writePort(1, data[i]);
    spc::writePort(0, index);
    if (!spc::waitForPort(0, index, 200)) {
      Serial.printf("ERROR data $%04X offset=%u expected=%02X actual=%02X\n",addr,(unsigned)i,index,spc::readPort(0));
      return false;
    }
    if ((i & 63) == 63) delay(1); // service ESP32 watchdog during long uploads
    if ((i & 4095) == 4095) Serial.printf("RAM %u/%u\n",(unsigned)(i+1),(unsigned)length);
  }
  Serial.printf("ACK $%04X %u bytes\n",addr,(unsigned)length);
  return true;
}

bool startSong() {
  spc::setMute(true);
  ledcWrite(33, 0); // verified setup uses the amplifier bypass / J5 line out
  Serial.printf("START %s\n",SPC_TITLE);
  if (!spc::reset()) { Serial.println("ERROR IPL not ready"); return false; }
  Serial.println("IPL AA BB");
  if (!upload(0x0002,SPC_RAM+2,0x00F0-2,true) ||
      !upload(0x0100,SPC_RAM+0x0100,0xFFC0-0x0100,false) ||
      !upload(STUB_ADDRESS,RESTORE_STUB,sizeof(RESTORE_STUB),false)) return false;
  spc::jumpTo(STUB_ADDRESS);
  uint8_t marker = spc::readPort(0);
  if (marker != 0x99 && marker != 0x98) {
    Serial.printf("ERROR restore marker=%02X\n",marker);
    return false;
  }
  for (uint8_t p = 1; p < 4; p++) spc::writePort(p,FINAL_PORTS[p]);
  spc::writePort(0,START_SIGNAL);
  if (!spc::waitForPort(0,0x98,2000)) { Serial.println("ERROR restore handshake"); return false; }
  spc::writePort(0,FINAL_PORTS[0]);
  spc::setMute(false);
  Serial.printf("PLAYING %s (native SPC loop, no host fade)\n",SPC_TITLE);
  return true;
}

void setup() {
  Serial.begin(115200);
  spc::begin();
  ledcAttach(33,20000,8);
  ledcWrite(33,0);
  delay(500);
  playing = startSong();
  if (!playing) { spc::setMute(true); retryAt = millis(); }
}
void loop() {
  // Music runs on SPC700 independently. Keep power on, no USB host required.
  if (!playing && (uint32_t)(millis()-retryAt) >= 5000) {
    playing = startSong();
    if (!playing) { spc::setMute(true); retryAt = millis(); }
  }
  delay(20);
}
