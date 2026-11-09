"use strict";

// Node's built-in test runner: entirely synthetic, no external dependencies.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..");
const A = "fake_sheet_abcdef123";
const B = "fake_sheet_qwerty987";
const MIME = "application/vnd.google-apps.spreadsheet";
const coreSource = fs.readFileSync(path.join(ROOT, "SupplierCore.gs"), "utf8");
const wrapperSource = fs.readFileSync(path.join(ROOT, "SupplierMonitor.gs"), "utf8");

function setup({allowlist=[A, B], baseline=null, ack=null, metadata={}} = {}) {
  const props = Object.create(null);
  if (allowlist !== null) props.SUPPLIER_ALLOWLIST_JSON = JSON.stringify(allowlist);
  if (baseline !== null) props.SUPPLIER_BASELINE_JSON = JSON.stringify(baseline);
  if (ack !== null) props.SUPPLIER_INIT_ACK = ack;
  const logs = [];
  const reads = [];
  let writes = 0;
  let locked = false;
  let lockAllowed = true;
  const data = {
    [A]: {id:A, mimeType:MIME, version:"1", modifiedTime:"2026-11-08T01:00:00Z", trashed:false},
    [B]: {id:B, mimeType:MIME, version:"3", modifiedTime:"2026-11-08T01:00:00Z", trashed:false},
    ...metadata,
  };
  const store = {
    getProperty: key => Object.hasOwn(props,key) ? props[key] : null,
    setProperty: (key,val) => {writes++; props[key]=val;},
    deleteProperty: key => {writes++; delete props[key];},
  };
  const context = vm.createContext({
    PropertiesService: {getScriptProperties: () => store},
    LockService: {
      getScriptLock: () => ({
        tryLock: () => { if (!lockAllowed || locked) return false; locked=true; return true; },
        releaseLock: () => { locked=false; },
      }),
    },
    Drive: {Files: {
      get: (id, options) => {
        reads.push({id,options});
        if (!(id in data)) throw Error("private ID "+id+" not found");
        return data[id];
      },
      list: () => { throw Error("Folder/list scanning is prohibited"); },
      update: () => {throw Error("Drive write prohibited");},
    }},
    console: {log: text => logs.push(text)},
  });
  vm.runInContext(coreSource, context, {filename:"SupplierCore.gs"});
  vm.runInContext(wrapperSource, context, {filename:"SupplierMonitor.gs"});
  const saved = () => props.SUPPLIER_BASELINE_JSON
    ? JSON.parse(props.SUPPLIER_BASELINE_JSON) : null;
  return {
    context, logs, reads, data, props, saved,
    writes:()=>writes,
    disallowLock:()=>{lockAllowed=false;},
    summary:()=>context.previewApprovedSupplierUpdates(),
    initialize:()=>context.initializeSupplierMonitorBaselineOnce(),
    snapshot:()=>context.SupplierMonitorCore.makeSnapshot(allowlist, data),
  };
}

function containsNoPrivateIds(data) {
  for (const id of [A,B]) assert.ok(!JSON.stringify(data).includes(id));
}

test("manual preview first run reads only explicit IDs, redacted output, no writes", () => {
  const t=setup();
  const result=t.summary();
  assert.equal(result.baselineRequired,true);
  assert.equal(result.observedCount,2);
  assert.equal(result.pendingCount,2);
  assert.equal(result.driveSourceWrites,0);
  assert.equal(result.triggersInstalled,0);
  assert.equal(t.reads.length,2);
  assert.deepEqual(t.reads.map(x=>x.id).sort(),[A,B].sort());
  assert.ok(t.reads.every(x=>x.options.fields === "id,mimeType,version,modifiedTime,trashed"));
  assert.equal(t.writes(),0);
  containsNoPrivateIds(t.logs);
  containsNoPrivateIds(result);
});

test("missing or invalid allowlist fails before Drive access", () => {
  for (const allowlist of [null,[],[A,A],["too-short"],[A,"bad!input"]]) {
    const t=setup({allowlist});
    assert.throws(t.summary, /ALLOWLIST|DUPLICATE/);
    assert.equal(t.reads.length,0);
    assert.equal(t.writes(),0);
  }
});

test("more than twenty allowlisted files is rejected", () => {
  const ids=Array.from({length:21},(_,i)=>"fake_document_"+String(i).padStart(5,"0"));
  const t=setup({allowlist:ids});
  assert.throws(t.summary,/INVALID_ALLOWLIST/);
  assert.equal(t.reads.length,0);
});

test("one-time initial baseline cannot be created without explicit approval", () => {
  const t=setup();
  assert.throws(t.initialize,/EXPLICIT_ONE_TIME_ACK/);
  assert.equal(t.writes(),0);
  assert.equal(t.reads.length,0);
});

test("explicit initial baseline is private, one-time, and no backfill or auto scan", () => {
  const t=setup({ack:"I_ACCEPT_INITIAL_BASELINE_NO_BACKFILL"});
  const first=t.initialize();
  assert.equal(first.baselineSavedToScriptProperties,true);
  assert.equal(first.observedCount,2);
  assert.equal(t.saved().approvedFileIds.length,2);
  assert.equal(Object.hasOwn(t.props,"SUPPLIER_INIT_ACK"),false);
  assert.equal(t.writes(),2);
  assert.throws(t.initialize,/BASELINE_EXISTS/);
  assert.equal(t.writes(),2);
  containsNoPrivateIds(t.logs);
});

test("preview detects a revised file but never advances baseline", () => {
  const t=setup();
  const original=t.snapshot();
  const x=setup({baseline:original,metadata:{
    [A]:{id:A,mimeType:MIME,version:"2",modifiedTime:"2026-11-08T04:00:00Z",trashed:false}
  }});
  const result=x.summary();
  assert.equal(result.baselineRequired,false);
  assert.equal(result.changedCount,1);
  assert.equal(result.unchangedCount,1);
  assert.equal(x.writes(),0);
  assert.equal(x.saved().revisions[A].version,"1");
  containsNoPrivateIds(x.logs);
});

test("inaccessible source aborts whole preview without rebaseline", () => {
  const t=setup({metadata:{[B]:null}});
  assert.throws(t.summary,/UNTRUSTED_OR_UNSUPPORTED_METADATA/);
  assert.equal(t.writes(),0);
});

test("Drive error is sanitized; private ID does not appear", () => {
  const t=setup({metadata:{}}); 
  delete t.data[B];
  assert.throws(t.summary, err => {
    assert.equal(err.message,"APPROVED_METADATA_READ_FAILED");
    assert.ok(!err.message.includes(B));
    return true;
  });
  assert.equal(t.writes(),0);
});

test("unexpected file ID, MIME, trashed and revision errors are refused", () => {
  const invalid = [
    {id:"fake_not_approved_123",mimeType:MIME,version:"1",modifiedTime:"",trashed:false},
    {id:A,mimeType:"application/pdf",version:"1",modifiedTime:"",trashed:false},
    {id:A,mimeType:MIME,version:"1",modifiedTime:"",trashed:true},
    {id:A,mimeType:MIME,version:"BAD",modifiedTime:"",trashed:false},
    {id:A,mimeType:MIME,version:"",modifiedTime:"",trashed:false},
  ];
  for (const value of invalid) {
    const t=setup({metadata:{[A]:value}});
    assert.throws(t.summary,/UNTRUSTED|INVALID|MISSING/);
    assert.equal(t.writes(),0);
  }
});

test("changing approved ID set requires a separate review", () => {
  const t=setup();
  const previous=t.snapshot();
  const v=setup({allowlist:[A],baseline:previous});
  assert.throws(v.summary,/ALLOWLIST_CHANGED_REVIEW_REQUIRED/);
  assert.equal(v.writes(),0);
});

test("corrupt baseline fails before any remote request", () => {
  const previous={schemaVersion:"bogus",approvedFileIds:[A,B],revisions:{}};
  const t=setup({baseline:previous});
  assert.throws(t.summary,/INVALID_PRIVATE_BASELINE/);
  assert.equal(t.reads.length,0);
});

test("lock contention aborts before remote request", () => {
  const t=setup();
  t.disallowLock();
  assert.throws(t.summary,/ALREADY_RUNNING/);
  assert.equal(t.reads.length,0);
});

test("manual manifest contains read-only scope and no scheduled triggers", () => {
  const manifest=JSON.parse(fs.readFileSync(path.join(ROOT,"appsscript.json"),"utf8"));
  assert.deepEqual(manifest.oauthScopes,
    ["https://www.googleapis.com/auth/drive.metadata.readonly"]);
  assert.deepEqual(manifest.dependencies.enabledAdvancedServices,
    [{userSymbol:"Drive",serviceId:"drive",version:"v3"}]);
  assert.doesNotMatch(wrapperSource,/ScriptApp\.newTrigger|MailApp\.|GmailApp\.|Drive\.Files\.update/);
});
