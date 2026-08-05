# TestCaseGen UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `backend/WebArayuz/testcasegen.html`'s emoji-and-inline-style-driven markup with a cohesive, modern-SaaS-styled UI (inline SVG icon set, card-header/body pattern, thumbnail strip, phone-frame live view, styled kanban and table) without changing any API call, data shape, or wizard step logic.

**Architecture:** Six sequential edits to the single file `backend/WebArayuz/testcasegen.html` (foundation → header → step 1 → step 2 → step 3 → step 4), each self-contained and independently verifiable, followed by a full regression/verification pass. No backend files change.

**Tech Stack:** Vanilla HTML/CSS/JS (no build step, no framework), hand-authored inline SVG icons, existing `css/style.css` design tokens (`--ai-*` custom properties already defined in this file) plus a few shared components (`.badge*`, `.spinner`, `.progress-bar`/`.progress-fill`, `.phone-frame`/`.phone-notch`/`.phone-screen`) from the shared stylesheet.

## Global Constraints

- Only `backend/WebArayuz/testcasegen.html` changes. `css/style.css` and every other page are out of scope.
- No API call, endpoint, request/response shape, or wizard step logic changes. This is a markup/CSS/icon refresh plus three purely-visual UX additions (button busy/spinner state, a progress bar in Step 2, a drag-over highlight in Step 3).
- Every existing `id`/`class` that JS looks up via `getElementById`/`querySelector`/`querySelectorAll` must keep working — when a task renames a class (e.g. `.tcg-screen-row` → `.tcg-screen-thumb`), every reference to that class (including drag/drop wiring and CSS) must be updated together in the same task.
- All new colors reference existing CSS custom properties (`var(--ai-red)`, `var(--ai-yellow)`, `var(--ai-accent)`, `var(--text-muted)`, etc.) — no hardcoded hex values for anything theme-sensitive.
- No external icon library or build step — icons are hand-authored inline `<svg>` strings, stroke-based, `currentColor`, defined once in a JS `ICONS` object.
- No frontend test runner exists in this repo. Verification per task is: `node --check` on the extracted `<script>` content (syntax only), plus live HTTP calls against the running backend where a task's markup consumes an API response shape, plus a final manual browser pass (Task 7).

---

## Task 1: Icon set + button-busy helper (foundation)

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Produces: `const ICONS` (object with keys: `upload`, `link`, `camera`, `trash`, `sparkle`, `scale`, `flask`, `download`, `retry`, `dragHandle`, `chevronLeft`, `chevronRight`, `check`, `warning`, `plus`, `folder`, `close`, `image` — each value is a string containing one `<svg>...</svg>`), `function setBtnBusy(btn, busy, busyLabel)`.

This task has no automated tests (no JS test runner in this repo). Verify manually per Step 3 below.

- [ ] **Step 1: Insert the `ICONS` object and `setBtnBusy` helper**

In `backend/WebArayuz/testcasegen.html`, find this exact block (currently around line 96-98):

```javascript
        let _session = null;
        let _currentStep = 1;
        let _screenListRenderGen = 0;

        const STEP_LABELS = ["Ekran Toplama", "Başlık Çıkarma", "Önceliklendirme", "Test Case Üretimi"];
```

Replace it with:

```javascript
        let _session = null;
        let _currentStep = 1;
        let _screenListRenderGen = 0;

        const ICONS = {
            upload: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
            link: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
            camera: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
            trash: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
            sparkle: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
            scale: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><path d="M8 21h8"/><path d="M5 7h14"/><path d="M5 7l-3 6a3 3 0 0 0 6 0z"/><path d="M19 7l-3 6a3 3 0 0 0 6 0z"/></svg>',
            flask: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6"/><path d="M10 3v6.5L4.5 19a1.5 1.5 0 0 0 1.3 2.3h12.4a1.5 1.5 0 0 0 1.3-2.3L14 9.5V3"/></svg>',
            download: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
            retry: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><polyline points="23 20 23 14 17 14"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>',
            dragHandle: '<svg width="14" height="14" viewBox="0 0 24 24"><circle cx="9" cy="6" r="1.4" fill="currentColor"/><circle cx="15" cy="6" r="1.4" fill="currentColor"/><circle cx="9" cy="12" r="1.4" fill="currentColor"/><circle cx="15" cy="12" r="1.4" fill="currentColor"/><circle cx="9" cy="18" r="1.4" fill="currentColor"/><circle cx="15" cy="18" r="1.4" fill="currentColor"/></svg>',
            chevronLeft: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>',
            chevronRight: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>',
            check: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
            warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
            plus: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
            folder: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
            close: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
            image: '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
        };

        function setBtnBusy(btn, busy, busyLabel) {
            if (!btn) return;
            if (busy) {
                if (!btn.dataset.idleHtml) btn.dataset.idleHtml = btn.innerHTML;
                btn.innerHTML = `<span class="spinner"></span> ${busyLabel}`;
                btn.disabled = true;
            } else {
                if (btn.dataset.idleHtml) btn.innerHTML = btn.dataset.idleHtml;
                btn.disabled = false;
            }
        }

        const STEP_LABELS = ["Ekran Toplama", "Başlık Çıkarma", "Önceliklendirme", "Test Case Üretimi"];
```

- [ ] **Step 2: Verify JS syntax**

Run:
```bash
node -e "
const fs = require('fs'), os = require('os'), path = require('path');
const html = fs.readFileSync('backend/WebArayuz/testcasegen.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/);
const out = path.join(os.tmpdir(), 'tcg-check.js');
fs.writeFileSync(out, m[1]);
console.log(out);
"
```
Then run `node --check <path printed above>`.
Expected: no output (syntax OK).

- [ ] **Step 3: Verify the ICONS object shape**

Run:
```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('backend/WebArayuz/testcasegen.html', 'utf8');
const keys = ['upload','link','camera','trash','sparkle','scale','flask','download','retry','dragHandle','chevronLeft','chevronRight','check','warning','plus','folder','close','image'];
const missing = keys.filter(k => !html.includes(k + \`: '<svg\`));
console.log(missing.length ? 'MISSING: ' + missing.join(',') : 'OK all icons present');
"
```
Expected: `OK all icons present`.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen UI: ikon seti (ICONS) ve buton busy-state helper'i eklendi"
```

---

## Task 2: Foundation CSS + Header/Session picker

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `ICONS`, `setBtnBusy` (Task 1).
- Produces: `function renderHeader()` (called once, before `initSession()`). New CSS classes used by later tasks: `.tcg-card-header`, `.tcg-session-item`, `.tcg-session-item-left`, `.tcg-session-item-info`, `.tcg-session-item-id`, `.tcg-session-item-meta`, `.tcg-session-delete`, `.tcg-empty-hint`, `.tcg-btn.success`, `.tcg-btn.ghost`, `.tcg-btn.connected`.

No automated tests (frontend, no test runner). Verify manually per Step 5.

- [ ] **Step 1: Add foundation + header + session-item CSS**

Find this exact block at the end of the `<style>` section:

```css
        .tcg-btn.primary { background: var(--ai-accent); border-color: var(--ai-accent); color: #fff; }
        .tcg-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    </style>
```

Replace with:

```css
        .tcg-btn.primary { background: var(--ai-accent); border-color: var(--ai-accent); color: #fff; }
        .tcg-btn:disabled { opacity: 0.5; cursor: not-allowed; }

        .tcg-btn { display: inline-flex; align-items: center; gap: 6px; font-weight: 500; }
        .tcg-btn:hover:not(:disabled) { border-color: var(--ai-accent); }
        .tcg-btn.primary:hover:not(:disabled) { background: var(--ai-accent-hover); }
        .tcg-btn.success { background: var(--ai-green); border-color: var(--ai-green); color: #fff; }
        .tcg-btn.success:hover:not(:disabled) { background: var(--ai-green-hover); }
        .tcg-btn.ghost { background: transparent; border-style: dashed; color: var(--text-muted); }
        .tcg-btn.ghost:hover:not(:disabled) { border-color: var(--ai-accent); color: var(--ai-accent); background: rgba(99,102,241,0.06); }
        .tcg-btn.connected { background: rgba(239,68,68,0.1); border-color: var(--ai-red); color: var(--ai-red); }
        .tcg-btn svg { flex-shrink: 0; }
        .tcg-btn .spinner { width: 14px; height: 14px; border-width: 2px; }

        .tcg-page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
        .tcg-page-header-left { display: flex; align-items: center; gap: 14px; }
        .tcg-page-icon {
            width: 44px; height: 44px; border-radius: var(--ai-radius-lg);
            background: linear-gradient(135deg, var(--ai-accent), var(--ai-cyan));
            display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0;
        }
        .tcg-page-header h1 { font-size: 1.4rem; font-weight: 700; margin: 0; }
        .tcg-page-header p { color: var(--text-muted); font-size: 0.85rem; margin: 2px 0 0; }
        .tcg-header-actions { display: flex; gap: 8px; }

        .tcg-card-header { display: flex; align-items: center; gap: 10px; padding-bottom: 14px; margin-bottom: 16px; border-bottom: 1px solid var(--border-color); }
        .tcg-card-header svg { color: var(--ai-accent); flex-shrink: 0; }
        .tcg-card-header h3 { font-size: 1rem; font-weight: 600; margin: 0; }

        .tcg-session-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 12px; border-radius: var(--ai-radius); cursor: pointer; transition: var(--ai-transition); }
        .tcg-session-item:hover { background: var(--bg-tertiary); }
        .tcg-session-item-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
        .tcg-session-item-left svg { color: var(--text-muted); flex-shrink: 0; }
        .tcg-session-item-info { min-width: 0; }
        .tcg-session-item-id { font-size: 0.85rem; font-weight: 500; }
        .tcg-session-item-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 0.72rem; color: var(--text-muted); margin-top: 4px; }
        .tcg-session-delete { background: none; border: none; color: var(--text-muted); cursor: pointer; padding: 6px; border-radius: var(--ai-radius); opacity: 0; transition: var(--ai-transition); display: flex; align-items: center; }
        .tcg-session-item:hover .tcg-session-delete { opacity: 1; }
        .tcg-session-delete:hover { background: rgba(239,68,68,0.1); color: var(--ai-red); }
        .tcg-empty-hint { color: var(--text-muted); font-size: 0.85rem; padding: 8px 12px; }
    </style>
```

- [ ] **Step 2: Replace the static header markup with a render target**

Find this exact block in the `<body>`:

```html
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div>
                        <h1>🧪 TestCaseGen</h1>
                        <p style="color:var(--text-muted); margin-bottom:20px;">
                            Ekran görüntülerinden ADO formatında test case üret.
                        </p>
                    </div>
                    <div style="display:flex; gap:8px;">
                        <button class="tcg-btn" onclick="startNewSession()">+ Yeni Oturum</button>
                        <button class="tcg-btn" onclick="toggleSessionList()">📂 Oturumlarım</button>
                    </div>
                </div>
                <div id="sessionListPanel" class="tcg-card" style="display:none;"></div>
```

Replace with:

```html
                <div id="tcgHeader"></div>
                <div id="sessionListPanel" class="tcg-card" style="display:none;"></div>
```

- [ ] **Step 3: Add `renderHeader()` and call it before `initSession()`**

Find this exact line near the end of the `<script>` block:

```javascript
        initSession();
```

Replace with:

```javascript
        function renderHeader() {
            document.getElementById("tcgHeader").innerHTML = `
                <div class="tcg-page-header">
                    <div class="tcg-page-header-left">
                        <div class="tcg-page-icon">${ICONS.flask}</div>
                        <div>
                            <h1>TestCaseGen</h1>
                            <p>Ekran görüntülerinden ADO formatında test case üret.</p>
                        </div>
                    </div>
                    <div class="tcg-header-actions">
                        <button class="tcg-btn" onclick="startNewSession()">${ICONS.plus} Yeni Oturum</button>
                        <button class="tcg-btn" onclick="toggleSessionList()">${ICONS.folder} Oturumlarım</button>
                    </div>
                </div>
            `;
        }

        renderHeader();
        initSession();
```

- [ ] **Step 4: Restyle the session list panel**

Find this exact function:

```javascript
        async function toggleSessionList() {
            const panel = document.getElementById("sessionListPanel");
            if (panel.style.display === "block") { panel.style.display = "none"; return; }
            try {
                const data = await API.get("/testcasegen/sessions");
                panel.innerHTML = data.sessions.length
                    ? data.sessions.map(s => `
                        <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid var(--border-color);">
                            <span style="cursor:pointer;" onclick="switchToSession('${s.id}')">
                                ${s.id.slice(0, 8)}… — ${s.screens.length} ekran, ${s.testcases.length} test case
                                <span style="color:var(--text-muted); font-size:0.75rem;">(${s.created_at})</span>
                            </span>
                            <button class="tcg-btn" onclick="deleteSessionFromList('${s.id}')">🗑</button>
                        </div>`).join("")
                    : '<p style="color:var(--text-muted);">Henüz oturum yok.</p>';
                panel.style.display = "block";
            } catch (e) {
                Toast.error("Oturumlar listelenemedi: " + e.message);
            }
        }
```

Replace with:

```javascript
        async function toggleSessionList() {
            const panel = document.getElementById("sessionListPanel");
            if (panel.style.display === "block") { panel.style.display = "none"; return; }
            try {
                const data = await API.get("/testcasegen/sessions");
                panel.innerHTML = data.sessions.length
                    ? data.sessions.map(s => `
                        <div class="tcg-session-item">
                            <div class="tcg-session-item-left" style="cursor:pointer; flex:1; min-width:0;" onclick="switchToSession('${s.id}')">
                                ${ICONS.folder}
                                <div class="tcg-session-item-info">
                                    <div class="tcg-session-item-id">${s.id.slice(0, 8)}…</div>
                                    <div class="tcg-session-item-meta">
                                        <span class="badge badge-primary">${s.screens.length} ekran</span>
                                        <span class="badge badge-success">${s.testcases.length} test case</span>
                                        <span>${s.created_at}</span>
                                    </div>
                                </div>
                            </div>
                            <button class="tcg-session-delete" onclick="deleteSessionFromList('${s.id}')" title="Sil">${ICONS.trash}</button>
                        </div>`).join("")
                    : `<p class="tcg-empty-hint">Henüz oturum yok.</p>`;
                panel.style.display = "block";
            } catch (e) {
                Toast.error("Oturumlar listelenemedi: " + e.message);
            }
        }
```

- [ ] **Step 5: Verify**

Run the same `node --check` sequence as Task 1 Step 2. Expected: no output.

Then, with the backend running (`cd backend && venv/Scripts/python.exe main.py`), confirm `GET /ui/testcasegen.html` still returns 200 and `GET /api/testcasegen/sessions` still returns the `{sessions: [{id, screens, testcases, created_at, ...}]}` shape this markup expects (unchanged from before — this task only changes how existing fields are displayed, not which fields are read). Stop the server when done.

- [ ] **Step 6: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen UI: sayfa basligi ve oturum secici yeniden tasarlandi"
```

---

## Task 3: Step 1 — Ekran Toplama (dropzone, thumbnail strip, canlı ADB paneli)

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `ICONS`, `setBtnBusy` (Task 1); `.tcg-card-header`, `.tcg-btn.connected` (Task 2).
- Produces: renamed screen-row class `.tcg-screen-thumb` (was `.tcg-screen-row` — every reference updated in this task).

No automated tests (frontend, no test runner). Verify manually per Step 6.

- [ ] **Step 1: Add Step-1-specific CSS**

Find this exact line (end of the `<style>` block, right before `</style>`, added in Task 2 Step 1):

```css
        .tcg-empty-hint { color: var(--text-muted); font-size: 0.85rem; padding: 8px 12px; }
    </style>
```

Replace with:

```css
        .tcg-empty-hint { color: var(--text-muted); font-size: 0.85rem; padding: 8px 12px; }

        .tcg-dropzone { border: 2px dashed var(--border-color); border-radius: var(--ai-radius-lg); padding: 36px 20px; text-align: center; cursor: pointer; margin-bottom: 16px; transition: var(--ai-transition); color: var(--text-muted); }
        .tcg-dropzone svg { color: var(--ai-accent); margin-bottom: 10px; }
        .tcg-dropzone-title { font-size: 0.92rem; font-weight: 500; color: var(--text-primary); }
        .tcg-dropzone-hint { font-size: 0.78rem; margin-top: 4px; }
        .tcg-dropzone.dragover { border-color: var(--ai-accent); background: rgba(99,102,241,0.06); }

        .tcg-screen-strip { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 6px; }
        .tcg-screen-thumb { flex: 0 0 160px; border: 1px solid var(--border-color); border-radius: var(--ai-radius); overflow: hidden; background: var(--bg-primary); cursor: grab; }
        .tcg-screen-thumb-img-wrap { position: relative; width: 100%; height: 200px; background: var(--bg-tertiary); }
        .tcg-screen-thumb-img-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
        .tcg-screen-thumb-index { position: absolute; top: 6px; left: 6px; background: rgba(0,0,0,0.65); color: #fff; font-size: 0.7rem; font-weight: 700; padding: 2px 7px; border-radius: 999px; }
        .tcg-screen-thumb-drag { position: absolute; top: 6px; right: 6px; color: #fff; background: rgba(0,0,0,0.5); border-radius: 6px; padding: 3px; display: flex; }
        .tcg-screen-thumb-body { padding: 8px; display: flex; gap: 6px; align-items: center; }
        .tcg-screen-thumb-body input { flex: 1; min-width: 0; border: 1px solid var(--border-color); border-radius: 6px; padding: 5px 8px; font-size: 0.75rem; background: var(--bg-secondary); color: var(--text-primary); }
        .tcg-screen-thumb-body button { background: none; border: none; color: var(--text-muted); cursor: pointer; padding: 4px; display: flex; }
        .tcg-screen-thumb-body button:hover { color: var(--ai-red); }

        .tcg-live-panel { display: flex; flex-direction: column; align-items: center; gap: 14px; }
        .tcg-live-controls { display: flex; gap: 10px; align-items: center; width: 100%; max-width: 320px; }
        .tcg-live-controls select { flex: 1; padding: 8px 12px; border-radius: var(--ai-radius); border: 1px solid var(--border-color); background: var(--bg-secondary); color: var(--text-primary); font-size: 0.85rem; }
        #tcgScreenImage { pointer-events: auto; width: 100%; height: 100%; object-fit: contain; }
    </style>
```

**Note (important):** the `#tcgScreenImage { pointer-events: auto; ... }` rule is required — style.css's shared `.phone-screen img` rule sets `pointer-events: none`, which would silently disable the tap-to-navigate click handler if not overridden by this higher-specificity ID selector. Do not drop this rule.

- [ ] **Step 2: Replace `renderStep1`**

Find this exact function (including its inner wiring — the whole function body):

```javascript
        function renderStep1() {
            if (_tcgWs) {
                _tcgWs.onopen = null;
                _tcgWs.onmessage = null;
                _tcgWs.onclose = null;
                _tcgWs.onerror = null;
                _tcgWs.close();
                _tcgWs = null;
            }
            _tcgLastFrameB64 = null;
            const panel = document.getElementById("panel-1");
            panel.innerHTML = `
                <div class="tcg-card">
                    <h3>Ekran Görüntüsü Yükle</h3>
                    <div id="dropzone" style="border:2px dashed var(--border-color); border-radius:var(--ai-radius);
                         padding:30px; text-align:center; cursor:pointer; margin-bottom:16px;">
                        Dosyaları buraya sürükleyin veya tıklayıp seçin
                        <input type="file" id="fileInput" multiple accept="image/*" style="display:none;">
                    </div>
                    <div id="screenList"></div>
                </div>
                <div class="tcg-card">
                    <h3>ADB ile Canlı Yakalama</h3>
                    <div style="display:flex; gap:10px; align-items:center; margin-bottom:12px;">
                        <select id="tcgDeviceSelect" style="flex:1;"></select>
                        <button class="tcg-btn" id="tcgConnectBtn" onclick="tcgToggleConnection()">🔗 Bağlan</button>
                        <button class="tcg-btn primary" id="tcgCaptureBtn" onclick="tcgCaptureFrame()" disabled>📸 Yakala</button>
                    </div>
                    <div id="tcgPhoneWrap" style="position:relative; width:300px;">
                        <img id="tcgScreenImage" style="width:100%; border:1px solid var(--border-color); border-radius:var(--ai-radius);">
                    </div>
                </div>
                <div class="tcg-actions">
                    <button class="tcg-btn primary" id="step1NextBtn" onclick="goToStep(2)">Devam →</button>
                </div>
            `;

            const dropzone = document.getElementById("dropzone");
            const fileInput = document.getElementById("fileInput");
            dropzone.onclick = () => fileInput.click();
            dropzone.ondragover = (e) => { e.preventDefault(); dropzone.style.borderColor = "var(--ai-accent)"; };
            dropzone.ondragleave = () => { dropzone.style.borderColor = "var(--border-color)"; };
            dropzone.ondrop = async (e) => {
                e.preventDefault();
                dropzone.style.borderColor = "var(--border-color)";
                await uploadFiles(e.dataTransfer.files);
            };
            fileInput.onchange = async (e) => { await uploadFiles(e.target.files); fileInput.value = ""; };

            renderScreenList();

            loadTcgDevices();
            document.getElementById("tcgScreenImage").addEventListener("click", (e) => {
                if (!_tcgWs || _tcgWs.readyState !== WebSocket.OPEN) return;
                const img = e.target;
                const rect = img.getBoundingClientRect();
                // Not: img.naturalWidth/Height burada KULLANILMAZ — WS "frame" görseli
                // emulator_service tarafından ~240px genişliğe küçültülmüş halde gelir.
                // Gerçek cihaz çözünürlüğü _tcgScreenWidth/_tcgScreenHeight içinde tutulur
                // (connect yanıtı + WS "init" mesajı), emulator.html'deki scaleX/scaleY
                // yaklaşımıyla aynı.
                const x = Math.round((e.clientX - rect.left) / rect.width * _tcgScreenWidth);
                const y = Math.round((e.clientY - rect.top) / rect.height * _tcgScreenHeight);
                _tcgWs.send(JSON.stringify({ type: "tap", x, y }));
            });
        }
```

Replace with:

```javascript
        function renderStep1() {
            if (_tcgWs) {
                _tcgWs.onopen = null;
                _tcgWs.onmessage = null;
                _tcgWs.onclose = null;
                _tcgWs.onerror = null;
                _tcgWs.close();
                _tcgWs = null;
            }
            _tcgLastFrameB64 = null;
            const panel = document.getElementById("panel-1");
            panel.innerHTML = `
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.upload}<h3>Ekran Görüntüsü Yükle</h3></div>
                    <div id="dropzone" class="tcg-dropzone">
                        ${ICONS.upload}
                        <div class="tcg-dropzone-title">Dosyaları buraya sürükleyin veya tıklayıp seçin</div>
                        <div class="tcg-dropzone-hint">PNG, JPG — birden fazla dosya seçebilirsiniz</div>
                        <input type="file" id="fileInput" multiple accept="image/*" style="display:none;">
                    </div>
                    <div id="screenList"></div>
                </div>
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.link}<h3>ADB ile Canlı Yakalama</h3></div>
                    <div class="tcg-live-panel">
                        <div class="tcg-live-controls">
                            <select id="tcgDeviceSelect"></select>
                            <button class="tcg-btn" id="tcgConnectBtn" onclick="tcgToggleConnection()">${ICONS.link} Bağlan</button>
                        </div>
                        <div class="phone-wrapper">
                            <div class="phone-frame">
                                <div class="phone-notch"></div>
                                <div class="phone-screen" id="tcgPhoneWrap">
                                    <img id="tcgScreenImage">
                                </div>
                            </div>
                            <button class="tcg-btn primary" id="tcgCaptureBtn" onclick="tcgCaptureFrame()" disabled>${ICONS.camera} Yakala</button>
                        </div>
                    </div>
                </div>
                <div class="tcg-actions">
                    <button class="tcg-btn primary" id="step1NextBtn" onclick="goToStep(2)">Devam ${ICONS.chevronRight}</button>
                </div>
            `;

            const dropzone = document.getElementById("dropzone");
            const fileInput = document.getElementById("fileInput");
            dropzone.onclick = () => fileInput.click();
            dropzone.ondragover = (e) => { e.preventDefault(); dropzone.classList.add("dragover"); };
            dropzone.ondragleave = () => { dropzone.classList.remove("dragover"); };
            dropzone.ondrop = async (e) => {
                e.preventDefault();
                dropzone.classList.remove("dragover");
                await uploadFiles(e.dataTransfer.files);
            };
            fileInput.onchange = async (e) => { await uploadFiles(e.target.files); fileInput.value = ""; };

            renderScreenList();

            loadTcgDevices();
            document.getElementById("tcgScreenImage").addEventListener("click", (e) => {
                if (!_tcgWs || _tcgWs.readyState !== WebSocket.OPEN) return;
                const img = e.target;
                const rect = img.getBoundingClientRect();
                // Not: img.naturalWidth/Height burada KULLANILMAZ — WS "frame" görseli
                // emulator_service tarafından ~240px genişliğe küçültülmüş halde gelir.
                // Gerçek cihaz çözünürlüğü _tcgScreenWidth/_tcgScreenHeight içinde tutulur
                // (connect yanıtı + WS "init" mesajı), emulator.html'deki scaleX/scaleY
                // yaklaşımıyla aynı.
                const x = Math.round((e.clientX - rect.left) / rect.width * _tcgScreenWidth);
                const y = Math.round((e.clientY - rect.top) / rect.height * _tcgScreenHeight);
                _tcgWs.send(JSON.stringify({ type: "tap", x, y }));
            });
        }
```

- [ ] **Step 3: Replace `renderScreenList`**

Find this exact function:

```javascript
        function renderScreenList() {
            const container = document.getElementById("screenList");
            const myGen = ++_screenListRenderGen;
            if (!_session.screens.length) {
                container.innerHTML = '<p style="color:var(--text-muted);">Henüz ekran eklenmedi.</p>';
                return;
            }
            container.innerHTML = _session.screens.map((s, i) => `
                <div class="tcg-screen-row" draggable="true" data-index="${i}"
                     style="display:flex; align-items:center; gap:12px; padding:8px; border:1px solid var(--border-color);
                            border-radius:var(--ai-radius); margin-bottom:8px; cursor:move; background:var(--bg-primary);">
                    <span style="font-weight:600;">#${i + 1}</span>
                    <img data-index="${i}" style="height:60px; border-radius:4px;">
                    <input type="text" value="${(s.user_note || "").replace(/"/g, '&quot;')}" placeholder="Not ekle (opsiyonel)"
                           style="flex:1;" onchange="editScreenNote(${i}, this.value)">
                    <button class="tcg-btn" onclick="deleteScreenAt(${i})">🗑</button>
                </div>
            `).join("");

            _session.screens.forEach(async (_, i) => {
                try {
                    const resp = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/screens/${i}/image`, {
                        headers: { "Authorization": `Bearer ${Auth.getToken()}` },
                    });
                    if (!resp.ok) return;
                    const blob = await resp.blob();
                    if (myGen !== _screenListRenderGen) return; // daha yeni bir render bunu gecersiz kildi
                    const imgEl = container.querySelector(`img[data-index="${i}"]`);
                    if (imgEl) imgEl.src = URL.createObjectURL(blob);
                } catch (e) { /* thumbnail yuklenemedi, sessizce atla */ }
            });

            let dragSrc = null;
            container.querySelectorAll(".tcg-screen-row").forEach(row => {
                row.addEventListener("dragstart", () => { dragSrc = row.dataset.index; });
                row.addEventListener("dragover", (e) => e.preventDefault());
                row.addEventListener("drop", async (e) => {
                    e.preventDefault();
                    const dstIndex = parseInt(row.dataset.index, 10);
                    const srcIndex = parseInt(dragSrc, 10);
                    if (srcIndex === dstIndex) return;
                    const order = _session.screens.map((_, i) => i);
                    order.splice(srcIndex, 1);
                    order.splice(dstIndex, 0, srcIndex);
                    await reorderScreens(order);
                });
            });
        }
```

Replace with:

```javascript
        function renderScreenList() {
            const container = document.getElementById("screenList");
            const myGen = ++_screenListRenderGen;
            if (!_session.screens.length) {
                container.innerHTML = `<p class="tcg-empty-hint">Henüz ekran eklenmedi.</p>`;
                return;
            }
            container.innerHTML = `<div class="tcg-screen-strip">${_session.screens.map((s, i) => `
                <div class="tcg-screen-thumb" draggable="true" data-index="${i}">
                    <div class="tcg-screen-thumb-img-wrap">
                        <span class="tcg-screen-thumb-index">#${i + 1}</span>
                        <span class="tcg-screen-thumb-drag">${ICONS.dragHandle}</span>
                        <img data-index="${i}">
                    </div>
                    <div class="tcg-screen-thumb-body">
                        <input type="text" value="${(s.user_note || "").replace(/"/g, '&quot;')}" placeholder="Not ekle (opsiyonel)"
                               onchange="editScreenNote(${i}, this.value)">
                        <button onclick="deleteScreenAt(${i})" title="Sil">${ICONS.trash}</button>
                    </div>
                </div>
            `).join("")}</div>`;

            _session.screens.forEach(async (_, i) => {
                try {
                    const resp = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/screens/${i}/image`, {
                        headers: { "Authorization": `Bearer ${Auth.getToken()}` },
                    });
                    if (!resp.ok) return;
                    const blob = await resp.blob();
                    if (myGen !== _screenListRenderGen) return; // daha yeni bir render bunu gecersiz kildi
                    const imgEl = container.querySelector(`img[data-index="${i}"]`);
                    if (imgEl) imgEl.src = URL.createObjectURL(blob);
                } catch (e) { /* thumbnail yuklenemedi, sessizce atla */ }
            });

            let dragSrc = null;
            container.querySelectorAll(".tcg-screen-thumb").forEach(row => {
                row.addEventListener("dragstart", () => { dragSrc = row.dataset.index; });
                row.addEventListener("dragover", (e) => e.preventDefault());
                row.addEventListener("drop", async (e) => {
                    e.preventDefault();
                    const dstIndex = parseInt(row.dataset.index, 10);
                    const srcIndex = parseInt(dragSrc, 10);
                    if (srcIndex === dstIndex) return;
                    const order = _session.screens.map((_, i) => i);
                    order.splice(srcIndex, 1);
                    order.splice(dstIndex, 0, srcIndex);
                    await reorderScreens(order);
                });
            });
        }
```

- [ ] **Step 4: Update connect/disconnect button label rendering**

Find this exact block inside `tcgConnectWebSocket`:

```javascript
            _tcgWs.onopen = () => {
                document.getElementById("tcgConnectBtn").textContent = "🔌 Kes";
                document.getElementById("tcgCaptureBtn").disabled = false;
                Toast.success("Cihaza bağlandı");
            };
```

Replace with:

```javascript
            _tcgWs.onopen = () => {
                const btn = document.getElementById("tcgConnectBtn");
                btn.innerHTML = `${ICONS.link} Kes`;
                btn.classList.add("connected");
                document.getElementById("tcgCaptureBtn").disabled = false;
                Toast.success("Cihaza bağlandı");
            };
```

Find this exact block (still inside `tcgConnectWebSocket`, the `onclose` handler):

```javascript
            _tcgWs.onclose = () => {
                document.getElementById("tcgConnectBtn").textContent = "🔗 Bağlan";
                document.getElementById("tcgCaptureBtn").disabled = true;
                _tcgWs = null;
            };
```

Replace with:

```javascript
            _tcgWs.onclose = () => {
                const btn = document.getElementById("tcgConnectBtn");
                btn.innerHTML = `${ICONS.link} Bağlan`;
                btn.classList.remove("connected");
                document.getElementById("tcgCaptureBtn").disabled = true;
                _tcgWs = null;
            };
```

Find this exact function:

```javascript
        function tcgDisconnect() {
            if (_tcgWs) { _tcgWs.close(); _tcgWs = null; }
            document.getElementById("tcgConnectBtn").textContent = "🔗 Bağlan";
            document.getElementById("tcgCaptureBtn").disabled = true;
            document.getElementById("tcgScreenImage").src = "";
            _tcgLastFrameB64 = null;
        }
```

Replace with:

```javascript
        function tcgDisconnect() {
            if (_tcgWs) { _tcgWs.close(); _tcgWs = null; }
            const btn = document.getElementById("tcgConnectBtn");
            btn.innerHTML = `${ICONS.link} Bağlan`;
            btn.classList.remove("connected");
            document.getElementById("tcgCaptureBtn").disabled = true;
            document.getElementById("tcgScreenImage").src = "";
            _tcgLastFrameB64 = null;
        }
```

- [ ] **Step 5: Verify**

Run the same `node --check` sequence as Task 1 Step 2. Expected: no output.

With the backend running, exercise `POST /api/testcasegen/sessions/{id}/screens/upload` and `GET /api/testcasegen/sessions/{id}/screens/{idx}/image` directly (e.g. via curl/httpx with a real JWT) to confirm the response shapes this markup consumes are unchanged. Stop the server when done.

- [ ] **Step 6: Manual browser check**

Open the page, go to Step 1: confirm the dropzone shows the upload icon and highlights on drag-over, uploaded screenshots render as a horizontal thumbnail strip with index badge and drag handle, drag-to-reorder still works, delete still works, and the live-device panel shows inside a phone-frame silhouette with a working "Bağlan"/"Kes" toggle (icon+label, red-tinted while connected) — tap-to-navigate on the device image must still work (this is the `pointer-events` override from Step 1; if taps stop working, check that rule first).

- [ ] **Step 7: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen UI: Adim 1 - dropzone, thumbnail seridi, telefon cercevesi"
```

---

## Task 4: Step 2 — Başlık Çıkarma

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `ICONS`, `setBtnBusy` (Task 1).
- Produces: none new (internal to this step's render functions).

No automated tests (frontend, no test runner). Verify manually per Step 5.

- [ ] **Step 1: Add Step-2-specific CSS**

Find this exact line (end of the `<style>` block, added in Task 3 Step 1):

```css
        #tcgScreenImage { pointer-events: auto; width: 100%; height: 100%; object-fit: contain; }
    </style>
```

Replace with:

```css
        #tcgScreenImage { pointer-events: auto; width: 100%; height: 100%; object-fit: contain; }

        .tcg-title-chip { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
        .tcg-title-chip input { flex: 1; border: 1px solid var(--border-color); border-radius: var(--ai-radius); padding: 8px 12px; font-size: 0.85rem; background: var(--bg-primary); color: var(--text-primary); }
        .tcg-title-chip input:focus { outline: none; border-color: var(--ai-accent); }
        .tcg-title-chip button { background: none; border: none; color: var(--text-muted); cursor: pointer; padding: 6px; border-radius: var(--ai-radius); display: flex; }
        .tcg-title-chip button:hover { color: var(--ai-red); background: rgba(239,68,68,0.08); }

        .tcg-screen-result { margin-bottom: 12px; }
        .tcg-screen-result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
        .tcg-screen-result-title { font-weight: 600; font-size: 0.9rem; }
        .tcg-screen-result-summary { color: var(--text-muted); font-size: 0.8rem; margin-top: 2px; }

        .tcg-warning-card { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.3); border-left: 3px solid var(--ai-yellow); border-radius: var(--ai-radius-lg); padding: 16px; }
        .tcg-warning-card-header { display: flex; align-items: center; gap: 8px; color: var(--ai-yellow); font-weight: 600; font-size: 0.85rem; margin-bottom: 8px; }
        .tcg-warning-card textarea { width: 100%; min-height: 90px; margin-top: 4px; border: 1px solid var(--border-color); border-radius: var(--ai-radius); padding: 10px 12px; background: var(--bg-primary); color: var(--text-primary); font-family: inherit; font-size: 0.85rem; resize: vertical; }
    </style>
```

- [ ] **Step 2: Replace `renderStep2`**

Find this exact function:

```javascript
        function renderStep2() {
            const panel = document.getElementById("panel-2");
            panel.innerHTML = `
                <div class="tcg-card">
                    <h3>Başlık Çıkarma</h3>
                    <button class="tcg-btn primary" id="extractBtn" onclick="runExtractTitles()">🤖 Başlıkları Çıkar</button>
                    <button class="tcg-btn" id="retryExtractBtn" style="display:none;" onclick="runExtractTitles()">🔁 Tekrar Dene</button>
                    <div id="extractProgress" style="margin-top:12px; color:var(--text-muted);"></div>
                    <div id="titlesResult" style="margin-top:16px;"></div>
                </div>
                <div class="tcg-actions">
                    <button class="tcg-btn" onclick="goToStep(1)">← Geri</button>
                    <button class="tcg-btn primary" onclick="goToStep(3)">Devam →</button>
                </div>
            `;
            renderTitlesResult();
        }
```

Replace with:

```javascript
        function renderStep2() {
            const panel = document.getElementById("panel-2");
            panel.innerHTML = `
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.sparkle}<h3>Başlık Çıkarma</h3></div>
                    <button class="tcg-btn primary" id="extractBtn" onclick="runExtractTitles()">${ICONS.sparkle} Başlıkları Çıkar</button>
                    <button class="tcg-btn" id="retryExtractBtn" style="display:none;" onclick="runExtractTitles()">${ICONS.retry} Tekrar Dene</button>
                    <div id="extractProgress" style="margin-top:14px;"></div>
                    <div id="titlesResult" style="margin-top:16px;"></div>
                </div>
                <div class="tcg-actions">
                    <button class="tcg-btn" onclick="goToStep(1)">${ICONS.chevronLeft} Geri</button>
                    <button class="tcg-btn primary" onclick="goToStep(3)">Devam ${ICONS.chevronRight}</button>
                </div>
            `;
            renderTitlesResult();
        }
```

- [ ] **Step 3: Replace `runExtractTitles` and `renderTitlesResult`**

Find this exact function:

```javascript
        async function runExtractTitles() {
            const btn = document.getElementById("extractBtn");
            const retryBtn = document.getElementById("retryExtractBtn");
            const progress = document.getElementById("extractProgress");
            btn.disabled = true;
            retryBtn.style.display = "none";
            progress.textContent = `0 / ${_session.screens.length} ekran işlendi...`;

            try {
                const response = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/extract-titles`, {
                    method: "POST",
                    headers: { "Authorization": `Bearer ${Auth.getToken()}` },
                });
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || "Başlık çıkarma başlatılamadı");
                }

                let done = 0;
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";
                while (true) {
                    const { done: readerDone, value } = await reader.read();
                    if (readerDone) break;
                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split("\n\n");
                    buffer = parts.pop();
                    for (const part of parts) {
                        const evtMatch = part.match(/^event:\s*(\S+)/m);
                        const dataLines = [...part.matchAll(/^data:\s*(.*)/gm)].map(m => m[1]);
                        const evtType = evtMatch ? evtMatch[1] : "log";
                        const dataText = dataLines.join("\n");

                        if (evtType === "screen_done") {
                            const payload = JSON.parse(dataText);
                            const screen = _session.screens[payload.screen_index];
                            screen.candidate_titles = payload.candidate_titles;
                            screen.screen_summary = payload.screen_summary;
                            screen.parse_error = payload.parse_error;
                            done += 1;
                            progress.textContent = `${done} / ${_session.screens.length} ekran işlendi...`;
                            renderTitlesResult();
                        } else if (evtType === "error") {
                            throw new Error(dataText || "Ollama hatası");
                        } else if (evtType === "complete") {
                            progress.textContent = "Tamamlandı.";
                        }
                    }
                }
            } catch (e) {
                Toast.error(e.message);
                progress.textContent = "Hata: " + e.message;
                retryBtn.style.display = "inline-block";
            } finally {
                btn.disabled = false;
            }
        }
```

Replace with:

```javascript
        async function runExtractTitles() {
            const btn = document.getElementById("extractBtn");
            const retryBtn = document.getElementById("retryExtractBtn");
            const progress = document.getElementById("extractProgress");
            setBtnBusy(btn, true, "Çıkarılıyor…");
            retryBtn.style.display = "none";
            const total = _session.screens.length;
            const renderProgress = (done, text) => {
                progress.innerHTML = `
                    <div class="progress-bar"><div class="progress-fill" style="width:${total ? (done / total * 100) : 0}%;"></div></div>
                    <div style="font-size:0.8rem; color:var(--text-muted);">${text}</div>
                `;
            };
            renderProgress(0, `0 / ${total} ekran işlendi...`);

            try {
                const response = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/extract-titles`, {
                    method: "POST",
                    headers: { "Authorization": `Bearer ${Auth.getToken()}` },
                });
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || "Başlık çıkarma başlatılamadı");
                }

                let done = 0;
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";
                while (true) {
                    const { done: readerDone, value } = await reader.read();
                    if (readerDone) break;
                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split("\n\n");
                    buffer = parts.pop();
                    for (const part of parts) {
                        const evtMatch = part.match(/^event:\s*(\S+)/m);
                        const dataLines = [...part.matchAll(/^data:\s*(.*)/gm)].map(m => m[1]);
                        const evtType = evtMatch ? evtMatch[1] : "log";
                        const dataText = dataLines.join("\n");

                        if (evtType === "screen_done") {
                            const payload = JSON.parse(dataText);
                            const screen = _session.screens[payload.screen_index];
                            screen.candidate_titles = payload.candidate_titles;
                            screen.screen_summary = payload.screen_summary;
                            screen.parse_error = payload.parse_error;
                            done += 1;
                            renderProgress(done, `${done} / ${total} ekran işlendi...`);
                            renderTitlesResult();
                        } else if (evtType === "error") {
                            throw new Error(dataText || "Ollama hatası");
                        } else if (evtType === "complete") {
                            renderProgress(total, "Tamamlandı.");
                        }
                    }
                }
            } catch (e) {
                Toast.error(e.message);
                progress.innerHTML = `<div style="color:var(--ai-red); font-size:0.8rem;">Hata: ${escapeHtml(e.message)}</div>`;
                retryBtn.style.display = "inline-block";
            } finally {
                setBtnBusy(btn, false);
            }
        }
```

Find this exact function:

```javascript
        function renderTitlesResult() {
            const container = document.getElementById("titlesResult");
            container.innerHTML = _session.screens.map((screen, i) => {
                if (screen.parse_error) {
                    return `
                        <div class="tcg-card">
                            <strong>Ekran #${i + 1}</strong> — JSON parse edilemedi, ham yanıt (düzenleyebilirsiniz):
                            <textarea style="width:100%; min-height:80px; margin-top:8px;"
                                      onchange="editRawScreenSummary(${i}, this.value)">${escapeHtml(screen.screen_summary)}</textarea>
                        </div>`;
                }
                const titles = (screen.candidate_titles || []).map((t, ti) => `
                    <div style="display:flex; gap:8px; align-items:center; margin-bottom:6px;">
                        <input type="text" value="${t.replace(/"/g, '&quot;')}" style="flex:1;"
                               onchange="editCandidateTitle(${i}, ${ti}, this.value)">
                        <button class="tcg-btn" onclick="removeCandidateTitle(${i}, ${ti})">🗑</button>
                    </div>`).join("");
                return `
                    <div class="tcg-card">
                        <strong>Ekran #${i + 1}</strong> <span style="color:var(--text-muted);">${escapeHtml(screen.screen_summary)}</span>
                        <div style="margin-top:8px;">${titles}</div>
                        <button class="tcg-btn" onclick="addCandidateTitle(${i})">+ Başlık Ekle</button>
                    </div>`;
            }).join("");
        }
```

Replace with:

```javascript
        function renderTitlesResult() {
            const container = document.getElementById("titlesResult");
            container.innerHTML = _session.screens.map((screen, i) => {
                if (screen.parse_error) {
                    return `
                        <div class="tcg-warning-card" style="margin-bottom:12px;">
                            <div class="tcg-warning-card-header">${ICONS.warning} Ekran #${i + 1} — JSON parse edilemedi</div>
                            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:6px;">Ham yanıt (düzenleyebilirsiniz):</div>
                            <textarea onchange="editRawScreenSummary(${i}, this.value)">${escapeHtml(screen.screen_summary)}</textarea>
                        </div>`;
                }
                const titles = (screen.candidate_titles || []).map((t, ti) => `
                    <div class="tcg-title-chip">
                        <input type="text" value="${t.replace(/"/g, '&quot;')}"
                               onchange="editCandidateTitle(${i}, ${ti}, this.value)">
                        <button onclick="removeCandidateTitle(${i}, ${ti})" title="Sil">${ICONS.trash}</button>
                    </div>`).join("");
                return `
                    <div class="tcg-card tcg-screen-result">
                        <div class="tcg-screen-result-header">
                            <div>
                                <div class="tcg-screen-result-title">Ekran #${i + 1}</div>
                                <div class="tcg-screen-result-summary">${escapeHtml(screen.screen_summary)}</div>
                            </div>
                        </div>
                        <div>${titles}</div>
                        <button class="tcg-btn ghost" style="margin-top:8px;" onclick="addCandidateTitle(${i})">${ICONS.plus} Başlık Ekle</button>
                    </div>`;
            }).join("");
        }
```

- [ ] **Step 4: Verify**

Run the same `node --check` sequence as Task 1 Step 2. Expected: no output.

- [ ] **Step 5: Manual browser check**

Complete Step 1 with at least one screenshot, go to Step 2. Confirm: "Başlıkları Çıkar" shows a spinner + "Çıkarılıyor…" while running, a progress bar fills as screens complete, resulting titles render as chip rows (editable/removable/addable), and a parse-error screen renders as an amber warning card instead of plain text. Stopping Ollama first and retrying should show the red error text + "Tekrar Dene" button.

- [ ] **Step 6: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen UI: Adim 2 - ilerleme cubugu, baslik chip'leri, uyari karti"
```

---

## Task 5: Step 3 — Önceliklendirme (Kanban)

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `ICONS`, `setBtnBusy` (Task 1).
- Produces: `function onKanbanDragOver(event)`, `function onKanbanDragLeave(event)` (new — wired via `ondragover`/`ondragleave` on kanban columns).

No automated tests (frontend, no test runner). Verify manually per Step 5.

- [ ] **Step 1: Add Step-3-specific CSS**

Find this exact line (end of the `<style>` block, added in Task 4 Step 1):

```css
        .tcg-warning-card textarea { width: 100%; min-height: 90px; margin-top: 4px; border: 1px solid var(--border-color); border-radius: var(--ai-radius); padding: 10px 12px; background: var(--bg-primary); color: var(--text-primary); font-family: inherit; font-size: 0.85rem; resize: vertical; }
    </style>
```

Replace with:

```css
        .tcg-warning-card textarea { width: 100%; min-height: 90px; margin-top: 4px; border: 1px solid var(--border-color); border-radius: var(--ai-radius); padding: 10px 12px; background: var(--bg-primary); color: var(--text-primary); font-family: inherit; font-size: 0.85rem; resize: vertical; }

        .tcg-kanban-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-top: 16px; }
        .tcg-kanban-col { background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--ai-radius-lg); padding: 16px; border-top: 3px solid var(--border-color); transition: var(--ai-transition); }
        .tcg-kanban-col.high { border-top-color: var(--ai-red); }
        .tcg-kanban-col.medium { border-top-color: var(--ai-yellow); }
        .tcg-kanban-col.low { border-top-color: var(--text-muted); }
        .tcg-kanban-col.drag-over { box-shadow: 0 0 0 2px var(--ai-accent) inset; }
        .tcg-kanban-col-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
        .tcg-kanban-col-header h4 { font-size: 0.9rem; font-weight: 700; margin: 0; }
        .tcg-kanban-empty { color: var(--text-muted); font-size: 0.78rem; text-align: center; padding: 20px 8px; }

        .tcg-kanban-card { padding: 10px 12px; border: 1px solid var(--border-color); border-left: 3px solid var(--border-color); border-radius: var(--ai-radius); margin-bottom: 8px; cursor: grab; background: var(--bg-primary); font-size: 0.85rem; transition: var(--ai-transition); }
        .tcg-kanban-card:hover { box-shadow: var(--shadow-sm); }
        .tcg-kanban-card.high { border-left-color: var(--ai-red); }
        .tcg-kanban-card.medium { border-left-color: var(--ai-yellow); }
        .tcg-kanban-card.low { border-left-color: var(--text-muted); }
        .tcg-kanban-card-rationale { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }
    </style>
```

- [ ] **Step 2: Replace `renderStep3`**

Find this exact function:

```javascript
        function renderStep3() {
            const panel = document.getElementById("panel-3");
            panel.innerHTML = `
                <div class="tcg-card">
                    <h3>Önceliklendirme</h3>
                    <button class="tcg-btn primary" id="prioritizeBtn" onclick="runPrioritize()">⚖️ Önceliklendir</button>
                    <button class="tcg-btn" id="retryPrioritizeBtn" style="display:none;" onclick="runPrioritize()">🔁 Tekrar Dene</button>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; margin-top:16px;">
                    <div class="tcg-card" id="col-high" data-level="high" ondragover="event.preventDefault()" ondrop="onKanbanDrop(event)">
                        <h4 style="color:var(--ai-red);">High</h4><div class="kanban-list"></div>
                    </div>
                    <div class="tcg-card" id="col-medium" data-level="medium" ondragover="event.preventDefault()" ondrop="onKanbanDrop(event)">
                        <h4 style="color:var(--ai-yellow);">Medium</h4><div class="kanban-list"></div>
                    </div>
                    <div class="tcg-card" id="col-low" data-level="low" ondragover="event.preventDefault()" ondrop="onKanbanDrop(event)">
                        <h4 style="color:var(--text-muted);">Low</h4><div class="kanban-list"></div>
                    </div>
                </div>
                <div class="tcg-actions">
                    <button class="tcg-btn" onclick="goToStep(2)">← Geri</button>
                    <button class="tcg-btn primary" onclick="goToStep(4)">Devam →</button>
                </div>
            `;
            renderKanban();
        }
```

Replace with:

```javascript
        function renderStep3() {
            const panel = document.getElementById("panel-3");
            panel.innerHTML = `
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.scale}<h3>Önceliklendirme</h3></div>
                    <button class="tcg-btn primary" id="prioritizeBtn" onclick="runPrioritize()">${ICONS.scale} Önceliklendir</button>
                    <button class="tcg-btn" id="retryPrioritizeBtn" style="display:none;" onclick="runPrioritize()">${ICONS.retry} Tekrar Dene</button>
                </div>
                <div class="tcg-kanban-grid">
                    <div class="tcg-kanban-col high" id="col-high" data-level="high" ondragover="onKanbanDragOver(event)" ondragleave="onKanbanDragLeave(event)" ondrop="onKanbanDrop(event)">
                        <div class="tcg-kanban-col-header"><h4 style="color:var(--ai-red);">High</h4><span class="badge badge-danger" id="count-high">0</span></div>
                        <div class="kanban-list"></div>
                    </div>
                    <div class="tcg-kanban-col medium" id="col-medium" data-level="medium" ondragover="onKanbanDragOver(event)" ondragleave="onKanbanDragLeave(event)" ondrop="onKanbanDrop(event)">
                        <div class="tcg-kanban-col-header"><h4 style="color:var(--ai-yellow);">Medium</h4><span class="badge badge-warning" id="count-medium">0</span></div>
                        <div class="kanban-list"></div>
                    </div>
                    <div class="tcg-kanban-col low" id="col-low" data-level="low" ondragover="onKanbanDragOver(event)" ondragleave="onKanbanDragLeave(event)" ondrop="onKanbanDrop(event)">
                        <div class="tcg-kanban-col-header"><h4 style="color:var(--text-muted);">Low</h4><span class="badge" id="count-low">0</span></div>
                        <div class="kanban-list"></div>
                    </div>
                </div>
                <div class="tcg-actions">
                    <button class="tcg-btn" onclick="goToStep(2)">${ICONS.chevronLeft} Geri</button>
                    <button class="tcg-btn primary" onclick="goToStep(4)">Devam ${ICONS.chevronRight}</button>
                </div>
            `;
            renderKanban();
        }
```

- [ ] **Step 3: Replace `runPrioritize`, `renderKanban`, `onKanbanDrop`**

Find this exact function:

```javascript
        async function runPrioritize() {
            const btn = document.getElementById("prioritizeBtn");
            const retryBtn = document.getElementById("retryPrioritizeBtn");
            btn.disabled = true;
            try {
                await promoteCandidateTitles();
                _session = await API.post(`/testcasegen/sessions/${_session.id}/prioritize`);
                retryBtn.style.display = "none";
                renderKanban();
                Toast.success("Önceliklendirme tamamlandı");
            } catch (e) {
                Toast.error(e.message);
                retryBtn.style.display = "inline-block";
            } finally {
                btn.disabled = false;
            }
        }

        function renderKanban() {
            ["high", "medium", "low"].forEach(level => {
                const col = document.querySelector(`#col-${level} .kanban-list`);
                const titles = _session.titles.filter(t => t.level === level);
                col.innerHTML = titles.map(t => `
                    <div class="tcg-kanban-card" draggable="true" data-id="${t.id}"
                         style="padding:8px; border:1px solid var(--border-color); border-radius:var(--ai-radius);
                                margin-bottom:8px; cursor:move; background:var(--bg-primary);"
                         ondragstart="event.dataTransfer.setData('text/plain', '${t.id}')">
                        <div>${escapeHtml(t.text)}</div>
                        <div style="font-size:0.75rem; color:var(--text-muted); margin-top:4px;">${escapeHtml(t.rationale || "")}</div>
                    </div>`).join("");
            });
        }

        async function onKanbanDrop(event) {
            event.preventDefault();
            const titleId = event.dataTransfer.getData("text/plain");
            const level = event.currentTarget.dataset.level;
            try {
                _session = await API.put(`/testcasegen/sessions/${_session.id}/titles/${titleId}/priority`, { level });
                renderKanban();
            } catch (e) {
                Toast.error(e.message);
            }
        }
```

Replace with:

```javascript
        async function runPrioritize() {
            const btn = document.getElementById("prioritizeBtn");
            const retryBtn = document.getElementById("retryPrioritizeBtn");
            setBtnBusy(btn, true, "Hesaplanıyor…");
            try {
                await promoteCandidateTitles();
                _session = await API.post(`/testcasegen/sessions/${_session.id}/prioritize`);
                retryBtn.style.display = "none";
                renderKanban();
                Toast.success("Önceliklendirme tamamlandı");
            } catch (e) {
                Toast.error(e.message);
                retryBtn.style.display = "inline-block";
            } finally {
                setBtnBusy(btn, false);
            }
        }

        function renderKanban() {
            ["high", "medium", "low"].forEach(level => {
                const col = document.querySelector(`#col-${level} .kanban-list`);
                const titles = _session.titles.filter(t => t.level === level);
                document.getElementById(`count-${level}`).textContent = titles.length;
                col.innerHTML = titles.length ? titles.map(t => `
                    <div class="tcg-kanban-card ${level}" draggable="true" data-id="${t.id}"
                         ondragstart="event.dataTransfer.setData('text/plain', '${t.id}')">
                        <div>${escapeHtml(t.text)}</div>
                        <div class="tcg-kanban-card-rationale">${escapeHtml(t.rationale || "")}</div>
                    </div>`).join("") : `<div class="tcg-kanban-empty">Henüz başlık yok</div>`;
            });
        }

        function onKanbanDragOver(event) {
            event.preventDefault();
            event.currentTarget.classList.add("drag-over");
        }

        function onKanbanDragLeave(event) {
            event.currentTarget.classList.remove("drag-over");
        }

        async function onKanbanDrop(event) {
            event.preventDefault();
            event.currentTarget.classList.remove("drag-over");
            const titleId = event.dataTransfer.getData("text/plain");
            const level = event.currentTarget.dataset.level;
            try {
                _session = await API.put(`/testcasegen/sessions/${_session.id}/titles/${titleId}/priority`, { level });
                renderKanban();
            } catch (e) {
                Toast.error(e.message);
            }
        }
```

- [ ] **Step 4: Verify**

Run the same `node --check` sequence as Task 1 Step 2. Expected: no output.

- [ ] **Step 5: Manual browser check**

Complete Steps 1-2, go to Step 3. Confirm: each column has a colored top accent bar and a live count badge, empty columns show "Henüz başlık yok", dragging a card over a column highlights it with a ring, and dropping moves the card and persists `level_source: "manual"` (check via `GET /api/testcasegen/sessions/{id}` in DevTools, same as before this refresh — the endpoint itself is unchanged).

- [ ] **Step 6: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen UI: Adim 3 - kanban kolon tasarimi ve surukleme vurgusu"
```

---

## Task 6: Step 4 — Test Case Üretimi (checklist, tablo, export)

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `ICONS`, `setBtnBusy` (Task 1).
- Produces: `function renderTitleChecklist()` (new — extracted from `renderStep4`, also called after successful generation to refresh the "already generated" indicator).

No automated tests (frontend, no test runner). Verify manually per Step 5.

- [ ] **Step 1: Add Step-4-specific CSS**

Find this exact line (end of the `<style>` block, added in Task 5 Step 1):

```css
        .tcg-kanban-card-rationale { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }
    </style>
```

Replace with:

```css
        .tcg-kanban-card-rationale { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }

        .tcg-title-checklist { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
        .tcg-title-check-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--ai-radius); }
        .tcg-title-check-row:hover { background: var(--bg-tertiary); }
        .tcg-title-check-row label { display: flex; align-items: center; gap: 10px; flex: 1; cursor: pointer; font-size: 0.85rem; }
        .tcg-generated-badge { display: inline-flex; align-items: center; gap: 4px; color: var(--ai-green); font-size: 0.72rem; font-weight: 600; }

        .tcg-testcase-table-wrap { overflow-x: auto; }
        .tcg-testcase-table { width: 100%; border-collapse: collapse; }
        .tcg-testcase-table thead th { text-align: left; padding: 10px 12px; font-size: 0.72rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid var(--border-color); background: var(--bg-tertiary); }
        .tcg-testcase-table td { padding: 8px 12px; border-bottom: 1px solid var(--border-color); font-size: 0.85rem; vertical-align: middle; }
        .tcg-testcase-table tr.tcg-title-row td { background: var(--bg-tertiary); font-weight: 600; }
        .tcg-testcase-table tr:hover td { background: var(--bg-hover); }
        .tcg-testcase-table tr.tcg-violation td { background: rgba(239,68,68,0.08); border-left: 3px solid var(--ai-red); }
        .tcg-testcase-table input.tcg-step-input { width: 100%; border: 1px solid var(--border-color); border-radius: 6px; padding: 6px 8px; background: var(--bg-primary); color: var(--text-primary); font-size: 0.82rem; }
        .tcg-testcase-table input.tcg-step-input:disabled { opacity: 0.5; }
        .tcg-violation-icon { color: var(--ai-red); display: inline-flex; margin-right: 4px; vertical-align: middle; }
    </style>
```

- [ ] **Step 2: Replace `renderStep4` — extract checklist rendering into its own function**

Find this exact function:

```javascript
        function renderStep4() {
            const panel = document.getElementById("panel-4");
            const titlesById = Object.fromEntries(_session.titles.map(t => [t.id, t]));
            const checkboxes = _session.titles.map(t => `
                <label style="display:block; margin-bottom:4px;">
                    <input type="checkbox" class="tcg-title-checkbox" value="${t.id}"> ${escapeHtml(t.text)}
                    <span style="font-size:0.75rem; color:var(--text-muted);">(${t.level || "-"})</span>
                </label>`).join("");

            panel.innerHTML = `
                <div class="tcg-card">
                    <h3>Test Case Üretimi</h3>
                    <div style="margin-bottom:12px;">${checkboxes || "<p>Önce Adım 3'te başlık önceliklendirin.</p>"}</div>
                    <button class="tcg-btn primary" id="genBtn" onclick="runGenerateTestcases()">🧪 Test Case Oluştur</button>
                    <button class="tcg-btn" id="retryGenBtn" style="display:none;" onclick="runGenerateTestcases()">🔁 Tekrar Dene</button>
                </div>
                <div id="testcaseTableWrap"></div>
                <div class="tcg-actions">
                    <button class="tcg-btn" onclick="goToStep(3)">← Geri</button>
                    <button class="tcg-btn primary" onclick="exportSelectedTestcases()">📥 Excel'e Aktar</button>
                </div>
            `;
            renderTestcaseTable();
        }
```

Replace with:

```javascript
        function renderTitleChecklist() {
            const container = document.getElementById("titleChecklist");
            const generatedTitleIds = new Set(_session.testcases.map(tc => tc.title_id));
            const rows = _session.titles.map(t => {
                const levelBadge = t.level
                    ? `<span class="badge badge-${t.level === 'high' ? 'danger' : t.level === 'medium' ? 'warning' : 'primary'}">${t.level}</span>`
                    : `<span class="badge">-</span>`;
                const generatedTag = generatedTitleIds.has(t.id)
                    ? `<span class="tcg-generated-badge">${ICONS.check} üretildi</span>` : "";
                return `
                    <div class="tcg-title-check-row">
                        <label>
                            <input type="checkbox" class="tcg-title-checkbox" value="${t.id}">
                            ${escapeHtml(t.text)}
                        </label>
                        ${levelBadge}${generatedTag}
                    </div>`;
            }).join("");
            container.innerHTML = rows || `<p class="tcg-empty-hint">Önce Adım 3'te başlık önceliklendirin.</p>`;
        }

        function renderStep4() {
            const panel = document.getElementById("panel-4");
            panel.innerHTML = `
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.flask}<h3>Test Case Üretimi</h3></div>
                    <div class="tcg-title-checklist" id="titleChecklist"></div>
                    <button class="tcg-btn primary" id="genBtn" onclick="runGenerateTestcases()">${ICONS.flask} Test Case Oluştur</button>
                    <button class="tcg-btn" id="retryGenBtn" style="display:none;" onclick="runGenerateTestcases()">${ICONS.retry} Tekrar Dene</button>
                </div>
                <div id="testcaseTableWrap"></div>
                <div class="tcg-actions">
                    <button class="tcg-btn" onclick="goToStep(3)">${ICONS.chevronLeft} Geri</button>
                    <button class="tcg-btn success" onclick="exportSelectedTestcases()">${ICONS.download} Excel'e Aktar</button>
                </div>
            `;
            renderTitleChecklist();
            renderTestcaseTable();
        }
```

**Note:** `renderTitleChecklist()` re-renders the whole checklist (including checkbox checked-state) whenever it runs — this is called again after a successful generation (Step 3 below) so the "✓ üretildi" badge appears immediately. This means any still-unchecked/checked boxes reset after each generation run; this is a deliberate, approved trade-off for delivering the "already generated" indicator live, not an oversight.

- [ ] **Step 3: Replace `runGenerateTestcases`, `renderTestcaseTable`**

Find this exact function:

```javascript
        async function runGenerateTestcases() {
            let ids = [...document.querySelectorAll(".tcg-title-checkbox:checked")].map(el => el.value);
            if (!ids.length) { Toast.error("En az bir başlık seçin"); return; }
            const alreadyGenerated = new Set(_session.testcases.map(tc => tc.title_id));
            ids = ids.filter(id => !alreadyGenerated.has(id));
            if (!ids.length) { Toast.error("Seçilen başlıklar için zaten test case üretilmiş"); return; }
            const btn = document.getElementById("genBtn");
            const retryBtn = document.getElementById("retryGenBtn");
            btn.disabled = true;
            try {
                const result = await API.post(`/testcasegen/sessions/${_session.id}/generate-testcases`, { title_ids: ids });
                _session.testcases = _session.testcases.concat(result.testcases);
                retryBtn.style.display = "none";
                renderTestcaseTable();
                Toast.success(`${result.testcases.length} test case üretildi`);
            } catch (e) {
                Toast.error(e.message);
                retryBtn.style.display = "inline-block";
            } finally {
                btn.disabled = false;
            }
        }

        function renderTestcaseTable() {
            const wrap = document.getElementById("testcaseTableWrap");
            const titlesById = Object.fromEntries(_session.titles.map(t => [t.id, t]));
            if (!_session.testcases.length) { wrap.innerHTML = ""; return; }

            let rows = "";
            _session.testcases.forEach(tc => {
                const title = titlesById[tc.title_id];
                rows += `<tr>
                    <td><input type="checkbox" class="tcg-export-checkbox" value="${tc.id}" checked></td>
                    <td>Test Case</td>
                    <td>${title ? escapeHtml(title.text) : ""}</td>
                    <td colspan="2"></td>
                </tr>`;
                tc.steps.forEach((step, si) => {
                    const hasViolations = step.violations && step.violations.length > 0;
                    const rowStyle = hasViolations ? 'background:rgba(239,68,68,0.12);' : '';
                    const tooltip = hasViolations ? step.violations.map(v => v.message).join(" | ") : "";
                    rows += `<tr style="${rowStyle}" title="${tooltip.replace(/"/g, '&quot;')}">
                        <td></td><td></td><td></td>
                        <td>${si + 1}</td>
                        <td><input type="text" class="tcg-step-input" value="${step.step_action.replace(/"/g, '&quot;')}"
                                   onchange="editTestcaseStep('${tc.id}', ${si}, this.value, null, this)"></td>
                        <td><input type="text" class="tcg-step-input" value="${step.step_expected.replace(/"/g, '&quot;')}"
                                   onchange="editTestcaseStep('${tc.id}', ${si}, null, this.value, this)"></td>
                    </tr>`;
                });
            });

            wrap.innerHTML = `
                <div class="tcg-card">
                    <table style="width:100%; border-collapse:collapse;">
                        <thead><tr>
                            <th>Seç</th><th>Work Item Type</th><th>Title</th><th>Step</th>
                            <th>Step Action</th><th>Step Expected</th>
                        </tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`;
        }
```

Replace with:

```javascript
        async function runGenerateTestcases() {
            let ids = [...document.querySelectorAll(".tcg-title-checkbox:checked")].map(el => el.value);
            if (!ids.length) { Toast.error("En az bir başlık seçin"); return; }
            const alreadyGenerated = new Set(_session.testcases.map(tc => tc.title_id));
            ids = ids.filter(id => !alreadyGenerated.has(id));
            if (!ids.length) { Toast.error("Seçilen başlıklar için zaten test case üretilmiş"); return; }
            const btn = document.getElementById("genBtn");
            const retryBtn = document.getElementById("retryGenBtn");
            setBtnBusy(btn, true, "Üretiliyor…");
            try {
                const result = await API.post(`/testcasegen/sessions/${_session.id}/generate-testcases`, { title_ids: ids });
                _session.testcases = _session.testcases.concat(result.testcases);
                retryBtn.style.display = "none";
                renderTitleChecklist();
                renderTestcaseTable();
                Toast.success(`${result.testcases.length} test case üretildi`);
            } catch (e) {
                Toast.error(e.message);
                retryBtn.style.display = "inline-block";
            } finally {
                setBtnBusy(btn, false);
            }
        }

        function renderTestcaseTable() {
            const wrap = document.getElementById("testcaseTableWrap");
            const titlesById = Object.fromEntries(_session.titles.map(t => [t.id, t]));
            if (!_session.testcases.length) { wrap.innerHTML = ""; return; }

            let rows = "";
            _session.testcases.forEach(tc => {
                const title = titlesById[tc.title_id];
                rows += `<tr class="tcg-title-row">
                    <td><input type="checkbox" class="tcg-export-checkbox" value="${tc.id}" checked></td>
                    <td>Test Case</td>
                    <td>${title ? escapeHtml(title.text) : ""}</td>
                    <td colspan="2"></td>
                </tr>`;
                tc.steps.forEach((step, si) => {
                    const hasViolations = step.violations && step.violations.length > 0;
                    const tooltip = hasViolations ? step.violations.map(v => v.message).join(" | ") : "";
                    const violationIcon = hasViolations ? `<span class="tcg-violation-icon">${ICONS.warning}</span>` : "";
                    rows += `<tr class="${hasViolations ? 'tcg-violation' : ''}" title="${tooltip.replace(/"/g, '&quot;')}">
                        <td></td><td></td><td></td>
                        <td>${violationIcon}${si + 1}</td>
                        <td><input type="text" class="tcg-step-input" value="${step.step_action.replace(/"/g, '&quot;')}"
                                   onchange="editTestcaseStep('${tc.id}', ${si}, this.value, null, this)"></td>
                        <td><input type="text" class="tcg-step-input" value="${step.step_expected.replace(/"/g, '&quot;')}"
                                   onchange="editTestcaseStep('${tc.id}', ${si}, null, this.value, this)"></td>
                    </tr>`;
                });
            });

            wrap.innerHTML = `
                <div class="tcg-card tcg-testcase-table-wrap">
                    <table class="tcg-testcase-table">
                        <thead><tr>
                            <th>Seç</th><th>Work Item Type</th><th>Title</th><th>Step</th>
                            <th>Step Action</th><th>Step Expected</th>
                        </tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`;
        }
```

- [ ] **Step 4: Verify**

Run the same `node --check` sequence as Task 1 Step 2. Expected: no output.

With the backend running, exercise `POST /generate-testcases`, `PUT /testcases/{tc_id}/steps/{idx}`, and `POST /export` directly to confirm response shapes are unchanged (same fields this markup already reads: `testcases[].id/title_id/steps[].step_action/step_expected/violations`).

- [ ] **Step 5: Manual browser check**

Complete Steps 1-3, go to Step 4. Confirm: title checklist shows priority badges (color-coded) and a green "✓ üretildi" tag for titles that already have a test case; generating shows the busy spinner; the table has a styled header, hover state, and violation rows show a left red border + warning icon with the tooltip; "Excel'e Aktar" is now the green success-styled button, separated from "Geri".

- [ ] **Step 6: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen UI: Adim 4 - baslik listesi rozetleri, tablo stili, export butonu"
```

---

## Task 7: Full regression + manual verification pass

**Files:** none (verification only)

**Interfaces:** none.

- [ ] **Step 1: Full-file syntax check**

Run the same `node --check` sequence as Task 1 Step 2 against the final file. Expected: no output.

- [ ] **Step 2: Backend regression sanity check**

No backend file was touched by Tasks 1-6, so this is a sanity check, not expected to fail:

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/ -v
```
Expected: same pass count as before this plan started (99 passed, 0 failed) — confirms nothing on the backend side was accidentally touched.

- [ ] **Step 3: Full end-to-end HTTP walk**

With the backend running, using a real JWT, walk the entire pipeline via direct HTTP calls (curl/httpx) exactly as in the original TestCaseGen plan's Task 20: create session → upload 2-3 screenshots → add/promote titles → prioritize → generate test cases → edit a step → export, confirming every response is 200 and the exported `.xlsx` opens correctly with openpyxl (header row, title row, step row match the ADO layout). This exercises the exact same endpoints Tasks 1-6 assumed unchanged, catching any accidental drift in the markup's assumptions about field names.

- [ ] **Step 4: Manual browser checklist**

Open the page in a real browser (light AND dark theme via the sidebar's theme toggle) and walk through:

- [ ] Page header shows the gradient icon badge, "+ Yeni Oturum" / "Oturumlarım" buttons with icons.
- [ ] Session picker panel: opens as a card list, shows badges for screen/testcase counts, delete icon appears on row hover and works.
- [ ] Step 1: dropzone drag-over highlight, click-to-browse upload, thumbnail strip renders with index badges and drag handles, drag-to-reorder works, per-thumbnail note field and delete work, live-device panel shows inside the phone-frame, Bağlan/Kes toggle works and turns red while connected, tap-to-navigate on the device image still works, Yakala appends a captured frame to the thumbnail strip.
- [ ] Step 2: Başlıkları Çıkar shows a spinner + progress bar while streaming, candidate titles render as editable chip rows, add/remove work, a parse-error screen renders as an amber warning card, stopping Ollama and retrying shows the error + Tekrar Dene button.
- [ ] Step 3: kanban columns show colored top bars and count badges, dragging over a column highlights it, dropping moves a card and marks it manual, Önceliklendir shows a spinner while running.
- [ ] Step 4: title checklist shows priority badges and "✓ üretildi" tags, Test Case Oluştur shows a spinner, the table shows styled headers/hover/violation rows with tooltip, editing a step re-validates (violation highlight clears when fixed), Excel'e Aktar (green button) downloads a working `.xlsx`.
- [ ] No console errors at any point in the above walk.

- [ ] **Step 5: Commit (if Step 4 surfaced any fixes)**

If the manual walk-through in Step 4 found and required a fix, commit it separately with a descriptive message (e.g. `git commit -m "TestCaseGen UI: manuel dogrulamada bulunan [X] duzeltildi"`). If no fixes were needed, no commit is required for this task — Tasks 1-6 already committed the actual work.

---
