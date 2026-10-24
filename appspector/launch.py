"""Launch a Charm++ job on a Slurm cluster from the laptop and watch it.

    python -m appspector.launch run   --site delta --sbatch /remote/wave2d.sbatch [--port 1234]
                                      [--viewer | --check] [--key KEY] [--wait 900]
    python -m appspector.launch attach --site delta --job JOBID --out /remote/wave2d-JOBID.out
    python -m appspector.launch watch --site delta --out /remote/file.out
    python -m appspector.launch stop  --site delta [--job JOBID]

The site is an ssh alias with an open control master (the human has done
the Duo login once; see charm-notes machines/delta.md). Everything else
is non-interactive: sbatch over ssh, poll the job output for the
"ccs: Server IP = ..., Server port = N" line, register a port forward in
the ssh master (ssh -O forward, removed again with ssh -O cancel), then
start the viewer (default) or just run a CCS self-check (--check). On
exit the forward is cancelled and the job is cancelled unless --keep.

This is the Python version of ~/software/recharm/lv-delta.sh.
"""

import argparse
import os
import re
import subprocess
import sys
import time

from ccsio import Server, CcsError, parse_server_line

FWD_FILE = os.path.expanduser("~/.appspector-forward")
MAX_CONSECUTIVE_FAILURES = 40      # 20 minutes of a dead controller before giving up


class LaunchError(Exception):
    pass


def ssh(site, cmd, check=True, timeout=120):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", site, cmd], capture_output=True,
                       text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise LaunchError("ssh %s '%s' failed (%d): %s" % (site, cmd, r.returncode,
                                                         r.stderr.strip()[-300:]))
    return r.stdout


def master_open(site):
    r = subprocess.run(["ssh", "-O", "check", site], capture_output=True, text=True)
    return r.returncode == 0


def forward_add(site, local_port, node, remote_port):
    spec = "%d:%s:%d" % (local_port, node, remote_port)
    forward_cancel(site)
    r = subprocess.run(["ssh", "-O", "forward", "-L", spec, site], capture_output=True, text=True)
    if r.returncode != 0:
        raise LaunchError("port forward %s failed: %s" % (spec, r.stderr.strip()))
    with open(FWD_FILE, "w") as f:
        f.write(spec)
    return spec


def forward_cancel(site):
    if not os.path.exists(FWD_FILE):
        return
    with open(FWD_FILE) as f:
        spec = f.read().strip()
    subprocess.run(["ssh", "-O", "cancel", "-L", spec, site], capture_output=True, text=True)
    os.unlink(FWD_FILE)


def submit(site, sbatch):
    out = ssh(site, "sbatch --parsable %s" % sbatch).strip()
    job = out.split(";")[0]
    if not job.isdigit():
        raise LaunchError("sbatch returned %r" % out)
    return job


def wait_for_server(site, job, out_path, wait_secs, log=print):
    """Poll until the job output has the CCS line; returns (ip, port, node)."""
    t0 = time.time()
    failures = 0
    while time.time() - t0 < wait_secs:
        try:
            text = ssh(site, "cat %s 2>/dev/null; echo '@@STATE'; squeue -j %s -h -o '%%T %%N'" % (out_path, job))
            failures = 0
        except LaunchError as e:
            # ssh or Slurm failed (master gone, login node down, controller
            # timing out): keep trying for a while instead of mistaking the
            # empty answer for a finished job
            failures += 1
            log("  %4ds  unreachable (%d): %s" % (time.time() - t0, failures, str(e).splitlines()[-1][-120:]))
            if failures >= MAX_CONSECUTIVE_FAILURES:
                raise LaunchError("cannot reach %s while waiting for job %s (ssh master open? Slurm up?): %s"
                                  % (site, job, e))
            time.sleep(30)
            continue
        body, _, state = text.partition("@@STATE")
        state = state.strip()
        try:
            ip, port = parse_server_line(body)
            node = state.split()[-1] if state else ip
            return ip, port, node
        except ValueError:
            pass
        if not state or state.split()[0] in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
            raise LaunchError("job %s ended before the server came up; output:\n%s" % (job, body[-2000:]))
        log("  %4ds  %s" % (time.time() - t0, state))
        time.sleep(10)
    raise LaunchError("timed out after %d s waiting for the server line" % wait_secs)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m appspector.launch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["run", "attach", "watch", "stop"])
    ap.add_argument("--site", default="delta", help="ssh alias with an open control master")
    ap.add_argument("--sbatch", help="remote path of the batch script (run)")
    ap.add_argument("--out", help="remote path of the job output; default: the sbatch's -o with %%j filled in")
    ap.add_argument("--job", help="job id (attach, stop)")
    ap.add_argument("--port", type=int, default=1234, help="the job's ++server-port; same port locally")
    ap.add_argument("--local-port", type=int, help="local port if different")
    ap.add_argument("--key", help="++server-auth key string")
    ap.add_argument("--wait", type=int, default=900, help="seconds to wait for the server line")
    ap.add_argument("--check", action="store_true", help="no viewer: connect, print the PE layout, exit")
    ap.add_argument("--keep", action="store_true", help="leave the job running on exit")
    ap.add_argument("--viewer-args", default="", help="extra arguments for appspector.viewer")
    a = ap.parse_args(argv)
    local_port = a.local_port or a.port

    if not master_open(a.site):
        print("no ssh control master for '%s': open one in a terminal with `ssh %s` (Duo), then retry"
              % (a.site, a.site), file=sys.stderr)
        return 2

    if a.action == "watch":
        if not a.out:
            a.out = ssh(a.site, "ls -t %s/*.out | head -1" % os.path.dirname(a.sbatch or "~")).strip()
        os.execvp("ssh", ["ssh", a.site, "tail -n +1 -f %s" % a.out])

    if a.action == "stop":
        forward_cancel(a.site)
        if a.job:
            ssh(a.site, "scancel %s" % a.job, check=False)
        print(ssh(a.site, "squeue -u $USER -h", check=False) or "no jobs queued")
        return 0

    job = a.job
    out_path = a.out
    if a.action == "run":
        if not a.sbatch:
            ap.error("run needs --sbatch")
        if not out_path:
            script = ssh(a.site, "cat %s" % a.sbatch)
            m = re.search(r"#SBATCH\s+(?:-o|--output)[=\s]+(\S+)", script)
            if not m:
                ap.error("cannot find #SBATCH -o in the script; pass --out")
            out_path = m.group(1)
        job = submit(a.site, a.sbatch)
        out_path = out_path.replace("%j", job)
        print("submitted job %s; output %s" % (job, out_path))
    elif not (job and out_path):
        ap.error("attach needs --job and --out")

    try:
        ip, port, node = wait_for_server(a.site, job, out_path, a.wait)
        print("server up on %s (%s), port %d" % (node, ip, port))
        spec = forward_add(a.site, local_port, node, port)
        print("forward %s registered in the ssh master" % spec)
        if a.check:
            s = Server("127.0.0.1", local_port, key=a.key, timeout=30)
            print("CCS self-check: %d node(s), %d PE(s): %s" % (s.num_nodes, s.num_pes, s.node_sizes))
            return 0
        from appspector import viewer
        args = ["127.0.0.1", str(local_port)] + (["-k", a.key] if a.key else []) + a.viewer_args.split()
        viewer.main(args)
        return 0
    except (LaunchError, CcsError) as e:
        print("appspector: %s" % e, file=sys.stderr)
        return 1
    finally:
        forward_cancel(a.site)
        if job and not a.keep:
            ssh(a.site, "scancel %s" % job, check=False)
            print("job %s cancelled" % job)
        elif job:
            print("job %s left running; stop it with: python -m appspector.launch stop --site %s --job %s"
                  % (job, a.site, job))


if __name__ == "__main__":
    sys.exit(main())
