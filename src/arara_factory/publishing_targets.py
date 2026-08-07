from __future__ import annotations

from dataclasses import dataclass

from .publishing import Platform, PublishQueue


@dataclass(frozen=True)
class QueueTargetSyncResult:
    removed_deliveries: int = 0
    removed_jobs: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.removed_deliveries or self.removed_jobs)


def prune_unselected_targets(
    queue: PublishQueue,
    platforms: list[Platform],
) -> QueueTargetSyncResult:
    """Remove unfinished deliveries for platforms the user no longer selected.

    Successful deliveries are preserved as history. We intentionally do not add
    newly selected platforms to old jobs: platform expansion applies only to new
    batches, while deselection immediately stops retries for old unfinished jobs.
    """
    allowed = {platform.value for platform in platforms}
    if not allowed:
        return QueueTargetSyncResult()

    removed_deliveries = 0
    removed_jobs = 0
    kept = []

    for job in queue.jobs:
        if job.done:
            kept.append(job)
            continue

        for name in list(job.deliveries):
            state = job.deliveries[name]
            if name not in allowed and state.status != "success":
                del job.deliveries[name]
                removed_deliveries += 1

        if job.deliveries:
            kept.append(job)
        else:
            removed_jobs += 1

    if removed_deliveries or removed_jobs:
        queue.jobs = kept
        queue.save()

    return QueueTargetSyncResult(
        removed_deliveries=removed_deliveries,
        removed_jobs=removed_jobs,
    )
