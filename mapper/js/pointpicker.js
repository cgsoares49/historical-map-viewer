// PointPicker: shared point-list digitizing tool (points table, arrow-key nudge,
// save/load .txt round-trip) used by both mapper/tools/digitizer.html (points
// picked off an imported image) and mapper-local.html's CREATOR "Digitize" mode
// (points picked off the app's own live rendered map). Each host supplies a
// `converter` that maps between its own native pixel space and lon/lat — the
// module itself has no opinion on projections, images, or canvases.
//
// File format (unchanged from the original digitizer.html): a count header line
// followed by "lon , lat" rows, rounded to 4 decimals.

(function (global) {
  const STYLE_ID = 'pointpicker-styles';

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .pp-header {
        padding: 8px 10px;
        background: #2a2a2a;
        border-bottom: 1px solid #444;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-family: system-ui, sans-serif;
      }
      .pp-count { font-size: 12px; color: #eee; }
      .pp-newrun {
        background: #3a5a8a; color: #fff; border: none;
        padding: 3px 8px; border-radius: 4px; cursor: pointer;
        font-size: 11px; white-space: nowrap;
      }
      .pp-newrun:hover:not(:disabled) { background: #4a6a9a; }
      .pp-newrun:disabled { background: #444; color: #888; cursor: default; }
      .pp-clear {
        background: #8a3a3a; color: #fff; border: none;
        padding: 3px 10px; border-radius: 4px; cursor: pointer; font-size: 11px;
      }
      .pp-clear:hover { background: #a94a4a; }
      .pp-table-wrap { overflow-y: auto; flex: 1 1 auto; min-height: 0; font-family: system-ui, sans-serif; }
      .pp-table { width: 100%; border-collapse: collapse; font-size: 12px; background: #252525; color: #eee; }
      .pp-table th, .pp-table td { padding: 4px 6px; border-bottom: 1px solid #3a3a3a; text-align: left; }
      .pp-table th { background: #2a2a2a; position: sticky; top: 0; }
      .pp-num { font-family: monospace; color: #ccc; }
      .pp-row-actions { display: flex; gap: 3px; align-items: center; }
      .pp-move-btn { background: none; border: none; color: #8ab4d8; cursor: pointer; font-size: 11px; padding: 0 2px; }
      .pp-move-btn:hover:not(:disabled) { color: #b6d8f5; }
      .pp-move-btn:disabled { color: #555; cursor: default; }
      .pp-del-btn { background: none; border: none; color: #d55; cursor: pointer; font-size: 14px; }
      .pp-del-btn:hover { color: #f66; }
      .pp-row.active { background: #2f3f2f; }
      .pp-row { cursor: pointer; }
      .pp-empty { padding: 14px; color: #777; font-size: 12px; font-family: system-ui, sans-serif; }
      .pp-save-section { padding: 10px; font-family: system-ui, sans-serif; }
      .pp-save {
        width: 100%; background: #3a8a5a; color: #fff; border: none;
        padding: 7px 10px; border-radius: 4px; cursor: pointer;
        font-size: 12px; font-weight: 600;
      }
      .pp-save:hover { background: #4a9a6a; }
      .pp-save-info { font-size: 11px; color: #888; margin-top: 4px; }
      .pp-load-label {
        display: block; text-align: center; margin-top: 8px;
        background: #3a6ea5; color: #fff; padding: 6px 12px;
        border-radius: 4px; cursor: pointer; font-size: 12px;
      }
      .pp-load-label:hover { background: #4a7eb5; }
      .pp-load-input { display: none; }
    `;
    document.head.appendChild(style);
  }

  class PointPicker {
    constructor(opts) {
      opts = opts || {};
      this.converter = opts.converter; // { pixelToLonLat(px,py), lonLatToPixel(lon,lat) }
      this.dbNamespace = opts.dbNamespace || 'default';
      this.onChange = opts.onChange || (() => {});
      this.onSelect = opts.onSelect || null; // optional: (point) => host can pan/center on it
      this.container = opts.container || null;

      this.points = []; // { id, lon, lat }
      this.activeId = null;
      this.nextId = 1;

      this._els = null;
      this.lastHandle = null;
      this.lastSaveName = localStorage.getItem(this._lsKey()) || 'digitized_points.txt';
      this._saveLabelResetTimer = null;

      if (this.container) {
        ensureStyles();
        this._buildUI();
      }
      if (window.showSaveFilePicker) {
        this._idbGet('lastHandle').then(handle => {
          if (handle) {
            this.lastHandle = handle;
            this.lastSaveName = handle.name;
            this._updateSaveLocLabel();
          }
        }).catch(() => {}); // e.g. private browsing without IndexedDB
      }
    }

    _lsKey() { return `pointpicker_${this.dbNamespace}_lastSaveName`; }

    // ── points list ops ──────────────────────────────────────────────────────
    addPoint(lon, lat) {
      const p = { id: this.nextId++, lon, lat };
      this.points.push(p);
      this.activeId = p.id;
      this._changed();
      return p;
    }

    addPointFromPixel(px, py) {
      const { lon, lat } = this.converter.pixelToLonLat(px, py);
      return this.addPoint(lon, lat);
    }

    removePoint(id) {
      this.points = this.points.filter(p => p.id !== id);
      if (this.activeId === id) this.activeId = null;
      this._changed();
    }

    removeActivePoint() {
      if (this.activeId != null) this.removePoint(this.activeId);
    }

    movePoint(id, delta) {
      const idx = this.points.findIndex(p => p.id === id);
      if (idx === -1) return;
      const newIdx = idx + delta;
      if (newIdx < 0 || newIdx >= this.points.length) return;
      [this.points[idx], this.points[newIdx]] = [this.points[newIdx], this.points[idx]];
      this._changed();
    }

    setActive(id) {
      this.activeId = id;
      this._changed();
    }

    getActivePoint() {
      return this.points.find(p => p.id === this.activeId) || null;
    }

    getPoints() {
      return this.points;
    }

    clearPoints() {
      if (this.points.length === 0) return;
      if (!confirm(`Clear all ${this.points.length} points?`)) return;
      this.points = [];
      this.activeId = null;
      this._changed();
    }

    // Continue a fresh run from wherever the last run left off (either end),
    // without hand-deleting a long list of already-saved points first.
    startNewRun(which) {
      if (this.points.length <= 1) return;
      const keep = which === 'first' ? this.points[0] : this.points[this.points.length - 1];
      const label = which === 'first' ? 'first point (#1)' : `last point (#${this.points.length})`;
      if (!confirm(`Discard the other ${this.points.length - 1} point(s) and keep only the ${label} as the start of a new run?`)) return;
      this.points = [keep];
      this.activeId = keep.id;
      this._changed();
    }

    // Nudge the active point by dxPixels/dyPixels in the host's own native pixel
    // unit. For Digitizer that's a fixed image pixel (zoom-independent); for
    // CREATOR there is no source image to anchor to, so "1 pixel" is naturally
    // 1 canvas pixel at the current zoom level — zoom in for finer nudges. This
    // is an intentional per-host difference, not a bug.
    nudgeActive(dxPixels, dyPixels) {
      const p = this.getActivePoint();
      if (!p) return;
      const { px, py } = this.converter.lonLatToPixel(p.lon, p.lat);
      let nx = px + dxPixels, ny = py + dyPixels;
      // Optional hook: hosts with a bounded pixel space (e.g. Digitizer's source
      // image) can clamp the nudge so it can't walk a point off the edge.
      // CREATOR has no such bound and simply omits this.
      if (this.converter.clampPixel) {
        ({ px: nx, py: ny } = this.converter.clampPixel(nx, ny));
      }
      const { lon, lat } = this.converter.pixelToLonLat(nx, ny);
      p.lon = lon;
      p.lat = lat;
      this._changed();
    }

    _changed() {
      this._redrawTable();
      this.onChange();
    }

    // ── save / load ──────────────────────────────────────────────────────────
    pointsFileContent() {
      const lines = [String(this.points.length)];
      this.points.forEach(p => lines.push(`${p.lon.toFixed(4)} , ${p.lat.toFixed(4)}`));
      return lines.join('\n') + '\n';
    }

    loadFromText(text) {
      const lines = text.split(/\r?\n/).filter(l => l.trim().length > 0);
      if (lines.length < 1) return;
      const count = parseInt(lines[0].trim(), 10);
      const rows = lines.slice(1, isNaN(count) ? undefined : count + 1);
      rows.forEach(line => {
        // Accept comma- or tab-separated (and mixes with stray whitespace).
        const parts = line.trim().split(/[,\t]+/).map(s => s.trim()).filter(s => s.length > 0);
        if (parts.length < 2) return;
        const lon = parseFloat(parts[0]), lat = parseFloat(parts[1]);
        if (isNaN(lon) || isNaN(lat)) return;
        this.points.push({ id: this.nextId++, lon, lat });
      });
      this._changed();
    }

    // Persist the last-used save handle (Chromium's File System Access API)
    // across browser restarts via IndexedDB, keyed per dbNamespace so Digitizer
    // and CREATOR each remember their own last save location independently.
    _idbOpen() {
      return new Promise((resolve, reject) => {
        const req = indexedDB.open('pointpicker-db', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('handles');
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }
    async _idbGet(key) {
      const db = await this._idbOpen();
      return new Promise((resolve, reject) => {
        const req = db.transaction('handles', 'readonly').objectStore('handles').get(`${this.dbNamespace}:${key}`);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }
    async _idbSet(key, value) {
      const db = await this._idbOpen();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('handles', 'readwrite');
        tx.objectStore('handles').put(value, `${this.dbNamespace}:${key}`);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    }

    async saveAs() {
      const content = this.pointsFileContent();
      if (window.showSaveFilePicker) {
        let handle;
        try {
          handle = await window.showSaveFilePicker({
            suggestedName: this.lastSaveName,
            // Biasing the dialog to reopen in the same folder is just a hint —
            // no permission is needed to pass a previous handle here.
            startIn: this.lastHandle || 'documents',
            types: [{ description: 'Text', accept: { 'text/plain': ['.txt'] } }],
          });
        } catch (e) {
          return; // user cancelled or picker unsupported mid-flight — no feedback needed
        }
        const writable = await handle.createWritable();
        await writable.write(content);
        await writable.close();
        this.lastHandle = handle;
        this.lastSaveName = handle.name;
        localStorage.setItem(this._lsKey(), this.lastSaveName);
        this._idbSet('lastHandle', handle).catch(() => {});
        this._flashSaveSuccess();
        return;
      }
      const filename = prompt("Save as (downloads to your browser's download folder):", this.lastSaveName) || this.lastSaveName;
      this.lastSaveName = filename;
      localStorage.setItem(this._lsKey(), this.lastSaveName);
      const blob = new Blob([content], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      this._flashSaveSuccess();
    }

    // ── UI: table + save/load controls rendered into opts.container ────────
    _buildUI() {
      this.container.innerHTML = `
        <div class="pp-header">
          <strong class="pp-count">0 points</strong>
          <div style="display:flex; gap:5px;">
            <button class="pp-newrun" data-which="first" title="Discard all but the first point, so it becomes the start of a new run" disabled>Keep 1st</button>
            <button class="pp-newrun" data-which="last" title="Discard all but the last point, so it becomes the start of a new run" disabled>Keep Last</button>
            <button class="pp-clear" title="Clear all points">Clear</button>
          </div>
        </div>
        <div class="pp-table-wrap">
          <table class="pp-table">
            <thead><tr><th>#</th><th>Lon</th><th>Lat</th><th></th></tr></thead>
            <tbody></tbody>
          </table>
          <div class="pp-empty">Click on the map to place points.</div>
        </div>
        <div class="pp-save-section">
          <button class="pp-save">Save Points...</button>
          <div class="pp-save-info"></div>
          <label class="pp-load-label">
            Load Points File
            <input type="file" class="pp-load-input" accept=".txt,.csv,text/plain,text/csv">
          </label>
        </div>
      `;
      this._els = {
        count: this.container.querySelector('.pp-count'),
        keepFirst: this.container.querySelector('.pp-newrun[data-which="first"]'),
        keepLast: this.container.querySelector('.pp-newrun[data-which="last"]'),
        clear: this.container.querySelector('.pp-clear'),
        table: this.container.querySelector('.pp-table'),
        body: this.container.querySelector('tbody'),
        empty: this.container.querySelector('.pp-empty'),
        saveBtn: this.container.querySelector('.pp-save'),
        saveInfo: this.container.querySelector('.pp-save-info'),
        loadInput: this.container.querySelector('.pp-load-input'),
      };
      this._els.keepFirst.addEventListener('click', () => this.startNewRun('first'));
      this._els.keepLast.addEventListener('click', () => this.startNewRun('last'));
      this._els.clear.addEventListener('click', () => this.clearPoints());
      this._els.saveBtn.addEventListener('click', () => this.saveAs());
      this._els.loadInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => this.loadFromText(reader.result);
        reader.readAsText(file);
        e.target.value = '';
      });
      this._updateSaveLocLabel();
      this._redrawTable();
    }

    _updateSaveLocLabel() {
      if (!this._els) return;
      clearTimeout(this._saveLabelResetTimer);
      this._els.saveInfo.style.color = '#888';
      this._els.saveInfo.textContent = `Next save: ${this.lastSaveName}`;
    }

    _flashSaveSuccess() {
      if (!this._els) return;
      clearTimeout(this._saveLabelResetTimer);
      this._els.saveInfo.style.color = '#6a6';
      this._els.saveInfo.textContent = `✓ Saved: ${this.lastSaveName}`;
      this._saveLabelResetTimer = setTimeout(() => this._updateSaveLocLabel(), 2500);
    }

    _redrawTable() {
      if (!this._els) return;
      const { count, keepFirst, keepLast, empty, table, body } = this._els;
      count.textContent = `${this.points.length} point${this.points.length === 1 ? '' : 's'}`;
      keepFirst.disabled = this.points.length <= 1;
      keepLast.disabled = this.points.length <= 1;
      empty.style.display = this.points.length === 0 ? 'block' : 'none';
      table.style.display = this.points.length === 0 ? 'none' : 'table';
      body.innerHTML = '';

      this.points.forEach((p, i) => {
        const tr = document.createElement('tr');
        tr.className = 'pp-row';
        if (p.id === this.activeId) tr.classList.add('active');
        tr.addEventListener('click', () => {
          this.activeId = p.id;
          this._redrawTable();
          this.onChange();
          if (this.onSelect) this.onSelect(p);
        });

        const tdIdx = document.createElement('td');
        tdIdx.textContent = i + 1;
        tr.appendChild(tdIdx);

        const tdLon = document.createElement('td');
        tdLon.className = 'pp-num';
        tdLon.textContent = p.lon.toFixed(5);
        tr.appendChild(tdLon);

        const tdLat = document.createElement('td');
        tdLat.className = 'pp-num';
        tdLat.textContent = p.lat.toFixed(5);
        tr.appendChild(tdLat);

        const tdActions = document.createElement('td');
        const actions = document.createElement('div');
        actions.className = 'pp-row-actions';

        const upBtn = document.createElement('button');
        upBtn.className = 'pp-move-btn';
        upBtn.textContent = '▲';
        upBtn.title = 'Move up';
        upBtn.disabled = i === 0;
        upBtn.addEventListener('click', (ev) => { ev.stopPropagation(); this.movePoint(p.id, -1); });
        actions.appendChild(upBtn);

        const downBtn = document.createElement('button');
        downBtn.className = 'pp-move-btn';
        downBtn.textContent = '▼';
        downBtn.title = 'Move down';
        downBtn.disabled = i === this.points.length - 1;
        downBtn.addEventListener('click', (ev) => { ev.stopPropagation(); this.movePoint(p.id, 1); });
        actions.appendChild(downBtn);

        const delBtn = document.createElement('button');
        delBtn.className = 'pp-del-btn';
        delBtn.textContent = '✕';
        delBtn.addEventListener('click', (ev) => { ev.stopPropagation(); this.removePoint(p.id); });
        actions.appendChild(delBtn);

        tdActions.appendChild(actions);
        tr.appendChild(tdActions);

        body.appendChild(tr);
      });
    }

    destroy() {
      if (this.container) this.container.innerHTML = '';
      this._els = null;
    }
  }

  global.PointPicker = PointPicker;
})(window);
