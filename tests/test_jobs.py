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
        self.assertEqual(c, "./pfield  +pe 4 ++server ++server-port 1234 +balancer GreedyRefineLB")
        self.assertEqual((v["nodes"], v["procs"], v["cores_per_proc"]), (1, 2, 2))      # 4 PEs over 2 procs
        d, c, v = J.JobSpec(program="pfield", args="-k 16 -n 400", pes=32, nodes=2, procs_per_node=4, port=2000).resolve(self.site)
        self.assertEqual(c, "./pfield -k 16 -n 400 +pe 32 ++server ++server-port 2000 +balancer GreedyRefineLB")
        self.assertEqual((v["nodes"], v["procs"], v["cores_per_proc"]), (2, 8, 4))      # 32 PEs over 8 procs
        with self.assertRaises(KeyError):
            J.JobSpec(program="nope").resolve(self.site)
        with self.assertRaises(ValueError):            # 4 PEs over 12 processes
            J.JobSpec(program="pfield", pes=4, nodes=4, procs_per_node=3).resolve(self.site)
        d, c, v = J.JobSpec(directory="/x", command="./mine +pe {pes} ++server ++server-port {port}", pes=3).resolve(self.site)
        self.assertEqual((d, c), ("/x", "./mine +pe 3 ++server ++server-port 1234"))

    def test_render_batch(self):
        script, out, v = J.render_batch(self.site, J.JobSpec(program="pfield", pes=16, nodes=2, procs_per_node=2))
        self.assertIn("#SBATCH -A alloc-cpu", script)
        self.assertIn("#SBATCH -p interactive", script)
        self.assertIn("#SBATCH -N 2", script)
        self.assertIn("#SBATCH --ntasks=4", script)
        self.assertIn("#SBATCH --cpus-per-task=4", script)      # 16 PEs over 4 procs
        self.assertIn("#SBATCH -o /work/alloc/me/appspector/jobs/pfield-%j.out", script)
        self.assertIn("source /work/alloc/me/appspector/env.sh", script)
        self.assertIn("cd /work/alloc/me/appSpector/apps/pfield", script)
        self.assertIn("stdbuf -o0 -e0 srun --mpi=pmix -n 4 -c 4 ./pfield  +pe 16 ++server ++server-port 1234 +balancer GreedyRefineLB", script)
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
        d, c, v = J.JobSpec(program="mine", args="-x", pes=2).resolve(again)
        self.assertEqual((d, c), ("/work/alloc/me/appspector/mine", "./mine -x +pe 2 ++server ++server-port 1234"))
        from appspector.shell import Shell
        sh = Shell(path)
        sh.say = lambda text: None
        sh.do_program("/home/me/prog/leanmd -s 10")
        d, c, v = sh.spec.resolve(sh.site)
        self.assertEqual((d, c), ("/home/me/prog", "./leanmd -s 10 +pe 4 ++server ++server-port 1234"))


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
