// Compile-only tests: evaluate the actual header's helpers at compile time.
// All helpers are pure; constexpr adds evaluation without changing their bodies.
#include <stddef.h>
#include <stdint.h>
#define inline constexpr
#include "../esp32_ble_player/spc_volume.h"
#undef inline

constexpr bool initializerChecks() {
  uint8_t stub[128*6]={};
  for(unsigned r=0;r<128;r++) {
    size_t p=r*6;
    stub[p]=0x8F; stub[p+1]=r; stub[p+2]=0xF2;
    stub[p+3]=0x8F; stub[p+4]=64; stub[p+5]=0xF3;
  }
  stub[0x1C*6+4]=192; // right master -64: retain the intended inversion
  stub[0x2C*6+4]=32; stub[0x3C*6+4]=224;
  if(!applySpcGain(stub,sizeof(stub),128)) return false;
  if(stub[0x0C*6+4]!=32 || stub[0x1C*6+4]!=224 ||
     stub[0x2C*6+4]!=16 || stub[0x3C*6+4]!=240) return false;
  // Preserve every voice, pitch, envelope, control and other DSP write.
  for(unsigned r=0;r<128;r++)
    if(!spcVolumeRegister(r) && stub[r*6+4]!=64) return false;
  if(!applySpcGain(stub,sizeof(stub),1024)) return false;
  if(stub[0x0C*6+4]!=127 || stub[0x1C*6+4]!=128) return false;
  uint8_t unrelated[6]={0x8F,0x0C,0xF2,0x8F,64,0xF3};
  if(applySpcGain(unrelated,sizeof(unrelated),128) || unrelated[4]!=64) return false;
  if(!applySpcGain(unrelated,sizeof(unrelated),256) || unrelated[4]!=64) return false;
  if(applySpcGain(unrelated,sizeof(unrelated),1025) || unrelated[4]!=64) return false;
  if(applySpcGain(unrelated,5,0) || unrelated[4]!=64) return false;
  return true;
}
static_assert(initializerChecks(),"SPC gain initializer, preservation and rejection tests");
