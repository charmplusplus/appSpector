import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from appspector import jobs as J
from appspector import sites as S

SITE_INI = """[site]
scheduler = slurm
ssh = cluster
work = /work/alloc/me/appspector
appspector = /work/alloc/me/appSpector
account = alloc-cpu
partition = interactive
cores_per_node = 128
default_nodes = 1
default_procs_per_node = 2
default_pes = 4
walltime = 00:30:00
mem = 16g
launcher = stdbuf -o0 -e0 srun --mpi=pmix -n {procs} -c {cores_per_proc}
port = 1234

[programs]
pfield = {appspector}/apps/pfield | ./pfield {args} +pe {pes} ++server ++server-port {port} +balancer GreedyRefineLB
wave2d = {work}/charm/examples/charm++/wave2d | ./wave2d-demo +pe {pes} ++server ++server-port {port}
"""


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "cluster.ini")
        with open(self.path, "w") as f:
            f.write(SITE_INI)
        self.site = S.load_site(self.path)

    def test_load(self):
        s = self.site
        self.assertEqual((s.name, s.scheduler, s.ssh, s.cores_per_node, s.port), ("cluster", "slurm", "cluster", 128, 1234))
        self.assertEqual(s.env, "/work/alloc/me/appspector/env.sh")
        self.assertEqual(s.programs["pfield"].directory, "/work/alloc/me/appSpector/apps/pfield")
        self.assertEqual(s.programs["wave2d"].directory, "/work/alloc/me/appspector/charm/examples/charm++/wave2d")

    def test_local_builtin(self):
        s = S.load_site("local")
        self.assertEqual(s.scheduler, "local")
        self.assertTrue(s.programs["pfield"].directory.endswith("/apps/pfield"))
        self.assertTrue(s.work.endswith("/runs"))

    def test_resolve_defaults_and_overrides(self):
        d, c, v = J.JobSpec(program="pfield").resolve(self.site)
        self.assertEqual(c, "./pfield  +pe 4 ++server ++server-port 1234 +balancer GreedyRefineLB"
                            " ++server-auth /work/alloc/me/appspector/jobs/pfield-<stamp>.key")
        self.assertEqual((v["nodes"], v["procs"], v["cores_per_proc"]), (1, 2, 2))      # 4 PEs over 2 procs
        d, c, v = J.JobSpec(program="pfield", args="-k 16 -n 400", pes=32, nodes=2, procs_per_node=4, port=2000,
                            auth=False).resolve(self.site)
        self.assertEqual(c, "./pfield -k 16 -n 400 +pe 32 ++server ++server-port 2000 +balancer GreedyRefineLB")
        self.assertEqual(v["keyfile"], "")
        self.assertEqual((v["nodes"], v["procs"], v["cores_per_proc"]), (2, 8, 4))      # 32 PEs over 8 procs
        with self.assertRaises(KeyError):
            J.JobSpec(program="nope").resolve(self.site)
        with self.assertRaises(ValueError):            # 4 PEs over 12 processes
            J.JobSpec(program="pfield", pes=4, nodes=4, procs_per_node=3).resolve(self.site)
        d, c, v = J.JobSpec(directory="/x", command="./mine +pe {pes} ++server ++server-port {port}", pes=3).resolve(self.site, "S1")
        self.assertEqual((d, c), ("/x", "./mine +pe 3 ++server ++server-port 1234 ++server-auth /work/alloc/me/appspector/jobs/job-S1.key"))
        # a command that places {keyfile} itself is left alone
        d, c, v = J.JobSpec(directory="/x", command="./mine ++server-auth {keyfile} +pe {pes}", pes=3).resolve(self.site, "S1")
        self.assertEqual(c, "./mine ++server-auth /work/alloc/me/appspector/jobs/job-S1.key +pe 3")
        # the site can turn auth off
        with open(self.path, "w") as f:
            f.write(SITE_INI.replace("port = 1234\n", "port = 1234\nauth = no\n"))
        off = S.load_site(self.path)
        self.assertFalse(off.auth)
        d, c, v = J.JobSpec(program="pfield").resolve(off, "S1")
        self.assertNotIn("++server-auth", c)
        d, c, v = J.JobSpec(program="pfield", auth=True).resolve(off, "S1")
        self.assertIn("++server-auth /work/alloc/me/appspector/jobs/pfield-S1.key", c)

    def test_render_batch(self):
        script, out, v = J.render_batch(self.site, J.JobSpec(program="pfield", pes=16, nodes=2, procs_per_node=2),
                                        stamp="20261026-093000")
        self.assertIn("#SBATCH -A alloc-cpu", script)
        self.assertIn("#SBATCH -p interactive", script)
        self.assertIn("#SBATCH -N 2", script)
        self.assertIn("#SBATCH --ntasks=4", script)
        self.assertIn("#SBATCH --cpus-per-task=4", script)      # 16 PEs over 4 procs
        self.assertIn("#SBATCH -o /work/alloc/me/appspector/jobs/pfield-%j.out", script)
        self.assertIn("source /work/alloc/me/appspector/env.sh", script)
        self.assertIn("cd /work/alloc/me/appSpector/apps/pfield", script)
        self.assertIn("stdbuf -o0 -e0 srun --mpi=pmix -n 4 -c 4 ./pfield  +pe 16 ++server ++server-port 1234 +balancer GreedyRefineLB"
                      " ++server-auth /work/alloc/me/appspector/jobs/pfield-20261026-093000.key\n", script)
        self.assertEqual(out, "/work/alloc/me/appspector/jobs/pfield-%j.out")
        # a site without a memory request leaves the line out
        site2 = S.load_site(self.path)
        site2.mem = ""
        script2, _, _ = J.render_batch(site2, J.JobSpec(program="pfield"))
        self.assertNotIn("--mem", script2)
        self.assertIn("#SBATCH -t 00:30:00", script2)


class AddProgramTests(unittest.TestCase):
    def test_add_program_and_path(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "cluster.ini")
        with open(path, "w") as f:
            f.write(SITE_INI)
        site = S.load_site(path)
        S.add_program(site, "mine", "{work}/mine", "./mine {args} +pe {pes} ++server ++server-port {port}", "--inject myInject")
        again = S.load_site(path)
        self.assertEqual(again.programs["mine"].directory, "/work/alloc/me/appspector/mine")
        self.assertEqual(again.programs["mine"].viewer_args, "--inject myInject")
        d, c, v = J.JobSpec(program="mine", args="-x", pes=2, auth=False).resolve(again)
        self.assertEqual((d, c), ("/work/alloc/me/appspector/mine", "./mine -x +pe 2 ++server ++server-port 1234"))
        from appspector.shell import Shell
        sh = Shell(path)
        sh.say = lambda text: None
        sh.do_program("/home/me/prog/leanmd -s 10")
        d, c, v = sh.spec.resolve(sh.site, "S1")
        self.assertEqual((d, c), ("/home/me/prog", "./leanmd -s 10 +pe 4 ++server ++server-port 1234"
                                                   " ++server-auth /work/alloc/me/appspector/jobs/job-S1.key"))


class AuthTests(unittest.TestCase):
    def test_key_format(self):
        from ccsio import protocol as P
        k1, k2 = J.new_key(), J.new_key()
        self.assertNotEqual(k1, k2)
        self.assertEqual(len(k1), 32)
        self.assertTrue(k1.isdigit())
        raw = P.parse_key(k1)                   # what the server makes of the string
        self.assertEqual(len(raw), 16)
        self.assertEqual(list(raw), [int(k1[i:i + 2]) for i in range(0, 32, 2)])
        self.assertEqual(J.key_file_text(k1), "0 %s\n" % k1)

    def test_slurm_start_writes_key_before_script(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "cluster.ini")
        with open(path, "w") as f:
            f.write(SITE_INI)
        site = S.load_site(path)
        from appspector import launch as L
        sent = []
        saved = (L.reachable, L.ssh, L.submit, J.JOBS_FILE)
        L.reachable = lambda alias: True
        L.ssh = lambda alias, cmd, **kw: sent.append(cmd) or ""
        L.submit = lambda alias, script: "4242"
        J.JOBS_FILE = os.path.join(tmp, "jobs.json")
        try:
            job = J.start(site, J.JobSpec(program="pfield", pes=4), log=lambda s: None)
            self.assertEqual(job.id, "4242")
            self.assertEqual(len(job.key), 32)
            cmd = sent[0]
            keyfile = cmd.split("touch ")[1].split("\n")[0]
            self.assertTrue(keyfile.startswith("/work/alloc/me/appspector/jobs/pfield-") and keyfile.endswith(".key"))
            self.assertIn("set -e\nmkdir -p /work/alloc/me/appspector/jobs\ntouch %s\nchmod 600 %s\ncat > %s <<'APPSPECTOR_EOF'\n0 %s\nAPPSPECTOR_EOF\ncat > /work/alloc/me/appspector/jobs/pfield-"
                          % (keyfile, keyfile, keyfile, job.key), cmd)
            self.assertIn("++server-auth %s\n" % keyfile, cmd)        # the batch script names the same file
            self.assertEqual(J.find_job("4242").key, job.key)          # the record keeps the key
            self.assertEqual(oct(os.stat(J.JOBS_FILE).st_mode & 0o777), "0o600")
            self.assertIn(", auth) submitted", job.label())
            # --no-auth: no key file, no key
            sent.clear()
            job2 = J.start(site, J.JobSpec(program="pfield", pes=4, auth=False), log=lambda s: None)
            self.assertEqual(job2.key, "")
            self.assertNotIn("chmod 600", sent[0])
            self.assertNotIn("++server-auth", sent[0])
        finally:
            L.reachable, L.ssh, L.submit, J.JOBS_FILE = saved

    def test_remote_write_command_through_bash(self):
        """The command the launcher sends over ssh, run by a real bash: both
        files land with the right contents (the 2026-10-26 bug put the batch
        script inside the key file)."""
        import subprocess
        work = tempfile.mkdtemp()
        script = "#!/bin/bash\n#SBATCH -J x\n./prog ++server-auth %s/jobs/k.key\n" % work
        cmd = J.remote_write_command(work, work + "/jobs/s.sbatch", script, work + "/jobs/k.key", "12" * 16)
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(work + "/jobs/k.key") as f:
            self.assertEqual(f.read(), "0 %s\n" % ("12" * 16))
        self.assertEqual(oct(os.stat(work + "/jobs/k.key").st_mode & 0o777), "0o600")
        with open(work + "/jobs/s.sbatch") as f:
            self.assertEqual(f.read(), script)
        # without a key: only the script
        cmd = J.remote_write_command(work, work + "/jobs/t.sbatch", script)
        self.assertEqual(subprocess.run(["bash", "-c", cmd]).returncode, 0)
        self.assertTrue(os.path.exists(work + "/jobs/t.sbatch"))
        # a failing step fails the whole command
        cmd = J.remote_write_command("/nonexistent-root/x", "/nonexistent-root/x/jobs/s", script)
        self.assertNotEqual(subprocess.run(["bash", "-c", cmd], capture_output=True).returncode, 0)

    def test_local_start_writes_key_file(self):
        tmp = tempfile.mkdtemp()
        prog = os.path.join(tmp, "prog")
        with open(prog, "w") as f:
            f.write("#!/bin/sh\nsleep 30\n")
        os.chmod(prog, 0o755)
        site = S.load_site("local")
        site.work = os.path.join(tmp, "runs")
        old = J.JOBS_FILE
        J.JOBS_FILE = os.path.join(tmp, "jobs.json")
        try:
            job = J.start(site, J.JobSpec(directory=tmp, command="./prog +pe {pes} ++server ++server-port {port}", pes=1),
                          log=lambda s: None)
            try:
                keyfiles = [f for f in os.listdir(site.work) if f.endswith(".key")]
                self.assertEqual(len(keyfiles), 1)
                kp = os.path.join(site.work, keyfiles[0])
                self.assertEqual(oct(os.stat(kp).st_mode & 0o777), "0o600")
                with open(kp) as f:
                    self.assertEqual(f.read(), "0 %s\n" % job.key)
                self.assertEqual(len(job.key), 32)
            finally:
                J.stop(site, job)
        finally:
            J.JOBS_FILE = old

    def test_jobs_lists_live_only_unless_all(self):
        from appspector.shell import Shell
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "cluster.ini")
        with open(path, "w") as f:
            f.write(SITE_INI)
        old = J.JOBS_FILE
        J.JOBS_FILE = os.path.join(tmp, "jobs.json")
        try:
            mk = lambda i, st: J.Job(id=i, site="cluster", program="pfield", args="", pes=4, port=1234, out="/o",
                                     submitted=float(i), state=st)
            J.save_jobs([mk("1", "completed"), mk("2", "cancelled"), mk("3", "completing"), mk("4", "up")])
            sh = Shell(path)
            out = []
            sh.say = out.append
            J_status = J.status
            J.status = lambda site, job: job.state           # no scheduler in a test
            try:
                sh.do_jobs("")
                self.assertEqual([l.split()[0] for l in out], ["3", "4"])
                del out[:]
                sh.do_jobs("all")
                self.assertEqual([l.split()[0] for l in out], ["1", "2", "3", "4"])
                del out[:]
                J.save_jobs([mk("1", "completed")])
                sh.do_jobs("")
                self.assertIn("no live jobs", out[0])
            finally:
                J.status = J_status
        finally:
            J.JOBS_FILE = old

    def test_view_passes_key(self):
        import subprocess
        from appspector.shell import Shell
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "cluster.ini")
        with open(path, "w") as f:
            f.write(SITE_INI)
        sh = Shell(path)
        sh.say = lambda text: None
        sh.current = J.Job(id="7", site="cluster", program="pfield", args="", pes=4, port=1234, out="/o",
                           submitted=1.0, state="up", node="cn1", key="12" * 16)
        calls = []
        saved = (J.connect, subprocess.Popen)
        J.connect = lambda site, job: ("127.0.0.1", 1234)
        subprocess.Popen = lambda cmdline, **kw: calls.append(cmdline) or type("P", (), {"wait": lambda self: 0})()
        try:
            sh.do_view("")
            self.assertEqual(calls[0][-2:], ["-k", "12" * 16])
            sh.do_view("-- --no-image -k 9999")
            self.assertEqual(calls[1][-3:], ["--no-image", "-k", "9999"])       # the user's key wins
            sh.current.key = ""
            sh.do_view("")
            self.assertNotIn("-k", calls[2])
        finally:
            J.connect, subprocess.Popen = saved


class RecordTests(unittest.TestCase):
    def test_records(self):
        tmp = tempfile.mkdtemp()
        old = J.JOBS_FILE
        J.JOBS_FILE = os.path.join(tmp, "jobs.json")
        try:
            j = J.Job(id="123", site="cluster", program="pfield", args="", pes=4, port=1234, out="/o", submitted=1.0)
            J.record(j)
            j.state = "up"
            j.node = "cn1"
            J.record(j)
            self.assertEqual(len(J.load_jobs()), 1)
            self.assertEqual(J.find_job("123").node, "cn1")
            self.assertIsNone(J.find_job("999"))
            self.assertIn("pfield on cluster (4 PEs, port 1234) up", J.find_job("123").label())
        finally:
            J.JOBS_FILE = old


if __name__ == "__main__":
    unittest.main()
