"""safe_write must not destroy the content it was asked to preserve.

The engines this backs are bulk mutators that walk thousands of files. Opening the target directly
truncates it the instant the handle opens, so a run interrupted between that and the last byte left
a half-written or empty note. Silent, and the damage is to exactly the content the caller was
trying to keep.

The test that matters is the one the OLD implementation fails: make the rename raise, then assert
the original file is byte-identical. Writing a file successfully proves nothing here.

The zone and root options are additive and default off; the controls below check they cannot
weaken the guards that were already there.
"""
import os

import pytest

from neurokeeper.lib import safe_write

# The refusals are asserted on the MESSAGE rather than the exception class. A caller of this
# function cares that the write was refused and why; pinning the class as well would couple these
# tests to where the type happens to be defined, which is exactly the private-module coupling
# neurokeeper.lib exists to avoid.


def test_it_writes(tmp_path):
    p = tmp_path / "note.md"
    safe_write(str(p), "hello", root=str(tmp_path))
    assert p.read_text(encoding="utf-8") == "hello"


def test_it_overwrites(tmp_path):
    p = tmp_path / "note.md"
    safe_write(str(p), "one", root=str(tmp_path))
    safe_write(str(p), "two", root=str(tmp_path))
    assert p.read_text(encoding="utf-8") == "two"


def test_an_interrupted_write_leaves_the_original_intact(tmp_path, monkeypatch):
    """THE one. The previous implementation fails this: it truncates on open."""
    p = tmp_path / "note.md"
    p.write_text("the content the caller wanted to keep", encoding="utf-8")
    original = p.read_bytes()

    def boom(src, dst):
        raise OSError("simulated interruption during rename")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        safe_write(str(p), "REPLACEMENT", root=str(tmp_path))
    assert p.read_bytes() == original


def test_no_partial_temp_file_is_left_behind(tmp_path, monkeypatch):
    p = tmp_path / "note.md"
    p.write_text("original", encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        safe_write(str(p), "new", root=str(tmp_path))
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]


def test_missing_parent_directories_are_created(tmp_path):
    p = tmp_path / "a" / "b" / "note.md"
    safe_write(str(p), "deep", root=str(tmp_path))
    assert p.read_text(encoding="utf-8") == "deep"


# --- the guards that already existed must still hold -------------------------------------------

def test_a_write_outside_the_boundary_is_refused(tmp_path):
    inside, outside = tmp_path / "vault", tmp_path / "elsewhere"
    inside.mkdir()
    outside.mkdir()
    with pytest.raises(Exception) as e:
        safe_write(str(outside / "escape.md"), "x", root=str(inside))
    assert "outside" in str(e.value)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privilege on Windows")
def test_a_symlink_target_is_refused(tmp_path):
    real = tmp_path / "real.md"
    real.write_text("real", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    with pytest.raises(Exception) as e:
        safe_write(str(link), "x", root=str(tmp_path))
    assert "symlink" in str(e.value)


# --- the new options ----------------------------------------------------------------------------

def test_a_forbidden_zone_is_refused(tmp_path):
    (tmp_path / "06 - Aankoop").mkdir()
    target = tmp_path / "06 - Aankoop" / "note.md"
    with pytest.raises(Exception) as e:
        safe_write(str(target), "x", root=str(tmp_path), zones=["06 - Aankoop"])
    assert "forbidden zone" in str(e.value)


def test_allow_zones_is_the_deliberate_override(tmp_path):
    (tmp_path / "06 - Aankoop").mkdir()
    target = tmp_path / "06 - Aankoop" / "note.md"
    safe_write(str(target), "x", root=str(tmp_path), zones=["06 - Aankoop"], allow_zones=True)
    assert target.read_text(encoding="utf-8") == "x"


def test_zones_default_off_so_existing_callers_are_unaffected(tmp_path):
    # The negative control for the whole port: five call sites pass none of the new arguments and
    # must behave exactly as before.
    (tmp_path / "06 - Aankoop").mkdir()
    target = tmp_path / "06 - Aankoop" / "note.md"
    safe_write(str(target), "x", root=str(tmp_path))
    assert target.read_text(encoding="utf-8") == "x"
