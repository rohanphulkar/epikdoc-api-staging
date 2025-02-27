from fastapi import APIRouter, Depends, Request, Body
from fastapi.responses import JSONResponse
from .model import Feedback
from .schema import FeedbackSchema
from sqlalchemy.orm import Session
from db.db import get_db
from utils.email import send_feedback_email
from utils.auth import get_current_user
from auth.model import User


feedback_router = APIRouter()

@feedback_router.post("/submit", 
    summary="Submit user feedback",
    description="Allows authenticated users to submit feedback with rating and optional suggestions",
    response_description="Returns success message if feedback is submitted successfully",
    responses={
        201: {
            "description": "Feedback submitted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Feedback submitted successfully"}
                }
            }
        },
        401: {
            "description": "Unauthorized - User not authenticated",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Failed to send feedback email"}
                }
            }
        }
    }
)
async def create_feedback(
    request: Request, 
    feedback: FeedbackSchema = Body(
        ...,
        example={
            "feedback": "Great service! Really helped streamline our workflow.",
            "rating": 5,
            "suggestions": "Would love to see more reporting features"
        },
        description="Feedback details from the user",
        content={
            "application/json": {
                "schema": {
                    "properties": {
                        "feedback": {
                            "type": "string",
                            "description": "User's feedback text"
                        },
                        "rating": {
                            "type": "integer",
                            "description": "Rating from 1-5",
                            "minimum": 1,
                            "maximum": 5
                        },
                        "suggestions": {
                            "type": "string",
                            "description": "Optional suggestions for improvement",
                            "nullable": True
                        }
                    },
                    "required": ["feedback", "rating"]
                }
            }
        }
    ),
    db: Session = Depends(get_db)
):
    try:
        current_user =  get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == current_user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        new_feedback = Feedback(
            user=user.id,
            feedback=feedback.feedback,
            rating=feedback.rating,
            suggestions=feedback.suggestions
        )
        db.add(new_feedback)
        db.commit()
        feedback_sent = send_feedback_email(user.email,new_feedback)
        if feedback_sent:
            return JSONResponse(status_code=201, content={"message": "Feedback submitted successfully"})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to send feedback email"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})