from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from signaldeck.api.server import get_db

router = APIRouter(tags=["bookmark-groups"])


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GroupRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class MemberSet(BaseModel):
    bookmark_ids: list[int]


class MemberAdd(BaseModel):
    bookmark_id: int


@router.get("/bookmark-groups")
async def list_groups():
    db = get_db()
    return await db.get_all_bookmark_groups_with_counts()


@router.post("/bookmark-groups", status_code=201)
async def create_group(data: GroupCreate):
    db = get_db()
    try:
        gid = await db.create_bookmark_group(data.name)
    except Exception:
        raise HTTPException(status_code=409, detail="Group name already exists")
    return {"id": gid, "name": data.name}


@router.patch("/bookmark-groups/{group_id}")
async def rename_group(group_id: int, data: GroupRename):
    db = get_db()
    ok = await db.rename_bookmark_group(group_id, data.name)
    if not ok:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"id": group_id, "updated": True}


@router.delete("/bookmark-groups/{group_id}")
async def delete_group(group_id: int):
    db = get_db()
    ok = await db.delete_bookmark_group(group_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"deleted": True}


@router.get("/bookmark-groups/{group_id}/members")
async def get_members(group_id: int):
    db = get_db()
    member_ids = await db.get_group_member_ids(group_id)
    bookmarks = await db.get_all_bookmarks()
    bm_map = {b.id: b for b in bookmarks}
    return [
        {"bookmark_id": mid, "label": bm_map[mid].label,
         "frequency_hz": bm_map[mid].frequency,
         "modulation": bm_map[mid].modulation}
        for mid in member_ids if mid in bm_map
    ]


@router.put("/bookmark-groups/{group_id}/members")
async def set_members(group_id: int, data: MemberSet):
    db = get_db()
    await db.set_group_members(group_id, data.bookmark_ids)
    return {"count": len(data.bookmark_ids)}


@router.post("/bookmark-groups/{group_id}/members")
async def add_member(group_id: int, data: MemberAdd):
    db = get_db()
    await db.add_group_member(group_id, data.bookmark_id)
    return {"added": True}


@router.delete("/bookmark-groups/{group_id}/members/{bookmark_id}")
async def remove_member(group_id: int, bookmark_id: int):
    db = get_db()
    ok = await db.remove_group_member(group_id, bookmark_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Membership not found")
    return {"removed": True}
