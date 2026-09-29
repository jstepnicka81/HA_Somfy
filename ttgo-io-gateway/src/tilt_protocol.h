#pragma once
#include <stdint.h>
#include <stddef.h>

// CMD04 Private responses with separate current-position and tilt fields. Targets at 2..3
// must never be reported as current position (4..5).
inline bool decodePosition(const uint8_t* data,size_t size,float& position){
 if(!data||size<6||(data[0]!=4&&data[0]!=5))return false;
 uint16_t raw=uint16_t(data[4])<<8|data[5];
 if(raw>51200)return false;
 position=100.0f-raw/512.0f;return true;
}
inline bool decodeTilt(const uint8_t* data,size_t size,float& tilt){
 if(!data||size<15||data[0]!=5||data[12]!=0x20)return false;
 uint16_t raw=uint16_t(data[13])<<8|data[14];
 if(raw>51200)return false;
 tilt=100.0f-raw/512.0f;return true;
}
inline void buildTiltCommand(uint8_t closure,uint8_t* data){
 // MP D400 preserves height, following io-openknx; verified on hardware.
 // Never substitute a fixed height.
 uint16_t raw=uint16_t(closure)*512;
 const uint8_t command[]={0,1,0xe7,0xd4,0,0x20,uint8_t(raw>>8),uint8_t(raw),0};
 for(size_t i=0;i<sizeof(command);i++)data[i]=command[i];
}
