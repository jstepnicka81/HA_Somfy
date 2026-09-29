#pragma once

WebServer server(80);
bool networkConfigured=false,serverStarted=false;
CommandQueue commandQueue;
String recentRequests[32];int recentCursor=0;
String provisionLine;bool provisionReading=false,provisionOverflow=false;
uint32_t nextRadio=0;
int queryCursor=0;

void respond(int status,const char* message){
 StaticJsonDocument<192> doc;doc["result"]=message;
 String body;serializeJson(doc,body);server.send(status,"application/json",body);
}
bool tokenValid(){
 String supplied=server.header("Authorization"),expected="Bearer "+apiToken;
 unsigned diff=supplied.length()^expected.length();
 for(unsigned i=0;i<expected.length();i++)diff|=uint8_t(expected[i])^uint8_t(i<supplied.length()?supplied[i]:0);
 return apiToken.length()>=32&&!diff;
}
bool authorized(){if(tokenValid())return true;respond(401,"unauthorized");return false;}
#include "gateway_ota.h"
bool parseBody(JsonDocument& doc){
 if(server.arg("plain").length()>12288 || deserializeJson(doc,server.arg("plain"))){respond(400,"invalid_json");return false;}
 return true;
}
bool decodeDevices(JsonArray rows,uint32_t* addresses,MotorState* states,int& count){
 if(rows.isNull()||rows.size()>MAX_MOTORS)return false;
 count=0;
 for(JsonObject row:rows){
  if(!row["address"].is<uint32_t>()||!row["id"].is<const char*>()||!row["name"].is<const char*>()||!row["kind"].is<const char*>())return false;
  uint32_t address=row["address"];
  char identity[16];snprintf(identity,sizeof(identity),"io-%06lx",address);
  String kind=row["kind"].as<String>(),name=row["name"].as<String>();
  if(!address||address>=0xffffff||address==ownNode||row["id"].as<String>()!=identity||name.length()>256||(kind!="blind"&&kind!="shutter"))return false;
  for(int j=0;j<count;j++)if(addresses[j]==address)return false;
  addresses[count]=address;states[count].id=identity;states[count].name=name;states[count].kind=kind;
  count++;
 }
 return true;
}
void writeInventory(JsonArray rows){
 for(int i=0;i<motorCount;i++){
  auto d=rows.createNestedObject();d["id"]=motorStates[i].id;d["address"]=motors[i];
  d["name"]=motorStates[i].name;d["kind"]=motorStates[i].kind;
 }
}
void jsonResponse(JsonDocument& doc){String body;serializeJson(doc,body);server.send(200,"application/json",body);}
void infoHandler(){
 if(!authorized())return;
 DynamicJsonDocument doc(16384);doc["api_version"]=1;doc["id"]=espId;doc["node"]=ownNode;
 doc["firmware"]="0.2.2";doc["ota_supported"]=true;doc["motion_enabled"]=motionEnabled;doc["polling_enabled"]=pollingEnabled;doc["key_present"]=keyPresent;
 writeInventory(doc.createNestedArray("devices"));jsonResponse(doc);
}
void statesHandler(){
 if(!authorized())return;
 DynamicJsonDocument doc(16384);doc["id"]=espId;doc["node"]=ownNode;doc["motion_enabled"]=motionEnabled;
 JsonObject rows=doc.createNestedObject("devices");
 for(int i=0;i<motorCount;i++){
  auto& state=motorStates[i];auto d=rows.createNestedObject(state.id);
  bool fresh=state.valid && millis()-state.seen<120000;
  bool tiltFresh=state.kind=="blind"&&state.tiltValid&&millis()-state.tiltSeen<120000;
  d["available"]=fresh||tiltFresh;d["last_result"]=state.result;
  if(state.rssiValid&&millis()-state.rssiSeen<120000)d["rssi_dbm"]=state.rssi;
  else d["rssi_dbm"]=nullptr;
  d["tilt_supported"]=state.kind=="blind";
  if(tiltFresh)d["tilt_position"]=state.tilt;else d["tilt_position"]=nullptr;
  if(fresh)d["position"]=state.position;else d["position"]=nullptr;
 }
 jsonResponse(doc);
}
void devicesHandler(){
 if(!authorized())return;
 if(controlActive||commandQueue.size()){respond(409,"busy");return;}
 DynamicJsonDocument doc(16384);if(!parseBody(doc))return;
 uint32_t addresses[MAX_MOTORS]={};MotorState states[MAX_MOTORS];int count=0;
 if(!decodeDevices(doc["devices"].as<JsonArray>(),addresses,states,count)){respond(400,"invalid_devices");return;}
 String stored;serializeJson(doc["devices"],stored);
 Preferences p;if(!p.begin("io-gateway",false)){respond(500,"storage_error");return;}
 bool saved=p.putString("devices",stored)==stored.length();p.end();
 if(!saved){respond(500,"storage_error");return;}
 motorCount=count;
 for(int i=0;i<count;i++){motors[i]=addresses[i];motorStates[i]=states[i];motorStates[i].nextQuery=millis()+1000+i*3000;}
 respond(200,"configured");
}
void commandHandler(){
 if(!authorized())return;
 if(!motionEnabled){respond(423,"motion_locked");return;}
 if(!keyPresent||!cryptoOk){respond(503,"missing_key");return;}
 DynamicJsonDocument doc(1024);if(!parseBody(doc))return;
 String id=doc["id"]|"",action=doc["action"]|"",request=doc["request_id"]|"";
 if(request.length()!=32){respond(400,"invalid_request_id");return;}
 for(char c:request)if(!isxdigit(c)){respond(400,"invalid_request_id");return;}
 int index=-1;for(int i=0;i<motorCount;i++)if(motorStates[i].id==id)index=i;
 if(index<0){respond(404,"unassigned_device");return;}
 int closure=-2;
 if(action=="position"||action=="tilt"){
  if(action=="tilt"&&motorStates[index].kind!="blind"){respond(400,"unsupported_action");return;}
  if(!doc["position"].is<int>()||doc["position"].as<int>()<0||doc["position"].as<int>()>100){respond(400,"invalid_position");return;}
  closure=100-doc["position"].as<int>();
 }else if(action!="stop"){respond(400,"unsupported_action");return;}
 for(const auto& prior:recentRequests)if(prior==request){respond(200,"duplicate");return;}
 if(action=="stop"){
  // Cancel queued moves for this motor. STOP preempts the active RF exchange.
  commandQueue.remove(index);
  if(controlActive){gatewayResult(controlTarget,nullptr,0,"interrupted",controlTilt);controlStop();}
  controlStart(index+1,-2);
  motorStates[index].nextQuery=millis()+1500;motorStates[index].trackingUntil=millis()+10000;
 }else{
  // Each axis has its own target. STOP still cancels both axes.
  if(!commandQueue.put(index,closure,millis(),action=="tilt")){respond(429,"queue_full");return;}
  motorStates[index].result="queued";
 }
 recentRequests[recentCursor]=request;recentCursor=(recentCursor+1)%32;
 respond(202,"accepted");
}

// Provisioning is USB-only and never echoes secrets. No network key import/export.
// One line: ^{"ssid":...,"password":...,"token":...,"motion_enabled":false,"polling_enabled":false}
void provision(const String& input){
 if(controlActive||commandQueue.size()){Serial.println("{\"provision\":\"busy\"}");return;}
 DynamicJsonDocument doc(2048);
 if(deserializeJson(doc,input)||!doc["ssid"].is<const char*>()||!doc["password"].is<const char*>()||!doc["token"].is<const char*>()||
    !doc["motion_enabled"].is<bool>()||!doc["polling_enabled"].is<bool>()){
  Serial.println("{\"provision\":\"invalid\"}");return;
 }
 String ssid=doc["ssid"],password=doc["password"],token=doc["token"];
 if(ssid.length()<1||ssid.length()>32||password.length()>63||token.length()!=64){Serial.println("{\"provision\":\"invalid\"}");return;}
 if(doc["motion_enabled"].as<bool>()&&!doc["polling_enabled"].as<bool>()){Serial.println("{\"provision\":\"invalid\"}");return;}
 for(char c:token)if(!isxdigit(c)){Serial.println("{\"provision\":\"invalid\"}");return;}
 // Optional existing io key for another ESP; its own NVS node is preserved.
 if(doc.containsKey("io_key")){
  String key=doc["io_key"]|"";if(key.length()!=32){Serial.println("{\"provision\":\"invalid\"}");return;}
  for(char c:key)if(!isxdigit(c)){Serial.println("{\"provision\":\"invalid\"}");return;}
  uint8_t bytes[16];for(int i=0;i<16;i++)bytes[i]=strtoul(key.substring(i*2,i*2+2).c_str(),nullptr,16);
  Preferences p;p.begin("io-receiver",false);
  uint8_t existing[16];bool ok=false;
  if(p.getBytesLength("key")==16){p.getBytes("key",existing,16);ok=memcmp(existing,bytes,16)==0;}
  else ok=p.putBytes("key",bytes,16)==16;
  p.end();memset(existing,0,16);memset(bytes,0,16);
  if(!ok){Serial.println("{\"provision\":\"storage_error\"}");return;}
 }
 Preferences p;p.begin("io-gateway",false);
 // A single blob commits the complete network configuration.
 String stored;doc.remove("io_key");serializeJson(doc,stored);
 bool saved=p.putString("network",stored)==stored.length();p.end();
 Serial.println(saved?"{\"provision\":\"saved_restart_required\"}":"{\"provision\":\"storage_error\"}");
}
void gatewaySetup(){
 uint64_t mac=ESP.getEfuseMac();char identity[24];snprintf(identity,sizeof(identity),"esp-%04x%08lx",uint16_t(mac>>32),uint32_t(mac));espId=identity;
 Preferences key;key.begin("io-receiver",true);keyPresent=key.getBytesLength("key")==16;key.end();
 Preferences p;p.begin("io-gateway",true);String network=p.getString("network","{}"),devices=p.getString("devices","[]");p.end();
 DynamicJsonDocument doc(16384);
 if(!deserializeJson(doc,devices)){
  if(!decodeDevices(doc.as<JsonArray>(),motors,motorStates,motorCount))motorCount=0;
 }
 for(int i=0;i<motorCount;i++)motorStates[i].nextQuery=millis()+5000+i*3000;
 doc.clear();if(deserializeJson(doc,network))return;
 apiToken=doc["token"]|"";motionEnabled=doc["motion_enabled"]|false;pollingEnabled=doc["polling_enabled"]|false;
 String ssid=doc["ssid"]|"",password=doc["password"]|"";
 networkConfigured=ssid.length() && apiToken.length()==64;
 Serial.printf("{\"status\":\"gateway_ready\",\"firmware\":\"0.2.2\",\"network_configured\":%s,\"motion_enabled\":%s,\"polling_enabled\":%s}\n",networkConfigured?"true":"false",motionEnabled?"true":"false",pollingEnabled?"true":"false");
 if(!networkConfigured)return;
 WiFi.persistent(false);WiFi.mode(WIFI_STA);WiFi.setAutoReconnect(true);WiFi.begin(ssid.c_str(),password.c_str());
 const char* headers[]={"Authorization","X-Firmware-Size","X-Firmware-SHA256"};server.collectHeaders(headers,3);
 server.on("/api/v1/info",HTTP_GET,infoHandler);server.on("/api/v1/states",HTTP_GET,statesHandler);
 server.on("/api/v1/devices",HTTP_PUT,devicesHandler);server.on("/api/v1/command",HTTP_POST,commandHandler);
 server.on("/api/v1/ota",HTTP_POST,otaHandler,otaUpload);
 server.onNotFound([](){respond(404,"not_found");});
}
void gatewayTick(){
 // Diagnostic !/K/P/X commands are disabled in the network firmware.
 while(Serial.available()){
  char c=Serial.read();
  if(!provisionReading){if(c=='^'){provisionReading=true;provisionOverflow=false;provisionLine="";}continue;}
  if(c=='\n'){
   if(!provisionOverflow)provision(provisionLine);
   provisionLine="";provisionReading=false;
  }else if(provisionLine.length()<2048)provisionLine+=c;else provisionOverflow=true;
 }
 if(otaRebootAt){listening=false;wr(REG_OPMODE,1);if(int32_t(millis()-otaRebootAt)>=0)ESP.restart();return;}
 if(!networkConfigured){listening=false;wr(REG_OPMODE,1);return;}
 if(WiFi.status()!=WL_CONNECTED){
  PendingCommand dropped;
  while(commandQueue.pop(dropped))motorStates[dropped.index].result="connection_lost";
  if(controlActive){gatewayResult(controlTarget,nullptr,0,"connection_lost",controlTilt);controlStop();}
  listening=false;wr(REG_OPMODE,1);return;
 }
 if(!serverStarted){server.begin();serverStarted=true;}
 server.handleClient();
 if(otaReceiving||otaRebootAt){listening=false;wr(REG_OPMODE,1);return;}
 if(controlActive)return;
 PendingCommand cmd;
 if(commandQueue.pop(cmd)){
  if(CommandQueue::expired(cmd,millis())){motorStates[cmd.index].result="expired";return;}
  controlStart(cmd.index+1,cmd.closure,cmd.tilt);motorStates[cmd.index].nextQuery=millis()+3000;
  motorStates[cmd.index].queryTilt=cmd.tilt;
  if(cmd.tilt)motorStates[cmd.index].tiltValid=false;
  motorStates[cmd.index].trackingUntil=millis()+90000;return;
 }
 if(pollingEnabled&&keyPresent&&int32_t(millis()-nextRadio)>=0){
  for(int offset=0;offset<motorCount;offset++){
   int i=(queryCursor+offset)%motorCount;
   if(int32_t(millis()-motorStates[i].nextQuery)<0)continue;
   bool blind=motorStates[i].kind=="blind";
   controlStart(i+1,-1,blind&&motorStates[i].queryTilt);
   motorStates[i].queryTilt=blind&&!motorStates[i].queryTilt;
   motorStates[i].nextQuery=millis()+(int32_t(motorStates[i].trackingUntil-millis())>0?2000:(blind?15000:30000));
   nextRadio=millis()+1000;queryCursor=(i+1)%motorCount;return;
  }
 }
 // No continuous receive/hopping when there is no outstanding RF transaction.
 listening=false;wr(REG_OPMODE,1);
}
