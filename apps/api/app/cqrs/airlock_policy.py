"""Per-account Airlock policy: thresholds, muted rules, egress allowlist.

The policy is what turns a fixed scanner into one a customer can tune
without forking it: a legal team whose contracts trip `authority_spoof`
mutes that rule for their account; a pipeline that would rather see more
flags lowers `flag_threshold`; an agent that only ever calls three hosts
puts them in the standing allowlist instead of on every egress call.

Two rules the module holds to:

- Absence is the default. No row means the defaults in `DEFAULT_POLICY`,
  which are exactly the constants the scanner used before policies
  existed. Reading a policy never writes one.
- It is read in the same query as the key (cqrs/airlock_billing.py joins
  this table into resolve_api_key), so a keyed scan pays no extra round
  trip for it. `policy_from_row` is the shared constructor for both paths.
"""

import re
import time
from dataclasses import dataclass, field

from ..airlock.rules import RULES_BY_ID
from ..database import Database

# The engine's own defaults (airlock/detector.py Detector.scan and
# airlock/semantic.py). Named once here so the policy layer and the
# scanner cannot disagree about what "unset" means.
DEFAULT_BLOCK_THRESHOLD = 0.75
DEFAULT_FLAG_THRESHOLD = 0.40

MAX_MUTED_RULES = 64
MAX_ALLOWLIST_HOSTS = 100

# A hostname or a suffix of one ("example.com", "api.example.com",
# ".internal"). Same family as EgressIn.allowlist, validated here so a
# bad entry is refused at PUT time rather than silently never matching.
_HOST = re.compile(r"^\.?[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*$")


class InvalidPolicy(ValueError):
    """The requested policy breaks an invariant; the message says which."""


@dataclass(frozen=True)
class Policy:
    block_threshold: float = DEFAULT_BLOCK_THRESHOLD
    flag_threshold: float = DEFAULT_FLAG_THRESHOLD
    muted_rules: tuple[str, ...] = ()
    egress_allowlist: tuple[str, ...] = ()
    # None when the account has never set anything (the defaults apply).
    updated_at: int | None = None

    @property
    def is_default(self) -> bool:
        return self.updated_at is None


DEFAULT_POLICY = Policy()


def policy_from_row(row: dict | None) -> Policy:
    """A `Policy` from a row of airlock_policies -- or from a row of a LEFT
    JOIN where the policy columns are NULL, or from no row at all. All
    three mean the same thing to the scanner."""
    if not row or row.get("block_threshold") is None:
        return DEFAULT_POLICY
    return Policy(
        block_threshold=float(row["block_threshold"]),
        flag_threshold=float(row["flag_threshold"]),
        muted_rules=tuple(row.get("muted_rules") or ()),
        egress_allowlist=tuple(row.get("egress_allowlist") or ()),
        updated_at=int(row["updated_at"]) if row.get("updated_at") is not None else None,
    )


POLICY_COLUMNS = "block_threshold, flag_threshold, muted_rules, egress_allowlist, updated_at"


async def handle_policy_query(database: Database, user_id: str) -> Policy:
    row = await database.fetch_one(
        f"SELECT {POLICY_COLUMNS} FROM airlock_policies WHERE user_id=%s", (user_id,)
    )
    return policy_from_row(row)


@dataclass(frozen=True)
class SetPolicyCommand:
    user_id: str
    block_threshold: float = DEFAULT_BLOCK_THRESHOLD
    flag_threshold: float = DEFAULT_FLAG_THRESHOLD
    muted_rules: list[str] = field(default_factory=list)
    egress_allowlist: list[str] = field(default_factory=list)


def _validate(command: SetPolicyCommand) -> tuple[list[str], list[str]]:
    """Returns the normalised (muted_rules, egress_allowlist) or raises
    InvalidPolicy. The database CHECKs repeat the threshold rules; the
    rule-id and hostname checks can only live here, because the rule list
    is code, not data."""
    if not 0 < command.block_threshold <= 1:
        raise InvalidPolicy("block_threshold must be in (0, 1]")
    if not 0 < command.flag_threshold <= command.block_threshold:
        raise InvalidPolicy("flag_threshold must be in (0, block_threshold]")

    muted = sorted({rule_id.strip().upper() for rule_id in command.muted_rules if rule_id.strip()})
    if len(muted) > MAX_MUTED_RULES:
        raise InvalidPolicy(f"At most {MAX_MUTED_RULES} muted rules")
    unknown = [rule_id for rule_id in muted if rule_id not in RULES_BY_ID]
    if unknown:
        raise InvalidPolicy(f"Unknown rule id(s): {', '.join(unknown)}")
    # Muting everything is a policy of "never block", which is a decision
    # the dashboard should not make quietly. It is allowed -- the account
    # owns its verdicts -- but a muted list can never exceed the rule set.

    hosts = sorted({host.strip().lower() for host in command.egress_allowlist if host.strip()})
    if len(hosts) > MAX_ALLOWLIST_HOSTS:
        raise InvalidPolicy(f"At most {MAX_ALLOWLIST_HOSTS} allowlisted hosts")
    bad = [host for host in hosts if len(host) > 253 or not _HOST.match(host)]
    if bad:
        raise InvalidPolicy(f"Not a hostname: {', '.join(bad[:3])}")
    return muted, hosts


async def handle_set_policy(database: Database, command: SetPolicyCommand) -> Policy:
    """Upsert; the whole policy is replaced, never patched, so what the
    dashboard shows after saving is exactly what it sent."""
    muted, hosts = _validate(command)
    now = int(time.time() * 1000)
    row = await database.fetch_one(
        f"""INSERT INTO airlock_policies (user_id, block_threshold, flag_threshold, muted_rules, egress_allowlist, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
              block_threshold = EXCLUDED.block_threshold,
              flag_threshold = EXCLUDED.flag_threshold,
              muted_rules = EXCLUDED.muted_rules,
              egress_allowlist = EXCLUDED.egress_allowlist,
              updated_at = EXCLUDED.updated_at
            RETURNING {POLICY_COLUMNS}""",
        (command.user_id, command.block_threshold, command.flag_threshold, muted, hosts, now),
    )
    return policy_from_row(row)


async def handle_reset_policy(database: Database, user_id: str) -> Policy:
    """Back to the defaults by deleting the row, not by writing defaults
    into it -- so `is_default` is true again and the dashboard can say so."""
    await database.execute("DELETE FROM airlock_policies WHERE user_id=%s", (user_id,))
    return DEFAULT_POLICY
