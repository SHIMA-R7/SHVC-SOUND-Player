#pragma once
#include <WiFi.h>
#include <WiFiUdp.h>
#include "wifi_credentials.h"
static WiFiServer wifiServer(28954);
static WiFiClient wifiClient;
static WiFiUDP wifiDiscovery;
static bool wifiStarted=false;
static bool wifiWasConnected=false;
static void initWifi() {
  if(!strlen(SHVC_WIFI_SSID)) return;
  WiFi.mode(WIFI_STA); WiFi.setHostname("shvc-apu"); WiFi.setSleep(false);
  WiFi.begin(SHVC_WIFI_SSID,SHVC_WIFI_PASSWORD);
}
static void pollWifi() {
  if(WiFi.status()!=WL_CONNECTED) { if(wifiWasConnected) stopRequested=true; wifiWasConnected=false; return; }
  if(!wifiStarted) {
    wifiServer.begin(); wifiServer.setNoDelay(true);
    wifiDiscovery.begin(28955); wifiStarted=true;
  }
  if(!wifiClient.connected()) {
    if(wifiWasConnected) stopRequested=true; wifiWasConnected=false;
    wifiClient=wifiServer.accept();
    if(wifiClient) { wifiWasConnected=true; wifiClient.setNoDelay(true); wifiClient.setTimeout(1000); }
  }
  int size=wifiDiscovery.parsePacket();
  if(size) {
    char query[20]={}; int received=wifiDiscovery.read(query,sizeof(query)-1);
    if(received==14 && !memcmp(query,"SHVC-APU-FIND1",14)) {
      wifiDiscovery.beginPacket(wifiDiscovery.remoteIP(),wifiDiscovery.remotePort());
      wifiDiscovery.write(reinterpret_cast<const uint8_t*>("SHVC-APU-WIFI1"),14); wifiDiscovery.endPacket();
    }
  }
}
