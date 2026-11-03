"""Unified diffs become changes with new-file line ranges."""

from codeatlas.impact import Change, parse_diff

DIFF = """diff --git a/src/a.py b/src/a.py
index 1..2 100644
--- a/src/a.py
+++ b/src/a.py
@@ -10,3 +10,4 @@ def f():
@@ -40 +41 @@ def g():
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,5 +0,0 @@
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,5 @@
"""


def test_ranges_use_the_new_file_numbering():
    changes = parse_diff(DIFF)
    assert changes[0] == Change("src/a.py", ((10, 13), (41, 41)))


def test_added_and_deleted_files_have_no_ranges():
    changes = parse_diff(DIFF)
    assert changes[1] == Change("old.py")
    assert changes[2] == Change("new.py")


def test_empty_diff_gives_nothing():
    assert parse_diff("") == []
