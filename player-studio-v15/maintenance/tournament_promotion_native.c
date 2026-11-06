/* Game-thread-only native tournament progression window adapter.
 * No league flow, save, worker callback or retained UObject dereference.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef unsigned long uptr;
#define EXPORT __attribute__((used,visibility("hidden"),noinline))
#define SECTION(n) __attribute__((section(n),used,visibility("hidden")))
typedef struct {uptr factory,setup,object_array,confirm_caller,weak_assign,name,find_widget,opacity;} Imports;
SECTION(".text.imports") volatile Imports imports={0x333b1f0,0x33401d4,0x9fe79b8,0x3bba220,0x45ee3f8,0x4414bec,0x54f0ce4,0x54c7964};
typedef struct {
    u32 sequence,event;
    u64 generation,token[2];
    u32 kind,division;
    u16 text[3][128];
} Request;
typedef struct {
    u32 menu_sequence,event;
    uptr parent;
    u64 parent_ticket,generation,tick;
    Request request;
    u32 status_sequence,status;
    u64 ack_token[2];
    uptr actor;
    u64 actor_ticket,actor_generation;
    u32 consumed_sequence,reason;
    u64 ack_generation;
    u32 enabled;
} Bus;
_Static_assert(sizeof(Request)==808,"request ABI");
_Static_assert(__builtin_offsetof(Bus,status_sequence)==848,"status ABI");
_Static_assert(__builtin_offsetof(Bus,enabled)==912,"enable ABI");
static void fence(void){__asm__ volatile("dmb ish":::"memory");}
static void copy(volatile void *d,const volatile void *s,u32 n){
    volatile u8 *to=d;const volatile u8 *from=s;for(u32 i=0;i<n;++i)to[i]=from[i];
}
/* self is ALWAYS the incoming live engine callback object or factory result.
 * FUObjectItem serial distinguishes allocator/index reuse from this actor. */
static u64 ticket(uptr self,u32 create_serial){
    if(!self)return 0;
    int index=*(int*)(self+12);
    if(index<0||index>=16777216)return 0;
    uptr chunks=*(uptr*)(imports.object_array+16);
    if(!chunks)return 0;
    uptr chunk=*(uptr*)(chunks+((u32)index>>16)*8);
    if(!chunk)return 0;
    uptr item=chunk+((u32)index&65535)*24;
    if(*(uptr*)item!=self||(*(u32*)(item+8)&0x20000000))return 0;
    u32 serial=*(u32*)(item+16);
    if(!serial&&create_serial){
        u64 weak=0;((void(*)(void*,uptr))imports.weak_assign)(&weak,self);
        serial=*(u32*)(item+16);
    }
    if(!serial)return 0;
    return ((u64)serial<<32)|(u32)index;
}
static void status(volatile Bus *b,u32 value,u32 reason,const Request *r){
    u32 seq=(b->status_sequence+2)&~1u;b->status_sequence=seq|1u;fence();
    b->status=value;b->reason=reason;
    if(r){b->ack_token[0]=r->token[0];b->ack_token[1]=r->token[1];b->ack_generation=r->generation;}
    fence();b->status_sequence=seq;
}
EXPORT void studio_promotion(u32 action,volatile Bus *b,uptr self,uptr event,uptr caller){
    if(!self||!b||!b->enabled)return;
    /* Destruction may already carry PendingKill. It can abandon our own
     * pending window, never confirm one, without dereferencing a stale actor. */
    if(action==4){
        if((b->status==1||b->status==2)&&b->actor==self){status(b,b->status==2?5:4,5,0);b->actor=0;}
        return;
    }
    if(action==6&&(b->status!=1||b->actor!=self))return;
    u64 live=ticket(self,action==1);if(!live)return;
    if(action==6){
        /* Original 333ffac is about to bind the old/new numbered PNG badges.
         * Only our created window hides their internal image slots. The
         * outer Default/New/Effect animations and tournament text remain.
         * These slots are NOT animation-bound in either original asset. */
        if(b->status!=1||b->actor!=self||b->actor_ticket!=live||b->actor_generation!=b->generation)return;
        u64 name=0;((void(*)(void*,const char*,u32))imports.name)(&name,"NamedSlotCustom",1);
        uptr owners[2]={event,caller};
        for(u32 i=0;i<2;++i)if(owners[i]){
            uptr slot=((uptr(*)(uptr,void*))imports.find_widget)(owners[i],&name);
            if(slot)((void(*)(uptr,float))imports.opacity)(slot,0.0f);
        }
        return;
    }
    if(action==1){
        u32 seq=(b->menu_sequence+2)&~1u;b->menu_sequence=seq|1u;fence();
        if(b->parent!=self||b->parent_ticket!=live||b->event!=event){
            if(b->status==1||b->status==2){status(b,b->status==2?5:4,4,0);b->actor=0;}
            ++b->generation;if(!b->generation)b->generation=1;
            b->parent=self;b->parent_ticket=live;b->event=event;
        }
        ++b->tick;fence();b->menu_sequence=seq;return;
    }
    if(action==3){
        /* Original button handler calls this AM virtual at 3bba21c. An
         * animation-end, foreign actor or programmatic close is not consent. */
        if(caller==imports.confirm_caller&&b->status==1&&b->actor==self&&b->actor_ticket==live&&
           b->actor_generation==b->generation)status(b,2,0,0);
        return;
    }
    if(action==5){
        if((b->status==1||b->status==2)&&b->actor==self&&b->actor_ticket==live){
            status(b,b->status==2?5:4,0,0);b->actor=0;
        }
        return;
    }
    if(action!=2||self!=b->parent||live!=b->parent_ticket)return;
    u32 ms=(b->menu_sequence+2)&~1u;b->menu_sequence=ms|1u;fence();
    ++b->tick;fence();b->menu_sequence=ms;
    if(*(u8*)(self+0x226)!=3||b->status==1||b->status==2)return;
    /* The original promotion fade-out resumes this same interactive EVENT
     * page. Refresh its render signal until Python persists confirmation and
     * clears the request, so an earned reward is not lost to a 2-second gate. */
    if(b->status==5&&b->request.sequence){
        volatile u32 *home=(volatile u32 *)((uptr)b-131136);
        home[8]=b->event;u32 render=home[9]+1;if(!render)render=1;
        fence();home[9]=render;
    }
    u32 sequence=b->request.sequence;
    if(!sequence||(sequence&1)||sequence==b->consumed_sequence)return;
    Request request;fence();copy(&request,&b->request,sizeof(request));fence();
    if(sequence!=b->request.sequence)return;
    if(request.event!=b->event||request.generation!=b->generation||request.kind!=1||
       request.division<1||request.division>10||(!request.token[0]&&!request.token[1])){
        b->consumed_sequence=sequence;status(b,3,1,&request);return;
    }
    if((b->status==4||b->status==5)&&request.generation==b->ack_generation&&
       request.token[0]==b->ack_token[0]&&request.token[1]==b->ack_token[1]){
        b->consumed_sequence=sequence;return;
    }
    struct {uptr pointer;u32 count,capacity;} text[3];
    for(u32 i=0;i<3;++i){
        u32 n=0;while(n<128&&request.text[i][n])++n;
        if(n==128){b->consumed_sequence=sequence;status(b,3,2,&request);return;}
        text[i].pointer=(uptr)&request.text[i][0];text[i].count=n+1;text[i].capacity=n+1;
    }
    b->consumed_sequence=sequence;
    uptr actor=((uptr(*)(uptr))imports.factory)(self);
    if(!actor){status(b,3,3,&request);return;}
    u64 actor_ticket=ticket(actor,1);
    /* A newly created actor must have a valid engine slot. Do not retry a
     * factory success just because some later lifecycle step is uncertain. */
    b->actor=actor;b->actor_ticket=actor_ticket;b->actor_generation=b->generation;
    ((void(*)(uptr,void*,void*,void*,u32,u32,u32,uptr))imports.setup)
        (actor,&text[0],&text[1],&text[2],request.division,1,0,self);
    status(b,1,actor_ticket?0:6,&request);
}
