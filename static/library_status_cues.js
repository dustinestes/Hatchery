/**
 * Shared Library status cue vocabulary (#387 / ADR-0018).
 * Keep in sync with lib/library_status_cues.py for Cached ↔ Content 1:1.
 * Soft-disable linked cue: #408.
 */
(function (global) {
  'use strict';

  var SOURCE_SHORT = {
    ok: '',
    missing: 'source missing',
    orphan: 'orphaned',
    disabled: 'connection disabled',
    rate_limited: 'rate limited',
    unreachable: 'unreachable',
    unconfirmable: 'tip unconfirmable',
  };

  var SYNC_SHORT = {
    in_sync: 'synced',
    out_of_sync: 'out of sync',
    unevaluated: '',
  };

  var _libraryEnabled = true;

  function setLibraryEnabled(enabled) {
    _libraryEnabled = !!enabled;
  }

  function libraryEnabled() {
    return _libraryEnabled;
  }

  function resolve(opts) {
    opts = opts || {};
    var drift = String(opts.drift_state || '').trim().toLowerCase();
    var orphan = !!opts.orphan;
    var orphanReason = String(opts.orphan_reason || '').trim();
    var status = String(opts.source_status || '').trim().toLowerCase();
    var sync = String(opts.sync_state || '').trim().toLowerCase();
    var message = String(opts.source_status_message || orphanReason || '').trim();
    var name = String(opts.cache_name || '').trim();
    var enabled = opts.library_enabled;
    if (enabled === undefined || enabled === null) {
      enabled = _libraryEnabled;
    } else {
      enabled = !!enabled;
    }

    if (drift === 'local' || (!status && !orphan && (!drift || drift === 'local'))) {
      return {
        cue: 'local',
        short: '',
        severity: 'muted',
        show_rail_icon: false,
        can_sync: false,
        can_reattach: false,
        header_label: '',
        header_aria: '',
        message: '',
        source_status: null,
        sync_state: null,
        filter_keys: ['local'],
      };
    }

    if (!status) {
      if (orphan || drift === 'orphan') {
        status = 'orphan';
        sync = 'unevaluated';
        message = message || orphanReason || 'Library connection or binding missing';
      } else if (drift === 'out_of_sync') {
        status = 'ok';
        sync = 'out_of_sync';
      } else if (drift === 'in_sync') {
        status = 'ok';
        sync = 'in_sync';
      } else if (drift === 'unknown') {
        status = 'unconfirmable';
        sync = 'unevaluated';
      } else {
        status = 'unconfirmable';
        sync = 'unevaluated';
      }
    }
    if (!sync) {
      sync = status !== 'ok' ? 'unevaluated' : 'in_sync';
    }
    if (orphan || status === 'orphan') {
      status = 'orphan';
      sync = 'unevaluated';
      message = message || orphanReason || 'Library connection or binding missing';
    }

    if (!enabled) {
      return {
        cue: 'linked',
        short: 'linked',
        severity: 'muted',
        show_rail_icon: true,
        can_sync: false,
        can_reattach: false,
        header_label: 'Linked',
        header_aria: 'Linked from Library (Library is disabled)',
        message: 'Library is disabled. Sync and re-attach are unavailable.',
        source_status: status,
        sync_state: sync,
        filter_keys: ['linked'],
      };
    }

    var short = '';
    var cue = 'unconfirmable';
    var severity = 'warn';
    var canSync = false;
    var canReattach = false;
    var showRail = true;
    var filterKeys = [];

    if (status === 'ok' && sync === 'in_sync') {
      cue = 'synced';
      short = SYNC_SHORT.in_sync;
      severity = 'ok';
      filterKeys = ['in_sync', 'ok'];
    } else if (status === 'ok' && sync === 'out_of_sync') {
      cue = 'out_of_sync';
      short = SYNC_SHORT.out_of_sync;
      severity = 'action';
      canSync = true;
      filterKeys = ['out_of_sync', 'ok'];
    } else if (status === 'orphan') {
      cue = 'orphan';
      short = SOURCE_SHORT.orphan;
      severity = 'warn';
      canReattach = true;
      filterKeys = ['orphan'];
    } else if (status === 'missing') {
      cue = 'missing';
      short = SOURCE_SHORT.missing;
      severity = 'warn';
      canReattach = true;
      filterKeys = ['missing'];
    } else if (status === 'rate_limited' || status === 'unreachable') {
      cue = 'communication';
      short = SOURCE_SHORT[status] || status.replace(/_/g, ' ');
      severity = 'warn';
      filterKeys = ['communication', status];
    } else if (status === 'disabled') {
      cue = 'disabled';
      short = SOURCE_SHORT.disabled;
      severity = 'muted';
      filterKeys = ['disabled'];
    } else {
      cue = 'unconfirmable';
      short = SOURCE_SHORT[status] || 'tip unconfirmable';
      severity = 'muted';
      filterKeys = ['unconfirmable', status];
    }

    var headerLabel;
    var headerAria;
    if (canSync) {
      headerLabel = 'Out of sync';
      headerAria = name ? 'Sync ' + name + ' from Library' : 'Sync from Library';
    } else if (canReattach) {
      headerLabel = short ? short.charAt(0).toUpperCase() + short.slice(1) : 'Re-attach';
      headerAria = message || headerLabel;
    } else if (cue === 'synced') {
      headerLabel = 'Synced';
      headerAria = 'In sync with Library';
    } else {
      headerLabel = short ? short.charAt(0).toUpperCase() + short.slice(1) : 'Library status';
      headerAria = message || headerLabel;
    }

    return {
      cue: cue,
      short: short,
      severity: severity,
      show_rail_icon: showRail,
      can_sync: canSync,
      can_reattach: canReattach,
      header_label: headerLabel,
      header_aria: headerAria,
      message: message,
      source_status: status,
      sync_state: sync,
      filter_keys: filterKeys,
    };
  }

  function resolveFromItem(item) {
    item = item || {};
    return resolve({
      source_status: item.source_status,
      sync_state: item.sync_state,
      source_status_message: item.source_status_message,
      drift_state: item.drift_state,
      orphan: item.orphan,
      orphan_reason: item.orphan_reason,
      cache_name: item.name,
      library_enabled: item.library_enabled,
    });
  }

  function resolveFromButton(btn) {
    if (!btn) return resolve({ drift_state: 'local' });
    return resolve({
      source_status: btn.getAttribute('data-source-status'),
      sync_state: btn.getAttribute('data-sync-state'),
      source_status_message: btn.getAttribute('data-source-status-message'),
      drift_state: btn.getAttribute('data-drift-state'),
      orphan: btn.getAttribute('data-orphan') === '1',
      orphan_reason: btn.getAttribute('data-orphan-reason'),
      cache_name: btn.getAttribute('data-name'),
    });
  }

  function matchesFilter(cue, filterValue) {
    if (!filterValue) return true;
    var keys = (cue && cue.filter_keys) || [];
    return keys.indexOf(filterValue) !== -1;
  }

  global.HatcheryLibraryStatus = {
    SOURCE_SHORT: SOURCE_SHORT,
    SYNC_SHORT: SYNC_SHORT,
    setLibraryEnabled: setLibraryEnabled,
    libraryEnabled: libraryEnabled,
    resolve: resolve,
    resolveFromItem: resolveFromItem,
    resolveFromButton: resolveFromButton,
    matchesFilter: matchesFilter,
  };
})(typeof window !== 'undefined' ? window : globalThis);
