from fastapi import APIRouter, Request, Depends, File, UploadFile, status, Form, Query
from sqlalchemy.orm import Session
from .schemas import *
from .models import *
from db.db import get_db
from auth.models import User
from fastapi.responses import JSONResponse
from utils.auth import verify_token
from sqlalchemy import insert, select, update, delete, func
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

patient_router = APIRouter()

def calculate_age(date_of_birth: datetime) -> str:
    if not date_of_birth:
        return None
    today = datetime.today()
    age = today.year - date_of_birth.year
    return str(age)

@patient_router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new patient record",
    description="""
    Create a new patient record in the system.
    
    Required fields:
    - name: Patient's full name
    - mobile_number: Primary contact number
    - gender: Patient's gender (male/female/other)
    - email: Valid email address
    - date_of_birth: Date of birth in YYYY-MM-DD format
    
    Optional fields:
    - secondary_mobile: Alternative contact number
    - address: Full residential address
    - blood_group: Blood group
    - medical_history: Previous medical conditions
    - remarks: Additional notes
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        201: {
            "description": "Patient created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Patient created successfully",
                        "patient_id": "uuid"
                    }
                }
            }
        },
        400: {
            "description": "Invalid request data or database error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error: [error details]"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: [error details]"}
                }
            }
        }
    }
)
async def create_patient(
    request: Request, 
    patient: PatientCreateSchema, 
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        user = db.execute(select(User).filter(User.id == decoded_token.get("user_id"))).scalar_one_or_none()
        if not user:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                content={"message": "Unauthorized"}
            )
        
        # calculate age
        age = calculate_age(patient.date_of_birth)
        
        # Create new patient record
        new_patient = Patient(
            doctor_id=user.id,
            name=patient.name,
            mobile_number=patient.mobile_number,
            gender=patient.gender,
            email=patient.email,
            date_of_birth=patient.date_of_birth,
            age=age
        )

        # Save to database
        db.add(new_patient)
        db.commit()
        db.refresh(new_patient)
        
        return {
            "message": "Patient created successfully",
            "patient_id": new_patient.id
        }
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, 
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.get(
    "/get-all",
    status_code=status.HTTP_200_OK,
    summary="Get all patients for authenticated doctor",
    description="""
    Retrieve all patients associated with the authenticated doctor.
    
    Returns a paginated list of patient records with complete details including:
    - Personal information (name, age, gender, contact details)
    - Medical information (blood group, history, notes)
    - Administrative data (patient number, created date)
    - Address details (locality, city, pincode)
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "List of all patients retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "patients": [{
                            "id": "uuid",
                            "name": "John Doe",
                            "mobile_number": "+1234567890", 
                            "email": "john@example.com",
                            "gender": "male",
                            "age": "35",
                            "blood_group": "O+",
                            "address": "123 Main St",
                            "city": "New York",
                            "created_at": "2023-01-01T00:00:00"
                        }],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: [error details]"}
                }
            }
        }
    }
)
async def get_all_patients(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get total count of patients
        total = db.execute(
            select(func.count()).select_from(Patient).where(
                Patient.doctor_id == decoded_token.get("user_id")
            )
        ).scalar()

        # Calculate pagination values
        total_pages = ceil((total or 0) / per_page)
        offset = (page - 1) * per_page
        
        # Get paginated patients for the authenticated doctor
        patients = db.execute(
            select(Patient)
            .where(Patient.doctor_id == decoded_token.get("user_id"))
            .offset(offset)
            .limit(per_page)
        ).scalars().all()
        
        # Convert patients to list of dictionaries
        patient_list = []
        for patient in patients:
            patient_dict = {
                "id": patient.id,
                "doctor_id": patient.doctor_id,
                "patient_number": patient.patient_number,
                "name": patient.name,
                "mobile_number": patient.mobile_number,
                "contact_number": patient.contact_number,
                "email": patient.email,
                "secondary_mobile": patient.secondary_mobile,
                "gender": patient.gender,
                "address": patient.address,
                "locality": patient.locality,
                "city": patient.city,
                "pincode": patient.pincode,
                "national_id": patient.national_id,
                "date_of_birth": patient.date_of_birth,
                "age": patient.age,
                "anniversary_date": patient.anniversary_date,
                "blood_group": patient.blood_group,
                "remarks": patient.remarks,
                "medical_history": patient.medical_history,
                "referred_by": patient.referred_by,
                "groups": patient.groups,
                "patient_notes": patient.patient_notes,
                "created_at": patient.created_at
            }
            patient_list.append(patient_dict)
        
        return {
            "patients": patient_list,
            "pagination": {
                "total": total or 0,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages
            }
        }
    except SQLAlchemyError as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.get(
    "/get-by-id/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Get detailed patient information by ID",
    description="""
    Retrieve complete patient information including:
    - Personal details
    - Medical history
    - Treatment history
    - Clinical notes
    - Treatment plans
    - Medical records with attachments
    - Appointment history
    
    Required parameters:
    - patient_id: UUID of the patient
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "Patient details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "uuid",
                        "name": "John Doe",
                        "mobile_number": "+1234567890",
                        "email": "john@example.com",
                        "gender": "male",
                        "age": "35",
                        "treatments": [],
                        "clinical_notes": [],
                        "treatment_plans": [],
                        "medical_records": [],
                        "appointments": []
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Patient not found",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: [error details]"}
                }
            }
        }
    }
)
async def get_patient_by_id(
    patient_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get patient by ID
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == decoded_token.get("user_id")
            )
        ).scalar_one_or_none()

        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )

        patient_data = {
            "id": patient.id,
            "doctor_id": patient.doctor_id,
            "patient_number": patient.patient_number,
            "name": patient.name,
            "mobile_number": patient.mobile_number,
            "contact_number": patient.contact_number,
            "email": patient.email,
            "secondary_mobile": patient.secondary_mobile,
            "gender": patient.gender.value,
            "address": patient.address,
            "locality": patient.locality,
            "city": patient.city,
            "pincode": patient.pincode,
            "national_id": patient.national_id,
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            "age": patient.age,
            "anniversary_date": patient.anniversary_date.isoformat() if patient.anniversary_date else None,
            "blood_group": patient.blood_group,
            "remarks": patient.remarks,
            "medical_history": patient.medical_history,
            "referred_by": patient.referred_by,
            "groups": patient.groups,
            "patient_notes": patient.patient_notes,
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
        }

        treatments = []
        clinical_notes = []
        treatment_plans = []
        medical_records = []
        appointments = []

        for treatment in patient.treatments:
            treatment_data = {
                "id": treatment.id,
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
            treatments.append(treatment_data)

        for clinical_note in patient.clinical_notes:
            clinical_note_data = {
                "id": clinical_note.id,
                "date": clinical_note.date.isoformat() if clinical_note.date else None,
                "note_type": clinical_note.note_type,
                "description": clinical_note.description,
                "is_revised": clinical_note.is_revised,
                "created_at": clinical_note.created_at.isoformat() if clinical_note.created_at else None
            }
            clinical_notes.append(clinical_note_data)

        for treatment_plan in patient.treatment_plans:
            treatment_plan_data = {
                "id": treatment_plan.id,
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
            treatment_plans.append(treatment_plan_data)

        for medical_record in patient.medical_records:
            medical_record_data = {
                "id": medical_record.id,
                "complaint": medical_record.complaint,
                "diagnosis": medical_record.diagnosis,
                "vital_signs": medical_record.vital_signs,
                "created_at": medical_record.created_at.isoformat() if medical_record.created_at else None,
                "attachments": [
                    {
                        "id": attachment.id,
                        "attachment": attachment.attachment,
                        "created_at": attachment.created_at.isoformat() if attachment.created_at else None
                    } for attachment in medical_record.attachments
                ],
                "treatments": [
                    {
                        "id": treatment.id,
                        "name": treatment.name,
                        "created_at": treatment.created_at.isoformat() if treatment.created_at else None
                    } for treatment in medical_record.treatments
                ],
                "medicines": [
                    {
                        "id": medicine.id,
                        "item_name": medicine.item_name,
                        "price": medicine.price,
                        "quantity": medicine.quantity,
                        "dosage": medicine.dosage,
                        "instructions": medicine.instructions,
                        "amount": medicine.amount,
                        "created_at": medicine.created_at.isoformat() if medicine.created_at else None
                    } for medicine in medical_record.medicines
                ]
            }
            medical_records.append(medical_record_data)

        db_appointments = db.execute(
            select(Appointment).filter(
                Appointment.patient_id == patient_id,
                Appointment.doctor_id == decoded_token.get("user_id")
            )
        ).scalars().all()

        for appointment in db_appointments:
            appointment_data = {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
                "patient_number": appointment.patient_number,
                "patient_name": appointment.patient_name,
                "doctor_id": appointment.doctor_id,
                "doctor_name": appointment.doctor_name,
                "notes": appointment.notes,
                "appointment_date": appointment.appointment_date.isoformat() if appointment.appointment_date else None,
                "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
                "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
                "status": appointment.status.value,
                "share_on_email": appointment.share_on_email,
                "share_on_sms": appointment.share_on_sms,
                "share_on_whatsapp": appointment.share_on_whatsapp,
                "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
                "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None
            }
            appointments.append(appointment_data)
            
        patient_data["treatments"] = treatments
        patient_data["clinical_notes"] = clinical_notes
        patient_data["treatment_plans"] = treatment_plans
        patient_data["medical_records"] = medical_records
        patient_data["appointments"] = appointments
        return JSONResponse(status_code=200, content=patient_data)
        
    except SQLAlchemyError as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.get(
    "/search",
    status_code=status.HTTP_200_OK,
    summary="Search patients by multiple criteria",
    description="""
    Search for patients using various filters:
    - Text search (name, mobile, ID, email)
    - Gender filter (male/female/other/all)
    - Age range (min and max age)
    
    Query parameters:
    - search_query: Text to search in name/mobile/ID/email
    - gender: Filter by gender (male/female/other/all)
    - min_age: Minimum age filter
    - max_age: Maximum age filter
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10)
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "List of matching patients with pagination info",
            "content": {
                "application/json": {
                    "example": {
                        "items": [{
                            "id": "uuid",
                            "name": "John Doe", 
                            "mobile_number": "+1234567890",
                            "gender": "male",
                            "age": "35"
                        }],
                        "total": 100,
                        "page": 1,
                        "per_page": 10,
                        "pages": 10
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: [error details]"}
                }
            }
        }
    }
)
async def search_patients(
    request: Request,
    search_query: Optional[str] = None,
    gender: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Base query
        query = select(Patient).filter(Patient.doctor_id == decoded_token.get("user_id"))
        
        # Add search filters if search_query provided
        if search_query:
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    Patient.name.ilike(f"%{search_query}%"),
                    Patient.mobile_number.ilike(f"%{search_query}%"),
                    Patient.id.ilike(f"%{search_query}%"),
                    Patient.email.ilike(f"%{search_query}%")
                )
            )
            
        # Add gender filter if provided
        if gender:
            if gender == "male":
                query = query.filter(Patient.gender == Gender.MALE)
            elif gender == "female":
                query = query.filter(Patient.gender == Gender.FEMALE)
            elif gender == "other":
                query = query.filter(Patient.gender == Gender.OTHER)
            elif gender == "all":
                pass
            
        # Add age filter if provided
        if min_age:
            from sqlalchemy import cast, Integer
            query = query.filter(cast(Patient.age, Integer) >= min_age)
        if max_age:
            from sqlalchemy import cast, Integer
            query = query.filter(cast(Patient.age, Integer) <= max_age)
            
        # Get total count for pagination
        from sqlalchemy import func
        total = db.execute(select(func.count()).select_from(query.subquery())).scalar()
        
        # Add pagination
        query = query.offset((page - 1) * per_page).limit(per_page)
            
        # Execute query
        patients = db.execute(query).scalars().all()
        
        # Calculate total pages
        pages = (total + per_page - 1) // per_page if total else 0
        
        return {
            "items": patients,
            "total": total or 0,
            "page": page,
            "per_page": per_page,
            "pages": pages
        }
        
    except SQLAlchemyError as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.patch(
    "/update/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Update patient information",
    description="""
    Update an existing patient's information.
    
    Path parameters:
    - patient_id: UUID of patient to update
    
    Updatable fields:
    - name: Patient's full name
    - mobile_number: Contact number
    - email: Email address
    - gender: Gender (male/female/other)
    - date_of_birth: Date of birth (YYYY-MM-DD)
    - address: Full address
    - blood_group: Blood group
    - medical_history: Medical history notes
    - remarks: Additional notes
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "Patient updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Patient updated successfully",
                        "patient": {
                            "id": "uuid",
                            "name": "John Doe",
                            "email": "john@example.com",
                            "mobile_number": "+1234567890",
                            "gender": "male",
                            "age": "45"
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid request data or database error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error: [error details]"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Patient not found",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: [error details]"}
                }
            }
        }
    }
)
async def update_patient(
    request: Request,
    patient_id: str,
    patient_update: PatientUpdateSchema,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get patient
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == decoded_token.get("user_id")
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )

        # Update patient fields
        update_data = patient_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(patient, field, value)
            
        # Update age if date_of_birth is updated
        if 'date_of_birth' in update_data and patient.date_of_birth is not None:
            patient.age = calculate_age(patient.date_of_birth)

        db.commit()
        db.refresh(patient)
        
        return {
            "message": "Patient updated successfully",
            "patient": patient
        }
        
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.delete(
    "/delete/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete patient record",
    description="""
    Permanently delete a patient record and all associated data.
    
    Path parameters:
    - patient_id: UUID of patient to delete
    
    This will delete:
    - Patient's personal information
    - Medical records
    - Treatment history
    - Appointments
    - Clinical notes
    - All other associated data
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Warning: This action cannot be undone.
    """,
    responses={
        200: {
            "description": "Patient deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Patient deleted successfully"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Patient not found",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: [error details]"}
                }
            }
        }
    }
)
async def delete_patient(
    request: Request,
    patient_id: str,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get patient
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == decoded_token.get("user_id")
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )

        # Delete patient
        db.delete(patient)
        db.commit()
        
        return {
            "message": "Patient deleted successfully"
        }
        
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.post(
    "/create-medical-record/{patient_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Create medical record with treatments, medicines and attachments",
    description="""
    Create a new medical record for a patient with treatments, medicines and file attachments.
    
    **Path Parameters:**
    - patient_id: ID of the patient
    
    **Form Data:**
    - complaint (required): Chief complaint text
    - diagnosis (required): Doctor's diagnosis text  
    - vital_signs (required): Patient vital signs data in JSON format
        {
            "temperature": "98.6",
            "blood_pressure": "120/80",
            "pulse": "72",
            "respiratory_rate": "16"
        }
    - treatments (optional): JSON array of treatments
        [
            {
                "name": "Treatment name"  // Required
            }
        ]
    - medicines (optional): JSON array of medicines
        [
            {
                "name": "Medicine name",          // Required
                "quantity": 1,                    // Optional, default: 1
                "price": 10.50,                  // Optional, default: 0
                "dosage": "1 tablet twice daily", // Optional
                "instructions": "After meals"     // Optional
            }
        ]
    - files (optional): List of file attachments (images, documents etc)
        - Supported formats: jpg, jpeg, png, pdf, doc, docx
        - Max file size: 5MB per file
        - Files are stored in uploads/medical_records/
    
    **Authentication:**
    - Required: Bearer token in Authorization header
    - Token must be for the doctor associated with the patient
    
    **Notes:**
    - Creates a medical record entry with basic details
    - Optionally adds treatments, medicines and file attachments
    - File paths are stored in database, files saved to disk
    - Medicine amount is auto-calculated as price * quantity
    - All monetary values should be in the system's default currency
    """,
    responses={
        201: {
            "description": "Medical record created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Medical record created successfully",
                        "medical_record_id": "550e8400-e29b-41d4-a716-446655440000"
                    }
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_json": {
                            "value": {"message": "Invalid JSON format for treatments or medicines"}
                        },
                        "db_error": {
                            "value": {"message": "Database error: [error details]"}
                        },
                        "missing_fields": {
                            "value": {"message": "Required fields missing: complaint, diagnosis, vital_signs"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "value": {"message": "Invalid authentication token"}
                        },
                        "expired_token": {
                            "value": {"message": "Authentication token has expired"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "Patient not found",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: [error details]"}
                }
            }
        }
    }
)
async def create_medical_record(
    request: Request,
    patient_id: str,
    complaint: str = Form(...),
    diagnosis: str = Form(...),
    vital_signs: str = Form(...),
    treatments: str = Form(None),  # JSON string of treatments
    medicines: str = Form(None),   # JSON string of medicines
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db)
):
    try:
        # Verify user and get patient
        decoded_token = verify_token(request)
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == decoded_token.get("user_id")
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )

        # Create medical record
        medical_record_db = MedicalRecord(
            patient_id=patient.id,
            complaint=complaint,
            diagnosis=diagnosis,
            vital_signs=vital_signs
        )
        db.add(medical_record_db)
        db.commit()
        db.refresh(medical_record_db)

        # Handle file attachments
        if files:
            attachments = []
            os.makedirs("uploads/medical_records", exist_ok=True)
            
            for file in files:
                file_ext = os.path.splitext(str(file.filename))[1]
                file_path = f"uploads/medical_records/{generate_uuid()}{file_ext}"
                
                with open(file_path, "wb") as f:
                    f.write(await file.read())

                attachments.append(MedicalRecordAttachment(
                    medical_record_id=medical_record_db.id,
                    attachment=file_path
                ))

            db.add_all(attachments)

        # Add treatments if provided
        if treatments:
            treatments_list = json.loads(treatments)
            treatments_db = [
                MedicalRecordTreatment(
                    medical_record_id=medical_record_db.id,
                    name=treatment["name"]
                )
                for treatment in treatments_list
            ]
            db.add_all(treatments_db)

        # Add medicines if provided
        if medicines:
            medicines_list = json.loads(medicines)
            medicines_db = [
                Medicine(
                    medical_record_id=medical_record_db.id,
                    item_name=medicine["name"],
                    quantity=medicine.get("quantity", 1),
                    price=medicine.get("price", 0),
                    amount=medicine.get("price", 0) * medicine.get("quantity", 1),
                    dosage=medicine.get("dosage"),
                    instructions=medicine.get("instructions")
                )
                for medicine in medicines_list
            ]
            db.add_all(medicines_db)

        db.commit()
        
        return {
            "message": "Medical record created successfully",
            "medical_record_id": medical_record_db.id
        }
        
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "Invalid JSON format for treatments or medicines"}
        )
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, 
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )