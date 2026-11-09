import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "data.json"
        self.out_js = Path(temp.name) / "data.js"
        self.history = json.loads(Path(collect.HISTORY).read_text())
        self.history_count = sum(len(p["commits"]) for p in self.history)
        contexts = contextlib.ExitStack()
        self.addCleanup(contexts.close)
        contexts.enter_context(patch.multiple(collect, OUT=str(self.out), OUT_JS=str(self.out_js)))
        self.fetch = contexts.enter_context(patch.object(collect, "commits_for", return_value=[]))
        contexts.enter_context(patch.object(collect.time, "sleep"))
        contexts.enter_context(contextlib.redirect_stdout(io.StringIO()))
        contexts.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def generate(self):
        collect.main()
        data = json.loads(self.out.read_text())
        js = self.out_js.read_text().removeprefix("window.CONTRIB = ").strip().removesuffix(";")
        self.assertEqual(data, json.loads(js))
        return data

    def test_history_survives_repeated_empty_searches_without_extra_queries(self):
        historical_urls = {c["url"] for p in self.history for c in p["commits"]}
        for _ in range(2):
            data = self.generate()
            self.assertEqual(data["totals"]["commits"], self.history_count)
            self.assertEqual(data["totals"]["projects"], len(self.history))
            self.assertEqual(data["totals"]["first"], "2016-08-29")
            self.assertEqual({c["url"] for p in data["projects"] for c in p["commits"]}, historical_urls)
        self.assertEqual([c.args[0] for c in self.fetch.call_args_list],
                         [r[0] for r in collect.REPOS] * 2)

    def test_failed_search_keeps_cache_and_history(self):
        commit = {"sha": "a" * 10, "date": "2026-01-01", "title": "Cached commit",
                  "url": "https://github.com/jemalloc/jemalloc/commit/" + "a" * 40}
        self.out.write_text(json.dumps({"projects": [{"repo": "jemalloc/jemalloc", "commits": [commit]}]}))
        self.fetch.return_value = None
        data = self.generate()
        self.assertEqual(data["totals"]["commits"], self.history_count + 1)
        project = next(p for p in data["projects"] if p["repo"] == "jemalloc/jemalloc")
        self.assertEqual(project["commits"], [commit])

    def test_live_history_overlap_keeps_pinned_attribution_without_duplicates(self):
        historical = next(p for p in self.history if p["repo"] == "knative/serving")
        pinned = historical["commits"][0]
        duplicate = {**pinned, "sha": pinned["url"].rsplit("/", 1)[-1]}
        duplicate.pop("pr")
        new_commit = {"sha": "b" * 10, "date": "2026-01-01", "title": "New commit",
                      "url": "https://github.com/knative/serving/commit/" + "b" * 40}
        self.fetch.return_value = [duplicate, new_commit]
        with patch.object(collect, "REPOS", [(historical["repo"], historical["era"],
                                             historical["label"], historical["lang"])]):
            data = self.generate()
        project = next(p for p in data["projects"] if p["repo"] == historical["repo"])
        self.assertEqual(project["commits"], [new_commit, pinned])
        self.assertEqual((project["count"], project["first"], project["last"]),
                         (2, pinned["date"], new_commit["date"]))
        self.assertEqual(data["totals"]["commits"], self.history_count + 1)
        self.fetch.assert_called_once_with(historical["repo"])


if __name__ == "__main__":
    unittest.main()
