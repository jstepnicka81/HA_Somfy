#pragma once
#include <Preferences.h>
#include <mbedtls/aes.h>
#include <esp_system.h>
uint32_t ownNode=0;
bool cryptoOk=false;
bool cryptBlock(const uint8_t* data,size_t len,const uint8_t* nonce,const uint8_t* key,uint8_t* out){
 uint8_t iv[16];memset(iv,0x55,8);iv[8]=iv[9]=0;
 for(size_t i=0;i<len;i++){
  uint8_t t=data[i]^iv[9],a=iv[8];
  iv[8]=((a&0x7f)<<1)|(t>>7);iv[9]=t<<1;
  if(a&0x80){iv[8]^=0x55;iv[9]^=0x5b;}
  if(i<8)iv[i]=data[i];
 }
 memcpy(iv+10,nonce,6);
 mbedtls_aes_context ctx;mbedtls_aes_init(&ctx);
 int rc=mbedtls_aes_setkey_enc(&ctx,key,128);
 if(!rc)rc=mbedtls_aes_crypt_ecb(&ctx,MBEDTLS_AES_ENCRYPT,iv,out);
 mbedtls_aes_free(&ctx);return rc==0;
}
uint32_t addr(const uint8_t* b){return uint32_t(b[0])<<16|uint32_t(b[1])<<8|b[2];}
void putAddr(uint8_t* b,uint32_t a){b[0]=a>>16;b[1]=a>>8;b[2]=a;}

void keyInit(){
 // Public AES-128 zero-key/zero-block known-answer test; no installation key.
 const uint8_t expected[16]={0x66,0xe9,0x4b,0xd4,0xef,0x8a,0x2c,0x3b,0x88,0x4c,0xfa,0x59,0xca,0x34,0x2b,0x2e};
 uint8_t zero[16]={},result[16]={};
 mbedtls_aes_context ctx;mbedtls_aes_init(&ctx);
 int rc=mbedtls_aes_setkey_enc(&ctx,zero,128);
 if(!rc)rc=mbedtls_aes_crypt_ecb(&ctx,MBEDTLS_AES_ENCRYPT,zero,result);
 mbedtls_aes_free(&ctx);cryptoOk=!rc&&!memcmp(result,expected,16);
 Preferences prefs;prefs.begin("io-receiver",false);
 ownNode=prefs.getUInt("node",0);
 if(!ownNode){ownNode=0xf00000|(esp_random()&0x0fffff);prefs.putUInt("node",ownNode);}
 bool stored=prefs.getBytesLength("key")==16;prefs.end();
 Serial.printf("{\"status\":\"key_receiver_ready\",\"node\":\"%06lx\",\"crypto_selftest\":%s,\"key_stored\":%s}\n",ownNode,cryptoOk?"true":"false",stored?"true":"false");
}
