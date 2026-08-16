#!/usr/bin/env python3
# @capability:  substrate-probe
# @portability: L1a-generic   (Windows-aware; degrades to size/encoding checks elsewhere)
# @status:      library
"""Ask whether the filesystem's answers can be trusted, before anything relies on them.

Knowledge collections live disproportionately on synced mounts: Drive, Dropbox, OneDrive. On those
substrates `size`, `mtime` and existence-immediately-after-a-write are not facts. Placeholders report
allocation-rounded sizes, files hydrate on access, and mtime belongs to the sync client rather than
to whoever wrote the note.

Every engine that touches the filesystem inherits that exposure, so it is answered once here rather
than separately (and differently) in each engine.

Three observed shapes, none of which produces an error:

  * a size cap enforced by stat()ing a file just written, passing files that were over it because
    the value returned was an allocation-rounded placeholder;
  * a freshness check reading mtime, understating staleness by a month;
  * a cache keyed on (mtime, size) serving entries that never invalidate.

The rule that survives all three: MEASURE THE BYTES YOU ENCODED, NOT THE FILE YOU WROTE, and where a
key must come from the filesystem, hash the content instead.
"""
import hashlib
import os
import sys

# Windows file attributes that mark a cloud placeholder whose bytes are not local.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_PLACEHOLDER = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

# Substrates whose metadata is known to be unreliable, matched against a resolved path. Deliberately
# a small, boring list: a wrong POSITIVE here only costs a hash, while a wrong negative costs
# correctness, so the bias is toward suspicion.
_SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "my drive", "icloud",
                 "nextcloud", "pcloud", "box sync", "creative cloud files")


def is_placeholder(path):
    """True when a file exists but its bytes are not local yet (so a read may be short or slow)."""
    try:
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & _PLACEHOLDER)


def probe(root):
    """Describe the substrate under `root`. Cheap: one stat plus a bounded sample.

    Returns a dict rather than a bool, because an engine may want to act differently on "this is a
    sync mount" than on "some files here are not hydrated".
    """
    root = os.path.abspath(root)
    low = root.replace("\\", "/").lower()
    named = next((m for m in _SYNC_MARKERS if m in low), None)

    placeholders, sampled = 0, 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if not fn.endswith((".md", ".markdown")):
                continue
            sampled += 1
            if is_placeholder(os.path.join(dirpath, fn)):
                placeholders += 1
            if sampled >= 200:                  # a sample, not a census: this runs on every doctor
                break
        if sampled >= 200:
            break

    unreliable = bool(named) or placeholders > 0
    return {
        "root": root,
        "sync_marker": named,
        "sampled": sampled,
        "placeholders": placeholders,
        "metadata_reliable": not unreliable,
        "note": _note(named, placeholders),
    }


def _note(named, placeholders):
    if placeholders:
        return (f"{placeholders} sampled file(s) are cloud placeholders: their bytes are not local, "
                f"so size and a read may both be wrong until they hydrate")
    if named:
        return (f"path looks like a {named} mount: size and mtime are the sync client's answers, "
                f"not the author's, so metadata-keyed caches and freshness checks are unreliable")
    return "ordinary local filesystem: metadata is trustworthy"


def content_signature(path, st=None):
    """A cache key that does not depend on the filesystem telling the truth.

    Hashing every file is the expensive option, which is why callers should use it only where
    `probe()` says metadata cannot be trusted. sha256 over the bytes, not over a size that a
    placeholder invented.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return "sha256:" + h.hexdigest()[:32]


def write_verified(path, text, encoding="utf-8"):
    """Write text and return the byte length that was ENCODED, never a size read back afterwards.

    A size read back from a synced mount immediately after a write is the sync client's guess. This
    exists so a caller enforcing a size limit measures the thing it actually produced.
    """
    data = text.encode(encoding)
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


if __name__ == "__main__":                       # tiny CLI so the probe is inspectable on its own
    import json
    print(json.dumps(probe(sys.argv[1] if len(sys.argv) > 1 else "."), indent=2))
