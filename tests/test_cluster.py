"""cluster/c4p_setup.py: the site-file and liveviz.py edits cluster/charm4py.sh makes."""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "cluster"))

import c4p_setup as C
from appspector import sites as S

ENTRIES = C.program_entries("/w/charm4py", "/w/charm4py/src")

SETUP_INI = """# written by cluster/setup.sh
[site]
scheduler = slurm
ssh = cluster
work = /w
appspector = /w/appSpector

[programs]
# the demo
pfield = {appspector}/apps/pfield | ./pfield {args} +pe {pes} ++server ++server-port {port}
"""


def load(text):
    path = os.path.join(tempfile.mkdtemp(), "site.ini")
    with open(path, "w") as f:
        f.write(text)
    return S.load_site(path)


class ProgramsTests(unittest.TestCase):
    def test_programs_last(self):
        text, msgs = C.add_programs(SETUP_INI, ENTRIES)
        self.assertEqual(msgs, ["added c4p_demo", "added c4p_liveviz"])
        self.assertTrue(text.startswith(SETUP_INI))          # comments and all kept
        site = load(text)
        self.assertEqual(set(site.programs), {"pfield", "c4p_demo", "c4p_liveviz"})
        self.assertEqual(site.programs["c4p_demo"].options, "procs=pes")
        # a second run changes nothing
        again, msgs = C.add_programs(text, ENTRIES)
        self.assertEqual(again, text)
        self.assertEqual(msgs, ["c4p_demo is up to date", "c4p_liveviz is up to date"])

    def test_programs_not_last(self):
        ini = SETUP_INI.replace("[programs]", "[programs]\nwave = /x | ./wave") + "\n[extra]\nnote = 1\n"
        ini = ini.replace("[site]", "[programs_notes]\na = 1\n\n[site]")
        text, _ = C.add_programs(ini, ENTRIES)
        self.assertEqual(text.count("[programs]"), 1)
        site = load(text)                                     # no DuplicateSectionError
        self.assertEqual(set(site.programs), {"pfield", "wave", "c4p_demo", "c4p_liveviz"})
        # the entries sit in [programs], before [extra]
        self.assertLess(text.index("c4p_liveviz ="), text.index("[extra]"))
        self.assertGreater(text.index("c4p_demo ="), text.index("[programs]\n"))

    def test_no_programs_section(self):
        ini = SETUP_INI[:SETUP_INI.index("[programs]")]
        text, _ = C.add_programs(ini, ENTRIES)
        self.assertEqual(text.count("[programs]"), 1)
        self.assertEqual(set(load(text).programs), {"c4p_demo", "c4p_liveviz"})

    def test_unmarked_entry_from_an_earlier_version(self):
        """The script before the mark wrote the same line without it: adopted, not duplicated."""
        old = SETUP_INI + ENTRIES[0][1] + "\n"
        text, msgs = C.add_programs(old, ENTRIES)
        self.assertEqual(msgs[0], "c4p_demo is up to date (now marked as this script's)")
        self.assertEqual(text.count("c4p_demo ="), 1)
        self.assertEqual(text.count(C.MARK), 2)
        self.assertEqual(C.add_programs(text, ENTRIES)[0], text)

    def test_user_entry_kept_marked_one_replaced(self):
        mine = "c4p_demo = /home/me/demo | python mine.py +pe {pes} ++server ++server-port {port} | | procs=pes"
        text, _ = C.add_programs(SETUP_INI + mine + "\n", ENTRIES)
        self.assertIn(mine + "\n", text)
        self.assertEqual(text.count("c4p_demo ="), 1)
        self.assertIn("c4p_liveviz =", text)
        # an entry the script wrote (marked) follows a changed C4P directory
        moved = C.program_entries("/new/charm4py", "/new/src")
        text2, msgs = C.add_programs(text, moved)
        self.assertIn(mine + "\n", text2)
        self.assertIn("kept your own c4p_demo", msgs[0])
        self.assertEqual(msgs[1], "updated c4p_liveviz")
        self.assertIn("/new/src/examples/liveviz", text2)
        self.assertNotIn("/w/charm4py/src/examples", text2)
        self.assertEqual(text2.count(C.MARK), 1)
        self.assertEqual(load(text2).programs["c4p_demo"].directory, "/home/me/demo")


class LivevizTests(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "charm4py"))
        path = os.path.join(d, "charm4py", "liveviz.py")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_states(self):
        stock = "def f():\n    buffer[a:b] %s\n" % C.LV_OLD
        path = self.write(stock)
        self.assertEqual(C.patch_liveviz(path, check_only=True)[0], "needs-patch")
        with open(path) as f:
            self.assertEqual(f.read(), stock)                   # --check never edits
        self.assertEqual(C.patch_liveviz(path)[0], "applied")
        self.assertEqual(C.patch_liveviz(path)[0], "patched")    # already applied
        self.assertEqual(C.patch_liveviz(self.write("img = np.add(a, b, dtype=np.uint8)\n"))[0], "not-needed")
        self.assertEqual(C.patch_liveviz(self.write("x = (a + b) % 256\n"))[0], "unknown")


if __name__ == "__main__":
    unittest.main()
