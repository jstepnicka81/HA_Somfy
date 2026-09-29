#pragma once
#include <Update.h>
#include <mbedtls/sha256.h>

bool otaReceiving=false;
uint32_t otaRebootAt=0;
size_t otaExpected=0,otaReceived=0;
int otaStatus=400;
const char* otaResult="missing_firmware";
String otaHash;
mbedtls_sha256_context otaSha;

void otaFail(int status,const char* result){
 if(otaReceiving){Update.abort();mbedtls_sha256_free(&otaSha);}
 otaReceiving=false;otaStatus=status;otaResult=result;
}
void otaUpload(){
 HTTPUpload& upload=server.upload();
 if(upload.status==UPLOAD_FILE_START){
  otaStatus=400;otaResult="invalid_upload";
  if(!tokenValid()){otaFail(401,"unauthorized");return;}
  if(otaRebootAt||controlActive||commandQueue.size()){otaFail(409,"busy");return;}
  if(upload.name!="firmware"){otaFail(400,"invalid_field");return;}
  String length=server.header("X-Firmware-Size");otaHash=server.header("X-Firmware-SHA256");
  if(length.length()==0||length.length()>7||otaHash.length()!=64){otaFail(400,"invalid_metadata");return;}
  for(char c:length)if(c<'0'||c>'9'){otaFail(400,"invalid_size");return;}
  for(char c:otaHash)if(!isxdigit(c)){otaFail(400,"invalid_sha256");return;}
  otaHash.toLowerCase();otaExpected=strtoul(length.c_str(),nullptr,10);otaReceived=0;
  if(otaExpected<32||otaExpected>ESP.getFreeSketchSpace()){otaFail(413,"firmware_too_large");return;}
  listening=false;wr(REG_OPMODE,1);
  if(!Update.begin(otaExpected,U_FLASH)){otaFail(500,"ota_begin_failed");return;}
  mbedtls_sha256_init(&otaSha);mbedtls_sha256_starts_ret(&otaSha,0);otaReceiving=true;
 }else if(upload.status==UPLOAD_FILE_WRITE&&otaReceiving){
  if(otaReceived+upload.currentSize>otaExpected){otaFail(400,"size_mismatch");return;}
  if(Update.write(upload.buf,upload.currentSize)!=upload.currentSize){otaFail(500,"ota_write_failed");return;}
  mbedtls_sha256_update_ret(&otaSha,upload.buf,upload.currentSize);otaReceived+=upload.currentSize;
 }else if(upload.status==UPLOAD_FILE_END&&otaReceiving){
  if(otaReceived!=otaExpected){otaFail(400,"size_mismatch");return;}
  uint8_t digest[32];mbedtls_sha256_finish_ret(&otaSha,digest);
  char hex[65];for(int i=0;i<32;i++)snprintf(hex+2*i,3,"%02x",digest[i]);
  if(otaHash!=hex){otaFail(400,"sha256_mismatch");return;}
  mbedtls_sha256_free(&otaSha);otaReceiving=false;
  if(!Update.end()){Update.abort();otaStatus=400;otaResult="invalid_firmware";return;}
  otaStatus=200;otaResult="updated_restart_pending";otaRebootAt=millis()+1500;
 }else if(upload.status==UPLOAD_FILE_ABORTED){otaFail(400,"upload_aborted");}
}
void otaHandler(){
 if(!tokenValid()){respond(401,"unauthorized");return;}
 if(otaReceiving)otaFail(400,"incomplete_upload");
 respond(otaStatus,otaResult);
 otaStatus=400;otaResult="missing_firmware";
}
