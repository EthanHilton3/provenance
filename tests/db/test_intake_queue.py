"""(2) Two concurrent workers never claim the same intake job (claim_intake_job, FOR UPDATE SKIP LOCKED)."""
import threading
import time

import pytest

from conftest import as_role, connect

JOBS = 60
WORKERS = 8


@pytest.fixture
def queued_jobs(make_user, admin):
    owner = make_user('owner')
    admin.execute('delete from intake_jobs')  # the local queue holds only this test's jobs
    ids = [r[0] for r in admin.execute(
        'insert into intake_jobs (owner_id) select %s from generate_series(1, %s) returning id', (owner, JOBS)
    ).fetchall()]
    return set(ids)


def claim(conn, worker: str):
    row = conn.execute('select id from claim_intake_job(%s)', (worker,)).fetchone()
    return row[0] if row else None


def test_locked_job_is_skipped_not_waited_for(queued_jobs):
    """Worker 1 holds its claim uncommitted; worker 2 gets a different job immediately instead of blocking."""
    with connect() as w1, connect() as w2:
        with as_role(w1, 'service_role'):
            first = claim(w1, 'w1')
            with as_role(w2, 'service_role'):
                w2.execute("set local lock_timeout = '1s'")   # would raise if worker 2 waited on worker 1's lock
                second = claim(w2, 'w2')
    assert first in queued_jobs and second in queued_jobs
    assert first != second


def test_concurrent_workers_claim_each_job_once(queued_jobs, admin):
    claimed: dict[str, list] = {f'w{i}': [] for i in range(WORKERS)}
    start = threading.Barrier(WORKERS)

    def worker(name: str) -> None:
        with connect() as conn:
            start.wait()
            while True:
                with as_role(conn, 'service_role'):
                    job = claim(conn, name)
                    time.sleep(0.002)  # hold the row lock a moment so claims overlap
                if job is None:
                    return
                claimed[name].append(job)

    threads = [threading.Thread(target=worker, args=(n,)) for n in claimed]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    all_claims = [j for jobs in claimed.values() for j in jobs]
    busy = sum(1 for jobs in claimed.values() if jobs)
    print(f'{len(all_claims)} claims by {busy} workers: {sorted(len(j) for j in claimed.values())}')
    assert len(all_claims) == len(set(all_claims)), 'a job was claimed twice'
    assert set(all_claims) == queued_jobs, 'every job claimed exactly once'
    assert busy > 1, 'the workers actually ran concurrently'
    rows = admin.execute(
        "select count(*) filter (where status = 'processing' and attempts = 1), count(distinct locked_by) "
        'from intake_jobs where id = any(%s)', (list(queued_jobs),)
    ).fetchone()
    assert rows[0] == JOBS


def test_stale_claim_is_reclaimed(queued_jobs, admin):
    """A crashed worker's job comes back after its lease; a job out of attempts does not."""
    stuck, spent = sorted(queued_jobs)[:2]
    admin.execute("update intake_jobs set status = 'done' where not (id = any(%s))", ([stuck, spent],))
    admin.execute(
        "update intake_jobs set status = 'processing', locked_by = 'dead', locked_at = now() - interval '10 minutes', "
        'attempts = case when id = %s then 1 else max_attempts end where id in (%s, %s)', (stuck, stuck, spent)
    )
    with connect() as conn, as_role(conn, 'service_role'):
        assert claim(conn, 'w-new') == stuck
        assert claim(conn, 'w-new') is None
