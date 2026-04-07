from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.user_management import create_feedback, list_feedback

router = APIRouter(tags=["feedback"])


class CreateFeedbackRequest(BaseModel):
    category: str
    title: str
    description: str


@router.post("/feedback")
async def create_feedback_endpoint(request: Request, body: CreateFeedbackRequest):
    username = getattr(request.state, "user_id", None)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    category = body.category.strip()
    title = body.title.strip()
    description = body.description.strip()

    if category not in {"bug", "feature"}:
        raise HTTPException(status_code=400, detail="Invalid feedback category")
    if len(title) < 3:
        raise HTTPException(status_code=400, detail="Title must be at least 3 characters")
    if len(description) < 10:
        raise HTTPException(
            status_code=400,
            detail="Description must be at least 10 characters",
        )

    feedback = await create_feedback(
        username=username,
        category=category,
        title=title,
        description=description,
    )
    return {"message": "Feedback submitted successfully", "feedback": feedback}


@router.get("/admin/feedback")
async def list_feedback_endpoint(request: Request):
    if not getattr(request.state, "is_admin", False):
        user_id = getattr(request.state, "user_id", None)
        if user_id != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")

    feedback_items = await list_feedback()
    return {"feedback": feedback_items}
