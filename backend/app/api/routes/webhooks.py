from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.services.webhooks import process_razorpay_webhook

router = APIRouter()


@router.post("/webhooks/razorpay")
async def webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(None),
    session: Session = Depends(get_db),
):
    raw = await request.body()
    result, valid = process_razorpay_webhook(
        session, raw, x_razorpay_signature, request.headers.get("x-razorpay-event-id"), getattr(request.state, "client_ip", None)
    )
    if not valid:
        raise HTTPException(401, "Invalid webhook signature")
    return result
