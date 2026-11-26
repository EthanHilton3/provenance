"""The intake worker. Run from backend/:  python -m app.worker   (or --once to drain the queue and exit)

Claims one job at a time with claim_intake_job() (FOR UPDATE SKIP LOCKED), so any number of worker processes can run
side by side. Per job: find the job's photo, re-check it belongs to the job's owner, download it with the service key,
ask the model (Luna for one item, Sol for a group photo), validate and clip the answer, and write it back as the job's
`card` with status 'needs_review' (the owner confirms it in S10; 'done' means an item was saved).

What can go wrong, and what happens:
* The worker crashes mid-job: the job stays 'processing' with its lease time. After the lease, the next claim takes it
  again (attempts + 1). If that was the last attempt, fail_stale_intake_jobs() marks it failed instead.
* The model errors or its answer is unusable: back to 'queued' with run_after pushed out (exponential backoff) and the
  reason in `error`; after the last attempt, 'failed' with that reason.
* The job itself is wrong (no photo, a photo that isn't the owner's, a missing or unreadable file): 'failed' at once.
* Two workers: the claim never hands one job to two workers. If a worker overruns its lease and another reclaims the
  job, the late worker's write matches nothing (every write is filtered by id, owner_id, locked_by = this worker and
  status = 'processing'), so a job's result is written once. The AI call's timeout is well under the lease.

The model's answer is data: schema-checked, clipped, and stored as `card`. It never chooses ids, owners or statuses, and
nothing in it is executed. Logs carry job ids, statuses, tokens and cost; never keys, tokens or photo contents.
"""
import argparse
import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from .ai import AIError, Categories, OpenAIClient, UnreadablePhoto, propose
from .config import get_settings
from .db import DbError, Rest, service_db
from .storage import Storage, StorageError, service_storage

logger = logging.getLogger('app.worker')

LEASE_SECONDS = 300      # claim_intake_job's default lease
BACKOFF_SECONDS = 30     # 30 s, then 60 s, ... between attempts
POLL_SECONDS = 2


class JobProblem(Exception):
    """Something is wrong with the job itself; retrying will not help."""


def add_usage(total: dict | None, call: dict | None) -> dict | None:
    """Usage summed over every call for a job, failed ones included (they cost money too)."""
    if not call:
        return total
    out = dict(total or {})
    for k in ('input_tokens', 'cached_tokens', 'output_tokens', 'reasoning_tokens', 'latency_ms'):
        out[k] = out.get(k, 0) + call.get(k, 0)
    out['cost_usd'] = round(out.get('cost_usd', 0) + call.get('cost_usd', 0), 6)
    out['calls'] = out.get('calls', 0) + 1
    out['model'] = call['model']
    return out


async def load_categories(db: Rest) -> Categories:
    rows = await db.select('categories', {'select': 'id,name,parent_id,description', 'owner_id': 'is.null'})
    return Categories.from_rows(rows)


class Worker:
    def __init__(self, db: Rest, storage: Storage, ai: OpenAIClient, categories: Categories, *, name: str | None = None,
                 lease_seconds: float = LEASE_SECONDS, backoff_seconds: float = BACKOFF_SECONDS):
        self.db, self.storage, self.ai, self.categories = db, storage, ai, categories
        self.name = name or f'{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}'
        self.lease_seconds = lease_seconds
        self.backoff_seconds = backoff_seconds

    @property
    def _lease(self) -> str:
        return f'{self.lease_seconds} seconds'

    async def run_once(self) -> bool:
        """Claims and handles one job. False when there was nothing to claim."""
        reaped = await self.db.rpc('fail_stale_intake_jobs', {'p_lease': self._lease})
        if reaped:
            logger.warning('%s job(s) failed: their worker stopped on the last attempt', reaped)
        rows = await self.db.rpc('claim_intake_job', {'p_worker': self.name, 'p_lease': self._lease})
        if not rows:
            return False
        await self.handle(rows[0])
        return True

    async def run_forever(self, poll_seconds: float = POLL_SECONDS, stop_when_idle: bool = False) -> None:
        while True:
            try:
                busy = await self.run_once()
            except Exception:  # noqa: BLE001 - keep the worker alive; the job's lease brings it back
                logger.exception('worker %s: unexpected error; the claimed job (if any) retries after its lease', self.name)
                busy = False
            if busy:
                continue
            if stop_when_idle:
                return
            await asyncio.sleep(poll_seconds)

    async def handle(self, job: dict) -> None:
        jid = job['id']
        usage = job.get('usage')
        logger.info('job %s: claimed (%s, attempt %s/%s)', jid, job['mode'], job['attempts'], job['max_attempts'])
        try:
            photo = await self._photo(job)
            jpeg = await self.storage.download(photo['storage_path'])
            card, call = await propose(self.ai, job['mode'], jpeg, self.categories)
        except (JobProblem, UnreadablePhoto) as e:
            await self._write(job, {'status': 'failed', 'error': str(e), 'usage': usage})
            return
        except AIError as e:
            await self._retry_or_fail(job, e.reason, add_usage(usage, e.usage))
            return
        except StorageError as e:  # before DbError: it is a subclass
            if e.status in (400, 404):  # Storage answers a missing object with either
                await self._write(job, {'status': 'failed', 'error': 'The photo file is missing', 'usage': usage})
            else:
                await self._retry_or_fail(job, f'Could not read the photo from storage (HTTP {e.status})', usage)
            return
        except DbError as e:
            await self._retry_or_fail(job, f'Could not read the job from the database (HTTP {e.status})', usage)
            return
        usage = add_usage(usage, call)
        logger.info('job %s: %s %s in (%s cached), %s out, $%.6f, %s ms', jid, call['model'], call['input_tokens'],
                    call['cached_tokens'], call['output_tokens'], call['cost_usd'], call['latency_ms'])
        await self._write(job, {'status': 'needs_review', 'card': card, 'error': None, 'usage': usage})

    async def _photo(self, job: dict) -> dict:
        """The job's photo, re-checked against the job's owner (the database's composite key already ties them; this
        holds even if that ever changes). Not filtered by owner in the query, so a mismatch is seen, not hidden."""
        rows = await self.db.select('photos', {'select': 'id,owner_id,storage_path', 'intake_job_id': f'eq.{job["id"]}',
                                               'order': 'position.asc,created_at.asc'})
        if not rows:
            raise JobProblem('The photo for this job was deleted')
        owner = job['owner_id']
        for r in rows:
            if r['owner_id'] != owner or not r['storage_path'].startswith(f'{owner}/'):
                logger.warning('job %s: photo %s does not belong to the job owner; job failed', job['id'], r['id'])
                raise JobProblem("This job's photo does not belong to its owner")
        return rows[0]

    async def _retry_or_fail(self, job: dict, reason: str, usage: dict | None) -> None:
        if job['attempts'] >= job['max_attempts']:
            await self._write(job, {'status': 'failed', 'usage': usage,
                                    'error': f'{reason}. Gave up after {job["attempts"]} tries.'})
            return
        delay = self.backoff_seconds * 2 ** (job['attempts'] - 1)
        run_after = datetime.now(timezone.utc) + timedelta(seconds=delay)
        await self._write(job, {'status': 'queued', 'run_after': run_after.isoformat(), 'usage': usage,
                                'error': f'{reason}; will retry'})

    async def _write(self, job: dict, values: dict) -> bool:
        """Scoped to this job, its owner and this worker's live claim. False if the claim was lost (nothing written)."""
        rows = await self.db.update(
            'intake_jobs',
            {'id': f'eq.{job["id"]}', 'owner_id': f'eq.{job["owner_id"]}', 'locked_by': f'eq.{self.name}',
             'status': 'eq.processing', 'select': 'id'},
            {**values, 'locked_by': None, 'locked_at': None},
        )
        if not rows:
            logger.warning('job %s: claim lost to another worker; this result was dropped', job['id'])
            return False
        logger.info('job %s: %s%s', job['id'], values['status'], f' ({values["error"]})' if values.get('error') else '')
        return True


async def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog='python -m app.worker', description='Provenance intake worker')
    ap.add_argument('--once', action='store_true', help='drain the queue, then exit')
    ap.add_argument('--poll', type=float, default=POLL_SECONDS, help='seconds between checks when the queue is empty')
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)  # its INFO lines are one per request

    key = get_settings().openai_api_key.get_secret_value()
    if not key:
        raise SystemExit('OPENAI_API_KEY is not set')
    async with httpx.AsyncClient(timeout=30) as http:
        db = service_db(http)
        worker = Worker(db, service_storage(http), OpenAIClient(http, key), await load_categories(db))
        logger.info('worker %s started: %s categories, lease %ss', worker.name, len(worker.categories.ids), worker.lease_seconds)
        await worker.run_forever(poll_seconds=args.poll, stop_when_idle=args.once)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # a job in flight goes back to the queue after its lease
