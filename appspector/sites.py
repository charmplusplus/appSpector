"""Site descriptions: where and how appSpector runs programs.

A site is an INI file. The built-in ``local`` site (appspector/sites/local.ini)
runs programs on this machine; cluster sites live in ~/.appspector/sites/
and are usually written by that cluster's setup script (delta/setup-delta.sh
writes one) and fetched with ``site fetch``.

    [site]
    scheduler = slurm | local
    ssh = delta                         ; ssh alias with an open control master (slurm)
    work = /work/hdd/ALLOC/USER/appspector   ; remote work dir: env.sh, jobs/, outputs
    appspector = /work/hdd/ALLOC/USER/appSpector  ; the repository checkout there
    env = {work}/env.sh                 ; sourced by every batch script
    account = ALLOC-delta-cpu
    partition = cpu-interactive
    cores_per_node = 128
    default_nodes = 1
    default_procs_per_node = 2
    default_pes = 4
    walltime = 00:10:00
    mem = 16g
    launcher = stdbuf -o0 -e0 srun --mpi=pmix -n {procs} -c {cores_per_proc}
    port = 1234

    [programs]
    name = directory | command line [| viewer options]   ; {args} {pes} {port} are filled in

Values may use {work}, {appspector}, {home} and, in commands, {args},
{pes}, {port}, {procs}, {cores_per_proc}.
"""

import configparser
import os
from dataclasses import dataclass, field
from typing import Dict, List

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sites")
USER_DIR = os.path.expanduser("~/.appspector/sites")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class Program:
    name: str
    directory: str
    command: str          # with {args} {pes} {port} ... placeholders
    viewer_args: str = "" # extra appspector.viewer options, e.g. --inject myHandler --no-image


@dataclass
class Site:
    name: str
    scheduler: str = "local"
    ssh: str = ""
    work: str = ""
    appspector: str = REPO_ROOT
    env: str = "{work}/env.sh"
    account: str = ""
    partition: str = ""
    cores_per_node: int = 8
    default_nodes: int = 1
    default_procs_per_node: int = 1
    default_pes: int = 4
    walltime: str = "00:10:00"
    mem: str = "16g"
    launcher: str = "srun -n {procs} -c {cores_per_proc}"
    port: int = 1234
    programs: Dict[str, Program] = field(default_factory=dict)
    path: str = ""

    def vars(self):
        return {"work": self.work, "appspector": self.appspector, "home": os.path.expanduser("~")}

    def expand(self, text, **extra):
        v = dict(self.vars())
        v.update(extra)
        # two passes so {work} inside env etc. resolves
        for _ in range(2):
            text = text.format_map(_Safe(v))
        return text


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def site_files():
    """{name: path} of every site file, user files winning over built-ins."""
    found = {}
    for d in (BUILTIN_DIR, USER_DIR):
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".ini"):
                    found[f[:-4]] = os.path.join(d, f)
    return found


def load_site(name_or_path):
    path = name_or_path if name_or_path.endswith(".ini") and os.path.exists(name_or_path) else site_files().get(name_or_path)
    if path is None:
        raise KeyError("no site '%s' (known: %s)" % (name_or_path, ", ".join(sorted(site_files())) or "none"))
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path)
    s = Site(name=os.path.basename(path)[:-4], path=path)
    sec = cp["site"] if cp.has_section("site") else {}
    for key in ("scheduler", "ssh", "work", "appspector", "env", "account", "partition", "walltime", "mem", "launcher"):
        if key in sec:
            setattr(s, key, sec[key])
    for key in ("cores_per_node", "default_nodes", "default_procs_per_node", "default_pes", "port"):
        if key in sec:
            setattr(s, key, int(sec[key]))
    if not s.work:
        s.work = "{appspector}/runs" if s.scheduler == "local" else ""
    s.appspector = s.expand(s.appspector)
    s.work = s.expand(s.work)
    s.env = s.expand(s.env)
    if cp.has_section("programs"):
        for name, spec in cp["programs"].items():
            if "|" not in spec:
                raise ValueError("%s: program %s needs 'directory | command'" % (path, name))
            parts = [x.strip() for x in spec.split("|")]
            s.programs[name] = Program(name, s.expand(parts[0]), parts[1], parts[2] if len(parts) > 2 else "")
    return s


def save_site_text(name, text):
    """Write a site file into the user directory; returns its path."""
    os.makedirs(USER_DIR, exist_ok=True)
    path = os.path.join(USER_DIR, name + ".ini")
    with open(path, "w") as f:
        f.write(text)
    return path


def add_program(site, name, directory, command, viewer_args=""):
    """Append a program to the site's file, copying a built-in site file into
    the user directory first so built-ins stay pristine. Returns the path."""
    path = site.path
    if path.startswith(BUILTIN_DIR):
        with open(path) as f:
            path = save_site_text(site.name, f.read())
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path)
    if not cp.has_section("programs"):
        cp.add_section("programs")
    cp["programs"][name] = "%s | %s" % (directory, command) + (" | " + viewer_args if viewer_args else "")
    with open(path, "w") as f:
        cp.write(f)
    site.programs[name] = Program(name, site.expand(directory), command, viewer_args)
    site.path = path
    return path


DEFAULT_COMMAND = "./{exe} {args} +pe {pes} ++server ++server-port {port}"
