from fastapi import APIRouter, Depends, Request, status
from .schema import ContactUsSchema
from .model import ContactUs
from utils.email import contact_us_email
from fastapi.responses import JSONResponse
from db.db import get_db
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

contact_router = APIRouter(prefix="/contact", tags=["Contact"])

@contact_router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def contact_us(request: Request, data: ContactUsSchema, db: Session = Depends(get_db)):
    try:
        # Send email
        contact_us_email(
            data.first_name, data.last_name, data.email, 
            data.topic, data.company_name, data.company_size, data.query
        )
        
        # Save to database
        contact_us_db = ContactUs(
            first_name=data.first_name, last_name=data.last_name, 
            email=data.email, topic=data.topic, 
            company_name=data.company_name, company_size=data.company_size, 
            query=data.query
        )
        db.add(contact_us_db)
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={"message": "Email sent and query saved successfully"})
    
    except SQLAlchemyError as db_error:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Database error occurred"})
    
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "An unexpected error occurred"})