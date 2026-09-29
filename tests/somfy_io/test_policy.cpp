#include <cassert>
#include "gateway_policy.h"
#include "tilt_protocol.h"
#include <cmath>
int main(){
 assert(!radioAllowed(true,false,false,0));
 assert(!radioAllowed(true,false,false,-2));
 assert(!radioAllowed(true,false,false,-1));
 assert(radioAllowed(true,false,true,-1));
 assert(!radioAllowed(false,true,true,100));
 CommandQueue q;PendingCommand c;
 assert(!q.pop(c));
 for(int i=0;i<8;i++)assert(q.put(i,50,100));
 assert(!q.put(8,50,100));
 assert(q.put(0,75,200));assert(q.size()==8);
 assert(q.pop(c)&&c.index==0&&c.closure==75&&c.queued==200);
 // STOP cancels all waiting motion for its motor, leaving other motors intact.
 q.remove(3);assert(q.size()==6);
 while(q.pop(c))assert(c.index!=3);
 assert(q.put(2,10,0));q.clear();assert(!q.pop(c));
 c={0,0,0xfffffff0,false};
 assert(!CommandQueue::expired(c,20));
 assert(CommandQueue::expired(c,6000));
 // A fresh queue after reboot cannot replay prior commands.
 CommandQueue rebooted;assert(rebooted.size()==0);
 // Changing tilt must not replace a queued height for the same motor.
 assert(q.put(0,10,100));assert(q.put(0,20,100,true));
 assert(q.put(0,30,200,true));assert(q.size()==2);
 assert(q.pop(c)&&!c.tilt&&c.closure==10);
 assert(q.pop(c)&&c.tilt&&c.closure==30);
 assert(q.put(0,10,100));assert(q.put(0,20,100,true));
 q.remove(0);assert(q.size()==0);
 // Anonymized motor-response fixtures. Target=54%,
 // actual closure=53.958984%; tilt varies independently.
 uint8_t reply[]={5,0,0x6c,0,0x6b,0xeb,0,0,0x12,0x34,0x56,1,0x20,0xc8,0,0};
 float height=-1,tilt=-1;
 assert(decodePosition(reply,sizeof(reply),height));
 assert(std::fabs(height-46.041015625f)<0.0001f);
 assert(decodeTilt(reply,sizeof(reply),tilt)&&tilt==0);
 reply[13]=0;assert(decodeTilt(reply,sizeof(reply),tilt)&&tilt==100);
 reply[13]=0x60;reply[14]=0x8d;
 assert(decodeTilt(reply,sizeof(reply),tilt));
 assert(std::fabs(tilt-51.724609375f)<0.0001f);
 assert(!decodeTilt(reply,14,tilt));
 reply[12]=0;assert(!decodeTilt(reply,sizeof(reply),tilt));
 reply[12]=0x20;reply[13]=0xff;assert(!decodeTilt(reply,sizeof(reply),tilt));
 assert(!decodePosition(nullptr,6,height));
 reply[4]=0xff;assert(!decodePosition(reply,sizeof(reply),height));
 // Command preserves height with D400, not the captured fixed 6C00.
 uint8_t command[9];buildTiltCommand(50,command);
 const uint8_t expected[]={0,1,0xe7,0xd4,0,0x20,0x64,0,0};
 for(unsigned i=0;i<9;i++)assert(command[i]==expected[i]);
 buildTiltCommand(100,command);assert(command[6]==0xc8&&command[7]==0);
 buildTiltCommand(0,command);assert(command[6]==0&&command[7]==0);
}
