'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
let now=1000000,values={},callbacks=[],timer,log=[],forwarded=[],stopped=0,disconnected=0;
const names=['mixer','pitch','jog','touch','button','padMode','pad','browse','sidebar','pfl'];
const nv={},original={};
names.forEach(name=>nv[name]=original[name]=function(...args){forwarded.push({name,receiver:this,args});return name+':'+args.length;});
const context=vm.createContext({BiteDJNV:nv,Date:{now:()=>now},console:{info:s=>log.push(JSON.parse(s.split('BITEDJ_DIAG ')[1]))},
    engine:{getValue:(g,k)=>values[g+','+k]||0,setValue:()=>{throw Error('Telemetry wrote a control');},
        makeConnection:(g,k,fn)=>{assert.equal(g,'[App]');assert.equal(k,'audio_latency_usage');callbacks.push(fn);return{disconnect:()=>disconnected++};},
        beginTimer:(ms,fn)=>{assert.equal(ms,3000);timer=fn;return 9;},stopTimer:id=>{assert.equal(id,9);stopped++;}},
    midi:{sendShortMsg:()=>{throw Error('Telemetry sent MIDI');}}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'payload/usr/local/share/bitedj-diag/BiteDJ-Diagnostics.js'),'utf8'),context);
const d=context.BiteDJDiag;values['[App],audio_latency_usage']=0.15;values['[App],audio_latency_overload_count']=3;
d.init();assert.equal(log.length,1);assert.equal(log[0].underflow_count,3);d.init();assert.equal(callbacks.length,1);
const receiver={test:true};names.forEach(name=>assert.equal(nv[name].call(receiver,1,2,127,0xb0,'[Channel1]'),name+':5'));
forwarded.forEach((r,i)=>{assert.equal(r.name,names[i]);assert.equal(r.receiver,receiver);assert.deepEqual(r.args,[1,2,127,0xb0,'[Channel1]']);});
callbacks[0](1.2);now+=3100;timer();assert.equal(log[1].usage_peak,1.2);assert.equal(log[1].midi_events_since_sample,10);assert.equal(log[1].controller_timer_interval_ms,3100);
now+=3000;timer();assert.equal(log[2].usage_peak,0.15);assert.equal(log[2].midi_events_since_sample,0);
d.shutdown();names.forEach(name=>assert.equal(nv[name],original[name]));assert.equal(stopped,1);assert.equal(disconnected,1);
d.shutdown();assert.equal(stopped,1);d.init();assert.equal(log.at(-1).midi_events_since_sample,0);d.shutdown();
process.stdout.write(JSON.stringify({forwarding:'passed',telemetry_read_only:'passed',peak_and_timer:'passed',lifecycle:'passed'})+'\n');
