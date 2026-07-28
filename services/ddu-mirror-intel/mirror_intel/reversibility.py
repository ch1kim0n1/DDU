"""Reversible vs. irreversible exposure classification.

Design rule 7. Almost every privacy tool hands you a checklist and implies
that working through it makes the problem go away. For a good half of what a
scan finds, that is false: a 2019 breach dump is on a hundred mirrors, an
archived page is in the Wayback Machine, and someone else's repost of your
photo is not yours to delete.

Saying so is the honest move *and* the differentiating one. But "you can't fix
this" is only useful if it comes with something you can do instead — hence
every irreversible classification carries a compensating control, and the
schema refuses to construct a finding without one.

Reversibility is a function of type *and* age. A post from this morning is
deletable; the same post from 2019 has been scraped, cached, and indexed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .schema import Effort, FindingType, Remediation

#: Days after which content is assumed to have been archived or scraped by
#: someone. Deliberately conservative — claiming a two-year-old post is still
#: deletable is the exact overpromise this module exists to prevent.
ARCHIVE_HORIZON_DAYS = 180


@dataclass(frozen=True)
class Rule:
    reversible: bool
    action: str
    compensating: str | None
    effort: Effort
    permanent_note: str | None = None
    #: When set, a finding older than ARCHIVE_HORIZON_DAYS flips to
    #: irreversible even though the fresh version is fixable.
    ages_out: bool = False


#: Base classification per finding type. The values here are the argument, so
#: they are worth reading as prose rather than skimming as a table.
RULES: dict[FindingType, Rule] = {
    FindingType.SEED_IDENTITY: Rule(
        reversible=True,
        action="This is the identity you verified. Nothing to remediate.",
        compensating=None,
        effort=Effort.LOW,
    ),
    FindingType.ACCOUNT: Rule(
        reversible=True,
        action="Close the account, or lock it down: private mode, no public follower list, "
        "no email/phone discoverability.",
        compensating="If the handle is already indexed, closing it won't unpublish cached "
        "copies — treat the handle itself as public going forward.",
        effort=Effort.LOW,
        ages_out=False,
    ),
    FindingType.BREACH: Rule(
        # The headline irreversible case, and the one the demo turns on.
        reversible=False,
        action="This password/email pair is in a breach corpus. It cannot be withdrawn.",
        compensating="Rotate this password everywhere it was reused, turn on hardware-backed "
        "or app-based MFA on the accounts tied to this address, and assume the "
        "address is permanently known to bulk attackers.",
        effort=Effort.MEDIUM,
        permanent_note="Breach corpora are mirrored and resold. There is no deletion path.",
    ),
    FindingType.GPS_EXPOSURE: Rule(
        reversible=True,
        action="Strip EXIF before posting, and delete the copies that still carry it.",
        compensating="If the photo has been public for a while, assume the coordinates were "
        "scraped. Harden the physical location and your account-recovery answers "
        "rather than relying on deletion.",
        effort=Effort.LOW,
        ages_out=True,
    ),
    FindingType.DEVICE_FINGERPRINT: Rule(
        reversible=True,
        action="Strip metadata on upload; most platforms do this for you, but direct "
        "file shares and self-hosted galleries do not.",
        compensating="Device make/model links your uploads across accounts. Where it is "
        "already public, assume the link is made.",
        effort=Effort.LOW,
        ages_out=True,
    ),
    FindingType.OBJECT_EXPOSURE: Rule(
        reversible=True,
        action="Delete or re-crop the image so the plate, badge, or house number is "
        "outside the frame.",
        compensating="Blurring after the fact doesn't recall copies already downloaded. "
        "If it has been up for months, treat the detail as known.",
        effort=Effort.LOW,
        ages_out=True,
    ),
    FindingType.LOCATION_INFERENCE: Rule(
        reversible=True,
        action="This is inferred from image content, not metadata, so stripping EXIF "
        "will not help. Remove or re-crop the image.",
        compensating="Visual geolocation works on anything already published. Assume the "
        "area is inferable from every photo you have posted from it.",
        effort=Effort.MEDIUM,
        ages_out=True,
    ),
    FindingType.FACE_LINK: Rule(
        reversible=True,
        action="Use a different avatar on the pseudonymous account — ideally not a photo "
        "of your face at all.",
        compensating="Anyone who already captured both avatars has the link. Changing it "
        "now prevents new linkage, not existing linkage.",
        effort=Effort.LOW,
        ages_out=True,
    ),
    FindingType.HANDLE_LINK: Rule(
        reversible=True,
        action="Stop reusing this handle. Pick an unrelated one for accounts you want "
        "kept separate.",
        compensating="Historical handle reuse is indexed. A rename breaks future linkage; "
        "it does not unlink what search engines already associated.",
        effort=Effort.MEDIUM,
        ages_out=True,
    ),
    FindingType.RECORD_CLASS: Rule(
        # Public records are the other genuinely-permanent case, but unlike
        # breaches there is usually a real suppression path — so it is
        # irreversible-by-default with a concrete route out.
        reversible=False,
        action="This record class is public by statute in your jurisdiction. You cannot "
        "delete it.",
        compensating="Many jurisdictions offer address-redaction programs for specific "
        "groups, and data brokers that resell these records have opt-out "
        "processes. See the records advisor for the path in your county.",
        effort=Effort.HIGH,
        permanent_note="The underlying record is a public government record. Suppression "
        "limits redistribution; it does not remove the record.",
    ),
    FindingType.CREDENTIAL_REUSE: Rule(
        reversible=True,
        action="Rotate the reused credential and switch to a password manager so it "
        "cannot be reused again.",
        compensating="Rotation fixes it going forward. Anywhere the old credential was "
        "already used successfully, assume that session or data is compromised.",
        effort=Effort.MEDIUM,
    ),
    FindingType.EMPLOYER_LINK: Rule(
        reversible=True,
        action="Remove the employer reference from the profile or commit metadata that "
        "exposes it.",
        compensating="Git history and cached profiles retain it. Rewriting history on a "
        "public repo rarely removes forks.",
        effort=Effort.MEDIUM,
        ages_out=True,
    ),
    FindingType.ATTACKER_NEXT_MOVE: Rule(
        reversible=True,
        action="Hypothesis only — no action until the underlying findings are confirmed.",
        compensating=None,
        effort=Effort.LOW,
    ),
}


def _age_days(observed_at: str | datetime | None) -> float | None:
    if observed_at is None:
        return None
    if isinstance(observed_at, str):
        try:
            observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            return None
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - observed_at).total_seconds() / 86400


def classify(
    finding_type: FindingType,
    observed_at: str | datetime | None = None,
) -> tuple[bool, Remediation]:
    """Return ``(reversible, remediation)`` for a finding.

    ``observed_at`` is when the *content* was published, not when we found it.
    Producers that don't know should pass None, which keeps the base rule.
    """
    rule = RULES.get(finding_type)
    if rule is None:
        # Unknown type: fail toward honesty. Claiming an unclassified exposure
        # is fixable is the failure mode this module exists to prevent.
        return False, Remediation(
            action="This exposure type has no classification yet.",
            compensating="Treat it as permanent until reviewed.",
            effort=Effort.MEDIUM,
            permanent_note="Unclassified finding type — conservatively treated as permanent.",
        )

    reversible = rule.reversible
    permanent_note = rule.permanent_note
    action = rule.action
    compensating = rule.compensating

    age = _age_days(observed_at)
    if rule.ages_out and age is not None and age > ARCHIVE_HORIZON_DAYS:
        reversible = False
        permanent_note = (
            f"Published about {int(age)} days ago. Content public for more than "
            f"{ARCHIVE_HORIZON_DAYS} days should be assumed archived or scraped; "
            "deleting the original no longer removes it."
        )
        action = f"{action} (Do this anyway — it stops further spread.)"

    if not reversible and not compensating:
        # The schema would reject this finding. Catch it here with a useful
        # message rather than at construction time with a validation error.
        compensating = (
            "Assume this exposure is permanent and harden the accounts and access "
            "paths that depend on it staying private."
        )

    return reversible, Remediation(
        action=action,
        compensating=compensating,
        effort=rule.effort,
        permanent_note=permanent_note,
    )
