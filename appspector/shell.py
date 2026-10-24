"""The appSpector command shell: fire a job, see that it is up, open the
viewer. Interaction with the running program (clicks, Balance, the load
views) lives in the viewer window, not here.

    python3 -m appspector                 # interactive
    python3 -m appspector run --site delta --program pfield --pes 16 --args "-k 16"
    python3 -m appspector view 23143979   # one-shot forms of the same commands

Shell commands:
    sites | site NAME | site fetch NAME [SSH:PATH]     choose or import a site
    programs | program NAME [ARGS...]                   what to run (free text after the name is its arguments)
    pes N | nodes N | ppn N | walltime HH:MM:SS | port N
    show                                                the spec as it stands
    run                                                 submit; the shell says when the job is up
    jobs | status [ID] | log [ID] | attach ID | stop [ID]
    view [ID]                                           open the viewer window on the job
    quit
"""

import argparse
import cmd
import shlex
import subprocess
import sys
import threading

from . import jobs as J
from . import launch as L
from . import sites as S


class Shell(cmd.Cmd):
    prompt = "appspector> "
    intro = "appSpector shell. 'help' lists commands; 'site delta' then 'program pfield', 'pes 16', 'run', 'view'."

    def __init__(self, site="local"):
        super().__init__()
        self.site = S.load_site(site)
        self.spec = J.JobSpec()
        self.current = None          # Job
        self.viewers = []
        self._waiters = []

    # -- helpers --------------------------------------------------------------
    def say(self, text):
        print(text)

    def _job(self, arg):
        job = J.find_job(arg.strip()) if arg.strip() else self.current
        if job is None:
            self.say("no job (give an id, see 'jobs')")
        return job

    def _site_of(self, job):
        return self.site if job.site == self.site.name else S.load_site(job.site)

    # -- site and spec ----------------------------------------------------------
    def do_sites(self, arg):
        """sites: list known sites."""
        for name, path in S.site_files().items():
            mark = "*" if name == self.site.name else " "
            self.say("%s %-10s %s" % (mark, name, path))

    def do_site(self, arg):
        """site NAME | site fetch NAME SSH:REMOTE_PATH: select a site, or copy a site file written by a cluster's setup script."""
        words = arg.split()
        if not words:
            self.say("site %s (%s), scheduler %s, work %s" % (self.site.name, self.site.path, self.site.scheduler, self.site.work))
            return
        if words[0] == "fetch":
            if len(words) < 3:
                self.say("usage: site fetch NAME SSH_ALIAS:/path/to/site.ini")
                return
            name, src = words[1], words[2]
            alias, _, path = src.partition(":")
            try:
                text = L.ssh(alias, "cat %s" % path)
            except L.LaunchError as e:
                self.say(str(e))
                return
            dest = S.save_site_text(name, text)
            self.say("saved %s" % dest)
            words = [name]
        try:
            self.site = S.load_site(words[0])
            self.spec = J.JobSpec()
            self.say("site %s: scheduler %s, programs: %s" % (self.site.name, self.site.scheduler, ", ".join(sorted(self.site.programs)) or "none"))
        except (KeyError, ValueError) as e:
            self.say(str(e))

    def do_programs(self, arg):
        """programs: the site's programs and their command lines."""
        for p in self.site.programs.values():
            self.say("%-14s %s\n%15s %s" % (p.name, p.directory, "", p.command))

    def do_program(self, arg):
        """program NAME [ARGS...]: what to run; everything after the name is passed as the program's arguments."""
        words = arg.split(None, 1)
        if not words:
            self.say("program %s %s" % (self.spec.program, self.spec.args))
            return
        if words[0] not in self.site.programs:
            self.say("unknown program %s (known: %s). For an arbitrary command use 'command DIR | CMD'." % (words[0], ", ".join(sorted(self.site.programs))))
            return
        self.spec.program = words[0]
        self.spec.args = words[1] if len(words) > 1 else ""
        self.spec.directory = self.spec.command = ""
        self.do_show("")

    def do_command(self, arg):
        """command DIRECTORY | COMMAND LINE: run an arbitrary program ({pes} {port} are filled in)."""
        if "|" not in arg:
            self.say("usage: command /path/to/dir | ./prog {args} +pe {pes} ++server ++server-port {port}")
            return
        d, c = arg.split("|", 1)
        self.spec.program = ""
        self.spec.directory, self.spec.command = d.strip(), c.strip()
        self.do_show("")

    def _set_int(self, attr, arg, what):
        try:
            setattr(self.spec, attr, int(arg))
        except ValueError:
            self.say("%s needs an integer" % what)
            return
        self.do_show("")

    def do_pes(self, arg):
        """pes N: total PEs."""
        self._set_int("pes", arg, "pes")

    def do_nodes(self, arg):
        """nodes N: nodes (slurm sites)."""
        self._set_int("nodes", arg, "nodes")

    def do_ppn(self, arg):
        """ppn N: processes per node (slurm sites)."""
        self._set_int("procs_per_node", arg, "ppn")

    def do_port(self, arg):
        """port N: the job's CCS port."""
        self._set_int("port", arg, "port")

    def do_walltime(self, arg):
        """walltime HH:MM:SS."""
        self.spec.walltime = arg.strip()
        self.do_show("")

    def do_show(self, arg):
        """show: the job spec with the site's defaults filled in."""
        try:
            directory, command, v = self.spec.resolve(self.site)
        except KeyError as e:
            self.say("spec incomplete: %s" % e)
            return
        self.say("site %s: %s PEs, %d node(s) x %d proc(s), port %d, walltime %s\n  cd %s\n  %s"
                 % (self.site.name, v["pes"], v["nodes"], v["procs"] // v["nodes"], v["port"], v["walltime"], directory, command))

    def do_script(self, arg):
        """script: print the batch script the current spec would submit (slurm sites)."""
        if self.site.scheduler == "local":
            self.say("local site: no batch script, the command runs directly")
            return
        try:
            self.say(J.render_batch(self.site, self.spec)[0])
        except KeyError as e:
            self.say(str(e))

    # -- jobs ---------------------------------------------------------------
    def do_run(self, arg):
        """run: submit or start the job; a background wait reports when its CCS server is up."""
        try:
            job = J.start(self.site, self.spec, log=self.say)
        except (L.LaunchError, KeyError, OSError) as e:
            self.say("run failed: %s" % e)
            return
        self.current = job
        if self.site.scheduler == "local":
            self.say("waiting for its CCS server; a line appears here when it is up, then 'view' opens the viewer.")
        else:
            self.say("queued on %s. A line appears here when the job starts and its CCS server answers\n"
                     "(queue waits range from seconds to hours); 'status' shows the queue state meanwhile,\n"
                     "'log' the job output, and 'view' opens the viewer once it is up. 'quit' keeps the job running;\n"
                     "come back with 'attach %s'." % (self.site.name, job.id))
        self._wait_in_background(job)

    def _wait_in_background(self, job):
        site = self._site_of(job)

        def waiter():
            try:
                J.wait_until_up(site, job, log=lambda s: None)
                self.say("\n*** job %s is up on %s, port %d. Type 'view' to open the viewer. ***\n%s" % (job.id, job.node, job.port, self.prompt))
            except L.LaunchError as e:
                self.say("\n[job %s: %s]\n%s" % (job.id, e, self.prompt))
        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        self._waiters.append(t)

    def do_jobs(self, arg):
        """jobs: recorded jobs, newest last."""
        for j in J.load_jobs()[-15:]:
            mark = "*" if self.current and j.id == self.current.id else " "
            self.say("%s %s" % (mark, j.label()))

    def do_status(self, arg):
        """status [ID]: refresh and show a job's state."""
        job = self._job(arg)
        if job:
            try:
                J.status(self._site_of(job), job)
            except L.LaunchError as e:
                self.say(str(e))
            self.say(job.label() + (" on " + job.node if job.node else ""))

    def do_log(self, arg):
        """log [ID]: last lines of the job's output."""
        job = self._job(arg)
        if job:
            self.say(J.log_tail(self._site_of(job), job))

    def do_attach(self, arg):
        """attach ID: make a recorded job current (and wait for it if it is not up yet)."""
        job = J.find_job(arg.strip())
        if job is None:
            self.say("no recorded job %s; 'jobs' lists them" % arg.strip())
            return
        self.current = job
        if job.site != self.site.name:
            self.site = S.load_site(job.site)
        if job.state != "up":
            self._wait_in_background(job)
        else:
            self.say("attached to " + job.label())

    def do_view(self, arg):
        """view [ID]: open the viewer window on the job (registers the port forward first)."""
        job = self._job(arg)
        if job is None:
            return
        site = self._site_of(job)
        if job.state != "up":
            self.say("job %s is %s, not up yet" % (job.id, job.state))
            return
        try:
            host, port = J.connect(site, job)
        except L.LaunchError as e:
            self.say(str(e))
            return
        cmdline = [sys.executable, "-m", "appspector.viewer", host, str(port)]
        self.say("viewer on %s:%d (close its window to come back; the job keeps running)" % (host, port))
        p = subprocess.Popen(cmdline)
        self.viewers.append(p)

    def do_stop(self, arg):
        """stop [ID]: cancel the job and its forward."""
        job = self._job(arg)
        if job:
            J.stop(self._site_of(job), job)
            self.say("stopped " + job.label())

    def do_quit(self, arg):
        """quit: leave the shell; running jobs keep running (stop them with 'stop')."""
        return True

    do_exit = do_EOF = do_quit

    def emptyline(self):
        pass


def one_shot(argv):
    """Non-interactive forms: run, view, status, stop, jobs, sites."""
    ap = argparse.ArgumentParser(prog="python3 -m appspector", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["run", "view", "status", "stop", "jobs", "sites", "script"])
    ap.add_argument("job", nargs="?", help="job id for view/status/stop")
    ap.add_argument("--site", default="local")
    ap.add_argument("--program")
    ap.add_argument("--args", default="")
    ap.add_argument("--pes", type=int, default=0)
    ap.add_argument("--nodes", type=int, default=0)
    ap.add_argument("--ppn", type=int, default=0)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--walltime", default="")
    ap.add_argument("--wait", type=int, default=21600, help="seconds to wait for the server (run)")
    ap.add_argument("--no-view", action="store_true", help="run: do not open the viewer once the job is up")
    a = ap.parse_args(argv)
    sh = Shell(a.site)
    if a.action == "sites":
        sh.do_sites("")
        return 0
    if a.action == "jobs":
        sh.do_jobs("")
        return 0
    if a.action in ("view", "status", "stop"):
        if not a.job:
            ap.error("%s needs a job id" % a.action)
        getattr(sh, "do_" + a.action)(a.job)
        for p in sh.viewers:
            p.wait()
        return 0
    if not a.program:
        ap.error("run/script need --program")
    sh.spec = J.JobSpec(program=a.program, args=a.args, pes=a.pes, nodes=a.nodes, procs_per_node=a.ppn,
                        port=a.port, walltime=a.walltime)
    if a.action == "script":
        sh.do_script("")
        return 0
    try:
        job = J.start(sh.site, sh.spec)
        J.wait_until_up(sh.site, job, wait_secs=a.wait)
        print("job %s is up on %s port %d" % (job.id, job.node, job.port))
        if not a.no_view:
            sh.current = job
            sh.do_view("")
            for p in sh.viewers:
                p.wait()
    except (L.LaunchError, KeyError) as e:
        print("appspector: %s" % e, file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        return one_shot(argv)
    Shell().cmdloop()
    return 0
