// Bounded radio transactions for devices assigned by Home Assistant.
bool controlActive=false;
bool controlTilt=false;
uint32_t controlTarget=0,controlNext=0;
uint8_t controlData[9],controlSize=0,controlAttempt=0,controlTx=0;
uint8_t controlKey[16];

void controlStop(){controlActive=false;memset(controlKey,0,16);}
bool controlSend(uint8_t cmd,const uint8_t* payload,size_t size,uint8_t flags,bool cold){
 if(!controlActive||controlTx>=8||size>16)return false;
 uint8_t b[32];size_t n=9+size;b[0]=flags|(n-1);b[1]=0;
 putAddr(b+2,controlTarget);putAddr(b+5,ownNode);b[8]=cmd;
 if(size)memcpy(b+9,payload,size);
 delay(cold?1:5);
 wr(REG_OPMODE,1);wr(REG_IRQFLAGS2,RF_IRQFLAGS2_FIFOOVERRUN);
 wr(REG_SYNCCONFIG,0x51);wr(REG_PREAMBLEMSB,0);wr(REG_PREAMBLELSB,cold?128:16);
 wr(REG_PACONFIG,0x88);wr(REG_FIFOTHRESH,0x80);
 for(size_t i=0;i<n;i++)wr(REG_FIFO,b[i]);
 wr(REG_OPMODE,3);uint32_t start=millis();
 while(!(rd(REG_IRQFLAGS2)&RF_IRQFLAGS2_PACKETSENT)&&millis()-start<150)delayMicroseconds(100);
 bool sent=rd(REG_IRQFLAGS2)&RF_IRQFLAGS2_PACKETSENT;
 wr(REG_OPMODE,1);wr(REG_SYNCCONFIG,0x52);tune();controlTx++;
 Serial.printf("{\"status\":\"control_tx\",\"target\":%lu,\"cmd\":%u,\"sent\":%s}\n",controlTarget,cmd,sent?"true":"false");
 return sent;
}
void controlStart(int index,int closure,bool tilt=false){
 // -1=query, -2=stop at current position. Stop may replace an in-flight request.
 if(index<1||index>motorCount||closure< -2||closure>100||(controlActive&&closure!=-2)||!cryptoOk){Serial.println("{\"status\":\"control_rejected\"}");return;}
 if(!gatewayControlAllowed(closure))return;
 if(tilt&&(motorStates[index-1].kind!="blind"||closure==-2))return;
 if(closure==-2)controlStop();
 Preferences prefs;prefs.begin("io-receiver",true);size_t n=prefs.getBytes("key",controlKey,16);prefs.end();
 if(n!=16){Serial.println("{\"status\":\"missing_key\"}");return;}
 controlTarget=motors[index-1];controlAttempt=controlTx=0;controlActive=true;controlTilt=tilt;
 if(closure==-1){controlData[0]=3;controlData[1]=3;controlData[2]=0;controlData[3]=0;controlSize=4;}
 else{uint16_t mp=closure==-2?0xd200:closure*512;uint8_t d[]={0,1,0xe7,uint8_t(mp>>8),uint8_t(mp),0,0};memcpy(controlData,d,7);controlSize=7;}
 if(tilt){
  if(closure==-1){uint8_t d[]={3,3,0x20,1,0};memcpy(controlData,d,5);controlSize=5;}
  else{buildTiltCommand(closure,controlData);controlSize=9;}
 }
 controlNext=millis();started=millis();listening=true;
 Serial.printf("{\"status\":\"control_started\",\"target\":%lu,\"closure\":%d,\"source\":%lu}\n",controlTarget,closure,ownNode);
}
void controlTick(){
 if(!controlActive||int32_t(millis()-controlNext)<0)return;
 if(controlAttempt>=3){Serial.println("{\"status\":\"control_timeout\"}");
 gatewayResult(controlTarget,nullptr,0,"timeout",controlTilt);
 controlStop();return;}
 ch=controlAttempt++;tune();controlSend(controlData[0],controlData+1,controlSize-1,0x40,true);controlNext=millis()+1000;
}
void controlPacket(const uint8_t* b,size_t n,bool crc,float rssi){
 if(!controlActive||!crc||n<9||n!=(b[0]&31)+1||(b[0]&32)||addr(b+5)!=controlTarget||addr(b+2)!=ownNode)return;
 const uint8_t* data=b+9;size_t size=n-9;
 // Only CRC-valid replies from the addressed motor, never our TX or Wi-Fi.
 if((b[8]==0x3c&&size==6)||b[8]==4||b[8]==0xfe)gatewayRssi(controlTarget,rssi);
 if(b[8]==0x3c&&size==6){
  uint8_t mac[16];if(cryptBlock(controlData,controlSize,data,controlKey,mac))controlSend(0x3d,mac,6,0,false);
  controlNext=millis()+1000;return;
 }
 if(b[8]==4||b[8]==0xfe){
  gatewayResult(controlTarget,data,size,b[8]==4?"response":"motor_error",controlTilt);
  Serial.printf("{\"status\":\"control_response\",\"target\":%lu,\"cmd\":%u,\"payload\":\"",controlTarget,b[8]);
  for(size_t i=0;i<size;i++)Serial.printf("%02x",data[i]);Serial.println("\"}");controlStop();
 }
}
