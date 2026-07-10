import csv
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import DD_API_KEY, DD_APP_KEY, DD_SITE

BASE_URL = f"https://api.{DD_SITE}"

# =====================================================
# Session HTTP
# =====================================================

session = requests.Session()

session.headers.update({
    "DD-API-KEY": DD_API_KEY,
    "DD-APPLICATION-KEY": DD_APP_KEY,
    "Accept": "application/json"
})

retry = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)

session.mount("https://", HTTPAdapter(max_retries=retry))

# =====================================================
# Monitors
# =====================================================

def get_monitors():

    print("Loading monitors...")

    monitors = []

    page = 0
    page_size = 1000
    total = None

    while True:

        response = session.get(
            f"{BASE_URL}/api/v1/monitor",
            params={
                "page": page,
                "page_size": page_size
            },
            timeout=30
        )

        response.raise_for_status()

        payload = response.json()

        if not payload:
            break

        monitors.extend(payload)

        if total is None:
            print(f"Paginating monitors...")

        print(f"{len(monitors)} monitors loaded...")

        # Si la réponse contient moins d'items que page_size, on a atteint la fin
        if len(payload) < page_size:
            break

        page += 1

        time.sleep(0.2)

    monitor_ids = set()
    monitor_infos = []
    tag_index = {}

    for monitor in monitors:

        monitor_id = int(monitor["id"])

        tags = set(monitor.get("tags", []))

        monitor_ids.add(monitor_id)

        monitor_infos.append({
            "id": monitor_id,
            "name": monitor["name"],
            "tags": tags
        })

        for tag in tags:
            tag_index.setdefault(tag, set()).add(monitor_id)

    print(f"{len(monitors)} monitors loaded ✓")

    return monitor_ids, monitor_infos, tag_index

# =====================================================
# Downtimes
# =====================================================

def get_downtimes():

    print("Loading downtimes...")

    downtimes = []

    offset = 0
    page_limit = 1000

    total = None

    while True:

        response = session.get(
            f"{BASE_URL}/api/v2/downtime",
            params={
                "page[limit]": page_limit,
                "page[offset]": offset
            },
            timeout=30
        )

        response.raise_for_status()

        payload = response.json()

        data = payload.get("data", [])

        if total is None:
            total = payload["meta"]["page"]["total_filtered_count"]
            print(f"Total downtimes: {total}")

        if not data:
            break

        downtimes.extend(data)

        print(f"{len(downtimes)} / {total}")

        if len(downtimes) >= total:
            break

        offset += page_limit

        time.sleep(0.2)

    print(f"{len(downtimes)} downtimes loaded ✓")

    return downtimes

# =====================================================
# Matching monitor_tags
# =====================================================

def impacted_from_tags(tags, tag_index):
    """
    Récupère les monitor IDs qui matchent TOUS les tags (intersection AND).

    Exemple:
    - Downtime avec tags ["env:prod", "service:api"]
    - Ne matchera que les monitors qui ont LES DEUX tags
    """

    if not tags:
        return set()

    result = None

    for tag in tags:

        ids = tag_index.get(tag, set())

        if result is None:
            result = ids.copy()
        else:
            result &= ids  # Intersection AND

        if not result:
            return set()

    return result or set()

# =====================================================
# Analyse
# =====================================================

def analyze():

    monitor_ids, monitor_infos, tag_index = get_monitors()

    monitor_name = {
        m["id"]: m["name"]
        for m in monitor_infos
    }

    downtimes = get_downtimes()

    results = []

    print("\nAnalyzing downtimes...")

    for dt in downtimes:

        attrs = dt["attributes"]

        identifier = attrs.get("monitor_identifier", {})

        impacted_ids = set()

        dtype = "unknown"

        reason = ""

        if "monitor_id" in identifier:

            dtype = "monitor_id"

            mid = int(identifier["monitor_id"])

            if mid in monitor_ids:
                impacted_ids.add(mid)
            else:
                reason = "Monitor does not exist"

        elif "monitor_tags" in identifier:

            dtype = "monitor_tags"

            impacted_ids = impacted_from_tags(
                identifier["monitor_tags"],
                tag_index
            )

            if not impacted_ids:
                reason = "No monitor matches monitor_tags"

        results.append({

            "downtime_id": dt["id"],

            "status": attrs.get("status"),

            "type": dtype,

            "created": attrs.get("created"),

            "modified": attrs.get("modified"),

            "scope": attrs.get("scope"),

            "message": attrs.get("message"),

            "impacted_monitors": len(impacted_ids),

            "monitor_ids": ",".join(
                map(str, sorted(impacted_ids))
            ),

            "monitor_names": " | ".join(
                monitor_name.get(i, "")
                for i in sorted(impacted_ids)
            ),

            "orphan": len(impacted_ids) == 0,

            "reason": reason

        })

    print("Exporting CSV...")

    with open(
            "csv/downtime_audit.csv",
            "w",
            newline="",
            encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "downtime_id",
                "status",
                "type",
                "created",
                "modified",
                "scope",
                "message",
                "impacted_monitors",
                "monitor_ids",
                "monitor_names",
                "orphan",
                "reason"
            ]
        )

        writer.writeheader()

        writer.writerows(results)

    print()
    print("========== SUMMARY ==========")
    print(f"Monitors      : {len(monitor_ids)}")
    print(f"Downtimes     : {len(results)}")
    print(f"Orphans       : {sum(r['orphan'] for r in results)}")
    orphan_count = sum(r['orphan'] for r in results)
    if orphan_count > 0:
        print(f"⚠️  {orphan_count} downtimes with no impacted monitors")
    print()
    print("✓ CSV exported: downtime_audit_NEW.csv")


if __name__ == "__main__":
    analyze()