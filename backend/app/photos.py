"""Photo upload, listing and delete.

A photo is two things that must stay together: a file in the private `photos` bucket and a row in `photos`.
Both are written as the signed-in user (RLS and the bucket policies apply). We never return or log a public URL;
reads go through signed URLs that expire in an hour, and the stored path is not returned at all.

Failure handling, so nothing is orphaned silently:
* upload: file first, then the row. If the row fails, the file is deleted again; if that also fails it is logged.
* delete: file first, then the row. If the file step fails nothing changed; if the row step fails the row is
  still there, so deleting again finishes the job. (Row first would leave a file nobody could find or retry.)
"""
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .auth import AuthUser, current_user, db_for, storage_for
from .db import DbError, Rest
from .images import NotSupported, Unreadable, clean_photo
from .storage import SIGNED_URL_SECONDS, Storage, StorageError

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # a 48 MP HEIC is about 10 MB
PUBLIC_COLUMNS = 'id,item_id,intake_job_id,taken_at,width,height,position,created_at'


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != 'storage_path'}


async def _item_exists(db: Rest, item_id: UUID) -> bool:
    return bool(await db.select('items', {'select': 'id', 'id': f'eq.{item_id}'}))


async def _discard(storage: Storage, path: str) -> None:
    """Best effort cleanup of a file whose row could not be saved. Loud if it fails, never silent."""
    try:
        await storage.remove([path])
    except StorageError as e:
        logger.error('Orphaned photo file %s (its row was not saved, and the cleanup failed too): %s', path, e)


async def remove_item_photos(db: Rest, storage: Storage, item_id: UUID) -> None:
    """Deleting an item cascades its photo rows in the database but cannot reach the files, so remove those first.
    If that fails, raise before the item is touched: the item and its rows stay, and deleting again retries."""
    rows = await db.select('photos', {'select': 'storage_path', 'item_id': f'eq.{item_id}'})
    try:
        await storage.remove([r['storage_path'] for r in rows])
    except StorageError as e:
        logger.error('Could not delete photo files for item %s: %s', item_id, e)
        raise HTTPException(502, detail={'message': 'Could not delete the photo files; nothing was deleted, try again'}) from None


async def _store(file: UploadFile, user: AuthUser, db: Rest, storage: Storage, item_id: UUID | None) -> dict:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail={'message': f'Photo is over the {MAX_UPLOAD_BYTES // 1024 // 1024} MB limit'})
    try:
        photo = await run_in_threadpool(clean_photo, data)  # CPU work: keep it off the event loop
    except NotSupported as e:
        raise HTTPException(415, detail={'message': str(e)}) from None
    except Unreadable as e:
        raise HTTPException(422, detail={'message': str(e)}) from None

    photo_id = uuid4()
    path = f'{user.id}/{photo_id}.jpg'  # the owner prefix is what the table check and the bucket policies require
    row = {'id': str(photo_id), 'storage_path': path, 'width': photo.width, 'height': photo.height,
           'taken_at': photo.taken_at.isoformat() if photo.taken_at else None}
    if item_id:
        # Same table rule as everywhere else: `position` orders photos within an item, so append after the last.
        last = await db.select('photos', {'select': 'position', 'item_id': f'eq.{item_id}',
                                          'order': 'position.desc', 'limit': '1'})
        row.update(item_id=str(item_id), position=last[0]['position'] + 1 if last else 0)

    await storage.upload(path, photo.jpeg)
    try:
        rows = await db.insert('photos', row)
    except DbError:
        await _discard(storage, path)
        raise
    return _public(rows[0])


@router.post('/items/{item_id}/photos', status_code=201)
async def upload_item_photo(item_id: UUID, file: UploadFile, user: AuthUser = Depends(current_user),
                            db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    if not await _item_exists(db, item_id):  # RLS hides other people's items, so theirs is a 404 too
        raise HTTPException(404, 'No such item')
    return await _store(file, user, db, storage, item_id)


@router.post('/photos', status_code=201)
async def upload_unattached_photo(file: UploadFile, user: AuthUser = Depends(current_user),
                                  db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    """For intake: a photo with no item yet (the photos table allows a null item_id)."""
    return await _store(file, user, db, storage, None)


@router.get('/items/{item_id}/photos')
async def list_item_photos(item_id: UUID, db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    """Each photo with a signed URL good for an hour (`url` is null if the file is missing)."""
    rows = await db.select('photos', {'select': f'{PUBLIC_COLUMNS},storage_path', 'item_id': f'eq.{item_id}',
                                      'order': 'position.asc,created_at.asc'})
    if not rows:
        if not await _item_exists(db, item_id):
            raise HTTPException(404, 'No such item')
        return []
    urls = await storage.sign([r['storage_path'] for r in rows])
    return [{**_public(r), 'url': urls.get(r['storage_path']), 'url_expires_in': SIGNED_URL_SECONDS} for r in rows]


@router.delete('/photos/{photo_id}', status_code=204)
async def delete_photo(photo_id: UUID, db: Rest = Depends(db_for), storage: Storage = Depends(storage_for)):
    rows = await db.select('photos', {'select': 'id,storage_path', 'id': f'eq.{photo_id}'})
    if not rows:
        raise HTTPException(404, 'No such photo')
    try:
        await storage.remove([rows[0]['storage_path']])
    except StorageError as e:
        logger.error('Could not delete the file for photo %s: %s', photo_id, e)
        raise HTTPException(502, detail={'message': 'Could not delete the photo file; nothing was deleted, try again'}) from None
    try:
        await db.delete('photos', {'id': f'eq.{photo_id}'})
    except DbError as e:
        logger.error('Deleted the file for photo %s but not its row: %s', photo_id, e)
        raise HTTPException(502, detail={'message': 'The file is gone but the record was not deleted; delete again to finish'}) from None
