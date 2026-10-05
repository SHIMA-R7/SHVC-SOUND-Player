#pragma once
#include <BLEDevice.h>
#include <BLE2902.h>
#include <esp_gap_ble_api.h>
static const char *APU_SERVICE="587a0001-5356-4348-8000-00805f9b34fb";
static const char *APU_TX="587a0002-5356-4348-8000-00805f9b34fb";
static const char *APU_RX="587a0003-5356-4348-8000-00805f9b34fb";
static volatile bool bleConnected=false;
static volatile bool stopRequested=false;
static BLECharacteristic *bleReply;
static QueueHandle_t bleBytes;
class BleStream: public Stream {
public:
  int available() override { return uxQueueMessagesWaiting(bleBytes); }
  int read() override { uint8_t b; return xQueueReceive(bleBytes,&b,0)==pdTRUE ? b : -1; }
  int peek() override { uint8_t b; return xQueuePeek(bleBytes,&b,0)==pdTRUE ? b : -1; }
  void flush() override {}
  size_t write(uint8_t b) override { return write(&b,1); }
  size_t write(const uint8_t *p,size_t n) override {
    size_t sent=0;
    while(sent<n && bleConnected) {
      size_t count=min(size_t(180),n-sent);
      bleReply->setValue(p+sent,count); bleReply->notify(); sent+=count;
    }
    return sent;
  }
};
static BleStream bleStream;
static Stream *transport=&Serial;
class ApuWrite: public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    auto value=c->getValue();
    for(size_t i=0;i<value.length();i++) {
      uint8_t b=value[i];
      if(xQueueSend(bleBytes,&b,0)!=pdTRUE) { xQueueReset(bleBytes); break; }
    }
  }
};
class ApuServer: public BLEServerCallbacks {
  void onConnect(BLEServer *,esp_ble_gatts_cb_param_t *param) override {
    xQueueReset(bleBytes); bleConnected=true;
    esp_ble_conn_update_params_t update={};
    memcpy(update.bda,param->connect.remote_bda,6);
    update.min_int=6; update.max_int=6; update.latency=0; update.timeout=400;
    esp_ble_gap_update_conn_params(&update);
  }
  void onDisconnect(BLEServer *) override {
    bleConnected=false; stopRequested=true; xQueueReset(bleBytes); BLEDevice::startAdvertising();
  }
};
static void initBle() {
  bleBytes=xQueueCreate(4096,1); bleStream.setTimeout(1000);
  BLEDevice::init("SHVC-APU Bridge"); BLEDevice::setMTU(517);
  auto server=BLEDevice::createServer(); server->setCallbacks(new ApuServer());
  auto service=server->createService(APU_SERVICE);
  auto command=service->createCharacteristic(APU_TX,BLECharacteristic::PROPERTY_WRITE_NR|BLECharacteristic::PROPERTY_WRITE);
  command->setCallbacks(new ApuWrite());
  bleReply=service->createCharacteristic(APU_RX,BLECharacteristic::PROPERTY_NOTIFY);
  bleReply->addDescriptor(new BLE2902()); service->start();
  auto adv=BLEDevice::getAdvertising(); adv->addServiceUUID(APU_SERVICE); adv->setScanResponse(true);
  BLEDevice::startAdvertising();
}
