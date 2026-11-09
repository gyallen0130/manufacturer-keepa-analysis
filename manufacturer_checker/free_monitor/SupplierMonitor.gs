/**
 * READ-ONLY Google Drive metadata check, manually invoked in Apps Script.
 *
 * Requirements: a PRIVATE standalone Apps Script project, Drive advanced
 * service v3, and the drive.metadata.readonly OAuth scope. This code is not
 * an installable trigger; it cannot create triggers or email messages.
 *
 * Script Properties (in the private script, never GitHub):
 *   SUPPLIER_ALLOWLIST_JSON: JSON array of 1..20 approved Sheets file IDs
 *   SUPPLIER_BASELINE_JSON: managed by this script after approval
 *   SUPPLIER_INIT_ACK: "I_ACCEPT_INITIAL_BASELINE_NO_BACKFILL" (one-time)
 *
 * IMPORTANT: Apps Script runs under the OWNER'S authorized identity, NOT
 * the previously used service account. drive.metadata.readonly lets a script
 * read metadata across accessible Drive files even though our source
 * allowlist restricts calls. Verify this permission before actual use.
 */
var SupplierMonitorApp = (function () {
  'use strict';
  var ALLOWLIST = 'SUPPLIER_ALLOWLIST_JSON';
  var BASELINE = 'SUPPLIER_BASELINE_JSON';
  var INITIAL_ACK = 'SUPPLIER_INIT_ACK';
  var PHRASE = 'I_ACCEPT_INITIAL_BASELINE_NO_BACKFILL';
  var LIMIT_BYTES = 9000; // Apps Script per-property value: 9 KB.

  function privateStore() {
    return PropertiesService.getScriptProperties();
  }

  function readAllowlist(store) {
    var raw = store.getProperty(ALLOWLIST);
    if (!raw || raw.length > LIMIT_BYTES) {
      throw new Error('PRIVATE_ALLOWLIST_NOT_CONFIGURED');
    }
    var items;
    try {
      items = JSON.parse(raw);
    } catch (ignore) {
      throw new Error('INVALID_PRIVATE_ALLOWLIST');
    }
    return SupplierMonitorCore.validateAllowlist(items);
  }

  function readBaseline(store) {
    var raw = store.getProperty(BASELINE);
    if (raw == null) {
      return null;
    }
    if (raw.length > LIMIT_BYTES) {
      throw new Error('INVALID_PRIVATE_BASELINE');
    }
    var snapshot;
    try {
      snapshot = JSON.parse(raw);
    } catch (ignore) {
      throw new Error('INVALID_PRIVATE_BASELINE');
    }
    SupplierMonitorCore.validateSnapshot(snapshot);
    return snapshot;
  }

  function scan(ids) {
    var data = Object.create(null);
    // Explicit file GET only. No Drive.Files.list or folder traversal.
    ids.forEach(function (id) {
      var item;
      try {
        item = Drive.Files.get(id, {
          fields: 'id,mimeType,version,modifiedTime,trashed',
          supportsAllDrives: true,
        });
      } catch (ignore) {
        // Do NOT echo raw Google errors: they may contain a private file ID.
        throw new Error('APPROVED_METADATA_READ_FAILED');
      }
      data[id] = item;
    });
    return SupplierMonitorCore.makeSnapshot(ids, data);
  }

  function withLock(action) {
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(1000)) {
      throw new Error('SUPPLIER_MONITOR_ALREADY_RUNNING');
    }
    try {
      return action();
    } finally {
      lock.releaseLock();
    }
  }

  function preview() {
    return withLock(function () {
      var store = privateStore();
      var ids = readAllowlist(store);
      var previous = readBaseline(store);
      var current = scan(ids);
      var counts = SupplierMonitorCore.compareSnapshots(previous, current);
      var summary = {
        mode: 'manual_metadata_preview_only',
        baselineRequired: counts.baselineRequired,
        observedCount: counts.observedCount,
        changedCount: counts.changedCount,
        unchangedCount: counts.unchangedCount,
        pendingCount: counts.pendingCount,
        driveSourceWrites: 0,
        stateWrites: 0,
        triggersInstalled: 0,
        downstreamProcessingStarted: false,
      };
      console.log(JSON.stringify(summary));
      return summary; // no IDs, source names, prices or revisions.
    });
  }

  function initializeBaselineOnce() {
    return withLock(function () {
      var store = privateStore();
      if (store.getProperty(BASELINE) !== null) {
        throw new Error('BASELINE_EXISTS_REFUSE_OVERWRITE');
      }
      if (store.getProperty(INITIAL_ACK) !== PHRASE) {
        throw new Error('BASELINE_REQUIRES_EXPLICIT_ONE_TIME_ACK');
      }
      var ids = readAllowlist(store);
      var current = scan(ids);
      var encoded = JSON.stringify(current);
      if (encoded.length > LIMIT_BYTES) {
        throw new Error('BASELINE_TOO_LARGE_FOR_SCRIPT_PROPERTIES');
      }
      // Writes ONLY to private Script Properties. No Drive source writes.
      store.setProperty(BASELINE, encoded);
      store.deleteProperty(INITIAL_ACK);
      var result = {
        mode: 'manually_initialized_private_baseline',
        observedCount: ids.length,
        baselineSavedToScriptProperties: true,
        driveSourceWrites: 0,
        triggersInstalled: 0,
      };
      console.log(JSON.stringify(result));
      return result;
    });
  }

  return {preview: preview, initializeBaselineOnce: initializeBaselineOnce};
}());

/**
 * Manually run this from Apps Script after configuring PRIVATE Script Properties.
 * No automatic notification, trigger, remote analysis or schedule.
 */
function previewApprovedSupplierUpdates() {
  return SupplierMonitorApp.preview();
}

/**
 * Manually run ONLY after reviewing the one-time baseline acknowledgment.
 * Initial files are considered known; this does not backfill or parse them.
 */
function initializeSupplierMonitorBaselineOnce() {
  return SupplierMonitorApp.initializeBaselineOnce();
}
