# ══════════════════════════════════════════
# Airtrinity v1 — FastAPI Backend
# main.py
# ══════════════════════════════════════════

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from datetime import datetime
import os, uuid, base64

# ── 환경변수 ──
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
BUCKET_NAME  = "post-images"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Airtrinity API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════

class UserCreate(BaseModel):
    nickname: str
    avatar: str = "🦋"
    sentence: str = ""
    visibility: str = "public"

class PostCreate(BaseModel):
    user_id: str
    text: str
    image_base64: str | None = None   # 프론트에서 압축된 base64
    image_position: str = "center top"

class CommentCreate(BaseModel):
    post_id: str
    user_id: str
    text: str
    parent_id: str | None = None

class ReportCreate(BaseModel):
    reporter_user_id: str
    target_id: str
    target_type: str   # 'post' | 'comment' | 'user'
    reason: str

# ══════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════

@app.get("/")
def root():
    return {"status": "✦ Airtrinity API is alive"}

# ══════════════════════════════════════════
# USERS
# ══════════════════════════════════════════

@app.post("/users")
def create_user(data: UserCreate):
    """온보딩 완료 시 유저 생성"""
    result = supabase.table("users").insert({
        "nickname":   data.nickname,
        "avatar":     data.avatar,
        "sentence":   data.sentence,
        "visibility": data.visibility,
    }).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="유저 생성 실패")
    return result.data[0]

@app.get("/users/{user_id}")
def get_user(user_id: str):
    result = supabase.table("users").select("*").eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="유저 없음")
    return result.data

# ══════════════════════════════════════════
# POSTS
# ══════════════════════════════════════════

@app.get("/posts")
def get_posts(limit: int = 20, offset: int = 0):
    """피드 — 최신순, 숨겨진 것 제외"""
    result = (
        supabase.table("posts")
        .select("*, users(nickname, avatar, visibility)")
        .eq("is_hidden", False)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"posts": result.data, "count": len(result.data)}

@app.post("/posts")
def create_post(data: PostCreate):
    """게시물 작성 — base64 이미지 있으면 Storage에 업로드"""
    image_url      = None
    image_position = data.image_position

    # 이미지 처리
    if data.image_base64:
        try:
            # base64 → bytes
            header, encoded = data.image_base64.split(",", 1)
            img_bytes = base64.b64decode(encoded)
            file_name = f"{uuid.uuid4()}.jpg"
            # Supabase Storage 업로드
            supabase.storage.from_(BUCKET_NAME).upload(
                file_name,
                img_bytes,
                {"content-type": "image/jpeg"}
            )
            image_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_name)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"이미지 업로드 실패: {str(e)}")

    # DB 저장
    result = supabase.table("posts").insert({
        "user_id":        data.user_id,
        "text":           data.text,
        "image_url":      image_url,
        "image_position": image_position,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="게시물 저장 실패")
    return result.data[0]

@app.delete("/posts/{post_id}")
def delete_post(post_id: str):
    """게시물 완전 삭제"""
    supabase.table("posts").delete().eq("id", post_id).execute()
    return {"ok": True}

# ══════════════════════════════════════════
# COMMENTS
# ══════════════════════════════════════════

@app.get("/posts/{post_id}/comments")
def get_comments(post_id: str):
    result = (
        supabase.table("comments")
        .select("*, users(nickname, avatar)")
        .eq("post_id", post_id)
        .eq("is_hidden", False)
        .order("created_at", desc=False)
        .execute()
    )
    return {"comments": result.data}

@app.post("/comments")
def create_comment(data: CommentCreate):
    result = supabase.table("comments").insert({
        "post_id":   data.post_id,
        "user_id":   data.user_id,
        "text":      data.text,
        "parent_id": data.parent_id,
    }).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="댓글 저장 실패")
    return result.data[0]

# ══════════════════════════════════════════
# REPORTS
# ══════════════════════════════════════════

@app.post("/reports")
def create_report(data: ReportCreate):
    result = supabase.table("reports").insert({
        "reporter_user_id": data.reporter_user_id,
        "target_id":        data.target_id,
        "target_type":      data.target_type,
        "reason":           data.reason,
    }).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="신고 저장 실패")
    return {"ok": True, "message": "신고가 접수되었어요"}
from pydantic import BaseModel

class HideUpdate(BaseModel):
    is_hidden: bool

class BlockUpdate(BaseModel):
    is_blocked: bool

# ── 게시물 숨김/공개 ──
@app.patch("/admin/posts/{post_id}/hide")
def toggle_hide_post(post_id: str, data: HideUpdate):
    """게시물 숨김 / 공개 처리"""
    result = (
        supabase.table("posts")
        .update({"is_hidden": data.is_hidden})
        .eq("id", post_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="게시물 없음")
    return {"ok": True, "is_hidden": data.is_hidden}

# ── 게시물 삭제 (admin용 — 본인 확인 없이) ──
@app.delete("/admin/posts/{post_id}")
def admin_delete_post(post_id: str):
    """관리자 게시물 강제 삭제"""
    supabase.table("posts").delete().eq("id", post_id).execute()
    return {"ok": True}

# ── 유저 차단 / 차단해제 ──
@app.patch("/admin/users/{user_id}/block")
def toggle_block_user(user_id: str, data: BlockUpdate):
    """유저 차단 / 차단 해제"""
    result = (
        supabase.table("users")
        .update({"is_blocked": data.is_blocked})
        .eq("id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="유저 없음")
    return {"ok": True, "is_blocked": data.is_blocked}

# ── 전체 유저 목록 (admin용) ──
@app.get("/admin/users")
def get_all_users(limit: int = 200, offset: int = 0):
    """관리자용 전체 유저 목록"""
    result = (
        supabase.table("users")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {"users": result.data, "count": len(result.data)}

# ── 신고 목록 (admin용) ──
@app.get("/admin/reports")
def get_all_reports(limit: int = 200):
    """관리자용 전체 신고 목록"""
    result = (
        supabase.table("reports")
        .select("*, posts(text, user_id, users(nickname, avatar))")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"reports": result.data, "count": len(result.data)}

# ── 신고 처리완료 ──
@app.patch("/admin/reports/{report_id}/resolve")
def resolve_report(report_id: str):
    """신고 처리 완료 표시"""
    result = (
        supabase.table("reports")
        .update({"resolved": True, "resolved_at": datetime.utcnow().isoformat()})
        .eq("id", report_id)
        .execute()
    )
    return {"ok": True}
