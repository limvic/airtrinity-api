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
def get_posts(limit: int = 20, offset: int = 0, user_id: str | None = None):
    """피드 — 최신순, 숨겨진 것 제외. user_id 주면 내가 좋아요한 여부 포함"""
    result = (
        supabase.table("posts")
        .select("*, users(nickname, avatar, visibility)")
        .eq("is_hidden", False)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    posts = result.data or []
    ids = [p["id"] for p in posts]
    like_counts, my_likes = {}, set()
    if ids:
        likes_res = (
            supabase.table("likes")
            .select("post_id, user_id")
            .in_("post_id", ids)
            .execute()
        )
        for row in (likes_res.data or []):
            like_counts[row["post_id"]] = like_counts.get(row["post_id"], 0) + 1
            if user_id and row["user_id"] == user_id:
                my_likes.add(row["post_id"])
    for p in posts:
        p["like_count"] = like_counts.get(p["id"], 0)
        p["liked"] = p["id"] in my_likes
    return {"posts": posts, "count": len(posts)}

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

# ══════════════════════════════════════════
# v1.1 — LIKES · FRIENDS · MESSAGES · TRANSLATE
# ══════════════════════════════════════════
import urllib.parse, urllib.request, json as _json

class LikeToggle(BaseModel):
    user_id: str

class FriendRequestCreate(BaseModel):
    requester_id: str
    addressee_id: str

class FriendUpdate(BaseModel):
    status: str   # 'accepted' | 'declined'

class TranslateRequest(BaseModel):
    text: str
    target_lang: str | None = None   # 없으면 자동 (ko↔vi)

class MessageCreate(BaseModel):
    sender_id: str
    receiver_id: str
    text: str
    target_lang: str | None = None

# ── 번역 헬퍼 (무료 gtx 엔드포인트, 키 불필요) ──
def _gtx_translate(text: str, target: str):
    """번역 실패 시 (None, None) — 프론트는 '번역 준비 중' 처리"""
    try:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            "?client=gtx&sl=auto&tl=" + urllib.parse.quote(target)
            + "&dt=t&q=" + urllib.parse.quote(text)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = _json.loads(r.read().decode("utf-8"))
        translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
        detected = data[2] if len(data) > 2 else None
        return translated, detected
    except Exception:
        return None, None

def _auto_target(text: str) -> tuple[str | None, str]:
    """소스 언어 감지 → 자동 타깃 결정 (1단계: 한국↔베트남)"""
    _, detected = _gtx_translate(text[:40], "en")  # 감지용 짧은 호출
    if detected == "ko":
        return detected, "vi"
    return detected, "ko"

# ── 번역 단독 엔드포인트 ──
@app.post("/translate")
def translate_text(data: TranslateRequest):
    target = data.target_lang
    if not target:
        _, target = _auto_target(data.text)
    translated, detected = _gtx_translate(data.text, target)
    if translated is None:
        raise HTTPException(status_code=502, detail="번역 서비스 일시 오류")
    return {
        "translated_text": translated,
        "translated_lang": target,
        "detected_lang":   detected,
    }

# ══════════════════════════════════════════
# LIKES
# ══════════════════════════════════════════

@app.post("/posts/{post_id}/like")
def toggle_like(post_id: str, data: LikeToggle):
    """좋아요 토글 — 있으면 취소, 없으면 추가"""
    existing = (
        supabase.table("likes")
        .select("id")
        .eq("post_id", post_id)
        .eq("user_id", data.user_id)
        .execute()
    )
    if existing.data:
        supabase.table("likes").delete().eq("id", existing.data[0]["id"]).execute()
        liked = False
    else:
        supabase.table("likes").insert({
            "post_id": post_id,
            "user_id": data.user_id,
        }).execute()
        liked = True

    count_res = supabase.table("likes").select("id").eq("post_id", post_id).execute()
    return {"liked": liked, "count": len(count_res.data)}

# ══════════════════════════════════════════
# FRIENDS
# ══════════════════════════════════════════

@app.post("/friends")
def request_friend(data: FriendRequestCreate):
    """친구 신청 — 상대가 이미 나에게 신청했다면 자동 수락(상호 연결)"""
    if data.requester_id == data.addressee_id:
        raise HTTPException(status_code=400, detail="자기 자신에게는 신청할 수 없어요")

    a, b = data.requester_id, data.addressee_id
    existing = (
        supabase.table("friendships")
        .select("*")
        .or_(
            f"and(requester_id.eq.{a},addressee_id.eq.{b}),"
            f"and(requester_id.eq.{b},addressee_id.eq.{a})"
        )
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        if row["status"] == "accepted":
            return {"id": row["id"], "status": "accepted"}
        if row["status"] == "pending":
            # 상대가 먼저 신청한 상태에서 내가 신청 → 상호 수락
            if row["requester_id"] == b:
                supabase.table("friendships").update({
                    "status": "accepted",
                    "responded_at": datetime.utcnow().isoformat(),
                }).eq("id", row["id"]).execute()
                return {"id": row["id"], "status": "accepted"}
            return {"id": row["id"], "status": "pending"}
        return {"id": row["id"], "status": row["status"]}

    result = supabase.table("friendships").insert({
        "requester_id": a,
        "addressee_id": b,
        "status": "pending",
    }).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="친구 신청 실패")
    return {"id": result.data[0]["id"], "status": "pending"}

@app.get("/friends/{user_id}")
def get_friends(user_id: str):
    """내가 관련된 모든 친구 관계 (신청함/받음/수락됨)"""
    result = (
        supabase.table("friendships")
        .select("*")
        .or_(f"requester_id.eq.{user_id},addressee_id.eq.{user_id}")
        .order("created_at", desc=True)
        .execute()
    )
    return {"friendships": result.data, "count": len(result.data)}

@app.patch("/friends/{friendship_id}")
def respond_friend(friendship_id: str, data: FriendUpdate):
    """친구 신청 수락 / 거절"""
    if data.status not in ("accepted", "declined"):
        raise HTTPException(status_code=400, detail="status는 accepted 또는 declined")
    result = (
        supabase.table("friendships")
        .update({"status": data.status, "responded_at": datetime.utcnow().isoformat()})
        .eq("id", friendship_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="친구 신청 없음")
    return {"ok": True, "status": data.status}

# ══════════════════════════════════════════
# MESSAGES (AI 번역 내장)
# ══════════════════════════════════════════

@app.post("/messages")
def send_message(data: MessageCreate):
    """메시지 전송 — 자동 번역 포함 (ko↔vi 기본, target_lang 지정 가능)"""
    target = data.target_lang
    if not target:
        _, target = _auto_target(data.text)
    translated, _ = _gtx_translate(data.text, target)

    result = supabase.table("messages").insert({
        "sender_id":       data.sender_id,
        "receiver_id":     data.receiver_id,
        "text":            data.text,
        "translated_text": translated,          # 실패 시 None → 프론트 '번역 준비 중'
        "translated_lang": target if translated else None,
    }).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="메시지 저장 실패")
    return result.data[0]

@app.get("/messages/{user_a}/{user_b}")
def get_conversation(user_a: str, user_b: str, limit: int = 100):
    """두 사람 사이의 대화 (양방향, 시간순)"""
    result = (
        supabase.table("messages")
        .select("*")
        .or_(
            f"and(sender_id.eq.{user_a},receiver_id.eq.{user_b}),"
            f"and(sender_id.eq.{user_b},receiver_id.eq.{user_a})"
        )
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return {"messages": result.data, "count": len(result.data)}
