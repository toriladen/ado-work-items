"""
Queries ADO for recent work items and rewrites index.html with fresh data.
Run by GitHub Actions on a schedule; requires ADO_PAT env var.
"""
import os, json, base64, re, urllib.request, urllib.error
from datetime import datetime, timezone

ORG     = "millenniumsi"
PROJECT = "MSI"
PAT     = os.environ["ADO_PAT"]
BASE    = f"https://millenniumsi.visualstudio.com"
AUTH    = base64.b64encode(f":{PAT}".encode()).decode()
HEADERS = {"Content-Type": "application/json", "Authorization": f"Basic {AUTH}"}

WIQL = (
    "SELECT [System.Id],[System.Title],[System.WorkItemType],"
    "[System.State],[System.CreatedDate],[System.AssignedTo] "
    "FROM WorkItems "
    "WHERE [System.TeamProject]='MSI' "
    "AND [System.IterationPath] UNDER 'MSI\\Team Data Troopers Backlog' "
    "AND [System.CreatedDate] >= @today - 7 "
    "ORDER BY [System.CreatedDate] DESC"
)


def ado_post(url, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def ado_get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def fetch_work_items():
    wiql_url = f"{BASE}/{PROJECT}/_apis/wit/wiql?api-version=7.1"
    result = ado_post(wiql_url, {"query": WIQL})
    ids = [w["id"] for w in result.get("workItems", [])]
    if not ids:
        return []

    batch_url = f"{BASE}/_apis/wit/workitemsbatch?api-version=7.1"
    fields = [
        "System.Id", "System.Title", "System.WorkItemType",
        "System.State", "System.CreatedDate", "System.AssignedTo"
    ]
    batch = ado_post(batch_url, {"ids": ids, "fields": fields})

    items = []
    for wi in batch.get("value", []):
        f = wi["fields"]
        assigned = f.get("System.AssignedTo") or {}
        if isinstance(assigned, dict):
            assigned = assigned.get("displayName", "")
        items.append({
            "id":         f["System.Id"],
            "title":      f.get("System.Title", ""),
            "type":       f.get("System.WorkItemType", ""),
            "state":      f.get("System.State", ""),
            "created":    f.get("System.CreatedDate", ""),
            "assignedTo": assigned,
        })
    items.sort(key=lambda x: x["created"], reverse=True)
    return items


def build_seed_js(items):
    lines = []
    for item in items:
        lines.append(
            f'    {{ id: {item["id"]}, '
            f'title: {json.dumps(item["title"])}, '
            f'type: {json.dumps(item["type"])}, '
            f'state: {json.dumps(item["state"])}, '
            f'created: {json.dumps(item["created"])}, '
            f'assignedTo: {json.dumps(item["assignedTo"])} }},'
        )
    return "  const SEED_DATA = [\n" + "\n".join(lines) + "\n  ];"


def update_html(items):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    new_seed = build_seed_js(items)
    # Replace everything from `const SEED_DATA = [` to the closing `];`
    html = re.sub(
        r"  const SEED_DATA = \[[\s\S]*?\];",
        new_seed,
        html,
        count=1
    )

    # Update the last-refreshed timestamp comment at the top of the script block
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = re.sub(
        r"// Last refreshed:.*",
        f"// Last refreshed: {ts}",
        html
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Updated index.html with {len(items)} work items ({ts})")


if __name__ == "__main__":
    items = fetch_work_items()
    print(f"Fetched {len(items)} work items from ADO")
    update_html(items)
