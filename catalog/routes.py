from fastapi import APIRouter, Request, Depends, File, UploadFile, status, Form, Query
from sqlalchemy.orm import Session
from .schemas import *
from .models import *
from db.db import get_db
from auth.models import User
from fastapi.responses import JSONResponse
from utils.auth import verify_token
from sqlalchemy import  func, asc, desc
import os
from sqlalchemy.exc import SQLAlchemyError
from PIL import Image
import io
import numpy as np
import json
from datetime import datetime
from typing import Optional, List
from appointment.models import Appointment
from math import ceil

catalog_router = APIRouter()

@catalog_router.post(
    "/create-treatment",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new treatment record",
    description="""
    Create a new treatment record in the system.
    
    Required fields:
    - treatment_date: Date and time of treatment (format: YYYY-MM-DD HH:MM:SS)
    - treatment_name: Name of the treatment procedure
    - treatment_cost: Cost per unit of treatment (decimal number)
    - amount: Total amount for treatment (decimal number)
    
    Optional fields:
    - patient_id: Unique identifier of the patient (UUID)
    - tooth_number: Tooth number for dental procedures (1-32)
    - treatment_notes: Additional notes about treatment (text)
    - quantity: Number of units (integer, default: 1)
    - discount: Discount amount (decimal number)
    - discount_type: Type of discount (enum: "percentage" or "fixed")
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Returns:
    - treatment_id: Unique identifier of created treatment (UUID)
    - message: Success message
    """,
    responses={
        201: {
            "description": "Treatment created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Treatment created successfully",
                        "treatment_id": "123e4567-e89b-12d3-a456-426614174000"
                    }
                }
            }
        },
        400: {
            "description": "Invalid request data or database error",
            "content": {
                "application/json": {
                    "example": {"message": "Invalid treatment data"}
                }
            }
        },
        401: {
            "description": "Authentication required or invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Authentication required"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error occurred"}
                }
            }
        }
    }
)
async def create_treatment(request: Request, treatment: TreatmentCreate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})

        treatment_data = treatment.model_dump()
        new_treatment = Treatment(**treatment_data)
        db.add(new_treatment)
        db.commit()
        db.refresh(new_treatment)
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED, 
            content={
                "message": "Treatment created successfully",
                "treatment_id": new_treatment.id
            }
        )
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.get(
    "/get-treatments",
    status_code=status.HTTP_200_OK,
    summary="Get all treatments with pagination and statistics",
    description="""
    Get all treatments from the system with pagination support and treatment statistics.
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    - sort_by: Sort field (options: treatment_date, treatment_name, amount) (default: treatment_date)
    - sort_order: Sort direction (asc/desc) (default: desc)
    
    Returns:
    - treatments: List of treatment records
    - pagination:
        - total: Total number of treatments
        - total_pages: Total number of pages
        - current_page: Current page number
        - per_page: Items per page
    - statistics:
        - today: Number and total amount of treatments today
        - this_month: Number and total amount of treatments this month
        - this_year: Number and total amount of treatments this year
        - overall: Total number and amount of all treatments
    """,
    responses={
        200: {
            "description": "List of treatments and statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Treatments retrieved successfully",
                        "treatments": [],
                        "pagination": {
                            "total": 0,
                            "total_pages": 0,
                            "current_page": 1,
                            "per_page": 10
                        },
                        "statistics": {
                            "today": {"count": 0, "total_amount": 0},
                            "this_month": {"count": 0, "total_amount": 0},
                            "this_year": {"count": 0, "total_amount": 0},
                            "overall": {"count": 0, "total_amount": 0}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication required or invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Authentication required"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error occurred"}
                }
            }
        }
    }
)
async def get_treatments(
    request: Request, 
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="treatment_date", description="Sort field"),
    sort_order: str = Query(default="desc", description="Sort direction"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Get total count
        total = db.query(func.count(Treatment.id)).filter(Treatment.doctor == user.id).scalar()
        total_pages = ceil(total / per_page)
        
        # Get statistics
        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)
        first_day_of_year = today.replace(month=1, day=1)
        
        today_stats = db.query(
            func.count(Treatment.id).label('count'),
            func.coalesce(func.sum(Treatment.amount), 0).label('total_amount')
        ).filter(
            Treatment.doctor == user.id,
            func.date(Treatment.treatment_date) == today
        ).first()
        
        month_stats = db.query(
            func.count(Treatment.id).label('count'),
            func.coalesce(func.sum(Treatment.amount), 0).label('total_amount')
        ).filter(
            Treatment.doctor == user.id,
            Treatment.treatment_date >= first_day_of_month
        ).first()
        
        year_stats = db.query(
            func.count(Treatment.id).label('count'),
            func.coalesce(func.sum(Treatment.amount), 0).label('total_amount')
        ).filter(
            Treatment.doctor == user.id,
            Treatment.treatment_date >= first_day_of_year
        ).first()
        
        overall_stats = db.query(
            func.count(Treatment.id).label('count'),
            func.coalesce(func.sum(Treatment.amount), 0).label('total_amount')
        ).filter(Treatment.doctor == user.id).first()
        
        # Get paginated treatments with sorting
        sort_column = getattr(Treatment, sort_by)
        if sort_order.lower() == "desc":
            sort_column = sort_column.desc()
            
        treatments = db.query(Treatment)\
            .filter(Treatment.doctor == user.id)\
            .order_by(sort_column)\
            .offset((page - 1) * per_page)\
            .limit(per_page)\
            .all()
            
        treatment_list = []

        for treatment in treatments:
            treatment_list.append({
                "id": treatment.id,
                "patient_id": treatment.patient_id,
                "treatment_date": treatment.treatment_date.isoformat() if treatment.treatment_date else None,
                "treatment_name": treatment.treatment_name,
                "tooth_number": treatment.tooth_number,
                "treatment_notes": treatment.treatment_notes,
                "quantity": treatment.quantity,
                "treatment_cost": treatment.treatment_cost,
                "amount": treatment.amount,
                "discount": treatment.discount,
                "discount_type": treatment.discount_type,
                "doctor": treatment.doctor,
                "created_at": treatment.created_at.isoformat() if treatment.created_at else None
            })
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatments retrieved successfully", 
            "treatments": treatment_list,
            "pagination": {
                "total": total,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page
            },
            "statistics": {
                "today": {
                    "count": today_stats[0] if today_stats else 0,
                    "total_amount": float(today_stats[1]) if today_stats else 0.0
                },
                "this_month": {
                    "count": month_stats[0] if month_stats else 0,
                    "total_amount": float(month_stats[1]) if month_stats else 0.0
                },
                "this_year": {
                    "count": year_stats[0] if year_stats else 0,
                    "total_amount": float(year_stats[1]) if year_stats else 0.0
                },
                "overall": {
                    "count": overall_stats[0] if overall_stats else 0,
                    "total_amount": float(overall_stats[1]) if overall_stats else 0.0
                }
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@catalog_router.get("/search-treatments",
    status_code=status.HTTP_200_OK,
    summary="Search treatments with pagination and statistics",
    description="""
    Search treatments by treatment name and/or patient ID with optional date range filtering, pagination and statistics.
    
    Query parameters:
    - treatment_name: Search by treatment name (optional)
    - patient_id: Filter by patient ID (optional)
    - start_date: Filter by start date (format: YYYY-MM-DD, optional)
    - end_date: Filter by end date (format: YYYY-MM-DD, optional)
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    - sort_by: Sort field (options: treatment_date, treatment_name, amount) (default: treatment_date)
    - sort_order: Sort direction (asc/desc) (default: desc)
    
    Returns:
    - treatments: List of matching treatments
    - pagination: Pagination details
    - statistics: Treatment statistics for filtered results
    """
)
async def search_treatments(
    request: Request, 
    treatment_name: str = Query(None, description="Search by treatment name"),
    patient_id: str = Query(None, description="Filter by patient ID"),
    start_date: str = Query(None, description="Filter by start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Filter by end date (YYYY-MM-DD)"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="treatment_date", description="Sort field"),
    sort_order: str = Query(default="desc", description="Sort direction"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Build base query
        query = db.query(Treatment).filter(Treatment.doctor == user.id)
        
        # Apply search if provided
        if treatment_name:
            query = query.filter(Treatment.treatment_name.ilike(f"%{treatment_name}%"))
        if patient_id:
            query = query.filter(Treatment.patient_id == patient_id)
            
        # Apply filters if provided
        if start_date:
            query = query.filter(Treatment.treatment_date >= start_date)
        if end_date:
            query = query.filter(Treatment.treatment_date <= end_date)
            
        # Get statistics for filtered results
        stats = query.with_entities(
            func.count(Treatment.id).label('count'),
            func.sum(Treatment.amount).label('total_amount')
        ).first()
            
        # Get total count
        total = query.count()
        total_pages = ceil(total / per_page)
        
        # Apply sorting
        sort_column = getattr(Treatment, sort_by)
        if sort_order.lower() == "desc":
            sort_column = sort_column.desc()
            
        # Apply pagination
        treatments = query.order_by(sort_column).offset((page - 1) * per_page).limit(per_page).all()
        
        treatment_list = []
        for treatment in treatments:
            treatment_list.append({
                "id": treatment.id,
                "patient_id": treatment.patient_id,
                "treatment_date": treatment.treatment_date.isoformat() if treatment.treatment_date else None,
                "treatment_name": treatment.treatment_name,
                "tooth_number": treatment.tooth_number,
                "treatment_notes": treatment.treatment_notes,
                "quantity": treatment.quantity,
                "treatment_cost": treatment.treatment_cost,
                "amount": treatment.amount,
                "discount": treatment.discount,
                "discount_type": treatment.discount_type,
                "doctor": treatment.doctor,
                "created_at": treatment.created_at.isoformat() if treatment.created_at else None
            })
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatments retrieved successfully",
            "treatments": treatment_list,
            "pagination": {
                "total": total,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page
            },
            "statistics": {
                "filtered_results": {
                    "count": stats[0] if stats else 0,
                    "total_amount": float(stats[1]) if stats else 0.0
                }
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.get("/get-treatment/{treatment_id}",
    status_code=status.HTTP_200_OK,
    summary="Get a treatment by ID",
    description="""
    Get detailed information about a specific treatment by its unique identifier.
    
    Path parameters:
    - treatment_id: Unique identifier of the treatment (UUID)
    
    Returns:
    - treatment: Detailed treatment information including all fields
    """,
    responses={
        200: {
            "description": "Treatment details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Treatment retrieved successfully",
                        "treatment": {
                            "id": "123e4567-e89b-12d3-a456-426614174000",
                            "patient_id": "patient-uuid",
                            "treatment_date": "2023-01-01T10:00:00",
                            "treatment_name": "Root Canal",
                            "tooth_number": 1,
                            "treatment_notes": "Sample notes",
                            "quantity": 1,
                            "treatment_cost": 100.00,
                            "amount": 100.00,
                            "discount": 0,
                            "discount_type": "percentage",
                            "doctor": "doctor-uuid",
                            "treatment_description": "Detailed procedure description",
                            "tooth_diagram": "Diagram data",
                            "created_at": "2023-01-01T10:00:00"
                        }
                    }
                }
            }
        },
        401: {"description": "Authentication required or invalid token"},
        404: {"description": "Treatment not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_treatment(treatment_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        treatment = db.query(Treatment).filter(Treatment.id == treatment_id, Treatment.doctor == user.id).first()
        if not treatment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment not found"})
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment retrieved successfully",
            "treatment": {
                "id": treatment.id,
                "patient_id": treatment.patient_id,
                "treatment_date": treatment.treatment_date.isoformat() if treatment.treatment_date else None,
                "treatment_name": treatment.treatment_name,
                "tooth_number": treatment.tooth_number,
                "treatment_notes": treatment.treatment_notes,
                "quantity": treatment.quantity,
                "treatment_cost": treatment.treatment_cost,
                "amount": treatment.amount,
                "discount": treatment.discount,
                "discount_type": treatment.discount_type,
                "doctor": treatment.doctor,
                "created_at": treatment.created_at.isoformat() if treatment.created_at else None
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.patch("/update-treatment/{treatment_id}",
    status_code=status.HTTP_200_OK,
    summary="Update a treatment by ID",
    description="""
    Update specific fields of an existing treatment record.
    
    Path parameters:
    - treatment_id: Unique identifier of the treatment (UUID)
    
    Optional fields to update:
    - treatment_date: Date and time of treatment (format: YYYY-MM-DD HH:MM:SS)
    - treatment_name: Name of the treatment procedure
    - tooth_number: Tooth number for dental procedures (1-32)
    - treatment_notes: Additional notes about treatment
    - quantity: Number of units
    - treatment_cost: Cost per unit of treatment
    - amount: Total amount for treatment
    - discount: Discount amount
    - discount_type: Type of discount (percentage/fixed)
    
    Only provided fields will be updated.
    """,
    responses={
        200: {
            "description": "Treatment updated successfully"
        },
        401: {"description": "Authentication required or invalid token"},
        404: {"description": "Treatment not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_treatment(treatment_id: str, request: Request, treatment: TreatmentUpdate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        existing_treatment = db.query(Treatment).filter(Treatment.id == treatment_id, Treatment.doctor == user.id).first()
        if not existing_treatment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment not found"})
            
        treatment_data = treatment.model_dump(exclude_unset=True)
        
        # Update each field individually
        for field, value in treatment_data.items():
            setattr(existing_treatment, field, value)
            
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment updated successfully",
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.delete("/delete-treatment/{treatment_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a treatment by ID",
    description="""
    Permanently delete a treatment record from the system.
    
    Path parameters:
    - treatment_id: Unique identifier of the treatment to delete (UUID)
    
    The treatment must belong to the authenticated doctor.
    
    Note: This action cannot be undone. All associated data will be permanently removed.
    """,
    responses={
        200: {
            "description": "Treatment deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Treatment deleted successfully"}
                }
            }
        },
        401: {"description": "Authentication required or invalid token"},
        404: {"description": "Treatment not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_treatment(treatment_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        treatment = db.query(Treatment).filter(Treatment.id == treatment_id, Treatment.doctor == user.id).first()
        if not treatment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment not found"})

        db.delete(treatment)
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Treatment deleted successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.post("/create-clinical-note",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new clinical note",
    description="""
    Create a new clinical note in the system.
    
    The clinical note will be associated with the authenticated doctor and specified patient.
    
    Required fields:
    - patient_id: ID of the patient this note is for
    - note_type: Type of clinical note (e.g. Progress Note, Assessment, Treatment Plan)
    - description: Detailed content of the clinical note
    - date: Date of the clinical note
    
    Optional fields:
    - is_revised: Whether this note has been revised (default: false)
    """
)
async def create_clinical_note(request: Request, clinical_note: ClinicalNoteCreate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        clinical_note_data = clinical_note.model_dump()
        new_clinical_note = ClinicalNote(**clinical_note_data)
        db.add(new_clinical_note)
        db.commit()
        db.refresh(new_clinical_note)
        
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={
            "message": "Clinical note created successfully"
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.get("/get-clinical-notes",
    status_code=status.HTTP_200_OK,
    summary="Get all clinical notes with pagination",
    description="""
    Get all clinical notes from the system with pagination support.
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    
    Returns:
    - List of clinical notes for the authenticated doctor
    - Pagination metadata
    - Statistics about clinical notes:
        - Today's count
        - This month's count  
        - This year's count
        - Overall total count
    """
)
async def get_clinical_notes(
    request: Request,
    page: int = Query(1, gt=0, description="Page number"),
    per_page: int = Query(10, gt=0, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Get total count
        total_count = db.query(ClinicalNote).filter(ClinicalNote.doctor == user.id).count()
        
        # Get paginated results
        clinical_notes = db.query(ClinicalNote)\
            .filter(ClinicalNote.doctor == user.id)\
            .offset((page - 1) * per_page)\
            .limit(per_page)\
            .all()
            
        clinical_note_list = []
        for note in clinical_notes:
            clinical_note_list.append({
                "id": note.id,
                "patient_id": note.patient_id,
                "date": note.date.isoformat() if note.date else None,
                "note_type": note.note_type,
                "description": note.description,
                "is_revised": note.is_revised,
                "created_at": note.created_at.isoformat() if note.created_at else None
            })
            
        # Get statistics
        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)
        first_day_of_year = today.replace(month=1, day=1)
        
        today_count = db.query(ClinicalNote)\
            .filter(ClinicalNote.doctor == user.id)\
            .filter(func.date(ClinicalNote.created_at) == today)\
            .count()
            
        month_count = db.query(ClinicalNote)\
            .filter(ClinicalNote.doctor == user.id)\
            .filter(ClinicalNote.created_at >= first_day_of_month)\
            .count()
            
        year_count = db.query(ClinicalNote)\
            .filter(ClinicalNote.doctor == user.id)\
            .filter(ClinicalNote.created_at >= first_day_of_year)\
            .count()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Clinical notes retrieved successfully",
            "clinical_notes": clinical_note_list,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_items": total_count,
                "total_pages": (total_count + per_page - 1) // per_page
            },
            "statistics": {
                "today": today_count,
                "this_month": month_count,
                "this_year": year_count,
                "total": total_count
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.get("/search-clinical-notes",
    status_code=status.HTTP_200_OK,
    summary="Search clinical notes with pagination",
    description="""
    Search clinical notes by patient ID and/or date range with pagination support.
    
    Query parameters:
    - patient_id: Filter by patient ID (optional)
    - start_date: Filter notes from this date (YYYY-MM-DD format)
    - end_date: Filter notes until this date (YYYY-MM-DD format)
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    
    Returns:
    - Filtered list of clinical notes
    - Pagination metadata
    - Statistics about filtered notes
    """
)
async def search_clinical_notes(
    request: Request,
    patient_id: str = Query(None, description="Patient ID to filter by"),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    page: int = Query(1, gt=0, description="Page number"),
    per_page: int = Query(10, gt=0, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Build base query
        query = db.query(ClinicalNote).filter(ClinicalNote.doctor == user.id)
        
        # Apply filters if provided
        if patient_id:
            query = query.filter(ClinicalNote.patient_id == patient_id)
        if start_date:
            query = query.filter(ClinicalNote.date >= start_date)
        if end_date:
            query = query.filter(ClinicalNote.date <= end_date)
            
        # Get total filtered count
        total_count = query.count()
            
        # Get paginated results
        clinical_notes = query.offset((page - 1) * per_page).limit(per_page).all()
        
        clinical_note_list = []
        for note in clinical_notes:
            clinical_note_list.append({
                "id": note.id,
                "patient_id": note.patient_id,
                "date": note.date.isoformat() if note.date else None,
                "note_type": note.note_type,
                "description": note.description,
                "is_revised": note.is_revised,
                "created_at": note.created_at.isoformat() if note.created_at else None
            })
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Clinical notes retrieved successfully",
            "clinical_notes": clinical_note_list,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_items": total_count,
                "total_pages": (total_count + per_page - 1) // per_page
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@catalog_router.get("/get-clinical-note/{clinical_note_id}",
    status_code=status.HTTP_200_OK,
    summary="Get a clinical note by ID",
    description="""
    Get a clinical note by its unique ID.
    
    Path parameters:
    - clinical_note_id: Unique identifier of the clinical note
    
    Returns:
    - Detailed information about the clinical note
    - The note must belong to the authenticated doctor
    """
)
async def get_clinical_note(clinical_note_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        clinical_note = db.query(ClinicalNote).filter(ClinicalNote.id == clinical_note_id, ClinicalNote.doctor == user.id).first()
        if not clinical_note:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Clinical note not found"})

        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Clinical note retrieved successfully",
            "clinical_note": {
                "id": clinical_note.id,
                "patient_id": clinical_note.patient_id,
                "date": clinical_note.date.isoformat() if clinical_note.date else None,
                "note_type": clinical_note.note_type,
                "description": clinical_note.description,
                "is_revised": clinical_note.is_revised,
                "created_at": clinical_note.created_at.isoformat() if clinical_note.created_at else None
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.patch("/update-clinical-note/{clinical_note_id}",
    status_code=status.HTTP_200_OK,
    summary="Update a clinical note by ID",
    description="""
    Update a clinical note by its unique ID.
    
    Path parameters:
    - clinical_note_id: Unique identifier of the clinical note to update
    
    The note must belong to the authenticated doctor.
    
    Updatable fields:
    - patient_id
    - date 
    - note_type
    - description
    - is_revised
    
    Only provide the fields that need to be updated.
    """
)
async def update_clinical_note(clinical_note_id: str, request: Request, clinical_note: ClinicalNoteUpdate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        existing_clinical_note = db.query(ClinicalNote).filter(ClinicalNote.id == clinical_note_id, ClinicalNote.doctor == user.id).first()
        if not existing_clinical_note:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Clinical note not found"})
        
        clinical_note_data = clinical_note.model_dump(exclude_unset=True)
        
        for field, value in clinical_note_data.items():
            setattr(existing_clinical_note, field, value)
            
        db.commit()

        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Clinical note updated successfully"
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.delete("/delete-clinical-note/{clinical_note_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a clinical note by ID",
    description="""
    Permanently delete a clinical note by its unique ID.
    
    Path parameters:
    - clinical_note_id: Unique identifier of the clinical note to delete
    
    The note must belong to the authenticated doctor.
    
    Note: This action cannot be undone. The clinical note will be permanently removed from the system.
    """
)
async def delete_clinical_note(clinical_note_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        clinical_note = db.query(ClinicalNote).filter(ClinicalNote.id == clinical_note_id, ClinicalNote.doctor == user.id).first()
        if not clinical_note:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Clinical note not found"})
        
        db.delete(clinical_note)
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Clinical note deleted successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.post("/create-treatment-plan",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new treatment plan",
    description="""
    Create a new treatment plan in the system.
    
    The treatment plan will be associated with the authenticated doctor and specified patient.
    
    Required fields:
    - patient_id: ID of the patient
    - treatment_name: Name of the treatment
    - unit_cost: Cost per unit of treatment
    - quantity: Number of units
    - amount: Total amount
    
    Optional fields:
    - date: Treatment date
    - discount: Discount amount
    - discount_type: Type of discount (percentage/fixed)
    - treatment_description: Detailed description
    - tooth_diagram: Diagram data
    """
)
async def create_treatment_plan(request: Request, treatment_plan: TreatmentPlanCreate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        treatment_plan_data = treatment_plan.model_dump()
        new_treatment_plan = TreatmentPlan(**treatment_plan_data)
        db.add(new_treatment_plan)
        db.commit()
        db.refresh(new_treatment_plan)
        
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={
            "message": "Treatment plan created successfully"
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.get("/get-treatment-plans",
    status_code=status.HTTP_200_OK,
    summary="Get all treatment plans with pagination",
    description="""
    Get all treatment plans from the system with pagination support.
    
    Query parameters:
    - page: Page number (default: 1)
    - limit: Number of items per page (default: 10)
    - sort_by: Field to sort by (default: created_at)
    - sort_order: Sort order (asc/desc, default: desc)
    
    Returns:
    - List of treatment plans
    - Pagination metadata
    - Statistics for different time periods
    """
)
async def get_treatment_plans(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})

        # Calculate statistics
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)
        
        stats = {
            "today": db.query(TreatmentPlan).filter(
                TreatmentPlan.doctor == user.id,
                func.date(TreatmentPlan.created_at) == today
            ).count(),
            "month": db.query(TreatmentPlan).filter(
                TreatmentPlan.doctor == user.id,
                TreatmentPlan.created_at >= month_start
            ).count(),
            "year": db.query(TreatmentPlan).filter(
                TreatmentPlan.doctor == user.id,
                TreatmentPlan.created_at >= year_start
            ).count(),
            "total": db.query(TreatmentPlan).filter(
                TreatmentPlan.doctor == user.id
            ).count()
        }

        # Build query with sorting
        query = db.query(TreatmentPlan).filter(TreatmentPlan.doctor == user.id)
        if hasattr(TreatmentPlan, sort_by):
            sort_column = getattr(TreatmentPlan, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

        # Apply pagination
        total_items = query.count()
        total_pages = (total_items + limit - 1) // limit
        offset = (page - 1) * limit
        
        treatment_plans = query.offset(offset).limit(limit).all()
        treatment_plan_list = []
        
        for plan in treatment_plans:
            treatment_plan_list.append({
                "id": plan.id,
                "patient_id": plan.patient_id,
                "date": plan.date.isoformat() if plan.date else None,
                "treatment_name": plan.treatment_name,
                "unit_cost": plan.unit_cost,
                "quantity": plan.quantity,
                "discount": plan.discount,
                "discount_type": plan.discount_type,
                "amount": plan.amount,
                "treatment_description": plan.treatment_description,
                "tooth_diagram": plan.tooth_diagram,
                "created_at": plan.created_at.isoformat() if plan.created_at else None
            })
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment plans retrieved successfully",
            "treatment_plans": treatment_plan_list,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_items": total_items,
                "items_per_page": limit
            },
            "statistics": stats
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.get("/search-treatment-plans",
    status_code=status.HTTP_200_OK,
    summary="Search treatment plans with pagination",
    description="""
    Search treatment plans by various criteria with pagination support.
    
    Query parameters:
    - patient_id: Filter by patient ID
    - start_date: Filter by start date (YYYY-MM-DD)
    - end_date: Filter by end date (YYYY-MM-DD)
    - page: Page number (default: 1)
    - limit: Number of items per page (default: 10)
    - sort_by: Field to sort by (default: created_at)
    - sort_order: Sort order (asc/desc, default: desc)
    
    Returns:
    - Filtered list of treatment plans
    - Pagination metadata
    - Search statistics
    """
)
async def search_treatment_plans(
    request: Request,
    patient_id: str = Query(None, description="Patient ID to filter by"),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
            
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        query = db.query(TreatmentPlan).filter(TreatmentPlan.doctor == user.id)
        
        if patient_id:
            query = query.filter(TreatmentPlan.patient_id == patient_id)
        if start_date:
            query = query.filter(TreatmentPlan.date >= start_date)
        if end_date:
            query = query.filter(TreatmentPlan.date <= end_date)
            
        # Apply sorting
        if hasattr(TreatmentPlan, sort_by):
            sort_column = getattr(TreatmentPlan, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

        # Apply pagination
        total_items = query.count()
        total_pages = (total_items + limit - 1) // limit
        offset = (page - 1) * limit
        
        treatment_plans = query.offset(offset).limit(limit).all()
        treatment_plan_list = []
        
        for plan in treatment_plans:
            treatment_plan_list.append({
                "id": plan.id,
                "patient_id": plan.patient_id,
                "date": plan.date.isoformat() if plan.date else None,
                "treatment_name": plan.treatment_name,
                "unit_cost": plan.unit_cost,
                "quantity": plan.quantity,
                "discount": plan.discount,
                "discount_type": plan.discount_type,
                "amount": plan.amount,
                "treatment_description": plan.treatment_description,
                "tooth_diagram": plan.tooth_diagram,
                "created_at": plan.created_at.isoformat() if plan.created_at else None
            })
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment plans retrieved successfully",
            "treatment_plans": treatment_plan_list,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_items": total_items,
                "items_per_page": limit
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.get("/get-treatment-plan/{treatment_plan_id}",
    status_code=status.HTTP_200_OK,
    summary="Get a treatment plan by ID",
    description="""
    Get detailed information about a specific treatment plan by its unique ID.
    
    Path parameters:
    - treatment_plan_id: Unique identifier of the treatment plan
    
    Returns:
    - Complete treatment plan details
    - The treatment plan must belong to the authenticated doctor
    """
)
async def get_treatment_plan(treatment_plan_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        treatment_plan = db.query(TreatmentPlan).filter(TreatmentPlan.id == treatment_plan_id, TreatmentPlan.doctor == user.id).first()
        if not treatment_plan:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment plan not found"})
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment plan retrieved successfully",
            "treatment_plan": {
                "id": treatment_plan.id,
                "patient_id": treatment_plan.patient_id,
                "date": treatment_plan.date.isoformat() if treatment_plan.date else None,
                "treatment_name": treatment_plan.treatment_name,
                "unit_cost": treatment_plan.unit_cost,
                "quantity": treatment_plan.quantity,
                "discount": treatment_plan.discount,
                "discount_type": treatment_plan.discount_type,
                "amount": treatment_plan.amount,
                "treatment_description": treatment_plan.treatment_description,
                "tooth_diagram": treatment_plan.tooth_diagram,
                "created_at": treatment_plan.created_at.isoformat() if treatment_plan.created_at else None
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.patch("/update-treatment-plan/{treatment_plan_id}",
    status_code=status.HTTP_200_OK,
    summary="Update a treatment plan by ID",
    description="""
    Update specific fields of an existing treatment plan.
    
    Path parameters:
    - treatment_plan_id: Unique identifier of the treatment plan to update
    
    The treatment plan must belong to the authenticated doctor.
    
    Only provided fields will be updated. Omitted fields will retain their current values.
    """
)
async def update_treatment_plan(treatment_plan_id: str, request: Request, treatment_plan: TreatmentPlanUpdate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})

        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        existing_treatment_plan = db.query(TreatmentPlan).filter(TreatmentPlan.id == treatment_plan_id, TreatmentPlan.doctor == user.id).first()
        if not existing_treatment_plan:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment plan not found"})
        
        treatment_plan_data = treatment_plan.model_dump(exclude_unset=True)
        
        for field, value in treatment_plan_data.items():
            setattr(existing_treatment_plan, field, value)
            
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment plan updated successfully"
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@catalog_router.delete("/delete-treatment-plan/{treatment_plan_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a treatment plan by ID",
    description="""
    Permanently delete a treatment plan by its unique ID.
    
    Path parameters:
    - treatment_plan_id: Unique identifier of the treatment plan to delete
    
    The treatment plan must belong to the authenticated doctor.
    
    Note: This action cannot be undone. The treatment plan will be permanently removed from the system.
    """
)
async def delete_treatment_plan(treatment_plan_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        treatment_plan = db.query(TreatmentPlan).filter(TreatmentPlan.id == treatment_plan_id, TreatmentPlan.doctor == user.id).first()
        if not treatment_plan:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment plan not found"})

        db.delete(treatment_plan)
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Treatment plan deleted successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})