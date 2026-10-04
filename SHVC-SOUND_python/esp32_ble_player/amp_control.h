#pragma once
#include <stdint.h>

// Profile 0: jack/external amp. 1: rev0.4 TDA7053A DC volume. 2: fixed-gain amp.
// Only profile 1 drives the verified GPIO33 -> R6/R5/C5 -> U6 pins 2 and 8.
struct AmpControl {
  uint8_t profile=0,level=160;
  bool fading=false,faded=false;
  uint32_t started=0,duration=0;
  constexpr void reset() { fading=false; faded=false; }
  constexpr bool fade(uint32_t now,uint32_t ms) {
    if(profile!=1 || !ms || ms>60000) return false;
    started=now; duration=ms; fading=true; faded=false; return true;
  }
  constexpr uint32_t remaining(uint32_t now) const {
    if(!fading) return 0;
    uint32_t elapsed=now-started;
    return elapsed>=duration?0:duration-elapsed;
  }
  constexpr uint8_t duty(uint32_t now,bool audible) {
    if(profile!=1 || !audible) return 0;
    if(fading) {
      uint32_t left=remaining(now);
      if(!left) { fading=false; faded=true; return 0; }
      return uint32_t(level)*left/duration;
    }
    return faded?0:level;
  }
  constexpr uint16_t state() const {
    return uint16_t(level)|(uint16_t(profile)<<8)|(uint16_t(fading)<<10)|(uint16_t(faded)<<11);
  }
};

// Compile-time regression: disabled output, muted output, and millis() rollover.
constexpr bool ampControlTimingCheck() {
  AmpControl a;
  if(a.duty(0,true)!=0 || a.fade(0,1000)) return false;
  a.profile=1;
  if(a.duty(0,false)!=0 || a.duty(0,true)!=160) return false;
  if(!a.fade(0xFFFFFFF0u,1000)) return false;
  if(a.duty(0x000001E4u,true)!=80) return false; // 500 ms after rollover.
  if(a.duty(0x000003D8u,true)!=0 || a.fading || !a.faded) return false;
  a.reset(); if(a.duty(2000,true)!=160) return false;
  a.profile=2; return a.duty(2000,true)==0 && !a.fade(2000,1000);
}
static_assert(ampControlTimingCheck(),"Amplifier envelope regression");
