#pragma once
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <poll.h>
#include <fcntl.h>
#include <unistd.h>
#include <ctime>
#include <cerrno>
#include <cstdint>
using HANDLE=int;
using DWORD=unsigned long;
#define INVALID_HANDLE_VALUE (-1)
static unsigned long GetTickCount() {
  timespec time; clock_gettime(CLOCK_MONOTONIC,&time);
  return time.tv_sec*1000UL+time.tv_nsec/1000000UL;
}
static bool ReadFile(int fd,void *buffer,DWORD size,DWORD *received,void *) {
  ssize_t count; do { count=recv(fd,buffer,size,0); } while(count<0 && errno==EINTR);
  *received=count>0?DWORD(count):0; return count>=0;
}
static bool WriteFile(int fd,const void *buffer,DWORD size,DWORD *sent,void *) {
  *sent=0; auto data=static_cast<const uint8_t*>(buffer);
  while(*sent<size) {
    ssize_t count=send(fd,data+*sent,size-*sent,MSG_NOSIGNAL);
    if(count<0 && errno==EINTR) continue;
    if(count<=0) return false; *sent+=count;
  }
  return true;
}
static void CloseHandle(int fd) { close(fd); }
static int androidConnect(const char *host) {
  sockaddr_in address={}; address.sin_family=AF_INET; address.sin_port=htons(28954);
  if(inet_pton(AF_INET,host,&address.sin_addr)!=1) return -1;
  int fd=socket(AF_INET,SOCK_STREAM,0); if(fd<0) return -1;
  int flags=fcntl(fd,F_GETFL,0); fcntl(fd,F_SETFL,flags|O_NONBLOCK);
  int result=connect(fd,reinterpret_cast<sockaddr*>(&address),sizeof(address));
  if(result<0 && errno==EINPROGRESS) {
    pollfd poller={fd,POLLOUT,0};
    if(poll(&poller,1,3000)>0) { int error=0; socklen_t size=sizeof(error); getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&size); result=error?-1:0; }
  }
  if(result<0) { close(fd); return -1; }
  fcntl(fd,F_SETFL,flags); int enabled=1; setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&enabled,sizeof(enabled));
  timeval timeout={3,0}; setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
  setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
  return fd;
}
