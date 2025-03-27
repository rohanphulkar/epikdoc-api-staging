from fastapi import APIRouter, Request, Depends, File, UploadFile, status, Form, Query
from sqlalchemy.orm import Session
from .schemas import *
from .models import *
from patient.models import Patient
from db.db import get_db
from auth.models import User, Clinic
from fastapi.responses import JSONResponse
from utils.auth import verify_token
from sqlalchemy import func, asc, desc, case
import os
from sqlalchemy.exc import SQLAlchemyError
from PIL import Image
import io
import numpy as np
import json
from datetime import datetime
from typing import Optional, List, Dict
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
    - appointment_id: Unique identifier of the appointment (UUID)
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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        clinic = db.query(Clinic).filter(Clinic.id == treatment.clinic_id).first()
        if not clinic:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid clinic ID"})
        
        appointment = db.query(Appointment).filter(Appointment.id == treatment.appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid appointment ID"})
        
        patient = db.query(Patient).filter(Patient.id == treatment.patient_id).first()
        if not patient:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid patient ID"})
        
        # Validate appointment and patient
        if treatment.appointment_id:
            appointment = db.query(Appointment).filter(Appointment.id == treatment.appointment_id).first()
            if not appointment:
                return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid appointment ID"})
        
        if treatment.patient_id:
            patient = db.query(Patient).filter(Patient.id == treatment.patient_id).first()
            if not patient:
                return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid patient ID"})

        # Create treatment record
        new_treatment = Treatment(
            doctor_id=user.id,
            clinic_id=clinic.id,
            patient_id=patient.id,
            appointment_id=appointment.id,
            treatment_date=treatment.treatment_date,
            treatment_name=treatment.treatment_name,
            tooth_number=treatment.tooth_number,
            treatment_notes=treatment.treatment_notes,
            quantity=treatment.quantity,
            unit_cost=treatment.unit_cost,
            amount=treatment.amount,
            discount=treatment.discount,
            discount_type=treatment.discount_type,
            treatment_description=treatment.treatment_description,
            tooth_diagram=treatment.tooth_diagram,
            completed=treatment.completed
        )

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
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
    
        # Get total count
        total = db.query(func.count(Treatment.id)).filter(Treatment.doctor_id == user.id).scalar()
        total_pages = ceil(total / per_page)
        
        # Calculate date ranges for statistics
        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)
        first_day_of_year = today.replace(month=1, day=1)
        
        # Get statistics using a single query for better performance
        stats = db.query(
            func.count(Treatment.id).label('count'),
            func.coalesce(func.sum(Treatment.amount), 0).label('total_amount'),
            func.sum(case((func.date(Treatment.treatment_date) == today, 1), else_=0)).label('today_count'),
            func.coalesce(func.sum(case((func.date(Treatment.treatment_date) == today, Treatment.amount), else_=0)), 0).label('today_amount'),
            func.sum(case((Treatment.treatment_date >= first_day_of_month, 1), else_=0)).label('month_count'),
            func.coalesce(func.sum(case((Treatment.treatment_date >= first_day_of_month, Treatment.amount), else_=0)), 0).label('month_amount'),
            func.sum(case((Treatment.treatment_date >= first_day_of_year, 1), else_=0)).label('year_count'),
            func.coalesce(func.sum(case((Treatment.treatment_date >= first_day_of_year, Treatment.amount), else_=0)), 0).label('year_amount')
        ).filter(Treatment.doctor_id == user.id).first()
        
        # Get paginated treatments with sorting
        sort_column = getattr(Treatment, sort_by)
        if sort_order.lower() == "desc":
            sort_column = sort_column.desc()
            
        treatments = db.query(Treatment)\
            .filter(Treatment.doctor_id == user.id)\
            .order_by(sort_column)\
            .offset((page - 1) * per_page)\
            .limit(per_page)\
            .all()
            
        treatment_list = [
            {
                "id": t.id,
                "patient_id": t.patient_id,
                "appointment_id": t.appointment_id,
                "treatment_plan_id": t.treatment_plan_id,
                "doctor_id": t.doctor_id,
                "clinic_id": t.clinic_id,
                "treatment_date": t.treatment_date.isoformat() if t.treatment_date else None,
                "treatment_name": t.treatment_name,
                "tooth_number": t.tooth_number,
                "treatment_notes": t.treatment_notes,
                "quantity": float(t.quantity) if t.quantity else 0.0,
                "unit_cost": float(t.unit_cost) if t.unit_cost else 0.0,
                "amount": float(t.amount) if t.amount else 0.0,
                "discount": float(t.discount) if t.discount else 0.0,
                "discount_type": t.discount_type,
                "treatment_description": t.treatment_description,
                "tooth_diagram": t.tooth_diagram,
                "completed": t.completed,
                "created_at": t.created_at.isoformat() if t.created_at else None
            }
            for t in treatments
        ]

        # Convert Decimal values to float for JSON serialization
        stats_dict = {
            "today": {
                "count": int(stats.today_count or 0),
                "total_amount": float(stats.today_amount or 0)
            },
            "this_month": {
                "count": int(stats.month_count or 0),
                "total_amount": float(stats.month_amount or 0)
            },
            "this_year": {
                "count": int(stats.year_count or 0),
                "total_amount": float(stats.year_amount or 0)
            },
            "overall": {
                "count": int(stats.count or 0),
                "total_amount": float(stats.total_amount or 0)
            }
        }
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatments retrieved successfully", 
            "treatments": treatment_list,
            "pagination": {
                "total": total,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page
            },
            "statistics": stats_dict
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})
    
@catalog_router.get("/search-treatments",
    status_code=status.HTTP_200_OK,
    summary="Search treatments with pagination and statistics",
    description="""
    Search treatments by treatment name and/or patient ID with optional date range filtering, pagination and statistics.
    
    Query parameters:
    - treatment_name: Search by treatment name (optional)
    - patient_id: Filter by patient ID (optional)
    - appointment_id: Filter by appointment ID (optional)
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
    appointment_id: str = Query(None, description="Filter by appointment ID"),
    start_date: str = Query(None, description="Filter by start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Filter by end date (YYYY-MM-DD)"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="treatment_date", description="Sort field"),
    sort_order: str = Query(default="desc", description="Sort direction"),
    db: Session = Depends(get_db)
):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Build base query
        query = db.query(Treatment).filter(Treatment.doctor_id == user.id)
        
        # Apply filters
        if treatment_name:
            query = query.filter(Treatment.treatment_name.ilike(f"%{treatment_name}%"))
        if patient_id:
            query = query.filter(Treatment.patient_id == patient_id)
        if appointment_id:
            query = query.filter(Treatment.appointment_id == appointment_id)
        if start_date:
            query = query.filter(Treatment.treatment_date >= start_date)
        if end_date:
            query = query.filter(Treatment.treatment_date <= end_date)
            
        # Get statistics for filtered results
        stats = query.with_entities(
            func.count(Treatment.id).label('count'),
            func.coalesce(func.sum(Treatment.amount), 0).label('total_amount')
        ).first()
            
        # Get total count and apply pagination
        total = query.count()
        total_pages = ceil(total / per_page)
        
        # Apply sorting
        sort_column = getattr(Treatment, sort_by)
        if sort_order.lower() == "desc":
            sort_column = sort_column.desc()
            
        treatments = query.order_by(sort_column).offset((page - 1) * per_page).limit(per_page).all()
        
        treatment_list = [
            {
                "id": t.id,
                "patient_id": t.patient_id,
                "appointment_id": t.appointment_id,
                "treatment_plan_id": t.treatment_plan_id,
                "doctor_id": t.doctor_id,
                "clinic_id": t.clinic_id,
                "treatment_date": t.treatment_date.isoformat() if t.treatment_date else None,
                "treatment_name": t.treatment_name,
                "tooth_number": t.tooth_number,
                "treatment_notes": t.treatment_notes,
                "quantity": t.quantity,
                "unit_cost": t.unit_cost,
                "amount": t.amount,
                "discount": t.discount,
                "discount_type": t.discount_type,
                "treatment_description": t.treatment_description,
                "tooth_diagram": t.tooth_diagram,
                "completed": t.completed,
                "created_at": t.created_at.isoformat() if t.created_at else None
            }
            for t in treatments
        ]
        
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
                    "count": stats.count or 0,
                    "total_amount": float(stats.total_amount) or 0.0
                }
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

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
                            "appointment_id": "appointment-uuid",
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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Get treatment
        treatment = db.query(Treatment).filter(
            Treatment.id == treatment_id,
            Treatment.doctor_id == user.id
        ).first()
        
        if not treatment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment not found"})
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment retrieved successfully",
            "treatment": {
                "id": treatment.id,
                "patient_id": treatment.patient_id,
                "appointment_id": treatment.appointment_id,
                "treatment_plan_id": treatment.treatment_plan_id,
                "doctor_id": treatment.doctor_id,
                "clinic_id": treatment.clinic_id,
                "treatment_date": treatment.treatment_date.isoformat() if treatment.treatment_date else None,
                "treatment_name": treatment.treatment_name,
                "tooth_number": treatment.tooth_number,
                "treatment_notes": treatment.treatment_notes,
                "quantity": treatment.quantity,
                "unit_cost": treatment.unit_cost,
                "amount": treatment.amount,
                "discount": treatment.discount,
                "discount_type": treatment.discount_type,
                "treatment_description": treatment.treatment_description,
                "tooth_diagram": treatment.tooth_diagram,
                "completed": treatment.completed,
                "created_at": treatment.created_at.isoformat() if treatment.created_at else None
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Get and update treatment
        existing_treatment = db.query(Treatment).filter(
            Treatment.id == treatment_id,
            Treatment.doctor_id == user.id
        ).first()
        
        if not existing_treatment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment not found"})
            
        treatment_data = treatment.model_dump(exclude_unset=True)
        for field, value in treatment_data.items():
            setattr(existing_treatment, field, value)
            
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment updated successfully",
            "treatment_id": existing_treatment.id
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Get and delete treatment
        treatment = db.query(Treatment).filter(
            Treatment.id == treatment_id,
            Treatment.doctor_id == user.id
        ).first()
        
        if not treatment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment not found"})

        db.delete(treatment)
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment deleted successfully",
            "treatment_id": treatment_id
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

@catalog_router.post("/create-treatment-plan",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new treatment plan",
    description="""
    Create a new treatment plan in the system.
    
    The treatment plan will be associated with the authenticated doctor and specified patient.
    
    Required fields:
    - patient_id: ID of the patient
    - appointment_id: ID of the appointment
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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        clinic = db.query(Clinic).filter(Clinic.id == treatment_plan.clinic_id).first()
        if not clinic:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid clinic ID"})
        
        appointment = db.query(Appointment).filter(Appointment.id == treatment_plan.appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid appointment ID"})
        
        patient = db.query(Patient).filter(Patient.id == treatment_plan.patient_id).first()
        if not patient:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid patient ID"})
        
        # Validate patient exists
        if treatment_plan.patient_id:
            patient = db.query(Patient).filter(Patient.id == treatment_plan.patient_id).first()
            if not patient:
                return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Patient not found"})
        
        # Validate appointment exists
        if treatment_plan.appointment_id:
            appointment = db.query(Appointment).filter(Appointment.id == treatment_plan.appointment_id).first()
            if not appointment:
                return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment not found"})
        
        # Create treatment plan
        new_treatment_plan = TreatmentPlan(
            doctor_id=user.id,
            patient_id=patient.id,
            appointment_id=appointment.id,
            clinic_id=clinic.id,
            date=treatment_plan.date or datetime.now(),
            created_at=datetime.now()
        )
        db.add(new_treatment_plan)
        db.commit()
        db.refresh(new_treatment_plan)
        
        # Create treatment plan items
        for item in treatment_plan.treatment_plan_items:
            new_treatment_plan_item = Treatment(
                treatment_plan_id=new_treatment_plan.id,
                patient_id=patient.id,
                appointment_id=appointment.id,
                doctor_id=user.id,
                clinic_id=clinic.id,
                treatment_date=item.treatment_date,
                treatment_name=item.treatment_name,
                tooth_number=item.tooth_number,
                treatment_notes=item.treatment_notes,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                amount=item.amount,
                discount=item.discount,
                discount_type=item.discount_type,
                treatment_description=item.treatment_description,
                tooth_diagram=item.tooth_diagram,
                completed=item.completed
            )
            db.add(new_treatment_plan_item)
        
        db.commit()
        
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={
            "message": "Treatment plan created successfully",
            "treatment_plan_id": new_treatment_plan.id
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

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
        # Validate authentication
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
                TreatmentPlan.doctor_id == user.id,
                func.date(TreatmentPlan.created_at) == today
            ).count(),
            "month": db.query(TreatmentPlan).filter(
                TreatmentPlan.doctor_id == user.id,
                TreatmentPlan.created_at >= month_start
            ).count(),
            "year": db.query(TreatmentPlan).filter(
                TreatmentPlan.doctor_id == user.id,
                TreatmentPlan.created_at >= year_start
            ).count(),
            "total": db.query(TreatmentPlan).filter(
                TreatmentPlan.doctor_id == user.id
            ).count()
        }

        # Build query with sorting
        query = db.query(TreatmentPlan).filter(TreatmentPlan.doctor_id == user.id)
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
        
        # Build response data
        for plan in treatment_plans:
            treatment_plan_items = [
                {
                    "id": item.id,
                    "patient_id": item.patient_id,
                    "appointment_id": item.appointment_id,
                    "doctor_id": item.doctor_id,
                    "clinic_id": item.clinic_id,
                    "treatment_date": item.treatment_date.isoformat() if item.treatment_date else None,
                    "treatment_name": item.treatment_name,
                    "tooth_number": item.tooth_number,
                    "treatment_notes": item.treatment_notes,
                    "quantity": item.quantity,
                    "unit_cost": item.unit_cost,
                    "amount": item.amount,
                    "discount": item.discount,
                    "discount_type": item.discount_type,
                    "treatment_description": item.treatment_description,
                    "tooth_diagram": item.tooth_diagram,
                    "completed": item.completed,
                    "created_at": item.created_at.isoformat() if item.created_at else None
                }
                for item in db.query(Treatment)
                .filter(Treatment.treatment_plan_id == plan.id)
                .all()
            ]
            
            treatment_plan_list.append({
                "id": plan.id,
                "patient_id": plan.patient_id,
                "appointment_id": plan.appointment_id,
                "date": plan.date.isoformat() if plan.date else None,
                "treatment_plan_items": treatment_plan_items,
                "created_at": plan.created_at.isoformat() if plan.created_at else None,
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
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

@catalog_router.get("/search-treatment-plans",
    status_code=status.HTTP_200_OK,
    summary="Search treatment plans with pagination",
    description="""
    Search treatment plans by various criteria with pagination support.
    
    Query parameters:
    - patient_id: Filter by patient ID
    - appointment_id: Filter by appointment ID 
    - treatment_name: Filter by treatment name
    - completed: Filter by treatment completion status (true/false)
    - start_date: Filter by start date (YYYY-MM-DD)
    - end_date: Filter by end date (YYYY-MM-DD)
    - page: Page number (default: 1)
    - limit: Number of items per page (default: 10)
    - sort_by: Field to sort by (default: created_at)
    - sort_order: Sort order (asc/desc, default: desc)
    
    Returns:
    - Filtered list of treatment plans with all their treatments
    - Pagination metadata
    """
)
async def search_treatment_plans(
    request: Request,
    patient_id: str = Query(None, description="Patient ID to filter by"),
    appointment_id: str = Query(None, description="Appointment ID to filter by"),
    treatment_name: str = Query(None, description="Filter by treatment name"),
    completed: bool = Query(None, description="Filter by completion status"),
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)"),
    db: Session = Depends(get_db)
):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
            
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Build base query
        query = db.query(TreatmentPlan).distinct()
        
        # Apply base filters
        query = query.filter(TreatmentPlan.doctor_id == user.id)
        
        if patient_id:
            query = query.filter(TreatmentPlan.patient_id == patient_id)
        if appointment_id:
            query = query.filter(TreatmentPlan.appointment_id == appointment_id)
        if start_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                query = query.filter(TreatmentPlan.date >= start)
            except ValueError:
                return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid start_date format"})
        if end_date:
            try:
                end = datetime.strptime(end_date, "%Y-%m-%d")
                query = query.filter(TreatmentPlan.date <= end)
            except ValueError:
                return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid end_date format"})
            
        # Get treatment plans that have matching treatments if treatment filters are applied
        if treatment_name is not None or completed is not None:
            matching_plan_ids = db.query(Treatment.treatment_plan_id).distinct()
            if treatment_name:
                matching_plan_ids = matching_plan_ids.filter(Treatment.treatment_name.ilike(f"%{treatment_name}%"))
            if completed is not None:
                matching_plan_ids = matching_plan_ids.filter(Treatment.completed == completed)
            query = query.filter(TreatmentPlan.id.in_(matching_plan_ids))
            
        # Apply sorting
        valid_sort_fields = ["created_at", "date", "patient_id", "appointment_id"]
        if sort_by not in valid_sort_fields:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": f"Invalid sort field. Must be one of: {', '.join(valid_sort_fields)}"})
            
        sort_column = getattr(TreatmentPlan, sort_by)
        if sort_order.lower() not in ["asc", "desc"]:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Sort order must be 'asc' or 'desc'"})
            
        query = query.order_by(desc(sort_column) if sort_order.lower() == "desc" else asc(sort_column))

        # Apply pagination
        total_items = query.count()
        total_pages = (total_items + limit - 1) // limit
        
        if page > total_pages and total_pages > 0:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": f"Page number exceeds total pages ({total_pages})"})
            
        offset = (page - 1) * limit
        treatment_plans = query.offset(offset).limit(limit).all()
        
        treatment_plan_list = []
        for plan in treatment_plans:
            # Get ALL treatments for this plan, regardless of filters
            treatments = db.query(Treatment).filter(Treatment.treatment_plan_id == plan.id).all()
            
            treatment_plan_items = [{
                "id": item.id,
                "treatment_name": item.treatment_name,
                "unit_cost": float(item.unit_cost),
                "quantity": item.quantity,
                "amount": float(item.amount),
                "discount": float(item.discount) if item.discount else None,
                "discount_type": item.discount_type,
                "treatment_description": item.treatment_description,
                "tooth_diagram": item.tooth_diagram,
                "tooth_number": item.tooth_number,
                "treatment_notes": item.treatment_notes,
                "completed": item.completed,
                "treatment_date": item.treatment_date.isoformat() if item.treatment_date else None,
                "doctor_id": item.doctor_id,
                "clinic_id": item.clinic_id
            } for item in treatments]
            
            treatment_plan_list.append({
                "id": plan.id,
                "patient_id": plan.patient_id,
                "appointment_id": plan.appointment_id,
                "date": plan.date.isoformat() if plan.date else None,
                "doctor_id": plan.doctor_id,
                "clinic_id": plan.clinic_id,
                "treatment_plan_items": treatment_plan_items,
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
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Get treatment plan
        treatment_plan = db.query(TreatmentPlan).filter(
            TreatmentPlan.id == treatment_plan_id,
            TreatmentPlan.doctor_id == user.id
        ).first()
        
        if not treatment_plan:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment plan not found"})
        
        # Get treatment plan items
        treatment_plan_items = [
            {
                "id": item.id,
                "treatment_name": item.treatment_name,
                "unit_cost": item.unit_cost,
                "quantity": item.quantity,
                "amount": item.amount,
                "discount": item.discount,
                "discount_type": item.discount_type,
                "treatment_description": item.treatment_description,
                "tooth_diagram": item.tooth_diagram,
                "completed": item.completed
            }
            for item in db.query(Treatment)
            .filter(Treatment.treatment_plan_id == treatment_plan.id)
            .all()
        ]
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment plan retrieved successfully",
            "treatment_plan": {
                "id": treatment_plan.id,
                "patient_id": treatment_plan.patient_id,
                "appointment_id": treatment_plan.appointment_id,
                "date": treatment_plan.date.isoformat() if treatment_plan.date else None,
                "treatment_plan_items": treatment_plan_items,
                "created_at": treatment_plan.created_at.isoformat() if treatment_plan.created_at else None
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})

        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        # Get treatment plan
        existing_treatment_plan = db.query(TreatmentPlan).filter(
            TreatmentPlan.id == treatment_plan_id,
            TreatmentPlan.doctor_id == user.id
        ).first()
        
        if not existing_treatment_plan:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment plan not found"})
        
        # Update treatment plan fields
        treatment_plan_data = treatment_plan.model_dump(exclude_unset=True)
        treatment_plan_items = treatment_plan_data.pop('treatment_plan_items', [])

        for field, value in treatment_plan_data.items():
            setattr(existing_treatment_plan, field, value)

        # Update treatment plan items
        for item in treatment_plan_items:
            if item.get('id'):
                # Update existing item
                existing_item = db.query(Treatment).filter(
                    Treatment.id == item['id'],
                    Treatment.treatment_plan_id == treatment_plan_id
                ).first()
                
                if existing_item:
                    for field, value in item.items():
                        if value is not None:
                            setattr(existing_item, field, value)
            else:
                # Create new item
                new_item = Treatment(
                    treatment_plan_id=treatment_plan_id,
                    **item
                )
                db.add(new_item)

        db.commit()
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment plan updated successfully",
            "treatment_plan_id": treatment_plan_id
        })
    
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

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
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})

        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})

        # Get treatment plan
        treatment_plan = db.query(TreatmentPlan).filter(
            TreatmentPlan.id == treatment_plan_id,
            TreatmentPlan.doctor_id == user.id
        ).first()
        
        if not treatment_plan:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment plan not found"})
        
        # Delete treatment plan items first
        db.query(Treatment).filter(
            Treatment.treatment_plan_id == treatment_plan_id
        ).delete()
        
        # Delete treatment plan
        db.delete(treatment_plan)
        db.commit()

        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment plan deleted successfully",
            "treatment_plan_id": treatment_plan_id
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

@catalog_router.get("/mark-treatment-as-completed/{treatment_plan_item_id}")
async def mark_treatment(request: Request, treatment_plan_item_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})

        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid token"})
        
        treatment_plan_item = db.query(Treatment).filter(Treatment.id == treatment_plan_item_id).first()

        if not treatment_plan_item:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment plan item not found"})
        
        treatment_plan_item.completed = True
        db.commit()
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Treatment status updated successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})