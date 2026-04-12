# Bookmark Scanning & Groups

_Design spec — 2026-04-12_

## Overview

Two related features for the Bookmarks page:

1. **Bookmark Groups** — named collections of bookmarks for organized scanning
2. **Bookmark Scanning** — three scan modes (dwell, activity, manual) with a toolbar on the Bookmarks page

Plus a bug fix: the Tune button on the Bookmarks page currently navigates to the Live page. It should stay on Bookmarks.

## 1. Bookmark Groups

### Data model

Two new tables:

```sql
CREATE TABLE IF NOT EXISTS bookmark_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmark_group_members (
    group_id INTEGER NOT NULL,
    bookmark_id INTEGER NOT NULL,
    PRIMARY KEY (group_id, bookmark_id),
    FOREIGN KEY (group_id) REFERENCES bookmark_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (bookmark_id) REFERENCES bookmarks(id) ON DELETE CASCADE
);
```

Many-to-many: a bookmark can belong to multiple groups.

### New model

```python
@dataclass
class BookmarkGroup:
    name: str
    id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### Database methods

- `create_bookmark_group(name) -> int` — returns new group ID
- `delete_bookmark_group(group_id) -> bool`
- `rename_bookmark_group(group_id, new_name) -> bool`
- `get_all_bookmark_groups() -> list[BookmarkGroup]`
- `get_group_members(group_id) -> list[int]` — returns bookmark IDs
- `set_group_members(group_id, bookmark_ids: list[int])` — replaces all members (simpler than individual add/remove for the bulk-filter UI)
- `add_group_member(group_id, bookmark_id) -> bool`
- `remove_group_member(group_id, bookmark_id) -> bool`
- `get_groups_for_bookmark(bookmark_id) -> list[BookmarkGroup]`

### API endpoints

All under `/api/bookmark-groups`:

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/bookmark-groups` | — | `[{id, name, member_count, created_at}]` |
| POST | `/bookmark-groups` | `{name}` | `{id, name}` |
| DELETE | `/bookmark-groups/{id}` | — | `{deleted: true}` |
| PATCH | `/bookmark-groups/{id}` | `{name}` | `{id, updated: true}` |
| GET | `/bookmark-groups/{id}/members` | — | `[{bookmark_id, label, frequency_hz, modulation}]` |
| PUT | `/bookmark-groups/{id}/members` | `{bookmark_ids: [int]}` | `{count: N}` |
| POST | `/bookmark-groups/{id}/members` | `{bookmark_id}` | `{added: true}` |
| DELETE | `/bookmark-groups/{id}/members/{bk_id}` | — | `{removed: true}` |

The `GET /bookmark-groups` response includes `member_count` so the UI can show group sizes without fetching all members.

### Frontend: Groups UI

Location: Bookmarks page, above the bookmark table.

**Group bar:**
- Row of group pill/chips showing each group name and member count
- "+" button to create a new group (inline text input or small modal)
- Clicking a group pill opens the **Manage Group modal**

**Manage Group modal:**
- Group name (editable inline)
- Filter bar: text search (matches label), frequency range (min/max MHz), modulation dropdown
- Bookmark list with checkboxes — all bookmarks shown, checked = in group
- "Select all matching filter" button — checks all bookmarks currently visible after filtering
- "Clear all" button
- Save / Cancel buttons
- Delete group button (with confirm)

When filters are applied, only matching bookmarks show in the list. "Select all matching filter" checks all visible rows (additive — doesn't uncheck hidden rows).

## 2. Bookmark Scanning

### Scan modes

| Mode | Behavior |
|------|----------|
| **Dwell** | Tune each bookmark for N seconds, auto-advance to next. Loops back to start. |
| **Activity** | Cycle through bookmarks. If gqrx squelch is closed (no signal), advance immediately (with a brief 300ms pause to let gqrx settle). When squelch opens (active signal), stay on that bookmark indefinitely. Resume scanning when squelch closes. |
| **Manual** | No auto-advance. Use Next/Prev buttons to step through bookmarks. |

### Scan order

Ascending by frequency within the selected scope.

### Scan scope

The scan toolbar has a scope picker:
- **All Bookmarks** — scans every bookmark
- **\<Group Name\>** — scans only bookmarks in that group

### Scan toolbar

Located above the bookmark table, below the group bar. Contains:

```
[ Scope: All Bookmarks v ] [ Mode: Dwell v ] [ Dwell: 5s v ] [ |< ] [ < Prev ] [ Start/Stop ] [ Next > ] [ >| ]
```

- **Scope dropdown**: "All Bookmarks" + each group name
- **Mode dropdown**: Dwell / Activity / Manual
- **Dwell time dropdown**: 3s / 5s / 10s / 15s / 30s (only visible in Dwell mode)
- **|< / >|**: Jump to first / last bookmark in scope
- **Prev / Next**: Step one bookmark (works in all modes, including during auto-scan)
- **Start / Stop**: Toggle scanning. In Manual mode this is hidden (Next/Prev are the controls).

### Visual feedback

- The currently-tuned bookmark row gets the `row-active` class (same highlight used on the Live page)
- During scanning, the toolbar shows the current bookmark label and a progress indicator (e.g. "5 / 30")

### Squelch detection for Activity mode

gqrx already exposes what we need:
- `get_signal_strength()` — rigctl `l STRENGTH`, returns dBFS
- `get_squelch()` — rigctl `l SQL`, returns the squelch threshold in dBFS

A signal is "active" when `signal_strength > squelch_threshold`.

New API endpoint:

```
GET /api/gqrx/squelch-open
Response: { "open": true/false, "strength_dbfs": -45.2, "squelch_dbfs": -60.0 }
```

The frontend polls this endpoint every 500ms during Activity scan. This keeps the scan logic in the frontend (Alpine state + timer) while leveraging the existing rigctl connection.

### Frontend state (Alpine)

New properties on the app data object:

```javascript
// Scan state
scanActive: false,          // is scanning running?
scanMode: 'dwell',          // 'dwell' | 'activity' | 'manual'
scanScope: 'all',           // 'all' | group ID
scanDwellMs: 5000,          // dwell time in ms
scanIndex: 0,               // current position in scan list
scanTimer: null,            // setInterval/setTimeout handle
scanSquelchPoll: null,      // polling interval for activity mode

// Computed: sorted bookmark list for current scope
get scanList() { ... }      // returns bookmarks filtered by scope, sorted by frequency
```

New methods:

```javascript
startScan()                 // begin scanning from current index
stopScan()                  // stop scanning, clear timers
scanNext()                  // advance to next bookmark (wraps)
scanPrev()                  // go to previous bookmark (wraps)
scanJumpFirst()             // jump to first
scanJumpLast()              // jump to last
scanTuneCurrent()           // tune the bookmark at scanIndex
pollSquelch()               // fetch /api/gqrx/squelch-open, decide whether to advance
```

### Scan lifecycle

**Dwell mode:**
1. `startScan()` sets `scanActive = true`, calls `scanTuneCurrent()`
2. `scanTuneCurrent()` calls `tuneAndListen(freq, mod)` for the current bookmark
3. Sets `scanTimer = setTimeout(scanNext, scanDwellMs)`
4. `scanNext()` increments `scanIndex`, wraps at end, calls `scanTuneCurrent()`
5. `stopScan()` clears timer, sets `scanActive = false`

**Activity mode:**
1. `startScan()` sets `scanActive = true`, calls `scanTuneCurrent()`
2. Starts `scanSquelchPoll = setInterval(pollSquelch, 500)`
3. `pollSquelch()` fetches squelch state:
   - If squelch open → stay (do nothing)
   - If squelch closed → wait 300ms, then `scanNext()`
4. `scanNext()` tunes next bookmark, polling continues
5. `stopScan()` clears poll interval

**Manual mode:**
1. No auto-advance. Next/Prev buttons call `scanNext()` / `scanPrev()` directly.
2. Start/Stop button is hidden. `scanActive` is set true when user clicks Next/Prev (so the row highlight works) and never auto-cleared.

## 3. Bug Fix: Tune Button Page Navigation

Current code (`index.html:367`):
```html
@click="navigate('live'); tuneAndListen(bm.frequency_hz, bm.modulation)"
```

Fix — remove the `navigate('live')` call:
```html
@click="tuneAndListen(bm.frequency_hz, bm.modulation)"
```

The bookmark row should highlight via `row-active` class when tuned, same as Live page signal rows.

## Files to create or modify

### New files
- `signaldeck/api/routes/bookmark_groups.py` — group API endpoints
- `tests/test_bookmark_groups.py` — group CRUD + membership tests
- `tests/test_bookmark_scanning.py` — scan endpoint + squelch polling tests

### Modified files
- `signaldeck/storage/models.py` — add `BookmarkGroup` dataclass
- `signaldeck/storage/database.py` — add group tables to schema, add group CRUD methods
- `signaldeck/api/server.py` — register `bookmark_groups` router
- `signaldeck/api/routes/bookmarks.py` or new `gqrx` route file — add `GET /api/gqrx/squelch-open`
- `signaldeck/web/index.html` — group bar, manage modal, scan toolbar, row-active on bookmarks, remove `navigate('live')` from Tune button
- `signaldeck/web/js/app.js` — scan state, scan methods, group fetch/management methods
- `signaldeck/web/css/style.css` — scan toolbar styles, group pill styles, active row on bookmarks page

## Testing strategy

- **Unit tests**: group CRUD (create, rename, delete, membership set/add/remove), cascade deletes
- **Unit tests**: squelch-open endpoint (mock gqrx client, test open/closed/error states)
- **Integration test**: scan list computation (scope filtering, frequency sort order)
- **Manual test**: run all three scan modes in the browser against live gqrx
