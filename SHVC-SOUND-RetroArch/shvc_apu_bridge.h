#pragma once
// Windows proof of concept: IPL packets use shadow values + real ACK checks;
// after IPL execution, game reads are supplied by the real hardware.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifdef __ANDROID__
#include "shvc_android_transport.h"
#else
#include <windows.h>
#endif
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <cstdint>
namespace shvc {
static HANDLE serial=INVALID_HANDLE_VALUE;
static bool tried=false,boot=true,failed=false,iplStarted=false,addrDirty=false,jumpPending=false,readyForIpl=false;
static unsigned seq=0,reads=0,writes=0,packets=0,liveReads=0;
static uint8_t last[4]={},pending[4]={},actual[4]={};
static std::vector<uint8_t> queue;
static FILE *logfile=nullptr;
static uint16_t crc16(const uint8_t *p,size_t n) { uint16_t c=0xffff; while(n--) { c^=uint16_t(*p++)<<8; for(int i=0;i<8;i++) c=(c&0x8000)?(c<<1)^0x1021:c<<1; } return c; }
static void log(const char *s) { if(!logfile) { const char *p=getenv("SHVC_APU_LOG"); if(p) logfile=fopen(p,"a"); } if(logfile) { fprintf(logfile,"%lu %s reads=%u writes=%u packets=%u\n",GetTickCount(),s,reads,writes,packets); fflush(logfile); } }
static bool exact(uint8_t *p,DWORD n) { while(n) { DWORD got=0; if(!ReadFile(serial,p,n,&got,nullptr)||!got) return false; p+=got; n-=got; } return true; }
static bool flush(std::vector<uint8_t> *result=nullptr) {
  if(queue.empty()) return true;
  uint16_t n=queue.size(),c=crc16(queue.data(),n); ++seq; ++packets;
  uint8_t h[]={0x41,0x50,uint8_t(seq),uint8_t(seq>>8),uint8_t(n),uint8_t(n>>8),uint8_t(c),uint8_t(c>>8)};
  std::vector<uint8_t> request(h,h+8); request.insert(request.end(),queue.begin(),queue.end());
  DWORD sent; bool ok=WriteFile(serial,request.data(),DWORD(request.size()),&sent,nullptr)&&sent==request.size();
  queue.clear(); uint8_t rh[8];
  if(!ok||!exact(rh,8)||rh[0]!=0xac||(rh[1]|(unsigned(rh[2])<<8))!=(seq&65535)) { failed=true; log("transport failure"); return false; }
  size_t size=rh[6]|(size_t(rh[7])<<8); if(size>512) { failed=true; log("invalid reply length"); return false; }
  std::vector<uint8_t> r(rh,rh+8); r.resize(10+size);
  if(!exact(r.data()+8,size+2)||crc16(r.data(),8+size)!=(r[8+size]|(uint16_t(r[9+size])<<8))||rh[3]) {
    char msg[100]; snprintf(msg,sizeof(msg),"bridge failure status=%u instruction=%u",rh[3],rh[4]|(unsigned(rh[5])<<8)); failed=true; log(msg); return false;
  }
  if(result) result->assign(r.begin()+8,r.begin()+8+size);
  return true;
}
static void cmd(uint8_t op,uint8_t p=0,uint8_t v=0) { if(writes<12) { char b[90]; snprintf(b,sizeof(b),"queued op=%02X port=%u value=%02X",op,p,v); log(b); } queue.push_back(op); queue.push_back(p); queue.push_back(v); }
static bool open() {
  if(tried) return serial!=INVALID_HANDLE_VALUE&&!failed;
  tried=true; const char *port=getenv("SHVC_APU_PORT"); if(!port||!*port) return false;
  #ifdef __ANDROID__
  serial=androidConnect(port);
  if(serial==INVALID_HANDLE_VALUE) { failed=true; log("cannot connect to Wi-Fi bridge"); return false; }
  #else
  char path[80]; snprintf(path,sizeof(path),"\\\\.\\%s",port);
  bool wireless=strcmp(port,"BLE")==0;
  if(wireless) snprintf(path,sizeof(path),"\\\\.\\pipe\\shvc-apu-ble");
  serial=CreateFileA(path,GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,0,nullptr);
  if(serial==INVALID_HANDLE_VALUE) { log("cannot open serial port"); return false; }
  if(!wireless) {
  DCB d={}; d.DCBlength=sizeof(d); GetCommState(serial,&d); d.BaudRate=921600; d.ByteSize=8; d.Parity=NOPARITY; d.StopBits=ONESTOPBIT;
  d.fBinary=TRUE; d.fDtrControl=DTR_CONTROL_DISABLE; d.fRtsControl=RTS_CONTROL_DISABLE; d.fOutxCtsFlow=FALSE; d.fOutxDsrFlow=FALSE; d.fOutX=FALSE; d.fInX=FALSE;
  if(!SetCommState(serial,&d)) { failed=true; log("serial settings failed"); return false; }
  COMMTIMEOUTS t={MAXDWORD,0,3000,0,3000}; SetCommTimeouts(serial,&t); SetupComm(serial,8192,8192);
  Sleep(2000); PurgeComm(serial,PURGE_RXCLEAR|PURGE_TXCLEAR);
  }
  #endif
  cmd(0x13); std::vector<uint8_t> r;
  if(!flush(&r)||r.size()!=2||r[0]!=0xaa||r[1]!=0xbb) { failed=true; log("IPL reset failed"); return false; }
  boot=true; log("connected: real IPL AA/BB"); return true;
}
static bool active() { return open(); }
static void reset() {
  if(!active()) return;
  queue.clear(); cmd(0x13); flush(); boot=true; iplStarted=false; addrDirty=false; jumpPending=false; readyForIpl=false;
  for(int i=0;i<4;i++) pending[i]=0;
  log("APU reset");
}
static void write(unsigned port,uint8_t value) {
  if(!active()) return; port&=3; ++writes;
  if(port>=2) addrDirty=true;
  if(port==0) {
    if(value==0xcc&&(boot||readyForIpl)) { boot=true; iplStarted=true; readyForIpl=false; for(unsigned i=0;i<4;i++) actual[i]=0; }
    jumpPending=boot&&iplStarted&&addrDirty&&last[1]==0;
    addrDirty=false;
  }
  last[port]=value; pending[port]=1; if(!(boot&&port==0)) cmd(0x10,port,value);
  if(!boot&&queue.size()>=1200) flush();
}
static uint8_t read(unsigned port,uint8_t shadow,bool inIpl,unsigned pc) {
  if(!active()) return shadow; port&=3; ++reads;
  if(boot&&(inIpl||iplStarted)) {
    // Ignore failed emulated polls. Verify each successful IPL echo on ESP.
    if(iplStarted&&port==0&&pending[port]&&shadow==last[port]) { cmd(0x10,0,last[0]); cmd(0x11,port,shadow); pending[port]=0; if(jumpPending) { cmd(0x14,0x20,0x4e); flush(); boot=false; jumpPending=false; log("IPL jump: ordered barrier"); } else if(queue.size()>=1200) flush(); }
    return shadow;
  }
  if(boot) { char m[90]; snprintf(m,sizeof(m),"IPL exit input=%02X %02X %02X %02X",last[0],last[1],last[2],last[3]); log(m); if(pending[0]) { cmd(0x10,0,last[0]); pending[0]=0; } if(!flush()) return shadow; boot=false; log("IPL complete: switching to real port reads"); }
  cmd(0x12,port); std::vector<uint8_t> r; if(!flush(&r)||r.size()!=1) return shadow;
  if(liveReads++<40 || liveReads%2048==0) { char m[100]; snprintf(m,sizeof(m),"read port=%u real=%02X shadow=%02X smpPC=%04X",port,r[0],shadow,pc); log(m); }
  actual[port]=r[0]; if(port<=1 && actual[0]==0xaa&&actual[1]==0xbb) readyForIpl=true;
  return r[0];
}
static void recordFrame() { static unsigned frames=0; if(++frames%300==0) { char m[90]; snprintf(m,sizeof(m),"video frame=%u hardware_failed=%u",frames,unsigned(failed)); log(m); } }
static void frame() { if(active()&&!boot) flush(); }
static void close() { if(serial!=INVALID_HANDLE_VALUE) { queue.clear(); if(!failed) { cmd(0x15); std::vector<uint8_t> stopped; if(flush(&stopped) && stopped.size()==2 && stopped[0]==0xaa && stopped[1]==0xbb) log("SHVC stopped: real IPL AA/BB confirmed"); else log("SHVC stop not confirmed"); } CloseHandle(serial); serial=INVALID_HANDLE_VALUE; } tried=false; failed=false; if(logfile) { fclose(logfile); logfile=nullptr; } }
}
