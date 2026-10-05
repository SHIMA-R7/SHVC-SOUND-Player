// BRR ring streaming using the established tools/pcm_stream.py driver.
#pragma once
#include "pcm_stream_driver.h"
constexpr uint16_t PCM_RING_START=0x0400,PCM_RING_END=0xF700;
constexpr uint32_t PCM_RING_BYTES=PCM_RING_END-PCM_RING_START;
bool pcmActive=false,pcmStarted=false;
uint32_t pcmStartedMs=0;
uint16_t pcmRate=8000;
uint8_t pcmError=0,pcmChannels=1;
uint32_t pcmRingBytes=PCM_RING_BYTES,pcmWriteUs=0,pcmWriteBytes=0;

bool pcmCommand(uint8_t command,uint8_t a=0,uint8_t b=0) {
  uint32_t savedCycles=spc::pcmWriteCycles; spc::pcmWriteCycles=0;
  spc::writePort(1,a); spc::writePort(2,b); spc::writePort(3,command);
  spc::driverSeq++; spc::writePort(0,spc::driverSeq);
  bool ok=spc::waitForPort(0,spc::driverSeq,100);
  spc::pcmWriteCycles=savedCycles;
  if(!ok) Serial.printf("PCM command timeout cmd=%u seq=%u received=%lu\n",command,spc::driverSeq,received);
  return ok;
}
bool pcmDsp(uint8_t reg,uint8_t value) { return pcmCommand(0,reg,value); }
uint32_t pcmPlayed() {
  if(!pcmStarted) return 0;
  return uint32_t(uint64_t(uint32_t(millis()-pcmStartedMs))*pcmRate*9*pcmChannels/16000);
}
void stopPcmStream() {
  if(pcmActive) pcmDsp(0x5C,(1<<pcmChannels)-1);
  pcmActive=pcmStarted=false; pcmError=0;
}
bool beginPcmStream(uint16_t rate,uint32_t bytes,uint8_t channels=1) {
  abortUpload(); stopPlayback();
  if(connected) BLEDevice::getServer()->updateConnParams(remoteAddress,6,6,0,500);
  pcmChannels=channels; pcmRingBytes=channels==2?29952:PCM_RING_BYTES;
  pcmWriteUs=pcmWriteBytes=0;
  pcmRate=rate; pcmError=0; received=0; total=bytes;
  uint8_t *silence=(uint8_t*)calloc(PCM_RING_BYTES,1);
  if(!silence) return false;
  silence[pcmRingBytes-9]=3;
  if(channels==2) silence[pcmRingBytes*2-9]=3;
  uint16_t right=PCM_RING_START+pcmRingBytes;
  uint8_t dir[]={0,4,0,4,uint8_t(right),uint8_t(right>>8),uint8_t(right),uint8_t(right>>8)};
  uint8_t ptr[]={0,4,0,4,0,uint8_t(right>>8)};
  if(channels==1) ptr[5]=0xF7;
  uint8_t rings[]={0,4,4,uint8_t(right>>8),uint8_t(right),uint8_t(right>>8),uint8_t(right>>8),uint8_t((right+pcmRingBytes)>>8)};
  beginShvcTransfer(PCM_RING_BYTES+sizeof(dir)+sizeof(ptr)+sizeof(PCM_STREAM_DRIVER));
  bool ok=spc::reset() && uploadBlock(0xF700,dir,sizeof(dir),true) &&
    uploadBlock(PCM_RING_START,silence,PCM_RING_BYTES,false) &&
    uploadBlock(2,ptr,sizeof(ptr),false) &&
    uploadBlock(8,(const uint8_t*)"\0",1,false) && uploadBlock(0x10,rings,sizeof(rings),false) && uploadBlock(0x0200,PCM_STREAM_DRIVER,sizeof(PCM_STREAM_DRIVER),false);
  free(silence);
  if(!ok) return false;
  spc::jumpTo(0x0200);
  if(!pcmCommand(5,0,4) || !pcmDsp(0x6C,0x60) || !pcmDsp(0x5C,255)) return false;
  for(uint8_t r=0;r<128;r++) if(r!=0x6C && r!=0x5C && !pcmDsp(r,0)) return false;
  uint16_t pitch=uint32_t(rate)*4096/32000;
  const uint8_t regs[]={0x0C,0x1C,0x5D,0,1,2,3,4,5,7};
  const uint8_t values[]={80,80,0xF7,96,96,uint8_t(pitch),uint8_t(pitch>>8),0,0,127};
  for(size_t i=0;i<sizeof(regs);i++) if(!pcmDsp(regs[i],values[i])) return false;
  if(channels==2) {
    if(!pcmDsp(1,0)) return false;
    const uint8_t regs2[]={0x10,0x11,0x12,0x13,0x14,0x15,0x17};
    const uint8_t values2[]={0,96,uint8_t(pitch),uint8_t(pitch>>8),1,0,127};
    for(size_t i=0;i<sizeof(regs2);i++) if(!pcmDsp(regs2[i],values2[i])) return false;
  }
  pcmActive=true; pcmStarted=false; mode=PCM_STREAM; applyMute(); return true;
}
// Writes remain ahead of playback and never overtake the ring's read position.
uint8_t feedPcmStream(uint32_t offset,const uint8_t *data,size_t n) {
  if(!pcmActive || offset!=received || !n || n%(9*pcmChannels) || n>total-received) return 2;
  uint32_t played=pcmPlayed();
  if(received<played || uint64_t(received-played)+n>pcmRingBytes*pcmChannels-2048) return 5;
  struct TimingScope {
    uint32_t saved;
    TimingScope():saved(spc::pcmWriteCycles) { spc::pcmWriteCycles=getCpuFrequencyMhz()/2; }
    ~TimingScope() { spc::pcmWriteCycles=saved; }
  } timing;
  uint32_t writeStart=micros();
  for(uint8_t ch=0;ch<pcmChannels;ch++) {
    if(pcmChannels==2 && !pcmCommand(8,ch)) return 4;
    uint8_t packed[512]; size_t size=n/pcmChannels;
    for(size_t block=0;block<n;block+=9*pcmChannels) {
      size_t dest=block/pcmChannels;
      memcpy(packed+dest,data+block+ch*9,9);
      packed[dest]&=0xFC;
      if(((offset+block)/pcmChannels)%pcmRingBytes==pcmRingBytes-9) packed[dest]|=3;
    }
    uint16_t position=PCM_RING_START+ch*pcmRingBytes+(received/pcmChannels)%pcmRingBytes;
    size_t done=0;
    while(done<size) {
      size_t bulk=min((size-done)/3*3,size_t((255-(position&255))/3*3));
      if(bulk) {
        if(!pcmCommand(9)) return 4;
        for(size_t i=done;i<done+bulk;i+=3) {
          spc::writePort(1,packed[i]); spc::writePort(2,packed[i+1]); spc::writePort(3,packed[i+2]);
          if(++spc::driverSeq==0) spc::driverSeq=1;
          spc::writePort(0,spc::driverSeq);
          if(!spc::waitForPort(0,spc::driverSeq,100)) return 4;
        }
        spc::writePort(0,0); if(!spc::waitForPort(0,0,100)) return 4;
        spc::driverSeq=0;
        done+=bulk; position+=bulk;
      } else {
        size_t tail=min(size_t(2),min(size-done,size_t(256-(position&255))));
        if(!pcmCommand(tail,packed[done],tail==2?packed[done+1]:0)) return 4;
        done+=tail; position+=tail;
        uint16_t end=PCM_RING_START+(ch+1)*pcmRingBytes;
        if(position==end) position=PCM_RING_START+ch*pcmRingBytes;
      }
    }
    if(!pcmCommand(3)) return 4;
    uint16_t ptr=spc::readPort(1,4)|(uint16_t(spc::readPort(2,4))<<8);
    uint16_t expected=PCM_RING_START+ch*pcmRingBytes+((received+n)/pcmChannels)%pcmRingBytes;
    if(ptr!=expected) { Serial.printf("PCM pointer mismatch ch=%u received=%lu n=%u ptr=%04X expected=%04X\n",ch,received,unsigned(n),ptr,expected); return 4; }
    if(!pcmStarted && offset==0) {
      uint16_t start=PCM_RING_START+ch*pcmRingBytes;
      if(!pcmCommand(5,uint8_t(start),uint8_t(start>>8))) return 4;
      for(size_t i=0;i<size;i++) {
        if(!pcmCommand(6)) return 4;
        uint8_t want=packed[i];
        if(spc::readPort(1,4)!=want) return 4;
      }
      if(!pcmCommand(5,uint8_t(expected),uint8_t(expected>>8))) return 4;
    }
  }
  pcmWriteUs+=uint32_t(micros()-writeStart); pcmWriteBytes+=n;
  if(pcmWriteBytes>=16384) {
    Serial.printf("PCM bus bytes=%lu us=%lu rate=%lu B/s channels=%u\n",pcmWriteBytes,pcmWriteUs,uint32_t(uint64_t(pcmWriteBytes)*1000000/pcmWriteUs),pcmChannels);
    pcmWriteUs=pcmWriteBytes=0;
  }
  received+=n;
  return 0;
}
bool startPcmStream() {
  if(!pcmActive || pcmStarted || received<min(total,uint32_t(pcmRate)*9*pcmChannels/16)) return false;
  if(!pcmDsp(0x5C,0) || !pcmDsp(0x6C,0x20) || !pcmDsp(0x4C,(1<<pcmChannels)-1) || !pcmDsp(0x4C,0)) return false;
  pcmStartedMs=millis(); pcmStarted=true; applyMute(); return true;
}
void pollPcmStream() {
  if(!pcmActive || !pcmStarted) return;
  uint32_t played=pcmPlayed();
  if(played>=total) { stopPlayback(); publish(0,0,0); }
  else if(played>=received) {
    stopPlayback(); mode=ERROR_MODE; applyMute(); publish(0,0,6);
    Serial.println("PCM underrun: stopped instead of replaying stale audio");
  }
}
