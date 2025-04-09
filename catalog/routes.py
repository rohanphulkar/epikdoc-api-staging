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
        
        if treatment.clinic_id:
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
        # Calculate amount with proper null handling
        amount = 0
        if treatment.quantity is not None and treatment.unit_cost is not None:
            if treatment.quantity > 0 and treatment.unit_cost > 0:
                amount = treatment.quantity * treatment.unit_cost
        
        new_treatment = Treatment(
            doctor_id=user.id,
            patient_id=patient.id,
            appointment_id=appointment.id,
            treatment_date=treatment.treatment_date,
            treatment_name=treatment.treatment_name,
            tooth_number=treatment.tooth_number,
            treatment_notes=treatment.treatment_notes,
            quantity=treatment.quantity,
            unit_cost=treatment.unit_cost,
            amount=float(amount) if amount else 0.0,
            discount=treatment.discount,
            discount_type=treatment.discount_type,
            treatment_description=treatment.treatment_description,
            tooth_diagram=treatment.tooth_diagram,
            completed=treatment.completed
        )

        if treatment.clinic_id:
            new_treatment.clinic_id = treatment.clinic_id
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
                "amount": float(t.amount) if t.amount else 0.0,
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
                "amount": float(treatment.amount) if treatment.amount else 0.0,
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

        # Calculate amount with proper null handling
        amount = 0
        if existing_treatment.quantity is not None and existing_treatment.unit_cost is not None:
            if existing_treatment.quantity > 0 and existing_treatment.unit_cost > 0:
                amount = existing_treatment.quantity * existing_treatment.unit_cost
        existing_treatment.amount = float(amount) if amount else 0.0
            
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
        
        if treatment_plan.clinic_id:
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
            date=treatment_plan.date or datetime.now(),
            created_at=datetime.now()
        )

        if treatment_plan.clinic_id:
            new_treatment_plan.clinic_id = treatment_plan.clinic_id
            
        db.add(new_treatment_plan)
        db.commit()
        db.refresh(new_treatment_plan)
        
        # Create treatment plan items
        for item in treatment_plan.treatment_plan_items:
            # Calculate amount based on quantity and unit_cost
            amount = 0
            if item.quantity is not None and item.unit_cost is not None:
                if item.quantity > 0 and item.unit_cost > 0:
                    amount = item.quantity * item.unit_cost
                    
            new_treatment_plan_item = Treatment(
                treatment_plan_id=new_treatment_plan.id,
                patient_id=patient.id,
                appointment_id=appointment.id,
                doctor_id=user.id,
                treatment_date=item.treatment_date,
                treatment_name=item.treatment_name,
                tooth_number=item.tooth_number,
                treatment_notes=item.treatment_notes,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                amount=float(amount) if amount else 0.0,
                discount=item.discount,
                discount_type=item.discount_type,
                treatment_description=item.treatment_description,
                tooth_diagram=item.tooth_diagram,
                completed=item.completed
            )
            if treatment_plan.clinic_id:
                new_treatment_plan_item.clinic_id = treatment_plan.clinic_id
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
                    "amount": float(item.amount) if item.amount else 0.0,
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
                "unit_cost": float(item.unit_cost) if item.unit_cost else 0.0,
                "quantity": item.quantity,
                "amount": float(item.amount) if item.amount else 0.0,
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
                "unit_cost": float(item.unit_cost) if item.unit_cost else 0.0,
                "quantity": item.quantity,
                "amount": float(item.amount) if item.amount else 0.0,
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

@catalog_router.post("/create-completed-procedure",
    status_code=status.HTTP_201_CREATED,
    summary="Create a completed procedure",
    description="""
    Create a new completed procedure record.

    Required fields in request body:
    - completed_procedure_items: List of procedure items, each containing:
      - procedure_name: Name of the procedure (string)
      - unit_cost: Cost per unit of procedure (decimal)
      - quantity: Number of units (integer, default: 1)

    Optional fields in request body:
    - clinic_id: ID of the clinic (string)
    - appointment_id: ID of the appointment (string)
    - completed_procedure_items[].procedure_description: Additional description of the procedure (string)
    - completed_procedure_items[].amount: Override calculated amount (decimal)
    
    The amount will be automatically calculated as unit_cost * quantity if not provided.
    The doctor_id will be set from the authenticated user's token.

    Returns:
    - 201: Completed procedure created successfully with procedure ID
    - 401: Authentication required or invalid token
    - 404: Clinic or appointment not found if IDs provided
    - 500: Database or internal server error
    """
)
async def create_completed_procedure(
    request: Request, 
    completed_procedure: CompletedProcedureCreate, 
    db: Session = Depends(get_db)
):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                content={"message": "Authentication required"}
            )

        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                content={"message": "Invalid token"}
            )
        
        # Validate clinic if provided
        clinic_id = None
        if completed_procedure.clinic_id:
            clinic = db.query(Clinic).filter(Clinic.id == completed_procedure.clinic_id).first()
            if not clinic:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND, 
                    content={"message": "Clinic not found"}
                )
            clinic_id = clinic.id
        
        # Validate appointment if provided
        appointment_id = None
        if completed_procedure.appointment_id:
            appointment = db.query(Appointment).filter(Appointment.id == completed_procedure.appointment_id).first()
            if not appointment:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND, 
                    content={"message": "Appointment not found"}
                )
            appointment_id = appointment.id
        
        # Validate procedure items
        if not completed_procedure.completed_procedure_items or len(completed_procedure.completed_procedure_items) == 0:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"message": "At least one procedure item is required"}
            )
            
        # Create completed procedure
        new_completed_procedure = CompletedProcedure(
            doctor_id=user.id,
            clinic_id=clinic_id,
            appointment_id=appointment_id
        )
        
        db.add(new_completed_procedure)
        db.commit()
        db.refresh(new_completed_procedure)

        for item in completed_procedure.completed_procedure_items:
            # Calculate total amount if not provided
            total_amount = item.amount
            if total_amount is None:
                total_amount = item.unit_cost * item.quantity if item.unit_cost and item.quantity and item.unit_cost > 0 and item.quantity > 0 else 0.0
                
            new_completed_procedure_item = CompletedProcedureItem(
                completed_procedure_id=new_completed_procedure.id,
                procedure_name=item.procedure_name,
                unit_cost=item.unit_cost,
                quantity=item.quantity,
                amount=total_amount,
                procedure_description=item.procedure_description
            )
            db.add(new_completed_procedure_item)
        
        db.commit()
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED, 
            content={
                "message": "Completed procedure created successfully",
                "completed_procedure_id": new_completed_procedure.id
            }
        )
        
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            content={"message": f"Internal error: {str(e)}"}
        )

@catalog_router.get("/get-completed-procedures-by-doctor",
    status_code=status.HTTP_200_OK,
    summary="Get paginated completed procedures by doctor",
    description="""
    Retrieve a paginated list of completed procedures for the authenticated doctor.

    Query parameters:
    - page: Page number (integer, min: 1, default: 1)
    - limit: Number of items per page (integer, min: 1, max: 100, default: 10)
    - sort_by: Field to sort by (string, default: created_at)
      Available fields: created_at, procedure_name, unit_cost, quantity, amount
    - sort_order: Sort order (string, options: asc/desc, default: desc)
    - search: Optional search term for procedure name (string)

    Returns:
    - 200: List of completed procedures with pagination info
    - 401: Authentication required or invalid token
    - 500: Database or internal server error
    """
)
async def get_completed_procedures_by_doctor(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)"),
    search: Optional[str] = Query(None, description="Search term for procedure name"),
    db: Session = Depends(get_db)
):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})

        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "User not found"})
        
        # Build base query
        base_query = db.query(CompletedProcedure).filter(CompletedProcedure.doctor_id == user.id)
        
        # Get total count for pagination
        total_procedures = base_query.count()
        total_pages = ceil(total_procedures / limit) if total_procedures > 0 else 1
        
        # Validate page number
        if page > total_pages and total_pages > 0:
            page = total_pages
        
        # Apply sorting
        if sort_by == "created_at":
            sort_column = CompletedProcedure.created_at
        else:
            # For other fields, we need to join with CompletedProcedureItem
            base_query = base_query.join(CompletedProcedureItem)
            
            # Map sort_by to the appropriate column
            if sort_by == "procedure_name":
                sort_column = CompletedProcedureItem.procedure_name
            elif sort_by == "unit_cost":
                sort_column = CompletedProcedureItem.unit_cost
            elif sort_by == "quantity":
                sort_column = CompletedProcedureItem.quantity
            elif sort_by == "amount":
                sort_column = CompletedProcedureItem.amount
            else:
                sort_column = CompletedProcedure.created_at
        
        # Apply search filter if provided
        if search:
            base_query = base_query.join(CompletedProcedureItem, isouter=True).filter(
                CompletedProcedureItem.procedure_name.ilike(f"%{search}%")
            )
            
        # Apply sort order
        base_query = base_query.order_by(asc(sort_column) if sort_order.lower() == "asc" else desc(sort_column))
            
        # Apply pagination
        completed_procedures = base_query.offset((page - 1) * limit).limit(limit).all()
        
        # Format response
        procedures_list = []
        for procedure in completed_procedures:
            # Get items for this procedure
            items = db.query(CompletedProcedureItem).filter(
                CompletedProcedureItem.completed_procedure_id == procedure.id
            ).all()
            
            procedure_items = [
                {
                    "id": item.id,
                    "procedure_name": item.procedure_name,
                    "unit_cost": float(item.unit_cost),
                    "quantity": item.quantity,
                    "amount": float(item.amount),
                    "procedure_description": item.procedure_description
                }
                for item in items
            ]
            
            procedures_list.append({
                "id": procedure.id,
                "clinic_id": procedure.clinic_id,
                "appointment_id": procedure.appointment_id,
                "created_at": procedure.created_at.isoformat() if procedure.created_at else None,
                "updated_at": procedure.updated_at.isoformat() if procedure.updated_at else None,
                "procedure_items": procedure_items
            })
        
        response = {
            "message": "Completed procedures retrieved successfully",
            "completed_procedures": procedures_list,
            "pagination": {
                "total_items": total_procedures,
                "total_pages": total_pages,
                "current_page": page,
                "items_per_page": limit,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }
        return JSONResponse(status_code=status.HTTP_200_OK, content=response)
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})
    
@catalog_router.get("/get-completed-procedures-by-appointment/{appointment_id}",
    status_code=status.HTTP_200_OK,
    summary="Get paginated completed procedures by appointment",
    description="""
    Retrieve a paginated list of completed procedures for a specific appointment.

    Path parameters:
    - appointment_id: Unique identifier of the appointment (string)

    Query parameters:
    - page: Page number (integer, min: 1, default: 1)
    - limit: Number of items per page (integer, min: 1, max: 100, default: 10)
    - sort_by: Field to sort by (string, default: created_at)
      Available fields: created_at, procedure_name, unit_cost, quantity, amount
    - sort_order: Sort order (string, options: asc/desc, default: desc)

    Returns:
    - 200: List of completed procedures with pagination info
    - 401: Authentication required or invalid token
    - 500: Database or internal server error
    """
)
async def get_completed_procedures_by_appointment(
    request: Request,
    appointment_id: str,
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
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "User not found"})
        
        # Validate sort_by field
        valid_sort_fields = ["created_at", "procedure_name", "unit_cost", "quantity", "amount"]
        if sort_by not in valid_sort_fields:
            sort_by = "created_at"
            
        # Build base query
        base_query = db.query(CompletedProcedure).filter(CompletedProcedure.appointment_id == appointment_id)
        
        # Get total count for pagination
        total_procedures = base_query.count()
        total_pages = ceil(total_procedures / limit)
        
        # Validate page number
        if page > total_pages and total_pages > 0:
            page = total_pages
            
        # Apply sorting
        sort_column = getattr(CompletedProcedure, sort_by, CompletedProcedure.created_at)
        base_query = base_query.order_by(asc(sort_column) if sort_order.lower() == "asc" else desc(sort_column))
        
        # Apply pagination
        completed_procedures = base_query.offset((page - 1) * limit).limit(limit).all()
        
        # Format response
        procedures_list = []
        for procedure in completed_procedures:
            # Get items for this procedure
            items = db.query(CompletedProcedureItem).filter(
                CompletedProcedureItem.completed_procedure_id == procedure.id
            ).all()
            
            procedure_items = [
                {
                    "id": item.id,
                    "procedure_name": item.procedure_name,
                    "unit_cost": float(item.unit_cost),
                    "quantity": item.quantity,
                    "amount": float(item.amount),
                    "procedure_description": item.procedure_description
                }
                for item in items
            ]
            
            procedures_list.append({
                "id": procedure.id,
                "clinic_id": procedure.clinic_id,
                "appointment_id": procedure.appointment_id,
                "created_at": procedure.created_at.isoformat() if procedure.created_at else None,
                "updated_at": procedure.updated_at.isoformat() if procedure.updated_at else None,
                "procedure_items": procedure_items
            })
        
        response = {
            "message": "Completed procedures retrieved successfully",
            "completed_procedures": procedures_list,
            "pagination": {
                "total_items": total_procedures,
                "total_pages": total_pages,
                "current_page": page,
                "items_per_page": limit,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }
        return JSONResponse(status_code=status.HTTP_200_OK, content=response)
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

@catalog_router.get("/get-completed-procedure-by-id/{procedure_id}",
    status_code=status.HTTP_200_OK,
    summary="Get a completed procedure by ID",
    description="""
    Retrieve detailed information about a specific completed procedure using its ID.

    Path parameters:
    - procedure_id: Unique identifier of the completed procedure (string)

    Returns:
    - 200: Completed procedure details with its items
    - 401: Authentication required or invalid token
    - 404: Completed procedure not found
    - 500: Database or internal server error
    """
)
async def get_completed_procedure_by_id(
    request: Request,
    procedure_id: str,
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
        
        # Get the completed procedure
        completed_procedure = db.query(CompletedProcedure).filter(
            CompletedProcedure.id == procedure_id,
            CompletedProcedure.doctor_id == user.id
        ).first()
        
        if not completed_procedure:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Completed procedure not found"})
        
        # Get procedure items
        procedure_items = db.query(CompletedProcedureItem).filter(
            CompletedProcedureItem.completed_procedure_id == procedure_id
        ).all()
        
        # Format procedure items
        formatted_items = [
            {
                "id": item.id,
                "procedure_name": item.procedure_name,
                "unit_cost": float(item.unit_cost),
                "quantity": item.quantity,
                "amount": float(item.amount),
                "procedure_description": item.procedure_description
            }
            for item in procedure_items
        ]
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Completed procedure retrieved successfully",
            "completed_procedure": {
                "id": completed_procedure.id,
                "doctor_id": completed_procedure.doctor_id,
                "clinic_id": completed_procedure.clinic_id,
                "appointment_id": completed_procedure.appointment_id,
                "created_at": completed_procedure.created_at.isoformat() if completed_procedure.created_at else None,
                "updated_at": completed_procedure.updated_at.isoformat() if completed_procedure.updated_at else None,
                "procedure_items": formatted_items
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

@catalog_router.get("/search-completed-procedures",
    status_code=status.HTTP_200_OK,
    summary="Search completed procedures",
    description="""
    Search for completed procedures by procedure name and/or appointment ID.

    Query parameters:
    - procedure_name: Search term for procedure name (string, optional)
    - appointment_id: Filter by appointment ID (string, optional)
    - page: Page number (integer, min: 1, default: 1)
    - limit: Number of items per page (integer, min: 1, max: 100, default: 10)
    - sort_by: Field to sort by (string, default: created_at)
      Available fields: created_at, procedure_name, unit_cost, quantity, amount
    - sort_order: Sort order (string, options: asc/desc, default: desc)

    Returns:
    - 200: List of matching completed procedures with pagination info
    - 401: Authentication required or invalid token
    - 500: Database or internal server error
    """
)
async def search_completed_procedures(
    request: Request,
    procedure_name: Optional[str] = Query(None, description="Search term for procedure name"),
    appointment_id: Optional[str] = Query(None, description="Filter by appointment ID"),
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
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "User not found"})

        # Validate sort_by field
        valid_sort_fields = ["created_at", "procedure_name", "unit_cost", "quantity", "amount"]
        if sort_by not in valid_sort_fields:
            sort_by = "created_at"

        # Build base query for completed procedures
        base_query = db.query(CompletedProcedure).filter(CompletedProcedure.doctor_id == user.id)

        # Apply appointment filter if provided
        if appointment_id:
            base_query = base_query.filter(CompletedProcedure.appointment_id == appointment_id)

        # For procedure name search, we need to join with CompletedProcedureItem
        if procedure_name:
            base_query = base_query.join(CompletedProcedureItem).filter(
                CompletedProcedureItem.procedure_name.ilike(f"%{procedure_name}%")
            ).distinct()

        # Get total count for pagination
        total_items = base_query.count()
        total_pages = ceil(total_items / limit) if total_items > 0 else 1
        
        # Validate page number
        if page > total_pages and total_pages > 0:
            page = total_pages

        # Apply sorting
        if sort_by == "created_at":
            sort_column = CompletedProcedure.created_at
        else:
            # For other fields, we need to join with CompletedProcedureItem if not already joined
            if not procedure_name:
                base_query = base_query.join(CompletedProcedureItem)
            
            # Map sort_by to the appropriate column
            if sort_by == "procedure_name":
                sort_column = CompletedProcedureItem.procedure_name
            elif sort_by == "unit_cost":
                sort_column = CompletedProcedureItem.unit_cost
            elif sort_by == "quantity":
                sort_column = CompletedProcedureItem.quantity
            elif sort_by == "amount":
                sort_column = CompletedProcedureItem.amount
            else:
                sort_column = CompletedProcedure.created_at
        
        # Apply sort order
        base_query = base_query.order_by(asc(sort_column) if sort_order.lower() == "asc" else desc(sort_column))
        
        # Apply pagination
        completed_procedures = base_query.offset((page - 1) * limit).limit(limit).all()
        
        # Format response
        procedures_list = []
        for procedure in completed_procedures:
            # Get items for this procedure
            items = db.query(CompletedProcedureItem).filter(
                CompletedProcedureItem.completed_procedure_id == procedure.id
            ).all()
            
            procedure_items = [
                {
                    "id": item.id,
                    "procedure_name": item.procedure_name,
                    "unit_cost": float(item.unit_cost),
                    "quantity": item.quantity,
                    "amount": float(item.amount),
                    "procedure_description": item.procedure_description
                }
                for item in items
            ]
            
            procedures_list.append({
                "id": procedure.id,
                "clinic_id": procedure.clinic_id,
                "appointment_id": procedure.appointment_id,
                "created_at": procedure.created_at.isoformat() if procedure.created_at else None,
                "updated_at": procedure.updated_at.isoformat() if procedure.updated_at else None,
                "procedure_items": procedure_items
            })

        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Completed procedures retrieved successfully",
            "completed_procedures": procedures_list,
            "pagination": {
                "total_items": total_items,
                "total_pages": total_pages,
                "current_page": page,
                "items_per_page": limit,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})

@catalog_router.patch("/update-completed-procedure/{procedure_id}",
    status_code=status.HTTP_200_OK,
    summary="Update a completed procedure",
    description="""
    Update the details of a completed procedure.

    Path parameters:
    - procedure_id: Unique identifier of the completed procedure (string)

    Request body fields (all optional):
    - clinic_id: New clinic ID (string)
    - appointment_id: New appointment ID (string)
    - completed_procedure_items: List of procedure items to update, each containing:
        - id: ID of the procedure item to update (string, required for existing items)
        - procedure_name: Name of the procedure (string)
        - unit_cost: Cost per unit (decimal)
        - quantity: Quantity (integer)
        - amount: Override calculated amount (decimal, optional)
        - procedure_description: Description (string, optional)
        
    Note: If no ID is provided for a procedure item, it will be treated as a new item.
    The amount will be automatically recalculated as unit_cost * quantity if not provided.

    Returns:
    - 200: Completed procedure updated successfully
    - 401: Authentication required or invalid token
    - 404: Completed procedure not found
    - 500: Database or internal server error
    """
)
async def update_completed_procedure(
    request: Request,
    procedure_id: str,
    procedure_data: CompletedProcedureUpdate,
    db: Session = Depends(get_db)
):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "User not found"})
        
        # Find the completed procedure and verify ownership
        completed_procedure = db.query(CompletedProcedure).filter(
            CompletedProcedure.id == procedure_id,
            CompletedProcedure.doctor_id == user.id
        ).first()
        
        if not completed_procedure:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Completed procedure not found"})

        # Update the completed procedure main record
        if procedure_data.clinic_id is not None:
            completed_procedure.clinic_id = procedure_data.clinic_id
        
        if procedure_data.appointment_id is not None:
            completed_procedure.appointment_id = procedure_data.appointment_id
        
        # Update procedure items if provided
        updated_items = []
        if procedure_data.completed_procedure_items:
            for item_data in procedure_data.completed_procedure_items:
                # Check if this is an existing item or a new one
                if item_data.id:
                    # Update existing item
                    item = db.query(CompletedProcedureItem).filter(
                        CompletedProcedureItem.id == item_data.id,
                        CompletedProcedureItem.completed_procedure_id == procedure_id
                    ).first()
                    
                    if item:
                        # Update fields if provided
                        if item_data.procedure_name is not None:
                            item.procedure_name = item_data.procedure_name
                        
                        if item_data.unit_cost is not None:
                            item.unit_cost = item_data.unit_cost
                        
                        if item_data.quantity is not None:
                            item.quantity = item_data.quantity
                        
                        if item_data.procedure_description is not None:
                            item.procedure_description = item_data.procedure_description
                        
                        # Calculate amount if not provided
                        if item_data.amount is not None:
                            item.amount = item_data.amount
                        else:
                            item.amount = item.unit_cost * item.quantity
                        
                        updated_items.append(item)
                else:
                    # Create new item
                    amount = item_data.amount
                    if amount is None:
                        amount = item_data.unit_cost * item_data.quantity if item_data.unit_cost and item_data.quantity else 0.0
                    
                    new_item = CompletedProcedureItem(
                        completed_procedure_id=procedure_id,
                        procedure_name=item_data.procedure_name,
                        unit_cost=item_data.unit_cost,
                        quantity=item_data.quantity,
                        amount=amount,
                        procedure_description=item_data.procedure_description
                    )
                    db.add(new_item)
                    updated_items.append(new_item)
        
        db.commit()    

        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Completed procedure updated successfully",
            "completed_procedure_id": completed_procedure.id
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})
    
@catalog_router.delete("/delete-completed-procedure-item/{item_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a completed procedure item",
    description="""
    Delete a completed procedure item by its ID.
    """
)
async def delete_completed_procedure_item(
    request: Request,
    item_id: str,
    db: Session = Depends(get_db)
):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "User not found"})
        
        # Check if the item exists
        item = db.query(CompletedProcedureItem).filter(
            CompletedProcedureItem.id == item_id
        ).first()
        
        if not item:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Completed procedure item not found"})
        
        # Delete the item
        db.delete(item)
        db.commit()

        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Completed procedure item deleted successfully",
            "item_id": item_id
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})
        


@catalog_router.delete("/delete-completed-procedure/{procedure_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a completed procedure",
    description="""
    Delete a completed procedure by its ID.

    Path parameters:
    - procedure_id: Unique identifier of the completed procedure (string)

    Returns:
    - 200: Completed procedure deleted successfully
    - 401: Authentication required or invalid token
    - 404: Completed procedure not found
    - 500: Database or internal server error
    """
)
async def delete_completed_procedure(
    request: Request,
    procedure_id: str,
    db: Session = Depends(get_db)
):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "User not found"})
        
        # First check if the procedure exists
        completed_procedure = db.query(CompletedProcedure).filter(
            CompletedProcedure.id == procedure_id,
            CompletedProcedure.doctor_id == user.id
        ).first()
        
        if not completed_procedure:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Completed procedure not found"})

        # Delete associated procedure items first to avoid foreign key constraint issues
        db.query(CompletedProcedureItem).filter(
            CompletedProcedureItem.completed_procedure_id == procedure_id
        ).delete()
        
        # Then delete the procedure itself
        db.delete(completed_procedure)
        db.commit()

        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Completed procedure deleted successfully",
            "procedure_id": procedure_id
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Internal error: {str(e)}"})
