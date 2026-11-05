# Team Data Troopers — Recent Work Items

A dashboard showing Azure DevOps work items created in the last 7 days under
`MSI\Team Data Troopers Backlog`, embedded in SharePoint.

**Live:** https://recentworkitems.netlify.app
**Embedded at:** https://millenniumsi.sharepoint.com/sites/EnterpriseSystems/SitePages/Home.aspx

---

## How it runs

There is no schedule, no build step, and no stored copy of the data. The page
asks Azure DevOps for work items every time someone opens it.

```
Browser opens the page
        │
        ▼
  GET /api/workitems                 (same origin, cache disabled)
        │
        ▼
  Netlify Function  ──── WIQL query ────▶  Azure DevOps
  (workitems.js)    ◀─── work items  ────
        │
        ▼
  JSON → table rendered in the browser
```

The page re-fetches **every 15 minutes** while open, and on every manual
**Refresh Now**. Because the query runs per request, "created in the last 7
days" is evaluated at the moment someone looks at it.

The ADO credential lives server-side as a Netlify environment variable. It is
never sent to the browser and never appears in page source.

### Deploying

Netlify is connected to this repo and redeploys on every push to `main`
(usually within ~30 seconds). You only need to deploy when the **code** changes
— never to refresh data.

---

## Files

| File | Purpose |
|---|---|
| `index.html` | The page. Fetches `/api/workitems`, renders the table, handles errors. No data in it. |
| `netlify/functions/workitems.js` | Server-side function. Holds the WIQL query, calls ADO, returns JSON. |
| `netlify.toml` | Routes `/api/workitems` to the function, sets the SharePoint iframe headers, disables caching. |

---

## Configuration

### The ADO token

Netlify → **Site configuration → Environment variables → `ADO_PAT`**

- Scope required: **Work Items → Read** (nothing else)
- Generated at https://millenniumsi.visualstudio.com/_usersSettings/tokens
- **Changing it requires a redeploy** — functions don't pick up new env vars
  until the next deploy. Use **Deploys → Trigger deploy → Clear cache and
  deploy site**.

### What the query returns

All of this lives at the top of `netlify/functions/workitems.js`:

| Setting | Current value |
|---|---|
| Iteration path | `MSI\Team Data Troopers Backlog` (includes children) |
| Time window | created in the last 7 days |
| Hidden states | `Removed`, `Canceled` |
| Max items | 200 |

### The refresh interval

`POLL_MS` at the top of the `<script>` block in `index.html`. Currently 15 minutes.

---

## Troubleshooting

The page is built so that failures are **visible**. If something breaks you get
a red banner, not stale data. Start by opening the live URL and reading the
banner and the **Data as of** timestamp in the top right.

`Data as of` is stamped by the server at query time, not by your browser clock —
so if it says a recent time, the data really is that fresh.

### Red banner: "ADO_PAT is not configured on this site."

The environment variable is missing, or was added without redeploying.
Add/confirm `ADO_PAT` in Netlify, then trigger a deploy.

### Red banner: "Azure DevOps rejected the credentials — the ADO_PAT has most likely expired."

The token expired or was revoked. Generate a new PAT (Work Items → Read),
update `ADO_PAT` in Netlify, trigger a deploy.

This is the one piece of recurring maintenance. Set a long expiry when you
create the token so it doesn't catch you out.

### Red banner: "Could not reach the work item service." / HTTP 404

`/api/workitems` isn't resolving to the function. Check that:

- `netlify.toml` still has the `/api/workitems` redirect
- `netlify/functions/workitems.js` exists in the repo
- the latest deploy actually succeeded

A 404 here is also what you'd see if you opened a **static-only copy** of the
page somewhere that can't run functions — see "Only one URL works" below.

### Table says "No work items created in the last 7 days"

Usually true rather than broken — the team may simply not have created anything
this week. Confirm in ADO with the same query the function uses (below). If ADO
returns rows but the page doesn't, check that those rows aren't all in a hidden
state.

### A state you wanted hidden is still showing

**Check the spelling against ADO, don't guess.** This project uses `Canceled`
with **one L**. `Cancelled` matches nothing and fails silently — no error, just
a filter that quietly does nothing.

Verify a state value really exists before adding it to `EXCLUDED_STATES`:

```sql
SELECT [System.Id] FROM WorkItems
WHERE [System.TeamProject] = 'MSI'
  AND [System.IterationPath] UNDER 'MSI\Team Data Troopers Backlog'
  AND [System.State] = 'YourStateHere'
```

If that returns rows, the spelling is right.

### The page shows old data after a code change

Netlify didn't deploy. Check **Deploys** in Netlify:

- **Is the build skipped?** Netlify honours `[skip ci]` in a commit message and
  will not build. Never put it in a commit to this repo.
- **Is auto-publishing stopped, or a deploy locked?** The Deploys page will say
  so. Resume it.
- **Is the repo still linked?** Site configuration → Build & deploy →
  Continuous deployment should show `toriladen/ado-work-items`, branch `main`,
  build command empty, publish directory `.`.

### SharePoint won't embed it

SharePoint's Embed web part rejects a bare URL with *"This website doesn't
support embedding using just the address."* Paste the full iframe instead:

```html
<iframe src="https://recentworkitems.netlify.app" width="100%" height="600" frameborder="0"></iframe>
```

The headers that permit framing come from `netlify.toml`. They must be sent as
**HTTP response headers** — `X-Frame-Options` and CSP `frame-ancestors` cannot
be set via HTML `<meta>` tags, which is why this can't be hosted anywhere that
doesn't let you configure headers.

### Only one URL works

`https://recentworkitems.netlify.app` is the only working address.

GitHub Pages **cannot** host this — it serves static files only and can't run
the function, so `/api/workitems` 404s and the page shows a permanent error
banner. The Pages copy of this repo was unpublished for that reason. Don't
re-enable it.

---

## Making common changes

**Hide another state** — in `netlify/functions/workitems.js`:

```js
const EXCLUDED_STATES = ['Removed', 'Canceled'];
```

Verify the spelling in ADO first (see above), add it to the array, commit.

**Change the time window** — the `@today - 7` in the `WIQL` constant in
`netlify/functions/workitems.js`.

**Add a colour for a work item state** — `index.html` needs both:

1. a CSS rule, e.g. `.state-ReadyForMerge { background: #d1fae5; color: #065f46; }`
2. an entry in the `STATE_CLASS` map, e.g. `'Ready For Merge': 'state-ReadyForMerge'`

States with no entry fall through to a neutral amber badge, which is harmless
but undifferentiated. `Dev Completed` and the `Defect` work item type currently
have no colour of their own.

---

## Why it's built this way

An earlier version baked the work items **into the HTML** and refreshed them on
a twice-daily GitHub Actions schedule that committed the updated file.

That design hid its own failures. The data flowed through four systems — ADO,
GitHub Actions, a git commit, a Netlify deploy — and a break anywhere left the
page rendering perfectly with weeks-old data and no indication anything was
wrong. It went stale for eleven days before anyone noticed, because the page's
"last refreshed" label showed the time the browser loaded it rather than the age
of the data.

The current design removes that whole class of problem: one moving part, data
fetched live, a server-stamped freshness timestamp, and loud on-screen errors.
Nothing has to be rewritten for the data to stay current.

If you add another ADO view later, copy the function and change the WIQL —
don't reintroduce build-time data.
