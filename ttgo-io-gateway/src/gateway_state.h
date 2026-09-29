#pragma once
#include <ArduinoJson.h>
#include <WiFi.h>
#include <WebServer.h>
#include "gateway_policy.h"
#include "tilt_protocol.h"

constexpr int MAX_MOTORS=32;
uint32_t motors[MAX_MOTORS]={};
int motorCount=0;
struct MotorState {
 String id,name,kind;
 float position=0,tilt=0,rssi=0;
 uint32_t seen=0,tiltSeen=0,rssiSeen=0, nextQuery=0, trackingUntil=0;
 bool valid=false,tiltValid=false,queryTilt=false,rssiValid=false;
 String result="unknown";
};
MotorState motorStates[MAX_MOTORS];
bool motionEnabled=false, pollingEnabled=false, keyPresent=false;
String apiToken,espId;

void gatewayRssi(uint32_t target,float rssi){
 for(int i=0;i<motorCount;i++)if(motors[i]==target){
  motorStates[i].rssi=rssi;motorStates[i].rssiSeen=millis();motorStates[i].rssiValid=true;
 }
}

bool gatewayControlAllowed(int closure){
 return radioAllowed(keyPresent,motionEnabled,pollingEnabled,closure);
}
void gatewayResult(uint32_t target,const uint8_t* data,size_t size,const char* result,bool tiltRequest=false){
 for(int i=0;i<motorCount;i++)if(motors[i]==target){
  auto& state=motorStates[i];state.result=result;
  if(String(result)=="response"){
   if(decodePosition(data,size,state.position)){state.seen=millis();state.valid=true;}
   else if(!tiltRequest)state.valid=false;
   if(state.kind=="blind"&&decodeTilt(data,size,state.tilt)){state.tiltSeen=millis();state.tiltValid=true;}
   else if(tiltRequest)state.tiltValid=false;
  }else if(tiltRequest)state.tiltValid=false;
  else state.valid=false;
 }
}
