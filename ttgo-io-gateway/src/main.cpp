// RX configuration adapted from charlyschulte/esphome-io-homecontrol.
// Apache-2.0 portions; see LICENSES and NOTICE. Gateway adaptation adds
// authenticated motor commands, network provisioning and OTA.
#include <Arduino.h>
#include <SPI.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Update.h>
#include "sx1276_regs_fsk.h"
constexpr int CS=18, RST=14;
const uint32_t channels[]={868250000,868950000,869850000};
uint8_t ch=0;
uint32_t tuned=0, lastPacket=0, started=0, count=0, heartbeat=0;
bool listening=false;
uint8_t rd(uint8_t a){
 SPI.beginTransaction(SPISettings(1000000,MSBFIRST,SPI_MODE0));
 digitalWrite(CS,LOW);SPI.transfer(a&0x7f);uint8_t v=SPI.transfer(0);
 digitalWrite(CS,HIGH);SPI.endTransaction();return v;
}
void wr(uint8_t a,uint8_t v){
 SPI.beginTransaction(SPISettings(1000000,MSBFIRST,SPI_MODE0));
 digitalWrite(CS,LOW);SPI.transfer(a|0x80);SPI.transfer(v);
 digitalWrite(CS,HIGH);SPI.endTransaction();
}
void tune(){
 wr(REG_OPMODE,0x01); // FSK standby, HF band; this helper only tunes RX.
 uint32_t f=(uint64_t(channels[ch])<<19)/32000000;
 wr(REG_FRFMSB,f>>16);wr(REG_FRFMID,f>>8);wr(REG_FRFLSB,f);
 wr(REG_IRQFLAGS2,RF_IRQFLAGS2_FIFOOVERRUN);
 wr(REG_OPMODE,0x05);tuned=millis();
}
#include "io_crypto.h"
#include "gateway_state.h"
#include "blind_control.h"
#include "gateway_api.h"
void setup(){
 Serial.begin(115200);delay(1000);
 pinMode(CS,OUTPUT);digitalWrite(CS,HIGH);
 pinMode(RST,OUTPUT);digitalWrite(RST,LOW);delay(2);digitalWrite(RST,HIGH);delay(20);
 SPI.begin(5,19,27,CS);
 Serial.printf("{\"status\":\"boot\",\"version\":%u,\"xtal_mhz\":%u,\"tx_enabled\":false}\n",rd(REG_VERSION),getXtalFrequencyMhz());
 if(rd(REG_VERSION)!=0x12){while(true)delay(1000);}
 // Diagnose tuning without transmitting. Same silicon version can be used
 // by different RF variants; PLL behaviour alone is not model identification.
 for(uint32_t f: {433920000UL,868950000UL}){
  uint8_t band=f<525000000?8:0;
  wr(REG_OPMODE,band);delay(5);wr(REG_OPMODE,band|1);
  uint32_t v=(uint64_t(f)<<19)/32000000;
  wr(REG_FRFMSB,v>>16);wr(REG_FRFMID,v>>8);wr(REG_FRFLSB,v);
  wr(REG_OPMODE,band|4);delay(100);
  Serial.printf("{\"test_frequency\":%lu,\"irq1\":%u,\"opmode\":%u,\"frf\":%lu}\n",f,rd(REG_IRQFLAGS1),rd(REG_OPMODE),(uint32_t(rd(REG_FRFMSB))<<16)|(uint32_t(rd(REG_FRFMID))<<8)|rd(REG_FRFLSB));
 }
 wr(REG_OPMODE,0x00);delay(2);wr(REG_OPMODE,0x01);
 uint32_t bitrate=32000000UL/38400UL;
 wr(REG_BITRATEMSB,bitrate>>8);wr(REG_BITRATELSB,bitrate);
 uint16_t dev=(uint64_t(19200)<<19)/32000000;
 wr(REG_FDEVMSB,dev>>8);wr(REG_FDEVLSB,dev);
 wr(REG_OSC,RF_OSC_CLKOUT_OFF);
 wr(REG_PACKETCONFIG1,RF_PACKETCONFIG1_PACKETFORMAT_VARIABLE|RF_PACKETCONFIG1_CRC_ON);
 wr(REG_PACKETCONFIG2,RF_PACKETCONFIG2_DATAMODE_PACKET|RF_PACKETCONFIG2_IOHOME_ON|0x10);
 wr(REG_SYNCCONFIG,RF_SYNCCONFIG_SYNC_ON|RF_SYNCCONFIG_SYNCSIZE_3);
 wr(REG_SYNCVALUE1,0xff);wr(REG_SYNCVALUE2,0x33);
 wr(REG_PAYLOADLENGTH,0xff);
 wr(REG_RSSICONFIG,RF_RSSICONFIG_SMOOTHING_8);
 wr(REG_RXCONFIG,RF_RXCONFIG_AFCAUTO_ON|RF_RXCONFIG_AGCAUTO_ON|RF_RXCONFIG_RXTRIGER_PREAMBLEDETECT|RF_RXCONFIG_RESTARTRXONCOLLISION_ON);
 wr(REG_RXBW,0x01);wr(REG_AFCBW,0x01);wr(REG_AFCFEI,0x01);
 wr(REG_LNA,RF_LNA_BOOST_ON|RF_LNA_GAIN_G1);
 wr(REG_PREAMBLEDETECT,RF_PREAMBLEDETECT_DETECTOR_ON|RF_PREAMBLEDETECT_DETECTORSIZE_2|RF_PREAMBLEDETECT_DETECTORTOL_10);
 keyInit();
 gatewaySetup();
 Serial.println("{\"status\":\"ready\",\"commands\":\"USB provisioning only\"}");
}
void loop(){
 gatewayTick();
 if(!listening){delay(1);return;}
 controlTick();
 if(millis()-started>=300000){listening=false;wr(REG_OPMODE,0x01);Serial.println("{\"status\":\"timeout\"}");return;}
 uint8_t irq2=rd(REG_IRQFLAGS2);
 if(irq2&RF_IRQFLAGS2_PAYLOADREADY){
  uint8_t data[66];unsigned n=0;float rssi=-0.5f*rd(REG_RSSIVALUE);
  while(!(rd(REG_IRQFLAGS2)&RF_IRQFLAGS2_FIFOEMPTY)&&n<sizeof(data))data[n++]=rd(REG_FIFO);
  bool crc=irq2&RF_IRQFLAGS2_CRCOK;count++;lastPacket=millis();
  Serial.printf("{\"ms\":%lu,\"frequency\":%lu,\"rssi_dbm\":%.1f,\"hw_crc\":%s,\"length\":%u,\"raw\":\"",lastPacket,channels[ch],rssi,crc?"true":"false",n);
  if(n>=9 && (data[8]==0x30 || data[8]==0x32))Serial.print("REDACTED_KEY_TRANSFER");
  else for(unsigned i=0;i<n;i++)Serial.printf("%02x",data[i]);
  Serial.println("\"}");
  controlPacket(data,n,crc,rssi);
  tune();
 }
 if(irq2&RF_IRQFLAGS2_FIFOOVERRUN)tune();
 // Stay through a packet and the immediate response; cap a false lock.
 uint8_t irq1=rd(REG_IRQFLAGS1);
 bool busy=irq1&(RF_IRQFLAGS1_PREAMBLEDETECT|RF_IRQFLAGS1_SYNCADDRESSMATCH);
 if(!controlActive && millis()-tuned>100 && millis()-lastPacket>100 && (!busy||millis()-tuned>200)){
  ch=(ch+1)%3;tune();
 }
 if(millis()-heartbeat>5000){
  heartbeat=millis();Serial.printf("{\"status\":\"rx\",\"packets\":%lu,\"frequency\":%lu,\"irq1\":%u,\"opmode\":%u}\n",count,channels[ch],rd(REG_IRQFLAGS1),rd(REG_OPMODE));
 }
 delayMicroseconds(100);
}
