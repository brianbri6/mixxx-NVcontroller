/* SPDX-License-Identifier: MIT. Read-only telemetry; original NV controls are forwarded. */
'use strict';
var BiteDJDiag = { timer:null, connections:[], original:{}, events:0, peak:0, last:0 };
BiteDJDiag.capture = function() {
    var now=Date.now(), usage=engine.getValue('[App]','audio_latency_usage');
    var row={wall_ms:now,usage:usage,usage_peak:Math.max(usage,BiteDJDiag.peak),
        underflow_count:engine.getValue('[App]','audio_latency_overload_count'),
        overload:engine.getValue('[App]','audio_latency_overload'),
        controller_timer_interval_ms:BiteDJDiag.last ? now-BiteDJDiag.last : null,
        midi_events_since_sample:BiteDJDiag.events,decks:[]};
    for(var d=1;d<=4;d++) {
        var group='[Channel'+d+']';
        row.decks.push({deck:d,play:engine.getValue(group,'play'),keylock:engine.getValue(group,'keylock'),
            rate:engine.getValue(group,'rate'),rateRange:engine.getValue(group,'rateRange')});
    }
    if(typeof console!=='undefined' && typeof console.info==='function') {
        console.info('BITEDJ_DIAG '+JSON.stringify(row));
    } else { print('BITEDJ_DIAG '+JSON.stringify(row)); }
    BiteDJDiag.last=now; BiteDJDiag.events=0; BiteDJDiag.peak=0;
};
BiteDJDiag.init = function() {
    if(BiteDJDiag.timer!==null) { return; }
    BiteDJDiag.last=0; BiteDJDiag.events=0; BiteDJDiag.peak=0;
    if(typeof BiteDJNV!=='undefined') {
        ['mixer','pitch','jog','touch','button','padMode','pad','browse','sidebar','pfl'].forEach(function(name) {
            if(typeof BiteDJNV[name]!=='function') { return; }
            var original=BiteDJNV[name]; BiteDJDiag.original[name]=original;
            BiteDJNV[name]=function() { BiteDJDiag.events++; return original.apply(this,arguments); };
        });
    }
    var c=engine.makeConnection('[App]','audio_latency_usage',function(value) { BiteDJDiag.peak=Math.max(BiteDJDiag.peak,value); });
    if(c) { BiteDJDiag.connections.push(c); }
    BiteDJDiag.capture(); BiteDJDiag.timer=engine.beginTimer(3000,BiteDJDiag.capture);
};
BiteDJDiag.shutdown = function() {
    if(BiteDJDiag.timer!==null) { engine.stopTimer(BiteDJDiag.timer); }
    BiteDJDiag.timer=null;
    BiteDJDiag.connections.forEach(function(c) { c.disconnect(); }); BiteDJDiag.connections=[];
    if(typeof BiteDJNV!=='undefined') {
        Object.keys(BiteDJDiag.original).forEach(function(name) { BiteDJNV[name]=BiteDJDiag.original[name]; });
    }
    BiteDJDiag.original={};
};
