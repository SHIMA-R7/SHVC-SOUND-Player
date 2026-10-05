// Experimental host-controlled APU bridge. No SPC/ROM/music data is embedded.
#define SHVC_FAST_GPIO 1
#include <Arduino.h>
#include "spc_bus.h"
#include "ble_transport.h"
#include "wifi_transport.h"
#include <BluetoothSerial.h>
static BluetoothSerial serialBt;
static bool bluetoothStarted=false;
static void sppEvent(esp_spp_cb_event_t event,esp_spp_cb_param_t *param) {
  if(event==ESP_SPP_SRV_OPEN_EVT) {
    BLEDevice::getAdvertising()->stop();
    esp_bt_gap_set_qos(param->srv_open.rem_bda,6);
  } else if(event==ESP_SPP_CLOSE_EVT) { stopRequested=true; BLEDevice::startAdvertising(); }
}
static uint8_t data[1536],reply[522];
uint16_t crc16(const uint8_t *p,size_t n) { uint16_t c=0xffff; while(n--) { c^=uint16_t(*p++)<<8; for(int i=0;i<8;i++) c=(c&0x8000)?(c<<1)^0x1021:c<<1; } return c; }
bool exact(uint8_t *p,size_t n) { return transport->readBytes(p,n)==n; }
bool coldReset() {
  // Silence/reset DSP and clear ARAM outside this tiny routine ($0200).
  // Clearing $F0-$FF as RAM would modify SMP I/O, so leave that range alone.
  const uint8_t code[]={0x20,0x8f,0x6c,0xf2,0x8f,0xe0,0xf3,0x8f,0x5c,0xf2,0x8f,0xff,0xf3,
    0xe8,0,0xcd,0,0xd4,0,0x3d,0xc8,0xf0,0xd0,0xf9,
    0xcd,0,0xd5,0,1,0x3d,0xd0,0xfa,
    0x8f,0,2,0x8f,3,3,0x8d,0,0xd7,2,0xfc,0xd0,0xfb,0xab,3,0xd0,0xf7,
    0x8f,0x5a,0xf4,0x8f,0xa5,0xf5,0x2f,0xfe};
  if(!spc::reset() || !spc::uploadBlock(0x200,code,sizeof(code),true)) return false;
  spc::jumpTo(0x200);
  if(!spc::waitForPort(0,0x5a,2000)) return false;
  return spc::reset();
}
void setup() {
  Serial.setRxBufferSize(4096); Serial.begin(921600); Serial.setTimeout(1000);
  pinMode(33,OUTPUT); digitalWrite(33,LOW); pinMode(2,OUTPUT); digitalWrite(2,LOW);
  spc::begin(); digitalWrite(spc::PIN_RESET,HIGH);
  if(strlen(SHVC_WIFI_SSID)) initWifi();
  else {
    serialBt.begin("SHVC-APU SPP",false,false); serialBt.setTimeout(1000);
    initBle(); serialBt.register_callback(sppEvent); bluetoothStarted=true;
  }
}
void loop() {
  pollWifi();
  if(stopRequested) { stopRequested=false; spc::setMute(true); digitalWrite(2,LOW); coldReset(); }
  transport=wifiClient.connected() ? static_cast<Stream*>(&wifiClient) : (bluetoothStarted && serialBt.hasClient()) ? static_cast<Stream*>(&serialBt) : bleConnected ? static_cast<Stream*>(&bleStream) : static_cast<Stream*>(&Serial);
  if(transport->available()<2) { delay(1); return; }
  if(transport->read()!=0x41 || transport->read()!=0x50) return;
  uint8_t h[6]; if(!exact(h,6)) return;
  uint16_t seq=h[0]|(uint16_t(h[1])<<8),n=h[2]|(uint16_t(h[3])<<8);
  uint8_t status=0; size_t out=0; uint16_t failed=0xffff;
  if(n>sizeof(data) || n%3 || !exact(data,n)) { status=1; }
  else if(crc16(data,n)!=(h[4]|(uint16_t(h[5])<<8))) status=2;
  else for(size_t i=0;i<n;i+=3) {
    uint8_t op=data[i],port=data[i+1],value=data[i+2];
    if(op==0x10 && port<4) spc::writePort(port,value);
    else if(op==0x11 && port<4) { if(!spc::waitForPort(port,value,100)) { status=3; failed=i/3; break; } }
    else if(op==0x12 && port<4 && out<512) reply[8+out++]=spc::readPort(port,4);
    else if(op==0x19) {
      int count=WiFi.scanNetworks();
      for(int j=0;j<count;j++) {
        String ssid=WiFi.SSID(j); size_t size=ssid.length();
        if(out+size+1>512) break;
        memcpy(reply+8+out,ssid.c_str(),size); out+=size; reply[8+out++]=0;
      }
      WiFi.scanDelete();
    }
    else if(op==0x1a && out<512) reply[8+out++]=WiFi.status();
    else if(op==0x18 && out<=508) { IPAddress ip=WiFi.localIP(); for(int j=0;j<4;j++) reply[8+out++]=ip[j]; }
    else if(op==0x14) delayMicroseconds(uint16_t(port)|(uint16_t(value)<<8));
    else if(op==0x15) {
      spc::setMute(true); digitalWrite(2,LOW);
      if(!coldReset()) { status=4; failed=i/3; break; }
      if(out>510) { status=1; break; }
      reply[8+out++]=0xaa; reply[8+out++]=0xbb;
    }
    else if(op==0x13) {
      spc::setMute(true); digitalWrite(2,LOW); if(!coldReset()) { status=4; failed=i/3; break; }
      if(out>510) { status=1; break; }
      reply[8+out++]=0xaa; reply[8+out++]=0xbb; spc::setMute(false); digitalWrite(2,HIGH);
    } else { status=1; failed=i/3; break; }
  }
  reply[0]=0xac; reply[1]=seq; reply[2]=seq>>8; reply[3]=status;
  reply[4]=failed; reply[5]=failed>>8; reply[6]=out; reply[7]=out>>8;
  uint16_t crc=crc16(reply,8+out); reply[8+out]=crc; reply[9+out]=crc>>8; transport->write(reply,10+out); transport->flush();
  if(status) { spc::setMute(true); digitalWrite(2,LOW); }
}
