/**
 * Netlify Function: /api/workitems
 *
 * Queries Azure DevOps for work items created in the last 7 days under
 * MSI\Team Data Troopers Backlog and returns them as JSON.
 *
 * Runs server-side on every request, so:
 *   - the data is never baked into the deployed HTML
 *   - "last 7 days" is evaluated when the page is opened, not at build time
 *   - the ADO PAT stays on the server and is never sent to the browser
 *
 * Requires the ADO_PAT environment variable (Netlify → Site configuration →
 * Environment variables). Scope needed: Work Items (Read).
 */

const ADO_BASE = 'https://millenniumsi.visualstudio.com';
const PROJECT = 'MSI';
const ITERATION = 'MSI\\Team Data Troopers Backlog'; // one literal backslash at runtime
const TIMEOUT_MS = 10000;
const MAX_ITEMS = 200; // the workitemsbatch endpoint accepts at most 200 ids

const WIQL =
  'SELECT [System.Id] FROM WorkItems ' +
  `WHERE [System.TeamProject] = '${PROJECT}' ` +
  `AND [System.IterationPath] UNDER '${ITERATION}' ` +
  'AND [System.CreatedDate] >= @today - 7 ' +
  'ORDER BY [System.CreatedDate] DESC';

const FIELDS = [
  'System.Id',
  'System.Title',
  'System.WorkItemType',
  'System.State',
  'System.CreatedDate',
  'System.AssignedTo',
];

const JSON_HEADERS = {
  'Content-Type': 'application/json',
  // Never let the CDN, the browser, or the SharePoint iframe cache this.
  'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
};

function reply(statusCode, payload) {
  return { statusCode, headers: JSON_HEADERS, body: JSON.stringify(payload) };
}

async function adoPost(url, body, auth) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Basic ${auth}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    const text = await res.text();

    // A bad or expired PAT does not come back as 401 — ADO answers 203 with an
    // HTML sign-in page, which would otherwise pass a plain res.ok check.
    if (res.status === 203 || !res.ok) {
      const err = new Error(`ADO returned ${res.status}`);
      err.status = res.status;
      err.detail = text.slice(0, 300);
      throw err;
    }

    try {
      return JSON.parse(text);
    } catch {
      const err = new Error('ADO returned a non-JSON response');
      err.status = res.status;
      err.detail = text.slice(0, 300);
      throw err;
    }
  } finally {
    clearTimeout(timer);
  }
}

exports.handler = async () => {
  const pat = process.env.ADO_PAT;
  if (!pat) {
    return reply(500, {
      ok: false,
      error: 'ADO_PAT is not configured on this site.',
      hint: 'Netlify → Site configuration → Environment variables → add ADO_PAT.',
    });
  }

  const auth = Buffer.from(`:${pat}`).toString('base64');

  try {
    const wiqlResult = await adoPost(
      `${ADO_BASE}/${PROJECT}/_apis/wit/wiql?api-version=7.1`,
      { query: WIQL },
      auth
    );

    const ids = (wiqlResult.workItems || []).map((w) => w.id).slice(0, MAX_ITEMS);

    if (ids.length === 0) {
      return reply(200, { ok: true, fetchedAt: new Date().toISOString(), items: [] });
    }

    const batch = await adoPost(
      `${ADO_BASE}/_apis/wit/workitemsbatch?api-version=7.1`,
      { ids, fields: FIELDS },
      auth
    );

    const items = (batch.value || []).map((wi) => {
      const f = wi.fields || {};
      const assigned = f['System.AssignedTo'];
      return {
        id: f['System.Id'],
        title: f['System.Title'] || '',
        type: f['System.WorkItemType'] || '',
        state: f['System.State'] || '',
        created: f['System.CreatedDate'] || '',
        assignedTo:
          assigned && typeof assigned === 'object'
            ? assigned.displayName || ''
            : assigned || '',
      };
    });

    items.sort((a, b) => new Date(b.created) - new Date(a.created));

    return reply(200, {
      ok: true,
      fetchedAt: new Date().toISOString(),
      items,
    });
  } catch (e) {
    const isAuth = e.status === 203 || e.status === 401 || e.status === 403;
    return reply(isAuth ? 401 : 502, {
      ok: false,
      error: isAuth
        ? 'Azure DevOps rejected the credentials — the ADO_PAT has most likely expired.'
        : `Could not reach Azure DevOps: ${e.message}`,
      detail: e.detail || undefined,
    });
  }
};
