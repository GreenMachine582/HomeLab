# callback_plugins/run_notify.py
#
# One Discord message per playbook run: the playbook, its hosts, the totals,
# how long it took, and who ran it. The nodes do not post login alerts for
# Ansible from the controller (roles/base_hardening on-ssh-success), so this
# is the record that a run happened.
#
# The webhook URL is read from ~/.config/homelab/run-notify.webhook, which
# playbooks/controller.yml writes. Without that file nothing is posted, and a
# failed post only prints a warning: it never fails the run. A run stopped
# with Ctrl-C posts nothing (Ansible skips the stats callback).
from __future__ import annotations

DOCUMENTATION = """
    name: run_notify
    type: notification
    short_description: Post one Discord message per playbook run
    description:
      - Posts the playbook, hosts, totals, duration and user to a Discord webhook when a run ends.
    requirements:
      - The webhook URL in ~/.config/homelab/run-notify.webhook (playbooks/controller.yml writes it).
"""

import getpass
import json
import os
import socket
import time
import urllib.request

from ansible import context
from ansible.plugins.callback import CallbackBase

WEBHOOK_FILE = os.path.expanduser(
    os.environ.get("HOMELAB_RUN_NOTIFY_WEBHOOK_FILE", "~/.config/homelab/run-notify.webhook")
)


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "run_notify"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self) -> None:
        super().__init__()
        self._playbook = "ad-hoc"
        self._start = time.monotonic()

    def v2_playbook_on_start(self, playbook) -> None:
        self._playbook = os.path.basename(playbook._file_name)
        self._start = time.monotonic()

    def v2_playbook_on_stats(self, stats) -> None:
        try:
            with open(WEBHOOK_FILE, encoding="utf-8") as f:
                url = f.read().strip()
        except OSError:
            return
        if not url:
            return

        hosts = sorted(stats.processed)
        totals = {"ok": 0, "changed": 0, "failures": 0, "unreachable": 0}
        failed, unreachable = [], []
        for host in hosts:
            s = stats.summarize(host)
            for key in totals:
                totals[key] += s.get(key, 0)
            if s.get("failures"):
                failed.append(host)
            if s.get("unreachable"):
                unreachable.append(host)

        icon = "❌" if failed or unreachable else "🤖"
        head = f"{icon} [Ansible] {self._playbook} on {', '.join(hosts) or 'no hosts'}:"
        parts = [f"ok {totals['ok']}", f"changed {totals['changed']}"]
        if failed:
            parts.append(f"failed on {', '.join(failed)}")
        if unreachable:
            parts.append(f"unreachable: {', '.join(unreachable)}")

        args = context.CLIARGS
        extras = []
        if args.get("check"):
            extras.append("check mode")
        if args.get("subset"):
            extras.append(f"limit {args['subset']}")
        tags = [t for t in (args.get("tags") or ()) if t != "all"]
        if tags:
            extras.append(f"tags {','.join(tags)}")
        extras.append(_duration(time.monotonic() - self._start))
        extras.append(f"{getpass.getuser()}@{socket.gethostname()}")

        content = f"{head} {', '.join(parts)} ({', '.join(extras)})"[:1900]
        request = urllib.request.Request(
            url,
            data=json.dumps({"content": content}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "homelab-run-notify"},
        )
        try:
            urllib.request.urlopen(request, timeout=10).close()
        except Exception as e:  # noqa: BLE001 - a notification never fails the run
            self._display.warning(f"run_notify: could not post the run summary: {e}")
