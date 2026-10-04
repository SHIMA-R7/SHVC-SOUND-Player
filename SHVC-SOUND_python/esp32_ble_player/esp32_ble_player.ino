// BLE control, persistent songs, and standard BLE MIDI. All SPC bus work runs in loop().
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLE2902.h>
#include <LittleFS.h>
#include <Preferences.h>
#include "spc_bus.h"
#include "bank_data.h"
#include "synth.h"
#include "midi_parser.h"
#if __has_include("spc_data.h")
#include "spc_data.h"
#define HAVE_BOOT_SONG 1
#endif

const char *SERVICE = "89e30000-3c3b-4df7-a74a-25fdd879b40c";
const char *COMMAND = "89e30001-3c3b-4df7-a74a-25fdd879b40c";
const char *STATUS_UUID = "89e30002-3c3b-4df7-a74a-25fdd879b40c";
const char *MIDI_SERVICE = "03b80e5a-ede8-4b33-a751-6ce34ec4c700";
const char *MIDI_CHAR = "7772e5db-3868-4112-a1a9-f2669d106bf3";
enum Mode : uint8_t { STOPPED, SPC, MIDI_LIVE, MIDI_FILE, LOADING, ERROR_MODE };
enum Op : uint8_t { INFO=1, PLAY=2, STOP=3, MUTE=4, MASTER=5, MIDI_MODE=6,
  CHANNEL=7, LOOP=8, BOOT=9, PROGRAM=10, BEGIN_FILE=16, DATA=17, COMMIT=18, ABORT=19 };
struct Packet { uint16_t length; uint8_t bytes[244]; };
struct MidiMsg { uint8_t status,d1,d2; };
struct __attribute__((packed)) Reply {
  uint16_t sequence; uint8_t op, code; uint32_t received,total;
  uint8_t mode,muted; uint16_t master; uint32_t dropped;
};
static_assert(sizeof(Reply)==20,"wire reply size");
QueueHandle_t commands,midi;
BLECharacteristic *statusChar;
Preferences prefs;
File incoming,sequenceFile;
Mode mode=STOPPED;
bool muted=false,repeatMidi=true,bootPlay=true,fsReady=false,uploading=false;
volatile bool disconnected=false,connected=false;
volatile uint32_t dropped=0;
volatile bool midiOverflow=false;
uint8_t activeSlot=0,uploadSlot=1,master=89;
uint32_t received=0,total=0,expectedCrc=0,runningCrc=0xFFFFFFFF,lastData=0;
uint32_t midiCount=0,eventIndex=0,midiDuration=0,midiStart=0;
uint8_t nextEvent[8]; bool haveEvent=false;
Reply reply{};

uint16_t get16(const uint8_t *p) { return p[0]|uint16_t(p[1])<<8; }
uint32_t get32(const uint8_t *p) { return p[0]|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24; }
uint32_t crcUpdate(uint32_t crc,const uint8_t *p,size_t n) {
  while(n--) { crc^=*p++; for(int i=0;i<8;i++) crc=(crc>>1)^(0xEDB88320u & (0u-(crc&1))); }
  return crc;
}
String slotPath(uint8_t slot) { return String("/song")+slot+".dat"; }
void publish(uint16_t seq,uint8_t op,uint8_t code) {
  uint8_t flags=uint8_t(muted)|(uint8_t(repeatMidi)<<1)|(uint8_t(bootPlay)<<2);
  reply={seq,op,code,received,total,uint8_t(mode),flags,master,dropped};
  statusChar->setValue(reinterpret_cast<uint8_t*>(&reply),sizeof(reply));
  if(connected) statusChar->notify();
  Serial.printf("ACK seq=%u op=%u code=%u mode=%u received=%lu\n",seq,op,code,mode,(unsigned long)received);
}
void applyMute() { spc::setMute(muted || mode==STOPPED || mode==LOADING || mode==ERROR_MODE); }
void abortUpload() {
  if(incoming) incoming.close();
  if(uploading) LittleFS.remove(slotPath(uploadSlot));
  uploading=false;
}
void stopPlayback() {
  if(sequenceFile) sequenceFile.close();
  if(mode==MIDI_LIVE || mode==MIDI_FILE) synth::allNotesOff(-1);
  mode=STOPPED; haveEvent=false; xQueueReset(midi); synth::driverError=false; applyMute();
}
bool uploadBlock(uint16_t addr,const uint8_t *p,size_t n,bool first) {
  spc::writePort(2,addr&255); spc::writePort(3,addr>>8); spc::writePort(1,1);
  uint8_t kick=first?0xCC:uint8_t(spc::readPort(0)+2); if(!first && !kick) kick=1;
  spc::writePort(0,kick); if(!spc::waitForPort(0,kick,1000)) return false;
  for(size_t i=0;i<n;i++) {
    spc::writePort(1,p[i]); spc::writePort(0,uint8_t(i));
    if(!spc::waitForPort(0,uint8_t(i),200)) return false;
    if((i&63)==63) delay(1);
  }
  return true;
}
bool finishSpc(uint16_t addr,uint8_t signal,const uint8_t *ports) {
  spc::jumpTo(addr);
  uint8_t marker=spc::readPort(0); if(marker!=0x99 && marker!=0x98) return false;
  for(int p=1;p<4;p++) spc::writePort(p,ports[p]);
  spc::writePort(0,signal); if(!spc::waitForPort(0,0x98,2000)) return false;
  spc::writePort(0,ports[0]); mode=SPC; applyMute(); return true;
}
bool startMidi() {
  stopPlayback(); mode=LOADING; applyMute();
  synth::driverError=false; spc::dryRun=false;
  if(!spc::reset() || !uploadBlock(SPC_DIR_ADDR,SPC_DIR,sizeof(SPC_DIR),true) ||
     !uploadBlock(SPC_SAMPLE_ADDR,SPC_BRR,sizeof(SPC_BRR),false) ||
     !uploadBlock(SPC_DRIVER_ADDR,SPC_DRIVER,sizeof(SPC_DRIVER),false)) return false;
  spc::jumpTo(SPC_DRIVER_ADDR); synth::masterVolume=master/127.0f; synth::initDsp();
  if(synth::driverError) return false;
  mode=MIDI_LIVE; xQueueReset(midi); applyMute(); return true;
}
bool validSong(File &f) {
  uint8_t h[16]; if(f.size()<16 || f.read(h,16)!=16) return false;
  if(!memcmp(h,"HSP1",4)) {
    uint16_t addr=get16(h+4),len=get16(h+6);
    return len>0 && len<=4096 && uint32_t(addr)+len==0xFFC0 && f.size()==16+65536u+len;
  }
  if(memcmp(h,"HTM1",4)) return false;
  uint32_t count=get32(h+4),duration=get32(h+8),prev=0;
  if(!count || count>30000 || duration>86400000 || f.size()!=16+8u*count) return false;
  uint8_t e[8];
  for(uint32_t i=0;i<count;i++) {
    if(f.read(e,8)!=8) return false;
    uint32_t t=get32(e); uint8_t type=e[4]&0xF0;
    if(t<prev || t>duration || e[5]>127 || e[6]>127 ||
       !(type==0x80 || type==0x90 || type==0xB0 || type==0xC0 || type==0xE0)) return false;
    prev=t; if((i&255)==255) delay(1);
  }
  return true;
}
bool nextMidiEvent() {
  haveEvent=eventIndex<midiCount && sequenceFile.read(nextEvent,8)==8;
  if(haveEvent) eventIndex++;
  return haveEvent;
}
bool playSaved() {
  stopPlayback();
  File f=fsReady?LittleFS.open(slotPath(activeSlot),"r"):File();
  if(f) {
    if(!validSong(f)) { f.close(); return false; }
    f.seek(0); uint8_t h[16]; f.read(h,16);
    if(!memcmp(h,"HTM1",4)) {
      f.close(); if(!startMidi()) return false;
      sequenceFile=LittleFS.open(slotPath(activeSlot),"r"); sequenceFile.seek(16);
      midiCount=get32(h+4); midiDuration=get32(h+8); eventIndex=0;
      midiStart=millis(); nextMidiEvent(); mode=MIDI_FILE; return true;
    }
    // Allocate only the snapshot while loading; release it before live MIDI starts.
    size_t n=65536u+get16(h+6); uint8_t *data=(uint8_t*)malloc(n);
    if(!data) { f.close(); return false; }
    bool ok=f.read(data,n)==n; f.close(); mode=LOADING; applyMute();
    ok=ok && spc::reset() && uploadBlock(2,data+2,238,true) &&
      uploadBlock(0x100,data+0x100,0xFEC0,false) &&
      uploadBlock(get16(h+4),data+65536,get16(h+6),false) && finishSpc(get16(h+4),h[8],h+9);
    free(data); return ok;
  }
#ifdef HAVE_BOOT_SONG
  mode=LOADING; applyMute();
  return spc::reset() && uploadBlock(2,SPC_RAM+2,238,true) &&
    uploadBlock(0x100,SPC_RAM+0x100,0xFEC0,false) &&
    uploadBlock(STUB_ADDRESS,RESTORE_STUB,sizeof(RESTORE_STUB),false) &&
    finishSpc(STUB_ADDRESS,START_SIGNAL,FINAL_PORTS);
#else
  return false;
#endif
}
void midiEnqueue(uint8_t status,uint8_t d1,uint8_t d2) {
  MidiMsg m{status,d1,d2}; if(xQueueSend(midi,&m,0)!=pdTRUE) { dropped++; midiOverflow=true; }
}
MidiStream midiStream(midiEnqueue);
class MidiCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    String s=c->getValue(); parseBleMidiPacket((const uint8_t*)s.c_str(),s.length(),midiStream);
  }
};
class CommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    String s=c->getValue();
    if(s.length()<3 || s.length()>244) { dropped++; return; }
    Packet p{}; p.length=s.length(); memcpy(p.bytes,s.c_str(),p.length);
    if(xQueueSend(commands,&p,0)!=pdTRUE) dropped++;
  }
};
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override { connected=true; }
  void onDisconnect(BLEServer*) override { connected=false; disconnected=true; midiStream=MidiStream(midiEnqueue); BLEDevice::startAdvertising(); }
};
void handle(const Packet &p) {
  uint16_t seq=get16(p.bytes); uint8_t op=p.bytes[2],code=0;
  const uint8_t *a=p.bytes+3; size_t n=p.length-3;
  switch(op) {
    case INFO: if(n) code=1; break;
    case PLAY: if(n || uploading) code=1; else if(!playSaved()) code=4; break;
    case STOP: if(n) code=1; else stopPlayback(); break;
    case MUTE: if(n!=1 || a[0]>1) code=1; else { muted=a[0]; applyMute(); } break;
    case MASTER:
      if(n!=1 || a[0]>127 || !(mode==MIDI_LIVE || mode==MIDI_FILE || mode==STOPPED)) code=1;
      else { master=a[0]; synth::masterVolume=master/127.0f;
        if(mode==MIDI_LIVE || mode==MIDI_FILE) for(int c=0;c<16;c++) synth::refreshVolumes(c); }
      break;
    case MIDI_MODE: if(n || uploading) code=1; else if(!startMidi()) code=4; break;
    case CHANNEL:
      if(n!=3 || a[0]>15 || a[1]>127 || a[2]>127 || !(mode==MIDI_LIVE || mode==MIDI_FILE)) code=1;
      else synth::controlChange(a[0],a[1],a[2]); break;
    case PROGRAM:
      if(n!=2 || a[0]>15 || a[1]>127 || !(mode==MIDI_LIVE || mode==MIDI_FILE)) code=1;
      else synth::programChange(a[0],a[1]); break;
    case LOOP: if(n!=1 || a[0]>1) code=1; else { repeatMidi=a[0]; prefs.putBool("loop",repeatMidi); } break;
    case BOOT: if(n!=1 || a[0]>1) code=1; else { bootPlay=a[0]; prefs.putBool("boot",bootPlay); } break;
    case BEGIN_FILE:
      if(n!=8 || !fsReady || get32(a)<16 || get32(a)>256000) { code=1; break; }
      abortUpload(); uploadSlot=1-activeSlot; total=get32(a); expectedCrc=get32(a+4);
      received=0; runningCrc=0xFFFFFFFF; incoming=LittleFS.open(slotPath(uploadSlot),"w");
      uploading=bool(incoming); lastData=millis(); if(!uploading) code=3; break;
    case DATA:
      if(!uploading || n<5 || get32(a)!=received || n-4>total-received) { code=2; break; }
      if(incoming.write(a+4,n-4)!=n-4) { abortUpload(); code=3; break; }
      runningCrc=crcUpdate(runningCrc,a+4,n-4); received+=n-4; lastData=millis(); break;
    case COMMIT: {
      if(n || !uploading || received!=total || (runningCrc^0xFFFFFFFF)!=expectedCrc) { code=2; break; }
      incoming.close(); File f=LittleFS.open(slotPath(uploadSlot),"r"); bool ok=f && validSong(f); f.close();
      if(!ok) { abortUpload(); code=2; break; }
      // NVS slot pointer changes only after the new complete file validates.
      if(prefs.putUChar("slot",uploadSlot)!=1) { abortUpload(); code=3; break; }
      activeSlot=uploadSlot; uploading=false; break;
    }
    case ABORT: if(n) code=1; else abortUpload(); break;
    default: code=1;
  }
  if(code==4 || synth::driverError) { mode=ERROR_MODE; applyMute(); if(!code) code=4; }
  publish(seq,op,code);
}
void setup() {
  Serial.begin(115200); spc::begin(); ledcAttach(33,20000,8); ledcWrite(33,0);
  commands=xQueueCreate(8,sizeof(Packet)); midi=xQueueCreate(256,sizeof(MidiMsg));
  if(!commands || !midi) { Serial.println("ERROR queues"); while(true) delay(1000); }
  prefs.begin("ble-player",false); activeSlot=prefs.getUChar("slot",0)&1;
  repeatMidi=prefs.getBool("loop",true); bootPlay=prefs.getBool("boot",true);
  fsReady=LittleFS.begin(false); // do not silently erase an existing filesystem
  if(!fsReady && !prefs.isKey("fs")) {
    Serial.println("First install: initialize song filesystem");
    fsReady=LittleFS.format() && LittleFS.begin(false);
  }
  if(fsReady) prefs.putBool("fs",true);
  if(!fsReady) Serial.println("FILESYSTEM unavailable; use explicit first-install format");
  BLEDevice::init("SHVC-SOUND Player"); BLEDevice::setMTU(247);
  BLEServer *server=BLEDevice::createServer(); server->setCallbacks(new ServerCallbacks());
  BLEService *control=server->createService(SERVICE);
  auto *command=control->createCharacteristic(COMMAND,BLECharacteristic::PROPERTY_WRITE);
  command->setCallbacks(new CommandCallbacks());
  statusChar=control->createCharacteristic(STATUS_UUID,BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY);
  statusChar->addDescriptor(new BLE2902()); control->start();
  BLEService *ms=server->createService(MIDI_SERVICE);
  auto *mc=ms->createCharacteristic(MIDI_CHAR,BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_WRITE_NR|BLECharacteristic::PROPERTY_NOTIFY);
  mc->addDescriptor(new BLE2902()); mc->setCallbacks(new MidiCallbacks()); ms->start();
  auto *adv=BLEDevice::getAdvertising(); adv->addServiceUUID(SERVICE); adv->setScanResponse(true); BLEDevice::startAdvertising();
  Serial.println("BLE READY SHVC-SOUND Player"); publish(0,INFO,0);
  if(bootPlay && !playSaved()) { mode=ERROR_MODE; applyMute(); }
  publish(0,INFO,0);
}
void loop() {
  if(disconnected) {
    disconnected=false; abortUpload(); xQueueReset(commands); xQueueReset(midi);
    if(mode==MIDI_LIVE) synth::allNotesOff(-1);
  }
  Packet p; if(xQueueReceive(commands,&p,0)==pdTRUE) handle(p);
  if(uploading && uint32_t(millis()-lastData)>30000) abortUpload();
  if(midiOverflow) {
    midiOverflow=false; xQueueReset(midi);
    if(mode==MIDI_LIVE) synth::allNotesOff(-1);
  }
  MidiMsg m; for(int i=0;i<32 && xQueueReceive(midi,&m,0)==pdTRUE;i++)
    if(mode==MIDI_LIVE || (mode==MIDI_FILE && ((m.status&0xF0)==0xB0 || (m.status&0xF0)==0xC0 || (m.status&0xF0)==0xE0)))
      synth::handleMessage(m.status,m.d1,m.d2);
  if(mode==MIDI_FILE) {
    for(int i=0;i<16 && haveEvent && uint32_t(millis()-midiStart)>=get32(nextEvent);i++) {
      synth::handleMessage(nextEvent[4],nextEvent[5],nextEvent[6]); nextMidiEvent();
    }
    if(!haveEvent && uint32_t(millis()-midiStart)>=midiDuration) {
      synth::allNotesOff(-1);
      if(repeatMidi) { synth::resetChannels(); sequenceFile.seek(16); eventIndex=0; midiStart=millis(); nextMidiEvent(); }
      else stopPlayback();
    }
  }
  if(synth::driverError && mode!=ERROR_MODE) { mode=ERROR_MODE; applyMute(); publish(0,INFO,4); }
  delay(1);
}
