# Bookmark Edit Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bookmarks editable after creation, and replace the one-click `quickBookmark` flow on Live Signals with a modal that lets the operator review and tweak pre-filled fields before saving.

**Architecture:** One shared Alpine modal component (`BookmarkEditModal`) powers three entry points — Edit button on the Bookmarks table, Bookmark button on Live Signals for a new signal (pre-filled from the signal), and Bookmark button on an already-bookmarked signal (opens Edit mode on the existing row). Backend gets a new `PATCH /api/bookmarks/{id}` endpoint with partial-update semantics (`None` = don't touch, `""` = clear to empty), backed by a new `Database.update_bookmark()` method. No schema migration — every field the edit UI touches (`label`, `modulation`, `decoder`, `priority`, `camp_on_active`, `notes`) already exists in the `bookmarks` table today.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, Pydantic (with `Field` constraints), pytest + pytest-asyncio + httpx ASGI transport, Alpine.js, vanilla CSS.

**Spec:** `docs/superpowers/specs/2026-04-11-bookmark-edit-feature-design.md`

---

## Task sequencing and dependencies

Tasks are ordered so that each commit leaves the repo in a testable, functional state:

- **Tasks 1–2 (backend)**: purely additive. `PATCH` endpoint + `Database.update_bookmark()` method. Nothing frontend-facing changes yet.
- **Task 3 (refactor)**: `findBookmarkForFrequency` added in `app.js`, `isBookmarked` becomes a thin wrapper. Purely additive — all existing callers continue to work.
- **Task 4 (modal state)**: modal Alpine state + new methods in `app.js`. Old `quickBookmark` / `addBookmark` / `newBookmark` state are **kept** for now so the HTML still works.
- **Task 5 (modal markup)**: modal HTML added at end of `<body>`. Hidden by default (`x-show="editingBookmark"`). Nothing yet opens it.
- **Task 6 (Bookmarks page)**: Bookmarks table gains Edit button + notes subtitle; inline Add form replaced with `+ Add bookmark` button. Old `addBookmark()` method and `newBookmark` state are **deleted** in this task because the HTML that called them is gone.
- **Task 7 (Live Signals)**: Bookmark button switches to `openCreateBookmarkFromSignal`. Old `quickBookmark()` method is **deleted** in this task because the HTML that called it is gone.
- **Task 8 (regression)**: full pytest suite + manual verification + spec acceptance walkthrough.

---

## Task 1: `Database.update_bookmark` method

**Files:**
- Modify: `signaldeck/storage/database.py` — add `update_bookmark` method inside the `Database` class
- Modify: `tests/test_database.py` — add three new tests

- [ ] **Step 1: Write the failing tests**

At the end of `tests/test_database.py`, append:

```python
from signaldeck.storage.models import Bookmark


async def test_update_bookmark_partial_fields(db: Database):
    """Only the fields passed in are modified; others are preserved."""
    # Seed a bookmark with every field set.
    bk = Bookmark(
        frequency=162_400_000.0,
        label="NOAA Weather",
        modulation="NFM",
        decoder="weather",
        priority=5,
        camp_on_active=False,
        notes="original notes",
        created_at=datetime.now(timezone.utc),
    )
    bk_id = await db.insert_bookmark(bk)

    # Update only priority.
    ok = await db.update_bookmark(bk_id, priority=3)
    assert ok is True

    # Fetch back and verify: priority changed, everything else unchanged.
    rows = await db.get_all_bookmarks()
    row = next(b for b in rows if b.id == bk_id)
    assert row.priority == 3
    assert row.label == "NOAA Weather"
    assert row.modulation == "NFM"
    assert row.decoder == "weather"
    assert row.camp_on_active is False
    assert row.notes == "original notes"


async def test_update_bookmark_returns_false_for_missing_id(db: Database):
    """Updating a nonexistent bookmark returns False."""
    ok = await db.update_bookmark(999999, label="ghost")
    assert ok is False


async def test_update_bookmark_empty_kwargs_checks_existence(db: Database):
    """Calling update_bookmark with no kwargs acts as 'does the row exist' check.

    Returns True if the bookmark exists, False if not. Does not modify
    any row. This matters because the API layer can call update_bookmark
    with an empty PATCH payload and still get a correct 404/200 outcome."""
    bk = Bookmark(
        frequency=100_100_000.0,
        label="Existing",
        modulation="FM",
        decoder=None,
        priority=3,
        camp_on_active=False,
        notes="",
        created_at=datetime.now(timezone.utc),
    )
    bk_id = await db.insert_bookmark(bk)

    # Empty kwargs on an existing id -> True (row exists)
    assert await db.update_bookmark(bk_id) is True
    # Empty kwargs on missing id -> False
    assert await db.update_bookmark(999999) is False

    # Verify the existing row was NOT modified (label should still be "Existing")
    rows = await db.get_all_bookmarks()
    row = next(b for b in rows if b.id == bk_id)
    assert row.label == "Existing"


async def test_update_bookmark_clears_notes_with_empty_string(db: Database):
    """Passing notes='' clears the notes field (stored as empty string)."""
    bk = Bookmark(
        frequency=146_520_000.0,
        label="2m Calling",
        modulation="FM",
        decoder=None,
        priority=2,
        camp_on_active=False,
        notes="some notes",
        created_at=datetime.now(timezone.utc),
    )
    bk_id = await db.insert_bookmark(bk)

    ok = await db.update_bookmark(bk_id, notes="")
    assert ok is True

    rows = await db.get_all_bookmarks()
    row = next(b for b in rows if b.id == bk_id)
    assert row.notes == ""
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_database.py::test_update_bookmark_partial_fields tests/test_database.py::test_update_bookmark_returns_false_for_missing_id tests/test_database.py::test_update_bookmark_empty_kwargs_checks_existence tests/test_database.py::test_update_bookmark_clears_notes_with_empty_string -v`

Expected: all four tests fail with `AttributeError: 'Database' object has no attribute 'update_bookmark'`.

- [ ] **Step 3: Add the `update_bookmark` method to the `Database` class**

In `signaldeck/storage/database.py`, locate the existing bookmark methods (search for `async def insert_bookmark`). After the existing bookmark-related methods (but before unrelated methods), add:

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
        """Partial update of a bookmark.

        Only fields passed with a non-None value are modified — this
        lets callers do "change just label and priority" without having
        to resend every other field. `notes=""` clears the notes to
        empty string (not null), which is the distinction the spec uses
        to separate "don't touch this field" from "clear this field".

        Returns True if the row existed (and was updated if there were
        any fields to change), False if no such bookmark. An empty
        kwargs call is treated as an existence check.
        """
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
            # No fields to change — just report whether the row exists.
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

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_database.py -v -k "update_bookmark"`

Expected: 4 tests pass.

Run the full `test_database.py` module to catch any regression:

Run: `.venv/bin/pytest tests/test_database.py -v`

Expected: all pre-existing database tests still pass.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/storage/database.py tests/test_database.py
git commit -m "$(cat <<'EOF'
feat: Database.update_bookmark partial-update method

Adds update_bookmark to the Database class with partial-update
semantics: None = don't touch this column, non-None = write the
value. notes="" specifically clears the notes field to empty
string (the frontend will send this when the user clears the
notes textarea in the edit modal). Empty kwargs is treated as a
"does this bookmark exist" check so the API layer can get correct
404/200 outcomes for empty PATCH payloads.

Keyword-only args (*,) matches the existing insert_remember_token
and create_remember_token patterns — prevents positional argument
confusion at call sites.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `PATCH /api/bookmarks/{id}` endpoint

**Files:**
- Modify: `signaldeck/api/routes/bookmarks.py` — add `BookmarkUpdate` model and `update_bookmark` route handler
- Modify: `tests/test_api_bookmarks.py` — add six new tests

- [ ] **Step 1: Write the failing tests**

At the end of `tests/test_api_bookmarks.py`, append:

```python
async def test_patch_bookmark_updates_label(client):
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 162_400_000.0,
        "label": "NOAA Weather",
        "modulation": "NFM",
        "priority": 5,
    })
    bk_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/bookmarks/{bk_id}",
        json={"label": "NOAA WX (renamed)"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json() == {"id": bk_id, "updated": True}

    list_resp = await client.get("/api/bookmarks")
    row = next(b for b in list_resp.json() if b["id"] == bk_id)
    assert row["label"] == "NOAA WX (renamed)"
    # Other fields preserved
    assert row["modulation"] == "NFM"
    assert row["priority"] == 5


async def test_patch_bookmark_partial_update(client):
    """PATCH with only priority leaves other fields unchanged."""
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 146_520_000.0,
        "label": "2m Calling",
        "modulation": "FM",
        "decoder": "aprs",
        "priority": 3,
        "notes": "do not touch",
    })
    bk_id = create_resp.json()["id"]

    patch_resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"priority": 5})
    assert patch_resp.status_code == 200

    list_resp = await client.get("/api/bookmarks")
    row = next(b for b in list_resp.json() if b["id"] == bk_id)
    assert row["priority"] == 5
    assert row["label"] == "2m Calling"
    assert row["modulation"] == "FM"
    assert row["decoder"] == "aprs"
    assert row["notes"] == "do not touch"


async def test_patch_bookmark_missing_returns_404(client):
    resp = await client.patch("/api/bookmarks/99999", json={"label": "nope"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Bookmark not found"


async def test_patch_bookmark_rejects_empty_label(client):
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 121_500_000.0,
        "label": "Aviation Guard",
        "modulation": "AM",
    })
    bk_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"label": ""})
    # Pydantic min_length=1 rejects with 422
    assert resp.status_code == 422


async def test_patch_bookmark_rejects_priority_out_of_range(client):
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 156_800_000.0,
        "label": "Marine Ch16",
        "modulation": "NFM",
    })
    bk_id = create_resp.json()["id"]

    # Too high
    resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"priority": 10})
    assert resp.status_code == 422
    # Too low
    resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"priority": 0})
    assert resp.status_code == 422


async def test_patch_bookmark_clears_notes_with_empty_string(client):
    """PATCH with notes='' stores an empty string (not null)."""
    create_resp = await client.post("/api/bookmarks", json={
        "frequency_hz": 100_300_000.0,
        "label": "Classic FM",
        "modulation": "FM",
        "notes": "has some notes",
    })
    bk_id = create_resp.json()["id"]

    patch_resp = await client.patch(f"/api/bookmarks/{bk_id}", json={"notes": ""})
    assert patch_resp.status_code == 200

    list_resp = await client.get("/api/bookmarks")
    row = next(b for b in list_resp.json() if b["id"] == bk_id)
    assert row["notes"] == ""
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_api_bookmarks.py -v -k "patch_bookmark"`

Expected: all 6 tests fail with 405 Method Not Allowed or similar (the PATCH route doesn't exist yet).

- [ ] **Step 3: Add the `BookmarkUpdate` model and PATCH handler**

Open `signaldeck/api/routes/bookmarks.py`. At the top of the file, update the imports to include `Field`:

```python
from pydantic import BaseModel, Field
```

After the existing `BookmarkCreate` model, add:

```python
class BookmarkUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    modulation: str | None = None
    decoder: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    camp_on_active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
```

After the existing `delete_bookmark` handler (the one decorated with `@router.delete("/bookmarks/{bookmark_id}")`), add:

```python
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

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_api_bookmarks.py -v`

Expected: all pre-existing bookmark tests still pass AND all 6 new PATCH tests pass.

- [ ] **Step 5: Commit**

```bash
git add signaldeck/api/routes/bookmarks.py tests/test_api_bookmarks.py
git commit -m "$(cat <<'EOF'
feat: PATCH /api/bookmarks/{id} partial-update endpoint

New BookmarkUpdate Pydantic model with Field constraints:
label (1..200 chars), priority (1..5), notes (max 2000 chars).
All fields are Optional so clients can send partial payloads.
Handler calls Database.update_bookmark with the submitted fields;
returns 404 if the bookmark doesn't exist, otherwise
{"id": ..., "updated": True}.

Enables the editable-bookmarks UI (modal-based edit flow on the
Bookmarks page + Live Signals bookmark button). No schema
migration — every field this touches already exists in the
bookmarks table.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Refactor `isBookmarked` → `findBookmarkForFrequency`

**Files:**
- Modify: `signaldeck/web/js/app.js` — replace `isBookmarked` body, add `findBookmarkForFrequency`

- [ ] **Step 1: Read the current `isBookmarked` method**

Find it in `signaldeck/web/js/app.js`. It currently reads approximately:

```javascript
    // Fuzzy match a signal frequency against the bookmark list.
    // Tolerance is ~2.5 kHz — tight enough to keep adjacent channels
    // (12.5/25/100 kHz spacings) distinct, wide enough to absorb
    // per-sweep center drift.
    isBookmarked(freqHz) {
      if (!freqHz || !this.bookmarks || !this.bookmarks.length) return false;
      for (const bm of this.bookmarks) {
        if (Math.abs((bm.frequency_hz || 0) - freqHz) < 2500) return true;
      }
      return false;
    },
```

- [ ] **Step 2: Replace the method block with two methods**

Replace the whole `isBookmarked` block above with:

```javascript
    // Find the bookmark (if any) matching a given frequency within a
    // ~2.5 kHz tolerance — tight enough to keep adjacent channels
    // (12.5/25/100 kHz spacings) distinct, wide enough to absorb
    // per-sweep center drift. Returns the bookmark object or null.
    findBookmarkForFrequency(freqHz) {
      if (!freqHz || !this.bookmarks || !this.bookmarks.length) return null;
      for (const bm of this.bookmarks) {
        if (Math.abs((bm.frequency_hz || 0) - freqHz) < 2500) return bm;
      }
      return null;
    },

    // Thin wrapper kept for existing callers. New code should prefer
    // findBookmarkForFrequency so it can use the returned object.
    isBookmarked(freqHz) {
      return !!this.findBookmarkForFrequency(freqHz);
    },
```

- [ ] **Step 3: Syntax-check the JS**

Run: `node -c /home/alan/signaldeck/signaldeck/web/js/app.js && echo "app.js: OK"`

Expected: `app.js: OK` (no parse errors).

Run: `.venv/bin/grep -n "findBookmarkForFrequency\|isBookmarked" /home/alan/signaldeck/signaldeck/web/js/app.js` (or use the Grep tool)

Expected: `findBookmarkForFrequency` defined once, `isBookmarked` defined once as a wrapper, plus one inline call to `isBookmarked` from inside `quickBookmark` (that call site is unchanged — the wrapper handles it transparently).

- [ ] **Step 4: Commit**

```bash
git add signaldeck/web/js/app.js
git commit -m "$(cat <<'EOF'
refactor: split isBookmarked into findBookmarkForFrequency + wrapper

Add findBookmarkForFrequency(freqHz) that returns the bookmark
object (or null) instead of just a boolean. Keep isBookmarked as
a thin wrapper (`!!findBookmarkForFrequency(freqHz)`) so existing
callers — index.html's :title binding and app.js's quickBookmark
— keep working unchanged. The bookmark-edit modal flow coming in
later tasks uses findBookmarkForFrequency directly to route a
click on an already-bookmarked Live Signals row into Edit mode
on the existing bookmark.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add modal Alpine state and methods (additive)

**Files:**
- Modify: `signaldeck/web/js/app.js` — add state fields and new methods; do NOT delete old methods yet

- [ ] **Step 1: Add modal state fields**

Find the top of the main Alpine component's `return {` block in `signaldeck/web/js/app.js` (search for `bookmarks: [],` — that line is near the state declarations). Add these four fields alongside the existing state:

```javascript
    // ---- Bookmark edit/create modal state ----
    editingBookmark: null,         // null = modal hidden; object = modal open
    editModalMode: 'create',       // 'create' | 'edit'
    editModalSignal: null,         // source Live signal for create-from-signal mode
    editModalError: '',
```

Place them near `bookmarks: [],` so they are visually grouped with other bookmark-related state.

- [ ] **Step 2: Add the five new methods**

Find the existing `quickBookmark` method (it was added earlier in the project and is still present). Add the five new methods **directly after** `quickBookmark`, so the bookmark-related methods stay grouped. Do NOT remove `quickBookmark` yet — Task 7 handles that.

```javascript
    // --- Bookmark edit/create modal methods ---

    openEditBookmark(bookmark) {
      // Clone so in-modal edits don't mutate the list until save
      this.editingBookmark = { ...bookmark };
      this.editModalMode = 'edit';
      this.editModalSignal = null;
      this.editModalError = '';
    },

    openCreateBookmarkFromSignal(sig) {
      // Dedupe — if already bookmarked, open Edit mode on the existing row
      const existing = this.findBookmarkForFrequency(sig.frequency);
      if (existing) {
        this.openEditBookmark(existing);
        return;
      }
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

    async saveBookmarkEdit() {
      if (!this.editingBookmark) return;
      const bm = this.editingBookmark;

      // Client-side validation
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

- [ ] **Step 3: Syntax-check**

Run: `node -c /home/alan/signaldeck/signaldeck/web/js/app.js && echo "app.js: OK"`

Expected: `app.js: OK`.

Also grep for all five new method names to confirm they landed:

```bash
cd /home/alan/signaldeck && .venv/bin/python -c "
from pathlib import Path
js = Path('signaldeck/web/js/app.js').read_text()
for m in ['openEditBookmark', 'openCreateBookmarkFromSignal', 'openNewBookmark', 'saveBookmarkEdit', 'cancelBookmarkEdit']:
    assert f'{m}' in js, f'missing method {m}'
assert 'editingBookmark:' in js, 'missing state'
print('all new methods and state present')
"
```

Expected: `all new methods and state present`.

- [ ] **Step 4: Run the full test suite as a smoke check**

Run: `.venv/bin/pytest tests/ --ignore=tests/test_ai_modulation.py --ignore=tests/test_integration.py -q 2>&1 | tail -5`

Expected: all tests pass (nothing changed that would affect backend tests, but running is cheap and catches import-level breaks).

- [ ] **Step 5: Commit**

```bash
git add signaldeck/web/js/app.js
git commit -m "$(cat <<'EOF'
feat: bookmark edit modal Alpine state and methods

Adds the state and methods that power the shared bookmark edit/
create modal. Three open-entry methods (openEditBookmark from
the Bookmarks table Edit button, openCreateBookmarkFromSignal
from the Live Signals Bookmark button, openNewBookmark from the
+ Add bookmark button) all populate a single editingBookmark
object. saveBookmarkEdit decides between POST (create) and PATCH
(edit) based on editModalMode.

openCreateBookmarkFromSignal uses findBookmarkForFrequency to
dedupe — if the signal is already bookmarked, it routes to edit
mode on the existing bookmark instead of creating a duplicate.

Old quickBookmark / addBookmark / newBookmark are still present;
they're removed in Tasks 6 and 7 once the HTML is switched over.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add modal markup to `index.html`

**Files:**
- Modify: `signaldeck/web/index.html` — append modal markup just before `</body>`

- [ ] **Step 1: Locate the end of `<body>`**

Run: `.venv/bin/grep -n '</body>' /home/alan/signaldeck/signaldeck/web/index.html` (or Grep tool)

Expected: exactly one match. Note the line number.

- [ ] **Step 2: Insert the modal markup**

Directly before the `</body>` tag (and before any other `<!-- Login overlay -->` or `<!-- First-run password modal -->` blocks from earlier tasks, if they're there — the order doesn't matter, just keep all modals grouped at the end of body), add:

```html
<!-- Bookmark edit/create modal — powers three entry points:
     (1) Edit button on the Bookmarks table
     (2) Bookmark button on a Live Signals row for a new signal
     (3) Bookmark button on a Live Signals row for an already-bookmarked
         signal (opens in Edit mode on the existing bookmark).
     See docs/superpowers/specs/2026-04-11-bookmark-edit-feature-design.md -->
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
        <!-- Frequency — read-only in edit mode and in create-from-signal mode -->
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

- [ ] **Step 3: HTML tag-balance check**

Run:

```bash
cd /home/alan/signaldeck && .venv/bin/python -c "
from pathlib import Path
html = Path('signaldeck/web/index.html').read_text()
assert html.count('<div') == html.count('</div>'), f'div mismatch: {html.count(\"<div\")} vs {html.count(\"</div>\")}'
assert html.count('<form') == html.count('</form>'), 'form mismatch'
assert html.count('<template') == html.count('</template>'), 'template mismatch'
assert 'editingBookmark' in html, 'editingBookmark not present in HTML'
assert 'saveBookmarkEdit' in html, 'saveBookmarkEdit not wired'
print('modal markup OK')
"
```

Expected: `modal markup OK`.

- [ ] **Step 4: Commit**

```bash
git add signaldeck/web/index.html
git commit -m "$(cat <<'EOF'
feat: bookmark edit/create modal markup

Adds the shared modal markup at the end of <body>, hidden by
default via x-show="editingBookmark". Form fields bind to the
Task 4 Alpine state (editingBookmark, editModalMode,
editModalSignal, editModalError). Frequency is read-only in
edit mode and when create mode was triggered from a Live Signals
row (editModalSignal !== null); editable only in create-from-
scratch mode (the + Add bookmark button on the Bookmarks page,
coming in Task 6).

Camp on active checkbox has a "(planned)" hint so the operator
knows the field persists but doesn't yet affect scanner behavior.
Notes textarea is 3 rows with natural wrap.

Nothing opens the modal yet — Tasks 6 and 7 wire the buttons.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update Bookmarks page — button, Edit action, notes subtitle, delete old addBookmark

**Files:**
- Modify: `signaldeck/web/index.html` — replace inline Add form with button, update table row markup
- Modify: `signaldeck/web/js/app.js` — delete `addBookmark` method and `newBookmark` state

- [ ] **Step 1: Replace the Bookmarks page section in index.html**

Find the existing `<section x-show="currentPage === 'bookmarks'" x-cloak>` block. It currently spans from the opening tag (around line 331) through the closing `</section>` (around line 425). Replace the ENTIRE section with:

```html
    <section x-show="currentPage === 'bookmarks'" x-cloak>
      <div class="page-header">
        <h1>Bookmarks</h1>
        <button class="btn btn-primary" @click="openNewBookmark()">+ Add bookmark</button>
      </div>

      <!-- Bookmarks Table -->
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

Key differences from the old section:

- The `<form class="bookmark-form">` block with frequency/label/modulation/decoder/priority inputs is **gone**.
- The page header now has a `+ Add bookmark` button that calls `openNewBookmark()`.
- Each row's Label column has two nested divs — label on top, notes (when present) as a muted subtitle below.
- Each row's Actions cell has three buttons: Tune, Edit, Delete. The Edit button calls `openEditBookmark(bm)`.

- [ ] **Step 2: Delete `addBookmark` method and `newBookmark` state in app.js**

In `signaldeck/web/js/app.js`, find the `newBookmark` state field — it looks approximately like:

```javascript
    newBookmark: {
      frequency: 0,
      label: '',
      modulation: 'FM',
      decoder: '',
      priority: 3,
    },
```

Delete the entire `newBookmark: { ... },` block. Leave a blank line in its place or remove it entirely — either is fine.

Next, find the `addBookmark` method — it looks approximately like:

```javascript
    async addBookmark() {
      // ... body reads this.newBookmark and POSTs to /api/bookmarks ...
    },
```

Delete the entire method, including the closing `},`.

- [ ] **Step 3: Verify nothing still references the deleted symbols**

Run:

```bash
cd /home/alan/signaldeck && .venv/bin/python -c "
from pathlib import Path
js = Path('signaldeck/web/js/app.js').read_text()
html = Path('signaldeck/web/index.html').read_text()

# In JS, addBookmark and newBookmark should be completely gone
assert 'addBookmark' not in js, 'addBookmark still in app.js'
assert 'newBookmark' not in js, 'newBookmark still in app.js'

# In HTML, the inline form should be gone and the new button should be present
assert 'bookmark-form' not in html, 'bookmark-form class still in HTML'
assert 'addBookmark()' not in html, 'addBookmark() call still in HTML'
assert 'openNewBookmark()' in html, '+ Add bookmark button missing'
assert 'openEditBookmark(bm)' in html, 'Edit button missing'

# Notes subtitle should be present
assert 'x-show=\"bm.notes\"' in html, 'notes subtitle markup missing'

print('Task 6 cleanup OK')
"
```

Expected: `Task 6 cleanup OK`.

Also syntax-check both files:

```bash
node -c /home/alan/signaldeck/signaldeck/web/js/app.js && echo "app.js: OK"
.venv/bin/python -c "
from pathlib import Path
html = Path('/home/alan/signaldeck/signaldeck/web/index.html').read_text()
assert html.count('<div') == html.count('</div>'), 'div mismatch'
assert html.count('<section') == html.count('</section>'), 'section mismatch'
print('index.html tags balanced')
"
```

- [ ] **Step 4: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js
git commit -m "$(cat <<'EOF'
feat: Bookmarks page Edit button, notes subtitle, + Add button

Replace the inline "Add Bookmark" form on the Bookmarks page
with a single "+ Add bookmark" button in the page header that
opens the shared edit modal via openNewBookmark(). Each table
row gains an "Edit" button between Tune and Delete, which opens
the modal in edit mode on that bookmark via openEditBookmark(bm).
The Label column now renders a muted subtitle under the label
showing bm.notes when present (rows without notes show only the
label — no visual noise).

Removes the addBookmark() method and newBookmark state field
from app.js since nothing calls them anymore. Removes the
bookmark-form markup entirely from index.html.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update Live Signals Bookmark button, delete `quickBookmark`

**Files:**
- Modify: `signaldeck/web/index.html` — change click handler and title binding on the Bookmark button
- Modify: `signaldeck/web/js/app.js` — delete `quickBookmark` method

- [ ] **Step 1: Find the Live Signals Bookmark button in index.html**

Search for `quickBookmark(sig)` — it appears exactly once in `signaldeck/web/index.html`, inside the action buttons for each Live Signals row. The current markup looks approximately like:

```html
                    <button class="btn btn-sm btn-success"
                            @click="quickBookmark(sig)"
                            :disabled="isBookmarked(sig.frequency)"
                            :title="isBookmarked(sig.frequency) ? 'Already bookmarked' : 'Bookmark'">
                      <svg viewBox="0 0 20 20" width="12" height="12"><path d="M5 2h10v16l-5-4-5 4V2z" fill="currentColor"/></svg>
                    </button>
```

Replace it with:

```html
                    <button class="btn btn-sm btn-success"
                            @click="openCreateBookmarkFromSignal(sig)"
                            :title="isBookmarked(sig.frequency) ? 'Edit bookmark' : 'Bookmark'">
                      <svg viewBox="0 0 20 20" width="12" height="12"><path d="M5 2h10v16l-5-4-5 4V2z" fill="currentColor"/></svg>
                    </button>
```

Three changes: `@click` points at the new method, `:disabled` binding is removed (the button is always clickable), and the `:title` text flips between "Bookmark" and "Edit bookmark" based on dedupe state.

- [ ] **Step 2: Delete `quickBookmark` method in app.js**

In `signaldeck/web/js/app.js`, find the `quickBookmark` method — it looks approximately like:

```javascript
    async quickBookmark(sig) {
      if (this.isBookmarked(sig.frequency)) {
        this.showToast('Already bookmarked', 'info');
        return;
      }
      const label = (sig.protocol || sig.modulation || 'Signal') + ' ' + this.formatFreq(sig.frequency);
      await this.apiFetch('/api/bookmarks', {
        method: 'POST',
        body: JSON.stringify({
          frequency_hz: sig.frequency,
          label: label,
          modulation: sig.modulation || 'FM',
          decoder: sig.protocol || null,
          priority: 3,
        }),
      });
      this.showToast('Bookmarked ' + this.formatFreq(sig.frequency), 'success');
      this.fetchBookmarks();
    },
```

Delete the entire method, including the trailing `},`.

- [ ] **Step 3: Verify cleanup**

Run:

```bash
cd /home/alan/signaldeck && .venv/bin/python -c "
from pathlib import Path
js = Path('signaldeck/web/js/app.js').read_text()
html = Path('signaldeck/web/index.html').read_text()

# quickBookmark should be gone from both
assert 'quickBookmark' not in js, 'quickBookmark still in app.js'
assert 'quickBookmark' not in html, 'quickBookmark still in index.html'

# The new handler should be wired
assert 'openCreateBookmarkFromSignal(sig)' in html, 'openCreateBookmarkFromSignal not wired in HTML'

# isBookmarked should still be present (used in the :title binding)
assert 'isBookmarked(sig.frequency)' in html, 'isBookmarked :title binding missing'

# findBookmarkForFrequency should be there (used inside openCreateBookmarkFromSignal)
assert 'findBookmarkForFrequency' in js, 'findBookmarkForFrequency missing'

print('Task 7 cleanup OK')
"

node -c /home/alan/signaldeck/signaldeck/web/js/app.js && echo "app.js: OK"
```

Expected: `Task 7 cleanup OK` and `app.js: OK`.

- [ ] **Step 4: Commit**

```bash
git add signaldeck/web/index.html signaldeck/web/js/app.js
git commit -m "$(cat <<'EOF'
feat: Live Signals Bookmark button opens modal instead of one-click

The Bookmark button on each Live Signals row now calls
openCreateBookmarkFromSignal(sig), which pops the shared edit
modal pre-filled from the signal. If the signal is already
bookmarked, the method routes to Edit mode on the existing
bookmark instead of creating a duplicate — the button becomes
"Edit bookmark" in the tooltip instead of being disabled.

Remove the :disabled binding on the button (it's always clickable
now) and delete the quickBookmark method which no longer has any
callers. The :title flips between "Bookmark" and "Edit bookmark"
based on the existing isBookmarked helper (unchanged).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Full regression sweep + acceptance walkthrough

**Files:**
- None modified unless a regression is found. This task verifies the feature end-to-end.

- [ ] **Step 1: Run the full pytest suite**

Run: `.venv/bin/pytest tests/ --ignore=tests/test_ai_modulation.py --ignore=tests/test_integration.py -q 2>&1 | tail -15`

Expected: all 445+ existing tests still pass, plus the 10 new tests from Tasks 1 and 2 (4 database tests + 6 API tests). Final line should look like `455 passed in ... s`.

If any test fails, diagnose it. Likely candidates:
- A test that imported `addBookmark` or `quickBookmark` by name — unlikely, those are Alpine methods not Python.
- A test that asserted on the old `isBookmarked` returning `False` — the wrapper still returns False for missing bookmarks, so this should still pass.
- A test that patterns-matches HTML templates — unlikely, the existing frontend tests are nonexistent.

- [ ] **Step 2: Smoke-test the running service state**

Run:

```bash
systemctl --user is-active signaldeck.service
curl -sS http://127.0.0.1:9090/api/health
```

Expected: service active, health returns `{"status":"ok","version":"..."}`. The running service does NOT have the new code yet — a restart is required for the operator to test the UI changes in the browser.

DO NOT restart the service here. The operator manages service restarts manually (per the handoff and the Tasks 1-18 auth work from earlier in the project). Report that a restart + browser hard-refresh is required.

- [ ] **Step 3: Walk through the spec's acceptance criteria**

For each acceptance criterion in `docs/superpowers/specs/2026-04-11-bookmark-edit-feature-design.md` → "Acceptance criteria" section, identify the task that implements it. Confirm each is covered by committed code:

1. `PATCH /api/bookmarks/{id}` accepts partial payload, 404 on missing — **Task 2**, verified by `test_patch_bookmark_updates_label`, `test_patch_bookmark_missing_returns_404`
2. PATCH rejects empty/out-of-range with 422 — **Task 2**, verified by `test_patch_bookmark_rejects_empty_label`, `test_patch_bookmark_rejects_priority_out_of_range`
3. `Database.update_bookmark` returns True/False for success/missing, handles empty-kwarg — **Task 1**, verified by `test_update_bookmark_returns_false_for_missing_id`, `test_update_bookmark_empty_kwargs_checks_existence`
4. Bookmarks page shows `+ Add bookmark` button opening modal in create-from-scratch mode — **Task 6**, HTML + method in Task 4
5. Every row has Tune/Edit/Delete buttons; Edit opens modal — **Task 6**
6. Rows with notes show notes as subtitle under label; rows without notes show only label — **Task 6**, verified by the `x-show="bm.notes"` guard
7. Live Signals Bookmark button opens modal; create-from-signal has frequency read-only; already-bookmarked signal opens Edit mode — **Task 7**, routing logic in Task 4's `openCreateBookmarkFromSignal`
8. Cancel closes modal without saving, without toast — **Task 4**, `cancelBookmarkEdit`
9. Save in create mode POSTs, save in edit mode PATCHes, both refresh list — **Task 4**, `saveBookmarkEdit`
10. `quickBookmark`, `addBookmark`, `newBookmark` state removed; `isBookmarked` refactored into `findBookmarkForFrequency` with wrapper — **Tasks 3, 6, 7**
11. All existing tests still pass, 7 new tests pass — this Task 8 verifies

All 11 criteria should be covered. If any are not, the implementation is incomplete — report what's missing.

- [ ] **Step 4: Write the handoff note**

No files modified unless a regression was found in Step 1. Report:

- Pass count from Step 1 (exact number)
- Acceptance criteria status (all ✅ or list of gaps)
- Service restart required: YES — the operator must run `systemctl --user restart signaldeck.service` and hard-refresh their browser for the new bookmark modal flow to be live
- Manual verification checklist (from the spec's `## Testing strategy` section's frontend manual verification sub-list) for the operator to run through after restart

- [ ] **Step 5: Final commit (only if something changed during regression fixes)**

If the regression sweep surfaced any small fixes, commit them:

```bash
git add <fixed files>
git commit -m "$(cat <<'EOF'
fix: regressions surfaced during bookmark-edit sweep

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

If nothing needed fixing, there is nothing to commit. Just report.

---

## Self-review check

Spec coverage:

- **Backend PATCH endpoint + model** → Task 2 ✅
- **Database.update_bookmark method** → Task 1 ✅
- **Frontend modal component (Alpine state + methods)** → Task 4 ✅
- **Frontend modal markup** → Task 5 ✅
- **Bookmarks page: + Add button, Edit button, notes subtitle** → Task 6 ✅
- **Live Signals: button opens modal, dedupe routes to Edit** → Task 7 ✅
- **findBookmarkForFrequency refactor** → Task 3 ✅
- **Remove quickBookmark, addBookmark, newBookmark** → Tasks 6 (addBookmark/newBookmark) + 7 (quickBookmark) ✅
- **6 API tests + 4 database tests** → Tasks 1, 2 ✅ (Task 1 has 4 database tests including one extra `test_update_bookmark_clears_notes_with_empty_string` at the DB layer; Task 2 has 6 API tests)
- **No schema migration** → handled implicitly (no ALTER TABLE in any task) ✅
- **Empty-string-clears-notes semantics** → tested at both DB layer (Task 1) and API layer (Task 2) ✅
- **All 11 acceptance criteria** → covered and walked through in Task 8 ✅

Type consistency:

- `findBookmarkForFrequency(freqHz)` signature matches in Task 3 definition and Task 4 call site inside `openCreateBookmarkFromSignal`
- `Database.update_bookmark(bookmark_id, *, label=None, ...)` signature matches Task 1 definition and Task 2 call site
- `BookmarkUpdate` Pydantic model field names match `Database.update_bookmark` kwargs exactly (`label`, `modulation`, `decoder`, `priority`, `camp_on_active`, `notes`)
- Modal state field names (`editingBookmark`, `editModalMode`, `editModalSignal`, `editModalError`) match between Task 4 (definitions + method bodies) and Task 5 (HTML `x-show` / `x-model` / `x-text` bindings)
- Method names `openEditBookmark`, `openCreateBookmarkFromSignal`, `openNewBookmark`, `saveBookmarkEdit`, `cancelBookmarkEdit` match between Task 4 definitions and Tasks 5/6/7 call sites

Placeholder scan: every step has actual code, actual commands, actual expected outputs. No TBDs, no "add error handling," no "similar to Task N" hand-waving.

---

## Execution notes

- **Working directory:** `/home/alan/signaldeck` (working on `master` directly per operator's choice — no worktree).
- **Model preference:** per operator's durable instruction, use Opus 4.6 for every subagent dispatch during execution. Sonnet is not to be used for implementer or reviewer subagents in this project.
- **Service restart:** the running service picks up backend Python changes only on restart. The operator manages restarts manually; do not run `systemctl --user restart` from within a subagent without explicit confirmation.
- **Frontend test discipline:** there's no frontend test harness. The JS/HTML syntax checks in each task are the only automated verification for frontend changes. The operator does manual browser verification after restart + hard-refresh.
