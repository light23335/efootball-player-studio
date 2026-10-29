/* V17 CPU match adapter. Freestanding, no heap, syscalls or Python callbacks.
 * Imports and the shared bus pointer are explicit relocatable literals.
 * Only a CPU team whose complete (card ID, serial) set matches the opt-in
 * entry is observed. Native emergency coaching always remains available.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef unsigned long uptr;
typedef struct {u64 id,serial;} Identity;
/* Original6905d9c/6905f9c/68fd4b8: signed32 serial,4 bytes padding,
 * then64-bit card ID. Padding is unspecified and never part of identity. */
typedef struct {u32 serial,padding;u64 id;} NativeIdentity;
typedef struct {float x,y,z;} Vec3;
#define NPLAYERS 23
#define PLAN_BYTES 0xe6c
#define BUS_BYTES 32768
#define SECTION(name) __attribute__((section(name),used,visibility("hidden")))
#define EXPORT __attribute__((used,visibility("hidden"),noinline))
#define FN(name,type) ((type)(uptr)imports.name)

typedef struct {
    uptr common,players,game_info,frame_root,frame_stats,goals;
    uptr human,count,physical,entry,identity,phase,period,stop_reason,clock;
    uptr player_state,stamina,disabled,other_disabled,eligible,remaining,windows;
    uptr queue_count,can_queue,queue_sub,plan,get_role,pitch,world;
    uptr set_role,set_planned_role,set_grid,set_world,set_planned_world;
    uptr plan_edited,multi_formation,activate_plan,apply_plan,attack_level,attack_reference;
    uptr card_metadata,abilities,aptitude,set_piece,set_overlap,queue_row,queue_remove,get_attack,entry_stamina;
    uptr discipline,injury,set_captain;
} Imports;
SECTION(".text.imports") volatile Imports imports={
    0x72c3e28,0x72c404c,0x72c3e80,0x72c3f2c,0x73044a0,0x6991db8,
    0x72e1478,0x68fb5fc,0x72f29c4,0x72f2d04,0x72f29e0,
    0x697b60c,0x68fb448,0x6a4eadc,0x697af00,
    0x72c40b0,0x7302020,0x6a642f8,0x6a64358,0x6ce6ef0,0x6b10090,0x6a64524,
    0x68fbf34,0x6ce5824,0x6ce6108,0x6a564d0,0x72b5058,0x72c3e6c,0x6cb3378,
    0x72b4db8,0x72b4e00,0x72b4ef8,0x72b4e48,0x72b4ea0,
    0x72b4f54,0x72b4f6c,0x72b4ca4,0x6a77cd0,0x6c512e0,0x6c5133c,
    0x72f3174,0x68fbea0,0x72b3658,0x72b4fc0,0x72b4fe8,0x72eb08c,0x72eb3b4,0x6ad3e64,0x6905d94,
    0x72f3010,0x72f3008,0x72b4fa4
};

typedef struct {
    u32 expected_index,lineup_slot,physical_index;
    int stamina;
    u32 disabled,other_disabled,eligible,attack_role,defence_role;
} LivePlayer;
typedef struct {
    u32 sequence,configuration_sequence;
    u64 epoch,game_id;
    u32 team,phase,period,stop_reason;
    float clock_frames;
    int score_for,score_against;
    u32 substitutions_left,windows_left,native_pending,roster_count;
    u32 native_event,post_event;
    LivePlayer live[NPLAYERS];
    u8 raw_plan[PLAN_BYTES];
    u32 yellow_count[NPLAYERS],direct_red[NPLAYERS],injury_state[NPLAYERS];
    u32 current_attack_level;
} Snapshot;
typedef struct {
    u32 expected_index,attack_role,defence_role;
    u32 attack_x,attack_y,defence_x,defence_y;
} Placement;
typedef struct {
    u32 sequence,checksum;
    u64 epoch,game_id,plan_id;
    u32 kind,based_on_snapshot,active_count;
    int score_for,score_against;
    u32 substitutions_left,windows_left,attack_level,placement_count,sub_count;
    float issued_clock_frames;
    u32 incoming[2],outgoing[2];
    Placement placement[11];
    u32 captain,set_piece[6],overlap[3];
} Command;

typedef struct {
    u32 sequence,calls,team,roster_count,reason,reserved;
    Identity actual[NPLAYERS];
} ScopeDiagnostic;
typedef struct {
    u32 configuration_sequence,enabled,auto_execute,heartbeat;
    u64 epoch,game_id;
    Identity expected[NPLAYERS];
    Snapshot snapshot;
    Command command;
    u64 ack_id;
    u32 ack_status,rejection_reason;
    uptr bound_root,bound_coach,bound_team;
    u32 last_heartbeat,changed_plan,managed;
    float last_heartbeat_frames;
    u64 active_epoch,last_command;
    uptr pending_root;
    Command pending;
    u64 plan_epoch;
    uptr plan_root;
    u32 desired_attack;
    u32 plan_field_mask;
    u32 diagnostic_enabled;
    ScopeDiagnostic diagnostic;
} Bus;
_Static_assert(sizeof(Bus)<=BUS_BYTES,"Bus overflow");
SECTION(".text.bus") volatile uptr bus_pointer=0x5354ee0000000000ULL;
#define BUS ((volatile Bus *)bus_pointer)
#define OFF(type,field) __builtin_offsetof(type,field)
SECTION(".text.layout") const u32 channel_layout[]={
    sizeof(Bus),sizeof(Snapshot),sizeof(Command),sizeof(LivePlayer),sizeof(Placement),
    OFF(Bus,configuration_sequence),OFF(Bus,enabled),OFF(Bus,auto_execute),OFF(Bus,heartbeat),
    OFF(Bus,epoch),OFF(Bus,game_id),OFF(Bus,expected),OFF(Bus,snapshot),OFF(Bus,command),
    OFF(Bus,ack_id),OFF(Bus,ack_status),OFF(Bus,rejection_reason),
    OFF(Snapshot,sequence),OFF(Snapshot,configuration_sequence),OFF(Snapshot,epoch),OFF(Snapshot,game_id),
    OFF(Snapshot,team),OFF(Snapshot,phase),OFF(Snapshot,period),OFF(Snapshot,stop_reason),
    OFF(Snapshot,clock_frames),OFF(Snapshot,score_for),OFF(Snapshot,score_against),
    OFF(Snapshot,substitutions_left),OFF(Snapshot,windows_left),OFF(Snapshot,native_pending),OFF(Snapshot,roster_count),
    OFF(Snapshot,native_event),OFF(Snapshot,post_event),OFF(Snapshot,live),OFF(Snapshot,raw_plan),
    OFF(Command,sequence),OFF(Command,checksum),OFF(Command,epoch),OFF(Command,game_id),OFF(Command,plan_id),
    OFF(Command,kind),OFF(Command,based_on_snapshot),OFF(Command,active_count),
    OFF(Command,score_for),OFF(Command,score_against),OFF(Command,substitutions_left),OFF(Command,windows_left),
    OFF(Command,attack_level),OFF(Command,placement_count),OFF(Command,sub_count),OFF(Command,issued_clock_frames),
    OFF(Command,incoming),OFF(Command,outgoing),OFF(Command,placement),
    OFF(Command,captain),OFF(Command,set_piece),OFF(Command,overlap),
    OFF(Bus,diagnostic_enabled),OFF(Bus,diagnostic),sizeof(ScopeDiagnostic),
    OFF(Snapshot,yellow_count),OFF(Snapshot,direct_red),OFF(Snapshot,injury_state),OFF(Snapshot,current_attack_level)
};

static void barrier(void){__asm__ volatile("dmb ish":::"memory");}
/* The policy worker may call this memory fence; it never touches engine
 * objects. Engine methods remain exclusively on the game's callback thread. */
EXPORT void studio_fence(void){barrier();}
static uptr ptr(uptr address,u32 offset){return *(uptr *)(address+offset);}
static u32 word(uptr address,u32 offset){return *(u32 *)(address+offset);}
static void copy_bytes(volatile void *dst,const volatile void *src,u32 count){
    volatile u8 *d=dst;const volatile u8 *s=src;
    for(u32 i=0;i<count;++i)d[i]=s[i];
}

/* A roster match remains valid after original substitutions reorder entries.
 * Do not compare only low player IDs: serials and every catalogue variant are
 * significant here, and no duplicate physical or expected identity is allowed.
 */
static int scope(uptr root,u32 team,u32 *order){
    volatile Bus *b=BUS;u32 seq=b->configuration_sequence;
    if(!seq||(seq&1)||!b->enabled||team>1)return 0;
    barrier();
    volatile ScopeDiagnostic *d=b->diagnostic_enabled?&b->diagnostic:0;
    u32 ds=d?(d->sequence+2)&~1u:0;
    if(d){d->sequence=ds|1u;barrier();++d->calls;d->team=team;d->roster_count=0;d->reason=0;
        for(u32 i=0;i<NPLAYERS;++i){d->actual[i].id=0;d->actual[i].serial=0;}}
    u32 reason=0;
    uptr common=FN(common,uptr(*)(uptr))(root);
    if(!common){reason=1;goto done;}
    if(FN(human,int(*)(uptr,u32))(common,team)){reason=2;goto done;}
    /* The first exact roster observation binds this entry epoch to one
     * native match root. A late callback from a different match must not
     * replace that binding, even if both rosters happen to be identical. */
    if(b->active_epoch==b->epoch&&b->bound_root&&b->bound_root!=root){reason=10;goto done;}
    uptr players=FN(players,uptr(*)(uptr,u32))(root,team);
    if(!players){reason=3;goto done;}
    u32 count=FN(count,u32(*)(uptr))(players);
    if(d)d->roster_count=count;
    if(count!=NPLAYERS){reason=4;goto done;}
    u32 seen=0;u64 physical_seen=0;
    for(u32 i=0;i<NPLAYERS;++i){
        u32 physical=FN(physical,u32(*)(uptr,u32))(players,i);
        if(physical>=40||(physical_seen&(1ULL<<physical))){reason=5;goto done;}
        physical_seen|=1ULL<<physical;
        uptr entry=FN(entry,uptr(*)(uptr,u32))(players,i);
        if(!entry){reason=6;goto done;}
        NativeIdentity native_id=FN(identity,NativeIdentity(*)(uptr))(entry);
        Identity id={native_id.id,(u64)native_id.serial};
        if(d){d->actual[i].id=id.id;d->actual[i].serial=id.serial;}
        u32 j=0;
        for(;j<NPLAYERS;++j)if(id.id==b->expected[j].id&&id.serial==b->expected[j].serial)break;
        if(j==NPLAYERS){reason=7;continue;}
        if(seen&(1u<<j)){reason=8;continue;}
        seen|=1u<<j;order[i]=j;
    }
done:
    barrier();
    if(seq!=b->configuration_sequence||!b->enabled)reason=9;
    if(d){d->reason=reason;barrier();d->sequence=ds;}
    return !reason;
}

EXPORT int studio_observe(uptr self,uptr event,u32 post){
    volatile Bus *b=BUS;u32 order[NPLAYERS];
    if(!self)return 0;
    uptr root=ptr(self,0x370),team_data=ptr(self,0x378);u32 team=word(self,8);
    if(!root||!team_data||!scope(root,team,order))return 0;
    uptr common=FN(common,uptr(*)(uptr))(root);
    uptr players=FN(players,uptr(*)(uptr,u32))(root,team);
    uptr info=FN(game_info,uptr(*)(uptr))(root);
    uptr plan=FN(plan,uptr(*)(uptr))(team_data);
    if(!info||!plan)return 0;
    u32 configuration=b->configuration_sequence;u64 epoch=b->epoch;
    if(b->active_epoch!=epoch){
        /* Command sequences and owned shapes are entry-local. A new entry's
         * first command must not equal a sequence consumed by the old one. */
        b->last_command=0;b->changed_plan=0;b->plan_epoch=0;b->plan_root=0;
        b->desired_attack=2;b->last_heartbeat=0;
    }
    volatile Snapshot *s=&b->snapshot;
    u32 seq=(s->sequence+2)&~1u;s->sequence=seq|1u;barrier();
    s->configuration_sequence=configuration;s->epoch=epoch;s->game_id=b->game_id;s->team=team;
    s->phase=FN(phase,u32(*)(uptr))(info);s->period=FN(period,u32(*)(uptr))(info);
    s->stop_reason=FN(stop_reason,u32(*)(uptr))(info);
    s->clock_frames=FN(clock,float(*)(uptr))(info);
    uptr frame=FN(frame_root,uptr(*)(uptr))(root);
    frame=frame?FN(frame_stats,uptr(*)(uptr))(frame):0;
    s->score_for=frame?FN(goals,int(*)(uptr,u32,u32))(frame,team,5):-1;
    s->score_against=frame?FN(goals,int(*)(uptr,u32,u32))(frame,team^1u,5):-1;
    s->substitutions_left=FN(remaining,u32(*)(uptr))(team_data);
    s->current_attack_level=FN(get_attack,u32(*)(uptr))(team_data);
    s->windows_left=FN(windows,u32(*)(uptr))(team_data);
    s->native_pending=FN(queue_count,u32(*)(uptr))(self+0x20);
    /* Original coaching moves requests into TeamData+a8 before the actual
     * member change. Observe both queues, including a technical recovery in
     * that interval; an empty coach queue alone does not mean idle. */
    u32 team_pending=FN(queue_count,u32(*)(uptr))(team_data+0xa8);
    if(team_pending>s->native_pending)s->native_pending=team_pending;
    s->native_event=event?word(event,0):0xffffffffu;s->post_event=post;s->roster_count=NPLAYERS;
    for(u32 i=0;i<NPLAYERS;++i){
        volatile LivePlayer *p=&s->live[i];p->lineup_slot=i;p->expected_index=order[i];
        p->physical_index=FN(physical,u32(*)(uptr,u32))(players,i);
        uptr entry=FN(entry,uptr(*)(uptr,u32))(players,i);
        uptr cards=FN(discipline,uptr(*)(uptr))(entry);
        uptr injury=FN(injury,uptr(*)(uptr))(entry);
        /* Original UI6a6359c and eligibility6b108cc: byte0 counts yellows,
         * byte1 is a direct dismissal. Injury word+14 is raw: only zero's
         * normal meaning is established by original68fbe6c. */
        s->yellow_count[i]=cards?*(u8*)cards:255;
        s->direct_red[i]=cards?*(u8*)(cards+1):255;
        s->injury_state[i]=injury?word(injury,0x14):0xffffffffu;
        p->eligible=FN(eligible,u32(*)(uptr,u32,uptr))(players,i,common);
        p->stamina=-1;p->disabled=0;p->other_disabled=0;p->attack_role=255;p->defence_role=255;
        if(i<11){
            u32 global=team*11+i;
            uptr state=FN(player_state,uptr(*)(uptr,u32))(root,global);
            /* The actual original getter returns an integer percentage in W0,
             * not a float in S0 and not the player's stamina ability stat. */
            if(state)p->stamina=FN(stamina,int(*)(uptr))(state);
            p->disabled=FN(disabled,u32(*)(uptr,u32))(info,global);
            p->other_disabled=FN(other_disabled,u32(*)(uptr,u32))(info,global);
            p->attack_role=FN(get_role,u32(*)(uptr,u32,u32,u32))(plan,i,1,2);
            p->defence_role=FN(get_role,u32(*)(uptr,u32,u32,u32))(plan,i,2,2);
        }else if(p->eligible){
            /* Original7189ac0(initial=1) reads this entry's metadata+109,
             * uses max(10,value)/100 as the incoming energy fraction, then
             * 7301f84 clamps current energy to the actual native capacity.
             * This is the native entry ratio, NOT a guessed bench100 and
             * NOT a team*11+bench-index read from another on-field actor. */
            uptr entry=FN(entry,uptr(*)(uptr,u32))(players,i);
            uptr meta=FN(card_metadata,uptr(*)(uptr))(entry);
            if(meta){
                u32 ratio=FN(entry_stamina,u32(*)(uptr))(meta);
                p->stamina=(int)(ratio<10?10:ratio>100?100:ratio);
            }
        }
    }
    copy_bytes(s->raw_plan,(void*)plan,PLAN_BYTES);
    barrier();
    if(configuration!=b->configuration_sequence||epoch!=b->epoch||!b->enabled){s->sequence=0;return 0;}
    b->bound_root=root;b->bound_coach=self;b->bound_team=team_data;b->active_epoch=epoch;
    s->sequence=seq;
    return 1;
}

/* Reviewed command protocol. This is NOT called by the read-only observer.
 * The installer must separately enable a validated dispatch entry. A Python
 * proposal is never executed from its worker thread, and ACK_ACCEPTED means
 * only that the original substitution queue contains our request.
 */
#define ACK_ACCEPTED 1u
#define ACK_APPLIED 2u
#define ACK_REJECTED 3u
#define ACK_STALE 4u
#define ACK_CANCELLED 5u
#define ACK_PARTIAL 6u
#define KIND_FORMATION 1u
#define KIND_SUBSTITUTION 2u
#define KIND_CANCEL 3u

static void ack(u64 id,u32 status,u32 reason){
    volatile Bus *b=BUS;b->ack_id=0;barrier();
    b->ack_status=status;b->rejection_reason=reason;barrier();b->ack_id=id;
}
static u32 checksum(const Command *c){
    const u8 *p=(const u8 *)c;u32 hash=2166136261u;
    for(u32 i=8;i<sizeof(Command);++i)hash=(hash^p[i])*16777619u;
    return hash;
}
static int slot_of(const u32 *order,u32 expected){
    for(u32 i=0;i<NPLAYERS;++i)if(order[i]==expected)return (int)i;
    return -1;
}
static u32 mask_count(u32 mask){u32 count=0;while(mask){mask&=mask-1;++count;}return count;}
static u32 active_field_mask(uptr root,u32 team,const u32 *order){
    uptr info=FN(game_info,uptr(*)(uptr))(root);
    uptr players=FN(players,uptr(*)(uptr,u32))(root,team);
    if(!info||!players)return 0;
    u32 mask=0;
    for(u32 i=0;i<11;++i){
        uptr entry=FN(entry,uptr(*)(uptr,u32))(players,i);
        uptr cards=FN(discipline,uptr(*)(uptr))(entry);
        uptr injury=FN(injury,uptr(*)(uptr))(entry);
        if(!cards||!injury||*(u8*)cards>2||*(u8*)(cards+1)>1)return 0;
        u32 active=FN(disabled,u32(*)(uptr,u32))(info,team*11+i);
        u32 other=FN(other_disabled,u32(*)(uptr,u32))(info,team*11+i);
        int departed=*(u8*)cards>=2||*(u8*)(cards+1)||word(injury,0x14);
        if(departed){
            /* A newly issued card or an injury still being treated is not a
             * completed departure. Never replace a red-card vacancy. The
             * original GK emergency must establish a legal keeper first. */
            if(active||i==0||other>1)return 0;
            continue;
        }
        if(active!=1||other)return 0;
        mask|=1u<<order[i];
    }
    return mask_count(mask)>=7?mask:0;
}
static int native_aptitude(uptr players,u32 slot,u32 role){
    if(slot>=NPLAYERS||role>12)return 0;
    uptr entry=FN(entry,uptr(*)(uptr,u32))(players,slot);
    uptr meta=FN(card_metadata,uptr(*)(uptr))(entry);
    uptr ability=FN(abilities,uptr(*)(uptr))(meta);
    return FN(aptitude,u32(*)(uptr,u32))(ability,role)==2;
}
static int queue_contains(uptr queue,u32 incoming,u32 outgoing){
    u32 count=FN(queue_count,u32(*)(uptr))(queue),found=0;
    if(count>7)return -1;
    for(u32 i=0;i<count;++i){
        uptr row=FN(queue_row,uptr(*)(uptr,u32))(queue,i);
        if(!row)return -1;
        u32 cause=word(row,0),out=word(row,4),in=word(row,8);
        if(in==incoming||out==incoming||in==outgoing||out==outgoing){
            if(cause!=3||in!=incoming||out!=outgoing||found)return -1;
            found=1;
        }
    }
    return (int)found;
}
static int remove_owned(uptr self,uptr players,const Command *c,const u32 *order){
    uptr team=ptr(self,0x378);u32 outgoing_present=0,incoming_present=0;
    /* Validate BOTH queues before erasing anything. A native injury request
     * using the same player must never be removed by our normal-plan cancel.
     */
    for(u32 k=0;k<c->sub_count;++k){
        int is=slot_of(order,c->incoming[k]),os=slot_of(order,c->outgoing[k]);
        if(is<0||os<0)return -1;
        u32 ip=FN(physical,u32(*)(uptr,u32))(players,(u32)is);
        u32 op=FN(physical,u32(*)(uptr,u32))(players,(u32)os);
        if(queue_contains(self+0x20,ip,op)<0||queue_contains(team+0xa8,ip,op)<0)return -1;
        incoming_present+=(is<11);outgoing_present+=(os<11);
    }
    for(u32 k=0;k<c->sub_count;++k){
        int is=slot_of(order,c->incoming[k]),os=slot_of(order,c->outgoing[k]);
        u32 ip=FN(physical,u32(*)(uptr,u32))(players,(u32)is);
        u32 op=FN(physical,u32(*)(uptr,u32))(players,(u32)os);
        if(queue_contains(self+0x20,ip,op)==1)FN(queue_remove,void(*)(uptr,u32))(self+0x20,ip);
        if(queue_contains(team+0xa8,ip,op)==1)FN(queue_remove,void(*)(uptr,u32))(team+0xa8,ip);
    }
    return incoming_present||outgoing_present<c->sub_count?1:0;
}
static int context_valid(uptr self,const Command *c,const u32 *order){
    volatile Bus *b=BUS;volatile Snapshot *s=&b->snapshot;
    if(c->epoch!=b->epoch||c->game_id!=b->game_id||s->epoch!=c->epoch||
       !c->plan_id||s->configuration_sequence!=b->configuration_sequence)return 1;
    if(!s->sequence||(s->sequence&1)||c->based_on_snapshot>s->sequence||!c->based_on_snapshot)return 2;
    if(c->score_for!=s->score_for||c->score_against!=s->score_against)return 3;
    if(c->active_count<7||c->active_count>11||c->placement_count!=c->active_count||c->sub_count>2||c->attack_level>4)return 4;
    float age=s->clock_frames-c->issued_clock_frames;
    if(!(age>=0&&age<=1800.0f))return 5; /* NaN fails too. */
    if(s->phase!=1&&s->phase!=2)return 6;
    if(c->substitutions_left!=s->substitutions_left||c->windows_left!=s->windows_left)return 7;
    u32 current=0,target=0,gk=0;
    uptr root=ptr(self,0x370);u32 team=word(self,8);
    uptr players=FN(players,uptr(*)(uptr,u32))(root,team);
    uptr common=FN(common,uptr(*)(uptr))(root);
    uptr plan=FN(plan,uptr(*)(uptr))(ptr(self,0x378));
    uptr info=FN(game_info,uptr(*)(uptr))(root);
    current=active_field_mask(root,team,order);
    if(mask_count(current)!=c->active_count)return 4;
    float now=FN(clock,float(*)(uptr))(info),direct_age=now-c->issued_clock_frames;
    if(!(direct_age>=0&&direct_age<=1800.0f))return 5;
    u32 phase=FN(phase,u32(*)(uptr))(info);
    if(phase!=1&&phase!=2)return 6;
    uptr frame=FN(frame_root,uptr(*)(uptr))(root);
    frame=frame?FN(frame_stats,uptr(*)(uptr))(frame):0;
    if(!frame||c->score_for!=FN(goals,int(*)(uptr,u32,u32))(frame,team,5)||
       c->score_against!=FN(goals,int(*)(uptr,u32,u32))(frame,team^1u,5))return 3;
    if(c->substitutions_left!=FN(remaining,u32(*)(uptr))(ptr(self,0x378))||
       c->windows_left!=FN(windows,u32(*)(uptr))(ptr(self,0x378)))return 7;
    for(u32 i=0;i<c->placement_count;++i){
        const Placement *p=&c->placement[i];
        if(p->expected_index>=NPLAYERS||(target&(1u<<p->expected_index)))return 8;
        if(p->attack_role>12||p->defence_role>12||p->attack_x>48||p->defence_x>48||
           p->attack_y>104||p->defence_y>104)return 8;
        int slot=slot_of(order,p->expected_index);
        /* 6ce6ef0 is substitution-candidate eligibility, not on-field
         * availability. Original CPU entrants have used-flag190 set and
         * return0 while actively playing. Require it only for a bench entrant. */
        if(slot<0||(slot<11&&!(current&(1u<<p->expected_index)))||
            (slot>=11&&!FN(eligible,int(*)(uptr,u32,uptr))(players,(u32)slot,common)))return 9;
        if(!native_aptitude(players,(u32)slot,p->attack_role)||!native_aptitude(players,(u32)slot,p->defence_role))return 10;
        if(!p->attack_role||!p->defence_role){
            if(p->attack_role||p->defence_role||slot!=0)return 11;
            ++gk;
        }
        target|=1u<<p->expected_index;
    }
    if(gk!=1)return 11;
    if(c->captain!=255&&(c->captain>=NPLAYERS||!(target&(1u<<c->captain))))return 28;
    for(u32 i=0;i<9;++i){
        u32 identity=i<6?c->set_piece[i]:c->overlap[i-6];
        if(identity!=255&&(identity>=NPLAYERS||!(target&(1u<<identity))))return 28;
    }
    u32 inmask=0,outmask=0;
    for(u32 i=0;i<c->sub_count;++i){
        u32 in=c->incoming[i],out=c->outgoing[i];
        if(in>=NPLAYERS||out>=NPLAYERS||(inmask&(1u<<in))||(outmask&(1u<<out)))return 12;
        int is=slot_of(order,in),os=slot_of(order,out);
        if(is<11||os<1||os>=11||!(current&(1u<<out)))return 12;
        u32 ar=FN(get_role,u32(*)(uptr,u32,u32,u32))(plan,(u32)os,1,2);
        u32 dr=FN(get_role,u32(*)(uptr,u32,u32,u32))(plan,(u32)os,2,2);
        if(!native_aptitude(players,(u32)is,ar)||!native_aptitude(players,(u32)is,dr))return 13;
        inmask|=1u<<in;outmask|=1u<<out;
    }
    if(((current&~outmask)|inmask)!=target)return 14;
    return 0;
}
static int normal_eleven(uptr root,u32 team);

/* Called only by a separately verified game-thread dispatch hook. Until that
 * hook is installed this helper is exercised by original-instruction probes.
 */
EXPORT int studio_queue_tick(uptr self){
    volatile Bus *b=BUS;u32 order[NPLAYERS];
    if(!self||!b->auto_execute||!b->heartbeat)return 0;
    uptr root=ptr(self,0x370);u32 team=word(self,8);
    if(!scope(root,team,order)||b->bound_root!=root||b->bound_coach!=self)return 0;
    uptr players=FN(players,uptr(*)(uptr,u32))(root,team);
    if(b->pending.plan_id&&(b->pending_root!=root||b->pending.epoch!=b->epoch||b->pending.game_id!=b->game_id)){
        /* Never erase from a NEW native match using an OLD entry's indices. */
        ack(b->pending.plan_id,ACK_STALE,1);b->pending.plan_id=0;b->managed=0;
    }
    if(!normal_eleven(root,team)){
        if(b->pending.plan_id){
            Command pending;copy_bytes(&pending,&b->pending,sizeof(pending));
            int partial=remove_owned(self,players,&pending,order);
            ack(pending.plan_id,partial>0?ACK_PARTIAL:ACK_CANCELLED,partial<0?22:27);
            b->pending.plan_id=0;
        }
        b->managed=0;return 0;
    }
    if(b->heartbeat!=b->last_heartbeat){
        b->last_heartbeat=b->heartbeat;b->last_heartbeat_frames=b->snapshot.clock_frames;
    }else if(b->snapshot.clock_frames-b->last_heartbeat_frames>1800.0f){
        if(b->pending.plan_id){
            Command pending;copy_bytes(&pending,&b->pending,sizeof(pending));
            int partial=remove_owned(self,players,&pending,order);
            ack(pending.plan_id,partial>0?ACK_PARTIAL:ACK_STALE,partial<0?22:23);
            b->pending.plan_id=0;
        }
        b->managed=0;return 0;
    }
    if(b->pending.plan_id){
        Command pending;copy_bytes(&pending,&b->pending,sizeof(pending));
        u32 current=active_field_mask(root,team,order),inmask=0,outmask=0;
        for(u32 i=0;i<pending.sub_count;++i){inmask|=1u<<pending.incoming[i];outmask|=1u<<pending.outgoing[i];}
        if(mask_count(current)!=pending.active_count){
            int partial=remove_owned(self,players,&pending,order);
            ack(pending.plan_id,partial>0?ACK_PARTIAL:ACK_CANCELLED,partial<0?22:27);
            b->pending.plan_id=0;b->managed=0;
        }else if((current&inmask)==inmask&&!(current&outmask)){
            ack(pending.plan_id,ACK_APPLIED,0);b->pending.plan_id=0;b->managed=0;
        }else if(pending.epoch!=b->epoch||pending.game_id!=b->game_id||
                  pending.score_for!=b->snapshot.score_for||pending.score_against!=b->snapshot.score_against||
                  b->snapshot.clock_frames-pending.issued_clock_frames>10800.0f){
            int partial=remove_owned(self,players,&pending,order);
            ack(pending.plan_id,partial>0?ACK_PARTIAL:ACK_STALE,partial<0?22:21);
            b->pending.plan_id=0;b->managed=0;
        }
    }
    u32 seq=b->command.sequence;
    if(!seq||(seq&1)||seq==b->last_command)return 0;
    Command c;barrier();copy_bytes(&c,&b->command,sizeof(c));barrier();
    if(seq!=b->command.sequence)return 0;
    /* The plan callback owns this command and must see the same unconsumed
     * transport sequence. The substitution callback never commits a shape. */
    if(c.kind==KIND_FORMATION)return 0;
    if(c.checksum!=checksum(&c)){b->last_command=seq;ack(c.plan_id,ACK_REJECTED,15);return 0;}
    /* A transport sequence is entry-local. An old buffer must not consume
     * the new entry's identical first sequence, or overwrite its stale ACK
     * with an ordinary rejection after the observer resets last_command. */
    if(c.epoch!=b->epoch||c.game_id!=b->game_id){ack(c.plan_id,ACK_STALE,1);return 0;}
    b->last_command=seq;
    if(c.kind==KIND_CANCEL){
        if(c.epoch!=b->epoch||c.game_id!=b->game_id){ack(c.plan_id,ACK_STALE,1);return 0;}
        if(b->pending.plan_id!=c.plan_id)return 0;
        Command pending;copy_bytes(&pending,&b->pending,sizeof(pending));
        int partial=remove_owned(self,players,&pending,order);
        if(partial<0){
            /* A native emergency now owns the pair. Hand it back without
             * deleting that request or keeping an orphaned workshop plan. */
            ack(c.plan_id,ACK_REJECTED,22);b->pending.plan_id=0;b->managed=0;return 0;
        }
        ack(c.plan_id,partial?ACK_PARTIAL:ACK_CANCELLED,0);b->pending.plan_id=0;b->managed=0;return 1;
    }
    if(b->pending.plan_id){
        ack(c.plan_id,c.plan_id==b->pending.plan_id?ACK_ACCEPTED:ACK_REJECTED,16);return 0;
    }
    int reason=context_valid(self,&c,order);
    if(reason){ack(c.plan_id,ACK_REJECTED,(u32)reason);return 0;}
    /* Formation commit belongs to the native plan-update callback, not this
     * substitution event. Do not silently acknowledge an unimplemented path. */
    if(c.kind!=KIND_SUBSTITUTION||!c.sub_count){ack(c.plan_id,ACK_REJECTED,17);return 0;}
    uptr team_data=ptr(self,0x378);
    if(FN(queue_count,u32(*)(uptr))(self+0x20)||FN(queue_count,u32(*)(uptr))(team_data+0xa8)||
       c.sub_count>c.substitutions_left||!FN(can_queue,int(*)(uptr))(self)){
        ack(c.plan_id,ACK_REJECTED,18);return 0;
    }
    for(u32 i=0;i<c.sub_count;++i){
        u32 is=(u32)slot_of(order,c.incoming[i]),os=(u32)slot_of(order,c.outgoing[i]);
        if(!FN(queue_sub,int(*)(uptr,u32,u32,u32))(self,is,os,3)){
            Command partial;copy_bytes(&partial,&c,sizeof(partial));partial.sub_count=i;
            remove_owned(self,players,&partial,order);ack(c.plan_id,ACK_REJECTED,19);return 0;
        }
    }
    copy_bytes(&b->pending,&c,sizeof(c));b->pending_root=root;b->managed=1;ack(c.plan_id,ACK_ACCEPTED,0);return 1;
}

static int alive(uptr root){
    volatile Bus *b=BUS;
    if(!b->auto_execute||!b->heartbeat||!b->enabled||b->bound_root!=root)return 0;
    uptr info=FN(game_info,uptr(*)(uptr))(root);
    if(!info)return 0;
    float now=FN(clock,float(*)(uptr))(info);
    if(b->heartbeat!=b->last_heartbeat){b->last_heartbeat=b->heartbeat;b->last_heartbeat_frames=now;}
    float age=now-b->last_heartbeat_frames;
    return age>=0&&age<=1800.0f;
}

/* Confirmed normal actors plus card/injury departures, without guessing injury
 * severity. GK emergencies and transitional actor flags remain original.
 * Re-check even with no command; old full-team shapes cannot own a new count. */
static int normal_eleven(uptr root,u32 team){
    uptr players=FN(players,uptr(*)(uptr,u32))(root,team);
    if(!players)return 0;
    u32 order[NPLAYERS];for(u32 i=0;i<NPLAYERS;++i)order[i]=i;
    return active_field_mask(root,team,order)!=0;
}

/* Only suppress a competing NORMAL CPU request while an owned request is
 * pending. Original injury/GK and discipline handlers are separate entries
 * and are never intercepted by this guard. */
EXPORT int studio_managed(uptr self){
    volatile Bus *b=BUS;u32 order[NPLAYERS];
    if(!self||!b->pending.plan_id||b->pending.epoch!=b->epoch)return 0;
    uptr root=ptr(self,0x370);u32 team=word(self,8);
    return b->pending_root==root&&b->bound_coach==self&&alive(root)&&scope(root,team,order)&&
           mask_count(active_field_mask(root,team,order))==b->pending.active_count;
}

static int owned_plan(uptr context,u32 *order){
    volatile Bus *b=BUS;
    u32 configuration=b->configuration_sequence;u64 epoch=b->epoch;
    /* A new entry is published before its first verified coach observation.
     * Do not dereference a coach retained from the previous match here. That
     * allocation may already be freed, including while the old root address
     * has been reused. Disabled/partial/new-epoch callbacks stay native. */
    if(!context||!configuration||(configuration&1)||!b->enabled||!b->auto_execute||
       !epoch||b->active_epoch!=epoch||!b->bound_root||!b->bound_team||!b->bound_coach)return 0;
    barrier();
    uptr root=ptr(context,0x6380),team_data=ptr(context,0x6388);u32 team=word(context,8);
    int scoped=root&&team_data&&team<=1&&root==b->bound_root&&
           team==b->snapshot.team&&team_data==b->bound_team&&alive(root)&&scope(root,team,order);
    if(!scoped)return 0;
    barrier();
    if(configuration!=b->configuration_sequence||epoch!=b->epoch||!b->enabled)return 0;
    u32 mask=active_field_mask(root,team,order);
    if(!mask||(b->changed_plan&&b->plan_field_mask!=mask)){
        b->changed_plan=0;b->plan_epoch=0;b->plan_root=0;
        return 0;
    }
    return 1;
}

/* The callback return is the original plan module's changed flag. -1 means
 * execute the untouched original callback. Only validated active-lineup plans
 * enter this path. A reduced command must exactly match confirmed native
 * departures; a GK emergency without a validated keeper remains original.
 */
EXPORT int studio_plan_tick(uptr context){
    volatile Bus *b=BUS;u32 order[NPLAYERS];
    if(!owned_plan(context,order))return -1;
    uptr root=ptr(context,0x6380),team_data=ptr(context,0x6388);
    u32 seq=b->command.sequence;
    int holding=b->changed_plan&&b->plan_epoch==b->epoch&&b->plan_root==root;
    if(!seq||(seq&1)||seq==b->last_command)return holding?0:-1;
    Command c;barrier();copy_bytes(&c,&b->command,sizeof(c));barrier();
    if(seq!=b->command.sequence)return holding?0:-1;
    if(c.kind!=KIND_FORMATION)return holding?0:-1;
    if(c.checksum!=checksum(&c)){b->last_command=seq;ack(c.plan_id,ACK_REJECTED,15);return holding?0:-1;}
    if(c.epoch!=b->epoch||c.game_id!=b->game_id){ack(c.plan_id,ACK_STALE,1);return holding?0:-1;}
    b->last_command=seq;
    if(b->pending.plan_id||c.sub_count){ack(c.plan_id,ACK_REJECTED,16);return holding?0:-1;}
    int reason=context_valid(b->bound_coach,&c,order);
    if(reason){ack(c.plan_id,ACK_REJECTED,(u32)reason);return holding?0:-1;}
    uptr current=FN(plan,uptr(*)(uptr))(team_data),pitch=FN(pitch,uptr(*)(uptr))(root);
    if(!current||!pitch){ack(c.plan_id,ACK_REJECTED,24);return holding?0:-1;}
    u8 baseline[PLAN_BYTES],next[PLAN_BYTES];
    copy_bytes(baseline,(void*)current,PLAN_BYTES);copy_bytes(next,baseline,PLAN_BYTES);
    for(u32 i=0;i<c.placement_count;++i){
        const Placement *p=&c.placement[i];u32 slot=(u32)slot_of(order,p->expected_index);
        /* Do not reorder physical players/actors to match template slots.
         * Put the requested role and coordinate on the real live lineup slot.
         */
        for(u32 axis=0;axis<3;++axis){
            u32 role=axis==2?p->defence_role:p->attack_role;
            FN(set_role,void(*)(uptr,u32,u32,u32,u32))((uptr)next,slot,role,axis,1);
            FN(set_planned_role,void(*)(uptr,u32,u32,u32,u32))((uptr)next,slot,role,axis,1);
            if(slot){
                u8 xy[2]={(u8)(axis==2?p->defence_x:p->attack_x),(u8)(axis==2?p->defence_y:p->attack_y)};
                Vec3 world=FN(world,Vec3(*)(uptr,const u8*))(pitch,xy);
                if(!(world.x>=-200&&world.x<=200&&world.y>=-200&&world.y<=200&&world.z>=-200&&world.z<=200)){
                    ack(c.plan_id,ACK_REJECTED,25);return holding?0:-1;
                }
                FN(set_grid,void(*)(uptr,u32,u32,u32,u32,u32))((uptr)next,slot-1,xy[0],xy[1],axis,1);
                FN(set_world,void(*)(uptr,u32,Vec3*,u32,u32))((uptr)next,slot,&world,axis,1);
                FN(set_planned_world,void(*)(uptr,u32,Vec3*,u32,u32))((uptr)next,slot,&world,axis,1);
            }
        }
    }
    /* Commands contain expected identities, never lineup or physical guesses.
     * Resolve AFTER native substitutions, on the game's callback thread. */
    uptr players=FN(players,uptr(*)(uptr,u32))(root,word(context,8));
    if(c.captain!=255){
        u32 slot=(u32)slot_of(order,c.captain);
        FN(set_captain,void(*)(uptr,u32))((uptr)next,FN(physical,u32(*)(uptr,u32))(players,slot));
    }
    for(u32 i=0;i<6;++i)if(c.set_piece[i]!=255){
        u32 slot=(u32)slot_of(order,c.set_piece[i]);
        FN(set_piece,void(*)(uptr,u32,u32))((uptr)next,FN(physical,u32(*)(uptr,u32))(players,slot),i);
    }
    for(u32 i=0;i<3;++i)if(c.overlap[i]!=255){
        u32 slot=(u32)slot_of(order,c.overlap[i]);
        FN(set_overlap,void(*)(uptr,u32,u32))((uptr)next,i,FN(physical,u32(*)(uptr,u32))(players,slot));
    }
    FN(plan_edited,void(*)(uptr,u32,u32))((uptr)next,1,1);
    FN(multi_formation,void(*)(uptr,u32,u32))((uptr)next,1,1);
    FN(activate_plan,void(*)(uptr,u32))((uptr)next,1);
    FN(apply_plan,void(*)(uptr,uptr))(team_data,(uptr)next);
    current=FN(plan,uptr(*)(uptr))(team_data);
    int valid=word(current,0)==1;
    for(u32 i=0;i<c.placement_count;++i){
        const Placement *p=&c.placement[i];u32 slot=(u32)slot_of(order,p->expected_index);
        if(FN(get_role,u32(*)(uptr,u32,u32,u32))(current,slot,1,2)!=p->attack_role||
           FN(get_role,u32(*)(uptr,u32,u32,u32))(current,slot,2,2)!=p->defence_role)valid=0;
        if(slot){
            u32 at=(slot-1)*6+0x3c;
            if(*(u16*)(current+0x124+at+2)!=p->attack_x||*(u16*)(current+0x19c+at+2)!=p->attack_y||
               *(u16*)(current+0x124+at+4)!=p->defence_x||*(u16*)(current+0x19c+at+4)!=p->defence_y)valid=0;
        }
    }
    for(u32 i=0;i<PLAN_BYTES;++i)if(*(u8*)(current+i)!=next[i])valid=0;
    if(!valid){
        FN(apply_plan,void(*)(uptr,uptr))(team_data,(uptr)baseline);
        ack(c.plan_id,ACK_REJECTED,26);return holding?0:-1;
    }
    u32 before=FN(get_attack,u32(*)(uptr))(team_data);
    FN(attack_level,void(*)(uptr,u32))(team_data,c.attack_level);
    FN(attack_reference,void(*)(uptr,u32))(team_data,before);
    b->desired_attack=c.attack_level;b->changed_plan=1;b->plan_epoch=b->epoch;b->plan_root=root;
    b->plan_field_mask=active_field_mask(root,word(context,8),order);
    ack(c.plan_id,ACK_APPLIED,0);return 1;
}

/* Preserve the chosen desired level against the original automatic level
 * module, with the same scope/dead-worker fallback as the formation module. */
EXPORT int studio_attack_tick(uptr context){
    volatile Bus *b=BUS;u32 order[NPLAYERS];
    if(!owned_plan(context,order)||!b->changed_plan||b->plan_epoch!=b->epoch||
       b->plan_root!=ptr(context,0x6380)||b->desired_attack>4)return -1;
    FN(attack_level,void(*)(uptr,u32))(ptr(context,0x6388),b->desired_attack);return 0;
}
