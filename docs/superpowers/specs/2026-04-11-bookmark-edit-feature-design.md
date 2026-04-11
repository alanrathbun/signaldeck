# Bookmark Edit Feature

**Date:** 2026-04-11
**Branch:** TBD
**Status:** Approved

## Overview

Make bookmarks editable after creation, and replace the one-click "quickBookmark" on the Live Signals page with a modal that lets the operator review and tweak fields before saving. A single modal component powers three entry points: the Edit button on the Bookmarks table, the Bookmark button on Live Signals for a new signal (pre-filled from the signal), and the Bookmark button on Live Signals for an already-bookmarked signal (opens Edit mode on the existing bookmark).

Editable fields: `label`, `modulation`, `decoder`, `priority`, `camp_on_active`, `notes`. Not editable: `frequency_hz` — changing the frequency means "different bookmark," delete+create is the right mental model.

Notes are displayed in the Bookmarks table as a muted subtitle under the label, not as a separate column. `camp_on_active` is exposed in the edit UI but is a dead field at runtime — the `BookmarkMonitor` engine class that would consume it exists but is not yet wired into the scanner loop. Surfacing it now prepares the data layer and UX for a future bookmark cycling feature that the operator plans to build separately.

## Non-goals

- **Making `camp_on_active` actually affect scanner behavior.** The field becomes editable and round-trips to the database. Wiring it into the scanner's bookmark cycling mode is a separate future project.
- **Wiring `BookmarkMonitor` into the main scanner loop.** The class has passing unit tests and is ready to plug in, but doing so is out of scope here.
- **Notes-aware features.** No sort-by-notes, no full-text search, no notes preview in any other UI. Notes are just stored and displayed.
- **Editing `frequency_hz`.** If a bookmark's frequency needs to change, delete it and create a new one.
- **Bulk operations** (edit N bookmarks at once, bulk delete, etc.).
- **Import/export of bookmarks.** Out of scope.
- **Schema migrations.** Every field the edit UI touches is already in the existing `bookmarks` table. `camp_on_active` and `notes` are ghost columns today — stored but unused.

## Architecture

Four small changes, no new files beyond one test file:

1. **Backend: `PATCH /api/bookmarks/{id}`** — new endpoint in `signaldeck/api/routes/bookmarks.py` that accepts a partial-update payload (JSON Merge Patch semantics: field present = update, field absent = leave alone). Backed by a new `Database.update_bookmark()` method with the same partial-update contract.
2. **Frontend: one shared `BookmarkEditModal`** — Alpine state + markup for a modal form that renders from an `editingBookmark` object. Three open-entry methods (`openEditBookmark`, `openCreateBookmarkFromSignal`, `openNewBookmark`) populate the object differently; one `saveBookmarkEdit` method decides between POST and PATCH based on `editModalMode`.
3. **Bookmarks page table gains an Edit button and a notes subtitle** under the label in each row. The existing inline "Add Bookmark" form above the table is replaced with a single `+ Add bookmark` button that opens the modal in new-create mode.
4. **Live Signals Bookmark button opens the modal** instead of toast-saving. The existing `isBookmarked(freqHz)` helper is refactored into `findBookmarkForFrequency(freqHz)` that returns the bookmark object (or null). The Click path uses that return value to decide whether to open Create or Edit mode, removing the `:disabled` behavior in favor of "button does double duty."

## Backend design

### `signaldeck/storage/database.py` — new method

```python
async def update_bookmark(
    self,
    bookmark_id: int,
    *,
    label: str | None = None,
    modulation: str | None = None,
    decoder: str | None = None,
    priority: int | None = None,
    camp_on_active: bool | None = None,
    notes: str | None = None,
) -> bool:
    """Partial update of a bookmark. Only fields passed with a non-None
    value are modified. Returns True if the row existed and was updated,
    False if no such bookmark."""
```

Implementation builds a dynamic `SET` clause from whichever kwargs are non-None:

```python
    async def update_bookmark(
        self,
        bookmark_id: int,
        *,
        label: str | None = None,
        modulation: str | None = None,
        decoder: str | None = None,
        priority: int | None = None,
        camp_on_active: bool | None = None,
        notes: str | None = None,
    ) -> bool:
        updates: list[str] = []
        params: list = []
        if label is not None:
            updates.append("label = ?")
            params.append(label)
        if modulation is not None:
            updates.append("modulation = ?")
            params.append(modulation)
        if decoder is not None:
            updates.append("decoder = ?")
            params.append(decoder)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if camp_on_active is not None:
            updates.append("camp_on_active = ?")
            params.append(int(camp_on_active))
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if not updates:
            # Nothing to change — still report whether the row exists.
            cursor = await self._conn.execute(
                "SELECT id FROM bookmarks WHERE id = ?", (bookmark_id,)
            )
            row = await cursor.fetchone()
            return row is not None

        params.append(bookmark_id)
        sql = f"UPDATE bookmarks SET {', '.join(updates)} WHERE id = ?"
        cursor = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cursor.rowcount > 0
```

**Why keyword-only args:** callers can't confuse positional ordering. Consistent with Task 3's `insert_remember_token` and Task 4's `create_remember_token`.

**Why `notes=""` is allowed (not null) when clearing:** the partial-update contract uses `None` to mean "don't touch this column." The frontend sends `notes: ""` (empty string) when the user clears the notes field in the modal, and the backend stores an empty string. Null would be ambiguous with "field omitted." The user explicitly chose empty-string semantics over null during brainstorming.

**Why `bool → int` cast on `camp_on_active`:** SQLite stores booleans as integers. Reads use `bool(row["camp_on_active"])` (already present in `get_all_bookmarks`).

**Why the empty-updates branch checks existence:** if a caller sends an empty PATCH (no fields to update), we still want to correctly return True/False based on whether the bookmark exists, so the caller can raise 404 appropriately.

### `signaldeck/api/routes/bookmarks.py` — new endpoint

```python
from pydantic import Field


class BookmarkUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    modulation: str | None = None
    decoder: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    camp_on_active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/bookmarks/{bookmark_id}")
async def update_bookmark(bookmark_id: int, data: BookmarkUpdate):
    db = get_db()
    ok = await db.update_bookmark(
        bookmark_id,
        label=data.label,
        modulation=data.modulation,
        decoder=data.decoder,
        priority=data.priority,
        camp_on_active=data.camp_on_active,
        notes=data.notes,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"id": bookmark_id, "updated": True}
```

**Validation:**
- `label`: 1–200 chars. Pydantic `min_length=1` rejects empty strings with 422. Clients that want to clear the label can't — it's required when present.
- `priority`: 1–5. Matches the existing Add form's HTML min/max and the model's semantic range.
- `notes`: 2000-char cap. Generous; plenty of room for multi-line notes without being unbounded.
- `modulation`, `decoder`, `camp_on_active`: Pydantic type validation only.

## Frontend design

### Alpine state

New fields on the main component return object:

```javascript
// ---- Bookmark edit/create modal state ----
editingBookmark: null,         // null = modal hidden; object = modal open
editModalMode: 'create',       // 'create' | 'edit'
editModalSignal: null,         // source Live signal for create-from-signal mode
editModalError: '',
```

**Why one `editingBookmark` object:** both create and edit paths show the same form with the same fields. The only differences are (a) which endpoint to call on save, and (b) whether the frequency field is editable. Both are derivable from `editModalMode` and `editModalSignal`. Keeping a single object means the modal markup doesn't branch on mode.

### Methods

```javascript
// --- Dedupe helper: refactor of isBookmarked ---

findBookmarkForFrequency(freqHz) {
  if (!freqHz || !this.bookmarks || !this.bookmarks.length) return null;
  for (const bm of this.bookmarks) {
    if (Math.abs((bm.frequency_hz || 0) - freqHz) < 2500) return bm;
  }
  return null;
},

isBookmarked(freqHz) {
  // Thin wrapper kept for any remaining callers; may be removed once
  // all call sites use findBookmarkForFrequency directly.
  return !!this.findBookmarkForFrequency(freqHz);
},

// --- Modal entry points ---

openEditBookmark(bookmark) {
  // Clone so edits don't mutate the list until save
  this.editingBookmark = { ...bookmark };
  this.editModalMode = 'edit';
  this.editModalSignal = null;
  this.editModalError = '';
},

openCreateBookmarkFromSignal(sig) {
  // If the signal is already bookmarked, route to edit mode on the existing row
  const existing = this.findBookmarkForFrequency(sig.frequency);
  if (existing) {
    this.openEditBookmark(existing);
    return;
  }
  // New bookmark — pre-fill from the signal
  this.editingBookmark = {
    id: null,
    frequency_hz: sig.frequency,
    label: (sig.protocol || sig.modulation || 'Signal') + ' ' + this.formatFreq(sig.frequency),
    modulation: sig.modulation || 'FM',
    decoder: sig.protocol || null,
    priority: 3,
    camp_on_active: false,
    notes: '',
  };
  this.editModalMode = 'create';
  this.editModalSignal = sig;
  this.editModalError = '';
},

openNewBookmark() {
  this.editingBookmark = {
    id: null,
    frequency_hz: null,
    label: '',
    modulation: 'FM',
    decoder: null,
    priority: 3,
    camp_on_active: false,
    notes: '',
  };
  this.editModalMode = 'create';
  this.editModalSignal = null;
  this.editModalError = '';
},

// --- Save / cancel ---

async saveBookmarkEdit() {
  if (!this.editingBookmark) return;
  const bm = this.editingBookmark;

  // Client-side validation before hitting the server
  if (!bm.label || !bm.label.trim()) {
    this.editModalError = 'Label is required';
    return;
  }
  if (this.editModalMode === 'create' && (!bm.frequency_hz || bm.frequency_hz <= 0)) {
    this.editModalError = 'Frequency is required';
    return;
  }

  const payload = {
    label: bm.label.trim(),
    modulation: bm.modulation || null,
    decoder: bm.decoder || null,
    priority: bm.priority || 3,
    camp_on_active: !!bm.camp_on_active,
    notes: bm.notes || '',
  };

  let result;
  if (this.editModalMode === 'edit') {
    result = await this.apiFetch(`/api/bookmarks/${bm.id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  } else {
    payload.frequency_hz = bm.frequency_hz;
    result = await this.apiFetch('/api/bookmarks', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  if (result) {
    this.showToast(
      this.editModalMode === 'edit' ? 'Bookmark updated' : 'Bookmarked ' + this.formatFreq(bm.frequency_hz),
      'success',
    );
    this.editingBookmark = null;
    this.fetchBookmarks();
  }
},

cancelBookmarkEdit() {
  this.editingBookmark = null;
  this.editModalError = '';
},
```

**Methods to delete:**

- `quickBookmark(sig)` — no longer called by anyone. The Live Signals Bookmark button now calls `openCreateBookmarkFromSignal` instead.
- `addBookmark()` — the inline Add form on the Bookmarks page is removed, and its callers go through the modal. The method body can be deleted.
- `newBookmark` Alpine state field — the inline Add form's backing object, no longer used.

### Modal markup

Placed at the end of `<body>`, same pattern as Task 15's login overlay and Task 15's first-run password modal:

```html
<!-- Bookmark edit/create modal -->
<div x-show="editingBookmark" x-cloak
     style="position:fixed;inset:0;background:rgba(0,0,0,0.8);
            display:flex;align-items:center;justify-content:center;z-index:2000;">
  <div style="background:var(--bg-secondary);padding:32px;border-radius:var(--radius);
              max-width:520px;width:90%;max-height:90vh;overflow-y:auto;
              box-shadow:0 20px 60px rgba(0,0,0,0.6);">
    <h2 style="margin:0 0 16px 0;"
        x-text="editModalMode === 'edit' ? 'Edit Bookmark' : 'New Bookmark'"></h2>

    <template x-if="editingBookmark">
      <form @submit.prevent="saveBookmarkEdit()">
        <div style="margin-bottom:12px;">
          <label>Frequency (MHz)</label>
          <input type="number" class="form-input" step="0.001"
                 :value="editingBookmark.frequency_hz ? (editingBookmark.frequency_hz / 1e6).toFixed(4) : ''"
                 @input="editingBookmark.frequency_hz = parseFloat($event.target.value) * 1e6"
                 :readonly="editModalMode === 'edit' || editModalSignal !== null"
                 :style="(editModalMode === 'edit' || editModalSignal !== null) ? 'opacity:0.6;' : ''">
        </div>

        <div style="margin-bottom:12px;">
          <label>Label *</label>
          <input type="text" class="form-input" x-model="editingBookmark.label" required>
        </div>

        <div style="margin-bottom:12px;">
          <label>Modulation</label>
          <select class="form-select" x-model="editingBookmark.modulation">
            <option value="">--</option>
            <option value="FM">FM</option>
            <option value="NFM">NFM</option>
            <option value="AM">AM</option>
            <option value="USB">USB</option>
            <option value="LSB">LSB</option>
            <option value="CW">CW</option>
            <option value="DIGITAL">Digital</option>
            <option value="P25">P25</option>
            <option value="DMR">DMR</option>
            <option value="ADSB">ADS-B</option>
          </select>
        </div>

        <div style="margin-bottom:12px;">
          <label>Decoder</label>
          <select class="form-select" x-model="editingBookmark.decoder">
            <option :value="null">None</option>
            <option value="adsb">ADS-B</option>
            <option value="acars">ACARS</option>
            <option value="aprs">APRS</option>
            <option value="pocsag">POCSAG</option>
            <option value="noaa_apt">NOAA APT</option>
            <option value="ais">AIS</option>
            <option value="broadcast_fm">Broadcast FM</option>
          </select>
        </div>

        <div style="margin-bottom:12px;">
          <label>Priority (1–5)</label>
          <input type="number" class="form-input" min="1" max="5"
                 x-model.number="editingBookmark.priority">
        </div>

        <div style="margin-bottom:12px;">
          <label style="display:flex;align-items:center;gap:8px;">
            <input type="checkbox" x-model="editingBookmark.camp_on_active">
            <span>Camp on active
              <span style="color:var(--text-secondary);font-size:0.8rem;">
                (planned: lock onto this frequency during bookmark scans)
              </span>
            </span>
          </label>
        </div>

        <div style="margin-bottom:12px;">
          <label>Notes</label>
          <textarea class="form-input" rows="3" x-model="editingBookmark.notes"
                    placeholder="Optional — shown in the bookmarks table under the label"></textarea>
        </div>

        <div x-show="editModalError" x-cloak
             style="color:var(--red);font-size:0.85rem;margin-bottom:12px;"
             x-text="editModalError"></div>

        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button type="button" class="btn" @click="cancelBookmarkEdit()">Cancel</button>
          <button type="submit" class="btn btn-primary"
                  x-text="editModalMode === 'edit' ? 'Save' : 'Add bookmark'"></button>
        </div>
      </form>
    </template>
  </div>
</div>
```

**Field behaviors:**

- **Frequency** is read-only in **edit mode** (can't change a bookmark's frequency) AND in **create-from-signal mode** (pre-filled from the signal, user didn't pick it). It's editable only in **create-from-scratch mode** (the `+ Add bookmark` button on the Bookmarks page), where the user types it in. The `:readonly` binding handles all three with a single expression.
- **Decoder "None" option** uses `:value="null"` so the model binding is actually `null`, not an empty string. Backend accepts either for "no decoder" but null is semantically cleaner.
- **Camp on active** label includes the "(planned)" hint so the operator knows the checkbox today persists the field but doesn't change scanner behavior.
- **Notes textarea** is 3 rows by default, user-resizable by browser default. Long notes wrap naturally.

### Bookmarks page table changes

Replace the current Add form (`index.html:337-386`) with a single button in the page header:

```html
<section x-show="currentPage === 'bookmarks'" x-cloak>
  <div class="page-header">
    <h1>Bookmarks</h1>
    <button class="btn btn-primary" @click="openNewBookmark()">+ Add bookmark</button>
  </div>

  <div class="card">
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Frequency (MHz)</th>
            <th>Label</th>
            <th>Modulation</th>
            <th>Decoder</th>
            <th>Priority</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <template x-for="bm in bookmarks" :key="bm.id">
            <tr>
              <td class="freq-cell" x-text="formatFreq(bm.frequency_hz)"></td>
              <td>
                <div x-text="bm.label"></div>
                <div x-show="bm.notes" x-cloak
                     style="font-size:0.8rem;color:var(--text-secondary);margin-top:2px;
                            white-space:pre-wrap;word-break:break-word;"
                     x-text="bm.notes"></div>
              </td>
              <td><span class="badge" :class="modBadge(bm.modulation)" x-text="bm.modulation || '--'"></span></td>
              <td x-text="bm.decoder || '--'"></td>
              <td>
                <span class="priority-stars" x-text="'*'.repeat(bm.priority || 0).replace(/\*/g, '\u2605')"></span>
              </td>
              <td>
                <button class="btn btn-sm btn-primary" @click="navigate('live'); tuneAndListen(bm.frequency_hz, bm.modulation)">Tune</button>
                <button class="btn btn-sm" @click="openEditBookmark(bm)">Edit</button>
                <button class="btn btn-sm btn-danger" @click="deleteBookmark(bm.id)">Delete</button>
              </td>
            </tr>
          </template>
          <tr x-show="bookmarks.length === 0">
            <td colspan="6" class="empty-state">No bookmarks saved.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

The inline Add form markup (lines 337–386 in the current file) and its `bookmark-form` CSS styling references are removed. The page becomes shorter and the table becomes the primary content.

### Live Signals Bookmark button changes

Current button at `index.html:280-286` gets rewritten:

```html
<button class="btn btn-sm btn-success"
        @click="openCreateBookmarkFromSignal(sig)"
        :title="isBookmarked(sig.frequency) ? 'Edit bookmark' : 'Bookmark'">
  <svg viewBox="0 0 20 20" width="12" height="12"><path d="M5 2h10v16l-5-4-5 4V2z" fill="currentColor"/></svg>
</button>
```

Changes from today:
- `@click` points at `openCreateBookmarkFromSignal(sig)` instead of `quickBookmark(sig)`
- `:disabled` binding is removed — the button is always clickable
- `:title` flips between "Bookmark" and "Edit bookmark" based on dedupe state
- Icon and styling unchanged

The `.btn:disabled` CSS rule stays as-is (other disabled buttons may exist elsewhere) — this change just doesn't use it on the bookmark button anymore.

## Error handling

- **Network / server error on save:** `apiFetch` returns null, `saveBookmarkEdit` doesn't clear the modal or show a success toast. The user sees the modal stay open with their edits intact. They can try again or cancel. If the error was a 401, `apiFetch` already triggers the login overlay via Task 15's mechanism — same pattern.
- **Client-side validation fails** (missing label, missing frequency in create-from-scratch): `editModalError` is set, shown inline in the modal under the last field. Server is not called.
- **Backend rejects the patch** (bookmark was deleted out from under us, Pydantic validation, etc.): the 4xx response body's `detail` field is shown as the toast error (same pattern as the existing `apiFetch` error handling).
- **Optimistic vs. pessimistic table refresh:** On save success, the modal closes immediately and `fetchBookmarks()` is called to pull the fresh list. This is pessimistic (one extra round trip) but simpler than reconciling an in-memory update against server state. The extra GET is cheap.
- **Simultaneous edits from two browsers:** last-write-wins at the backend, by row id. No conflict detection. Acceptable for the single-operator use case.

## Testing strategy

### Backend tests

Six new tests in `tests/test_api_bookmarks.py` (existing file — append):

1. `test_patch_bookmark_updates_label` — create, PATCH label, GET by id via list, confirm label changed
2. `test_patch_bookmark_partial_update` — create with full field set, PATCH only priority, confirm other fields (label, modulation, decoder, camp_on_active, notes) are unchanged
3. `test_patch_bookmark_missing_returns_404` — PATCH a nonexistent id
4. `test_patch_bookmark_rejects_empty_label` — PATCH with `{"label": ""}`, expect 422
5. `test_patch_bookmark_rejects_priority_out_of_range` — PATCH with `{"priority": 10}`, expect 422
6. `test_patch_bookmark_clears_notes_with_empty_string` — create with non-empty notes, PATCH with `{"notes": ""}`, confirm notes is now empty string (not null) in the GET response

One new test in `tests/test_database.py` (or a new `tests/test_database_bookmark_update.py`, implementer's choice):

7. `test_update_bookmark_returns_false_for_missing_id` — call `db.update_bookmark(999999, label="whatever")` and confirm the return value is False

### Regression coverage

Existing tests in `tests/test_api_bookmarks.py` (create, list, delete) must continue to pass unchanged. Existing tests in `tests/test_database_clear.py` that insert bookmarks must continue to pass. Running these after the change confirms no accidental breakage of the pre-existing CRUD paths.

### Frontend manual verification

No frontend test harness in this repo (consistent with Tasks 15/16/17). Manual test plan for the operator after deploy:

1. Navigate to Bookmarks page, click `+ Add bookmark`, fill in a new bookmark manually, confirm it appears in the table with the correct fields and the "Add Bookmark" form no longer exists inline
2. Click Edit on a bookmark, change the label and priority, save, confirm both update in the table
3. Click Edit, add notes, save, confirm the notes appear as a muted subtitle under the label
4. Click Edit, clear the notes field, save, confirm the subtitle disappears
5. Click Edit, toggle `camp_on_active` on, save, re-open Edit on the same bookmark, confirm the checkbox is still checked (round-trip check — the field is dead at runtime but must persist)
6. Navigate to Live Signals, click Bookmark on an unsaved signal, confirm the modal opens pre-filled with the signal's values (frequency read-only), save, confirm the bookmark appears on the Bookmarks page with the expected fields
7. Click Bookmark again on the same signal (now bookmarked), confirm the modal opens in Edit mode on that existing bookmark
8. Click Cancel in the modal, confirm nothing is saved and no toast appears
9. Navigate to Bookmarks page, click Delete on a bookmark, confirm it disappears (regression — delete path should be unchanged)

## Migration and backwards compatibility

- **No schema migrations.** Every field the edit UI touches (`label`, `modulation`, `decoder`, `priority`, `camp_on_active`, `notes`) already exists in the `bookmarks` table.
- **Existing bookmarks** are fully compatible. Their `notes` field (if never set) reads back as `""` from SQLite's default, which the frontend displays as an empty subtitle (i.e., no subtitle at all). Their `camp_on_active` reads as `False` — checkbox defaults to unchecked on re-open.
- **The old `quickBookmark` and `addBookmark` code paths** are removed, not deprecated. Anyone who had bookmarks created via those paths sees no functional difference — their bookmarks are indistinguishable from ones created via the new modal.
- **The existing `POST /api/bookmarks` endpoint is unchanged** — same contract. Scripts and curl calls that hit it continue to work.
- **No dependency on Tailscale, auth, audio modes, or any other recently-shipped feature.** This change is orthogonal to Phase A/B/C of the auth + audio project and can be deployed independently.

## Acceptance criteria

1. `PATCH /api/bookmarks/{id}` accepts a partial payload and updates only the sent fields, returning `{id, updated: true}` on success or 404 if the id doesn't exist.
2. `PATCH` with empty or out-of-range values returns 422 via Pydantic validation.
3. `Database.update_bookmark` returns True on success, False for a missing id, and handles empty-kwarg calls as "does the row exist" checks.
4. The Bookmarks page shows an `+ Add bookmark` button instead of an inline form, and clicking it opens the modal in create-from-scratch mode.
5. Every row in the Bookmarks table has a `Tune / Edit / Delete` button set. Clicking Edit opens the modal pre-filled with that bookmark's values.
6. Rows whose bookmarks have non-empty notes show the notes as a muted subtitle under the label; rows without notes show only the label.
7. The Live Signals Bookmark button opens the modal. For a new signal, the modal opens in create mode pre-filled from the signal with the frequency read-only. For an already-bookmarked signal, the modal opens in edit mode on the existing bookmark.
8. Cancel in the modal closes it without saving and without showing a toast.
9. Save in create mode POSTs to `/api/bookmarks` and refreshes the bookmarks list; save in edit mode PATCHes `/api/bookmarks/{id}` and refreshes the list.
10. `quickBookmark()` and the inline `addBookmark()` method/form are removed. `isBookmarked()` is refactored into `findBookmarkForFrequency()` that returns the bookmark object or null, with `isBookmarked` kept as a thin wrapper for any remaining callers.
11. All 445+ existing tests still pass, and the 7 new tests pass.

## Open questions

None outstanding after the brainstorming round. Every design question was answered during the session.
