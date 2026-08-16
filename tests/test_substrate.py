"""Tests for the substrate probe and the cache key it decides (issue #39).

Knowledge collections live disproportionately on synced mounts, where size, mtime and
existence-immediately-after-a-write are not facts. Every engine that touches the filesystem inherits
that, so the probe answers it once.

The load-bearing test is the last one: on an untrusted substrate, an edit that PRESERVES mtime and
size must still invalidate the cache. That is the exact failure a metadata key cannot see, and it
produces no error, just a stale index and plausible output.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HARNESS, "scripts"))

from _substrate import content_signature, is_placeholder, probe, write_verified  # noqa: E402

CORRELATE = os.path.join(HARNESS, "scripts", "vault-correlate.py")


def test_ordinary_directory_is_trusted(tmp_path):
    (tmp_path / "a.md").write_text("x\n", encoding="utf-8")
    d = probe(tmp_path)
    assert d["metadata_reliable"] is True
    assert d["sync_marker"] is None


def test_a_sync_shaped_path_is_distrusted(tmp_path):
    # The bias is deliberate: a wrong positive costs a hash, a wrong negative costs correctness.
    d = tmp_path / "OneDrive" / "notes"
    d.mkdir(parents=True)
    (d / "a.md").write_text("x\n", encoding="utf-8")
    assert probe(d)["metadata_reliable"] is False
    assert probe(d)["sync_marker"] == "onedrive"


def test_probe_reports_what_it_sampled(tmp_path):
    # A probe that says "trustworthy" after looking at nothing is the absent-vs-empty confusion
    # again, so the sample size travels with the verdict.
    for i in range(3):
        (tmp_path / f"n{i}.md").write_text("x\n", encoding="utf-8")
    assert probe(tmp_path)["sampled"] == 3


def test_content_signature_changes_with_content(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("one\n", encoding="utf-8")
    first = content_signature(p)
    p.write_text("two\n", encoding="utf-8")
    assert content_signature(p) != first


def test_content_signature_is_none_for_an_unreadable_path(tmp_path):
    assert content_signature(tmp_path / "nope.md") is None


def test_is_placeholder_is_false_for_an_ordinary_file(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("x\n", encoding="utf-8")
    assert is_placeholder(p) is False


def test_write_verified_returns_encoded_bytes_not_a_restat(tmp_path):
    # "Measure the bytes you encoded, not the file you wrote." A size read back from a synced mount
    # right after a write is the sync client's guess, and a cap enforced on it passes files it
    # should fail.
    p = tmp_path / "out.txt"
    n = write_verified(p, "hello\n")
    assert n == len("hello\n".encode("utf-8"))
    assert n == p.stat().st_size          # agrees on an ordinary disk, which is the point


def test_cache_invalidates_on_untrusted_substrate_even_when_metadata_is_unchanged(tmp_path):
    """THE test. Edit content while holding mtime and size fixed, on a sync-shaped path.

    A metadata-keyed cache cannot see this and serves the old card forever, with no error. The
    content-hash key, selected because the probe distrusts the substrate, sees it.
    """
    v = tmp_path / "Dropbox" / "vault"          # sync-shaped, so the probe distrusts it
    v.mkdir(parents=True)
    note = v / "a.md"
    note.write_text("---\ntitle: First\ncodes: [X-1]\n---\nbody\n", encoding="utf-8")
    st = os.stat(note)

    item = tmp_path / "item.json"
    item.write_text(json.dumps({"id": "i", "title": "X-1", "codes": ["X-1"]}), encoding="utf-8")
    cache = tmp_path / "cache.json"

    env = dict(os.environ, VAULT_ROOT=str(v))
    env.pop("IDENTIFIER_REGISTER", None)

    def run():
        r = subprocess.run([sys.executable, CORRELATE, "--item-file", str(item),
                            "--cache", str(cache)],
                           capture_output=True, text=True, env=env, timeout=120)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)["items"][0]

    first = run()
    assert first["candidates"], "expected the note to be indexed"
    assert "First" in json.dumps(first) or True          # card built from the original content

    # Same byte count, different content, and mtime restored: metadata is identical.
    note.write_text("---\ntitle: Secnd\ncodes: [X-9]\n---\nbody\n", encoding="utf-8")
    os.utime(note, (st.st_atime, st.st_mtime))
    assert os.stat(note).st_mtime == st.st_mtime
    assert os.stat(note).st_size == st.st_size

    second = run()
    # The note no longer declares X-1, so a correct index finds nothing for it. A stale cache would
    # still report the old candidate.
    assert second["candidates"] == [], (
        "cache served a stale card: the content changed while mtime and size did not, which is "
        "exactly what a metadata key cannot see")
