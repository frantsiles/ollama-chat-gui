---
name: adding-frontend-modules
description: Adds or modifies a UI module in the open-agent-ia web frontend, which is vanilla JavaScript with no build step, no framework and no bundler. Use when adding a panel, button, dropdown or any client-side feature under web/static/, or before reaching for a framework, npm package or ES module import in this project.
---

# Adding a frontend module

`web/static/` is plain JavaScript loaded through `<script>` tags. **There is no build
step, no bundler, no npm, and no framework.** Modules communicate through globals on
`window`. Do not introduce `import`/`export`, JSX, TypeScript or a package manager — none
of it is wired up, and FastAPI serves these files as static assets exactly as written.

## Checklist

```
- [ ] 1. web/static/js/<name>.js       module object + window export
- [ ] 2. web/static/index.html         <script> tag, before app.js
- [ ] 3. web/static/js/app.js          safeInitModule('<Name>', window.<Name>)
- [ ] 4. web/static/css/<name>.css     only if it needs its own styles
- [ ] 5. web/static/index.html         <link> for that stylesheet
```

## The module pattern

```javascript
/**
 * Thing module — one line on what it owns.
 */

const Thing = {
    _btn: null,

    init() {
        this._btn = document.getElementById('thing-btn');
        if (!this._btn) return;          // degrade quietly when markup is absent
        this._btn.addEventListener('click', () => this.doIt());
    },

    async doIt() {
        // ...
    },
};

window.Thing = Thing;
```

`init()` is the only required entry point. `App.safeInitModule()` skips any object
without one and catches throws, so a broken module degrades instead of taking down the
whole UI — which also means **a silent failure looks like "nothing happened"**. Check the
console for `Utils.log` output when a module seems inert.

Prefix internal state and helpers with `_`.

## Registration order matters

Script tags run in document order and `app.js` must come last. Inside `App.init()`, order
is also meaningful: `Chat` and `Shortcuts` initialize after the modules whose DOM they
depend on. Add new modules next to the ones they relate to, not blindly at the end.

## Reuse Utils

`web/static/js/utils.js` already provides `escapeHtml`, `parseMarkdown`, `showToast`,
`downloadText`, `copyToClipboard`, `debounce`, `throttle`, `formatFileSize`,
`formatRelativeTime`, `storage.get/set/remove` and `log`. Check there before writing a
helper.

**Always render user or model text through `escapeHtml` or `parseMarkdown`** — never
assign it to `innerHTML` raw.

## Dropdowns

Reuse the existing pattern rather than inventing one: wrap in `.input-selector-wrap`,
menu as `.input-selector-menu`, items as `.selector-menu-item`. For a menu anchored in
the header, add `.header-dropdown-menu` so it opens downward and right-aligned.

Toggling MUST close sibling menus and keep `aria-expanded` in sync on the button. See
`Export.init()` in `web/static/js/export.js` for the reference implementation.

## Talking to the backend

Call the REST API with `fetch` against relative paths (`/api/...`); the UI is served from
the same origin. Live agent traffic goes over the WebSocket owned by
`web/static/js/websocket.js` — for streaming, tool events or plan updates, hook into that
module instead of polling.
