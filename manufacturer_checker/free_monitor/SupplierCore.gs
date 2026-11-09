/**
 * Supplier metadata monitor — pure, deterministic logic for Google Apps Script.
 * PUBLIC CODE, FAKE TEST DATA ONLY. Never put real supplier IDs in this file.
 * No Drive access, network, logging or persistence in the core.
 */
var SupplierMonitorCore = (function () {
  'use strict';
  var SCHEMA = 'supplier-apps-script-baseline-v1';
  var MIME = 'application/vnd.google-apps.spreadsheet';
  var ID_RE = /^[A-Za-z0-9_-]{10,200}$/;
  var MAX_FILES = 20;

  function validateAllowlist(ids) {
    if (!Array.isArray(ids) || ids.length < 1 || ids.length > MAX_FILES) {
      throw new Error('INVALID_ALLOWLIST');
    }
    var seen = Object.create(null);
    var sorted = [];
    ids.forEach(function (id) {
      if (typeof id !== 'string' || !ID_RE.test(id) || seen[id]) {
        throw new Error('INVALID_OR_DUPLICATE_FILE_ID');
      }
      seen[id] = true;
      sorted.push(id);
    });
    return sorted.sort();
  }

  function normalizeMetadata(expectedId, item) {
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        item.id !== expectedId || item.mimeType !== MIME ||
        item.trashed === true) {
      throw new Error('UNTRUSTED_OR_UNSUPPORTED_METADATA');
    }
    if (item.trashed !== false && item.trashed !== undefined) {
      throw new Error('INVALID_TRASH_FLAG');
    }
    var version = item.version == null ? '' : String(item.version);
    var modified = item.modifiedTime == null ? '' : item.modifiedTime;
    if (version && !/^[0-9]+$/.test(version)) {
      throw new Error('INVALID_VERSION');
    }
    if (typeof modified !== 'string' ||
        (modified && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(modified))) {
      throw new Error('INVALID_MODIFIED_TIME');
    }
    if (!version && !modified) {
      throw new Error('MISSING_REVISION_MARKER');
    }
    return {version: version, modifiedTime: modified, mimeType: MIME};
  }

  function makeSnapshot(ids, metadataById) {
    var approved = validateAllowlist(ids);
    if (!metadataById || typeof metadataById !== 'object' ||
        Array.isArray(metadataById) ||
        Object.keys(metadataById).length !== approved.length) {
      throw new Error('INCOMPLETE_METADATA_RESULT');
    }
    var revisions = Object.create(null);
    approved.forEach(function (id) {
      if (!Object.prototype.hasOwnProperty.call(metadataById, id)) {
        throw new Error('MISSING_APPROVED_FILE');
      }
      revisions[id] = normalizeMetadata(id, metadataById[id]);
    });
    // No source data is included — file IDs/revisions are still private.
    return {schemaVersion: SCHEMA, approvedFileIds: approved, revisions: revisions};
  }

  function validateSnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== 'object' ||
        snapshot.schemaVersion !== SCHEMA ||
        !Array.isArray(snapshot.approvedFileIds) ||
        !snapshot.revisions || typeof snapshot.revisions !== 'object' ||
        Array.isArray(snapshot.revisions)) {
      throw new Error('INVALID_PRIVATE_BASELINE');
    }
    var ids = validateAllowlist(snapshot.approvedFileIds);
    if (JSON.stringify(ids) !== JSON.stringify(snapshot.approvedFileIds) ||
        Object.keys(snapshot.revisions).length !== ids.length) {
      throw new Error('INVALID_PRIVATE_BASELINE');
    }
    ids.forEach(function (id) {
      var entry = snapshot.revisions[id];
      if (!entry || entry.mimeType !== MIME ||
          typeof entry.version !== 'string' ||
          typeof entry.modifiedTime !== 'string' ||
          (!entry.version && !entry.modifiedTime) ||
          (entry.version && !/^[0-9]+$/.test(entry.version)) ||
          (entry.modifiedTime && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(entry.modifiedTime))) {
        throw new Error('INVALID_PRIVATE_BASELINE');
      }
    });
    return ids;
  }

  function compareSnapshots(previous, current) {
    var currentIds = validateSnapshot(current);
    if (previous == null) {
      return {
        baselineRequired: true,
        observedCount: currentIds.length,
        changedCount: 0,
        unchangedCount: 0,
        pendingCount: currentIds.length,
        writesPerformed: 0,
      };
    }
    var oldIds = validateSnapshot(previous);
    if (JSON.stringify(oldIds) !== JSON.stringify(currentIds)) {
      throw new Error('ALLOWLIST_CHANGED_REVIEW_REQUIRED');
    }
    var changed = 0;
    currentIds.forEach(function (id) {
      var a = previous.revisions[id];
      var b = current.revisions[id];
      if (a.version !== b.version || a.modifiedTime !== b.modifiedTime ||
          a.mimeType !== b.mimeType) {
        changed += 1;
      }
    });
    return {
      baselineRequired: false,
      observedCount: currentIds.length,
      changedCount: changed,
      unchangedCount: currentIds.length - changed,
      pendingCount: changed,
      writesPerformed: 0,
    };
  }

  return {
    schema: SCHEMA,
    validateAllowlist: validateAllowlist,
    makeSnapshot: makeSnapshot,
    validateSnapshot: validateSnapshot,
    compareSnapshots: compareSnapshots,
  };
}());
