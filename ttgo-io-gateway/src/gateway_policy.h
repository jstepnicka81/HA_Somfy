#pragma once
#include <stdint.h>

inline bool radioAllowed(bool key,bool motion,bool polling,int closure){
 return key && (closure==-1?polling:motion);
}
struct PendingCommand{int index,closure;uint32_t queued;bool tilt;};
class CommandQueue {
 PendingCommand items[8];
 int count=0;
 public:
 int size() const{return count;}
 void clear(){count=0;}
 void remove(int index){
  for(int i=count-1;i>=0;i--)if(items[i].index==index){for(int j=i;j<count-1;j++)items[j]=items[j+1];count--;}
 }
 bool put(int index,int closure,uint32_t now,bool tilt=false){
  int slot=-1;for(int i=0;i<count;i++)if(items[i].index==index&&items[i].tilt==tilt)slot=i;
  if(slot<0){if(count==8)return false;slot=count++;}
  items[slot]={index,closure,now,tilt};return true;
 }
 bool pop(PendingCommand& result){
  if(!count)return false;
  result=items[0];for(int i=0;i<count-1;i++)items[i]=items[i+1];count--;return true;
 }
 static bool expired(const PendingCommand& item,uint32_t now){return uint32_t(now-item.queued)>5000;}
};
