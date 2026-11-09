#!/usr/bin/env python3
"""Combine GitHub commit search with verified local history into data.json and data.js.

Usage: python3 scripts/collect.py   (needs the GitHub CLI `gh`, authenticated: gh auth login, or GH_TOKEN set)
"""
import json, subprocess, time, datetime, collections, sys, os

USER = "xinydev"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data.json")
OUT_JS = os.path.join(ROOT, "data.js")
HISTORY = os.path.join(ROOT, "scripts", "history.json")

# canonical upstream repos; (owner/repo, era, project label, domain)
REPOS = [
    ("jemalloc/jemalloc",        "memory",  "jemalloc",             "C"),
    ("pytorch/pytorch",          "memory",  "PyTorch",              "C++/Python"),
    ("spdk/spdk-csi",            "storage", "SPDK-CSI",             "Go"),
    ("spdk/spdk",                "storage", "SPDK",                 "C"),
    ("torvalds/linux",           "storage", "Linux kernel",         "C"),
    ("xinydev/telemetry-solution","storage","Arm Telemetry Solution","Python"),
    ("kubernetes/kubernetes",    "cloud",   "Kubernetes",           "Go"),
    ("kubernetes/kubeadm",       "cloud",   "kubeadm",              "Go"),
    ("kubernetes/website",       "cloud",   "Kubernetes docs",      "Markdown"),
    ("kubernetes/test-infra",    "cloud",   "Kubernetes test-infra","Go"),
    ("kubernetes-sigs/kubetest2","cloud",   "kubetest2",            "Go"),
    ("kubernetes-sigs/kind",     "cloud",   "kind",                 "Go"),
    ("knative/eventing",         "cloud",   "Knative Eventing",     "Go"),
]
# repos whose canonical home is not on GitHub: link commits to the mirror but label the upstream
UPSTREAM_HOME = {
    "xinydev/telemetry-solution": "https://gitlab.arm.com/telemetry-solution/telemetry-solution",
}

def gh(args):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        print("gh error:", r.stderr[:200], file=sys.stderr)
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None

def commits_for(repo):
    for attempt in range(3):
        d = gh(["search", "commits", "--author", USER, "--repo", repo, "--limit", "300",
                "--json", "sha,commit,url,repository"])
        if d is not None:
            break
        time.sleep(30)
    else:
        return None
    out, seen = [], set()
    for c in d:
        if c["sha"] in seen:
            continue
        seen.add(c["sha"])
        out.append({
            "sha": c["sha"][:10],
            "date": c["commit"]["author"]["date"][:10],
            "title": c["commit"]["message"].splitlines()[0],
            "url": c["url"],
        })
    out.sort(key=lambda x: x["date"], reverse=True)
    return out

def merge_commits(*groups):
    # Commit URLs contain the full SHA; displayed SHAs are abbreviated.
    commits = {c["url"]: c for group in groups for c in group}
    return sorted(commits.values(), key=lambda c: c["date"], reverse=True)

def main():
    with open(HISTORY) as f:
        history = {p["repo"]: p for p in json.load(f)}
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = {p["repo"]: p for p in json.load(open(OUT))["projects"]}
        except Exception:
            pass
    live_repos = {repo for repo, _, _, _ in REPOS}
    specs = {repo: (era, label, lang) for repo, era, label, lang in REPOS}
    for repo, p in history.items():
        specs.setdefault(repo, (p["era"], p["label"], p["lang"]))
    projects = []
    for repo, (era, label, lang) in specs.items():
        cs = []
        if repo in live_repos:
            cs = commits_for(repo)
            if cs is None:                   # keep last good data if the API failed
                cs = prev.get(repo, {}).get("commits", [])
                print("kept cached commits for", repo, file=sys.stderr)
        cs = merge_commits(cs, history.get(repo, {}).get("commits", []))
        projects.append({"repo": repo, "label": label, "era": era, "lang": lang,
                         "upstream": UPSTREAM_HOME.get(repo, f"https://github.com/{repo}"),
                         "count": len(cs), "first": cs[-1]["date"] if cs else None,
                         "last": cs[0]["date"] if cs else None, "commits": cs})
        if repo in live_repos:
            time.sleep(3)
    allc = [dict(c, repo=p["repo"], label=p["label"], era=p["era"]) for p in projects for c in p["commits"]]
    years = collections.Counter(c["date"][:4] for c in allc)
    data = {
        "user": USER,
        "name": "Xin Yang",
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "totals": {"commits": len(allc), "projects": sum(1 for p in projects if p["count"]),
                   "years": sorted(years.items()), "first": min(c["date"] for c in allc) if allc else None},
        "projects": projects,
    }
    json.dump(data, open(OUT, "w"), ensure_ascii=False, indent=1)
    with open(OUT_JS, "w") as f:
        f.write("window.CONTRIB = " + json.dumps(data, ensure_ascii=False) + ";\n")
    print(f"wrote data.json + data.js: {len(allc)} commits across {data['totals']['projects']} projects")

if __name__ == "__main__":
    main()
