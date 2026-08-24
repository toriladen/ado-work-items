"""
Queries ADO for work items created in the last 7 days under
MSI\\Team Data Troopers Backlog, then rewrites the WORK_ITEMS array and the
DATA_AS_OF stamp in index.html.

Run by GitHub Actions on a schedule; requires the ADO_PAT env var.

If the file cannot be rewritten, this exits non-zero so the workflow turns red.
A silent "success" that changes nothing is what previously let the page go
stale for days without anyone noticing.
"""
import os
import re
import sys
import json
import base64
import urllib.request
from datetime import datetime, timezone

PROJECT = "MSI"
BASE = "https://millenniumsi.visualstudio.com"
ITERATION = r"MSI\Team Data Troopers Backlog"
HTML_FILE = "index.html"

PAT = os.environ.get("ADO_PAT")
if not PAT:
    sys.exit("ERROR: ADO_PAT environment variable is not set.")

AUTH = base64.b64encode(f":{PAT}".encode()).decode()
HEADERS = {"Content-Type": "application/json", "Authorization": f"Basic {AUTH}"}

WIQL = (
    "SELECT [System.Id],[System.Title],[System.WorkItemType],"
    "[System.State],[System.CreatedDate],[System.AssignedTo] "
    "FROM WorkItems "
    f"WHERE [System.TeamProject]='{PROJECT}' "
    f"AND [System.IterationPath] UNDER '{ITERATION}' "
    "AND [System.CreatedDate] >= @today - 7 "
    "ORDER BY [System.CreatedDate] DESC"
)

FIELDS = [
    "System.Id",
    "System.Title",
    "System.WorkItemType",
    "System.State",
    "System.CreatedDate",
    "System.AssignedTo",
]


def ado_post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=HEADERS, method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def fetch_work_items():
    result = ado_post(f"{BASE}/{PROJECT}/_apis/wit/wiql?api-version=7.1", {"query": WIQL})
    ids = [w["id"] for w in result.get("workItems", [])]
    if not ids:
        return []

    batch = ado_post(
        f"{BASE}/_apis/wit/workitemsbatch?api-version=7.1",
        {"ids": ids, "fields": FIELDS},
    )

    items = []
    for wi in batch.get("value", []):
        f = wi["fields"]
        assigned = f.get("System.AssignedTo") or ""
        if isinstance(assigned, dict):
            assigned = assigned.get("displayName", "")
        items.append(
            {
                "id": f["System.Id"],
                "title": f.get("System.Title", ""),
                "type": f.get("System.WorkItemType", ""),
                "state": f.get("System.State", ""),
                "created": f.get("System.CreatedDate", ""),
                "assignedTo": assigned,
            }
        )
    items.sort(key=lambda x: x["created"], reverse=True)
    return items


def build_items_js(items):
    lines = [
        "    {{ id: {id}, title: {title}, type: {type}, state: {state}, "
        "created: {created}, assignedTo: {assigned} }},".format(
            id=i["id"],
            title=json.dumps(i["title"]),
            type=json.dumps(i["type"]),
            state=json.dumps(i["state"]),
            created=json.dumps(i["created"]),
            assigned=json.dumps(i["assignedTo"]),
        )
        for i in items
    ]
    if not lines:
        return "  const WORK_ITEMS = [];"
    return "  const WORK_ITEMS = [\n" + "\n".join(lines) + "\n  ];"


def update_html(items):
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Replace the WORK_ITEMS array (non-greedy up to the first closing "];").
    html, n_items = re.subn(
        r"  const WORK_ITEMS = \[[\s\S]*?\];",
        build_items_js(items).replace("\\", "\\\\"),
        html,
        count=1,
    )
    if n_items != 1:
        sys.exit(f"ERROR: could not locate the WORK_ITEMS array in {HTML_FILE}.")

    # Replace the freshness stamp.
    html, n_stamp = re.subn(
        r'  const DATA_AS_OF = "[^"]*";',
        f'  const DATA_AS_OF = "{stamp}";',
        html,
        count=1,
    )
    if n_stamp != 1:
        sys.exit(f"ERROR: could not locate the DATA_AS_OF constant in {HTML_FILE}.")

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote {len(items)} work item(s) to {HTML_FILE}; DATA_AS_OF={stamp}")


if __name__ == "__main__":
    work_items = fetch_work_items()
    print(f"Fetched {len(work_items)} work item(s) from ADO")
    for w in work_items:
        print(f"  #{w['id']}  {w['created'][:10]}  {w['title'][:70]}")
    update_html(work_items)
