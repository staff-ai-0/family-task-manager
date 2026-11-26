"""The on-prem stack's systemd unit: its wait for DNS before `compose up`.

No database: the unit file is read from the repo checkout. Skipped where only
`backend/` is present (the dev container mounts just that directory).
"""
import re
from pathlib import Path

import pytest

UNIT = Path(__file__).resolve().parents[2] / "scripts/systemd/family-task-manager.service"

pytestmark = pytest.mark.skipif(not UNIT.exists(), reason="needs the repo checkout, not only backend/")


def _exec_start_pre() -> str:
    lines = [ln for ln in UNIT.read_text().splitlines() if ln.startswith("ExecStartPre=")]
    assert len(lines) == 1, lines
    return lines[0]


def test_dns_wait_probes_a_name_that_has_address_records():
    """`getent hosts` only answers for a name with A/AAAA records. The bare apex
    `argotunnel.com` has none (cloudflared finds the edge through an SRV record
    and the region hosts), so probing it can never succeed: on the 2026-11-25
    reboot every start burned the full wait before `compose up`. The region
    hosts are the ones cloudflared dials, and they do resolve."""
    probed = re.findall(r"getent hosts (\S+)", _exec_start_pre())
    assert probed, "the unit no longer waits for DNS"
    assert "argotunnel.com" not in probed
    for name in probed:
        assert re.fullmatch(r"region[12]\.v2\.argotunnel\.com", name), name


def test_dns_wait_is_bounded_and_never_fails_the_unit():
    """A resolver that never comes up must not keep the stack down: the loop is
    finite and its last word is `exit 0` (ensure-tunnel-onprem.sh, run after
    `compose up`, starts the tunnel again if it exited)."""
    pre = _exec_start_pre()
    tries = re.search(r"seq (\d+)", pre)
    pause = re.search(r"sleep (\d+)", pre)
    assert tries and pause, pre
    assert 0 < int(tries.group(1)) * int(pause.group(1)) <= 180
    assert pre.rstrip().endswith("exit 0'")
