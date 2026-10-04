#pragma once
#include <stddef.h>
#include <stdint.h>

// HSP1 restore code emits MOV $F2,#register / MOV $F3,#value pairs.
// Change only its initial volume writes; never patch the song's running code.
inline bool spcVolumePair(const uint8_t *p) {
  return p[0]==0x8F && p[2]==0xF2 && p[3]==0x8F && p[5]==0xF3 && p[1]<128;
}
inline bool spcVolumeRegister(uint8_t reg) {
  return reg==0x0C || reg==0x1C || reg==0x2C || reg==0x3C;
}
constexpr uint8_t spcScaleVolume(uint8_t raw,uint16_t gain) {
  int value=raw<128?raw:int(raw)-256;
  int scaled=(value*int(gain)+(value<0?-128:128))/256;
  if(scaled>127) scaled=127;
  if(scaled<-128) scaled=-128;
  return uint8_t(scaled);
}
static_assert(spcScaleVolume(64,128)==32,"half gain");
static_assert(spcScaleVolume(192,128)==224,"negative phase preserved");
static_assert(spcScaleVolume(64,1024)==127,"positive saturation");
static_assert(spcScaleVolume(192,1024)==128,"negative saturation");
static_assert(spcScaleVolume(128,256)==128,"negative full scale unity");
static_assert(spcScaleVolume(127,0)==0,"zero gain");
inline bool applySpcGain(uint8_t *stub,size_t length,uint16_t gain) {
  if(gain>1024) return false;
  if(gain==256) return true; // Original code, including unknown custom HSP1 stubs.
  bool seen[128]={}; unsigned count=0;
  for(size_t i=0;i+6<=length;i++) if(spcVolumePair(stub+i)) {
    if(!seen[stub[i+1]]) { seen[stub[i+1]]=true; count++; }
    i+=5;
  }
  // Require a complete DSP initializer, not an incidental instruction pattern.
  if(count<124 || !seen[0x0C] || !seen[0x1C]) return false;
  for(size_t i=0;i+6<=length;i++) if(spcVolumePair(stub+i)) {
    if(spcVolumeRegister(stub[i+1])) stub[i+4]=spcScaleVolume(stub[i+4],gain);
    i+=5;
  }
  return true;
}
