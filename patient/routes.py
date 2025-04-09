from fastapi import APIRouter, Request, Depends, File, UploadFile, status, Form, Query
from sqlalchemy.orm import Session
from .schemas import *
from .models import *
from db.db import get_db
from auth.models import User
from fastapi.responses import JSONResponse
from utils.auth import verify_token
from sqlalchemy import select, func
import os
from sqlalchemy.exc import SQLAlchemyError
from PIL import Image
import io
import numpy as np
import json
from datetime import datetime, time
from typing import Optional, List
from appointment.models import Appointment
from math import ceil
from catalog.models import Treatment, TreatmentPlan
from sqlalchemy import case, cast, Integer, or_
from payment.models import Payment, Invoice, InvoiceItem
from appointment.models import Appointment
from catalog.models import *
from prediction.models import *
from auth.models import Clinic
from datetime import date


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
    - clinic_id: ID of the clinic where patient is being registered (optional)
    - name: Patient's full name
    - mobile_number: Primary contact number
    - gender: Patient's gender (male/female/other)
    - email: Valid email address
    - date_of_birth: Date of birth in YYYY-MM-DD format
    
    Optional fields:
    - secondary_mobile: Alternative contact number 
    - contact_number: Additional contact number
    - address: Full residential address
    - locality: Area/neighborhood
    - city: City name
    - pincode: Postal code
    - national_id: Government ID number
    - abha_id: ABHA health ID
    - blood_group: Blood group (A+, B+, AB+, O+, A-, B-, AB-, O-)
    - occupation: Patient's profession
    - relationship: Relationship status
    - medical_history: Previous medical conditions
    - referred_by: Referral source
    - groups: Patient groups/categories
    - patient_notes: Additional clinical notes
    - allergies: Patient's allergies
    - habits: Patient's habits or lifestyle factors
    - weight: Patient's weight in kg
    - height: Patient's height in cm
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Returns:
    - 201: Patient created successfully with patient ID
    - 400: Invalid request data or database error
    - 401: Unauthorized access or invalid clinic association
    - 500: Internal server error
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
                    "examples": {
                        "invalid_data": {
                            "value": {"message": "Invalid data: Missing required fields"}
                        },
                        "db_error": {
                            "value": {"message": "Database error: [error details]"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "value": {"message": "Unauthorized"}
                        },
                        "unauthorized_clinic": {
                            "value": {"message": "You are not authorized to access this clinic"}
                        }
                    }
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
        
        # check if clinic is associated with the doctor
        if patient.clinic_id:
            clinic = db.execute(select(Clinic).filter(Clinic.id == patient.clinic_id, Clinic.doctors.any(User.id == user.id))).scalar_one_or_none()
            if not clinic:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED, 
                    content={"message": "You are not authorized to access this clinic"}
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
            age=age,
            address=patient.address,
            locality=patient.locality,
            city=patient.city,
            pincode=patient.pincode,
            national_id=patient.national_id,
            abha_id=patient.abha_id,
            blood_group=patient.blood_group,
            occupation=patient.occupation,
            relationship=patient.relationship,
            medical_history=patient.medical_history,
            referred_by=patient.referred_by,
            groups=patient.groups,
            patient_notes=patient.patient_notes,
            allergies=patient.allergies,
            habits=patient.habits,
            weight=patient.weight,
            height=patient.height
        )
        
        if patient.clinic_id:
            new_patient.clinic_id = patient.clinic_id

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
    summary="Get all patients with statistics",
    description="""
    Retrieve all patients associated with the authenticated doctor with detailed statistics.
    
    Returns a paginated list of patient records with complete details including:
    - Personal information (name, age, gender, contact details)
    - Medical information (blood group, history, notes)
    - Administrative data (patient number, created date)
    - Address details (locality, city, pincode)
    
    Also includes statistics for:
    - Today's registered patients count
    - This month's registered patients count 
    - This year's registered patients count
    - Overall patients count
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10, max: 100)
    - sort_by: Sort field (default: created_at)
    - sort_order: Sort direction - asc or desc (default: desc)
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "List of all patients with statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "patients": [{
                            "id": "uuid",
                            "patient_number": "P12345",
                            "name": "John Doe",
                            "mobile_number": "+1234567890", 
                            "contact_number": "+1987654321",
                            "email": "john@example.com",
                            "secondary_mobile": "+1122334455",
                            "gender": "male",
                            "address": "123 Main St",
                            "locality": "Downtown",
                            "city": "New York",
                            "pincode": "10001",
                            "national_id": "ABC123456",
                            "abha_id": "ABHA12345",
                            "date_of_birth": "1988-01-15",
                            "age": "35",
                            "anniversary_date": "2015-06-20",
                            "blood_group": "O+",
                            "occupation": "Engineer",
                            "relationship": "Single",
                            "medical_history": "No major issues",
                            "referred_by": "Dr. Smith",
                            "groups": "Regular",
                            "patient_notes": "Regular checkup needed",
                            "created_at": "2023-01-01T00:00:00"
                        }],
                        "statistics": {
                            "today": {
                                "count": 5
                            },
                            "month": {
                                "count": 45
                            },
                            "year": {
                                "count": 250
                            },
                            "overall": {
                                "count": 1000
                            }
                        },
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
                    "examples": {
                        "invalid_token": {
                            "value": {"message": "Invalid authentication token"}
                        },
                        "expired_token": {
                            "value": {"message": "Authentication token has expired"}
                        },
                        "missing_token": {
                            "value": {"message": "Authentication token is missing"}
                        }
                    }
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "example": {"message": "Invalid query parameters"}
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
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="created_at", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort direction (asc/desc)"),
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

        # Get statistics
        today = datetime.now().date()
        first_day_of_month = today.replace(day=1)
        first_day_of_year = today.replace(month=1, day=1)

        today_stats = db.query(func.count(Patient.id)).filter(
            Patient.doctor_id == decoded_token.get("user_id"),
            func.date(Patient.created_at) == today
        ).scalar()

        month_stats = db.query(func.count(Patient.id)).filter(
            Patient.doctor_id == decoded_token.get("user_id"),
            Patient.created_at >= first_day_of_month
        ).scalar()

        year_stats = db.query(func.count(Patient.id)).filter(
            Patient.doctor_id == decoded_token.get("user_id"),
            Patient.created_at >= first_day_of_year
        ).scalar()

        overall_stats = db.query(func.count(Patient.id)).filter(
            Patient.doctor_id == decoded_token.get("user_id")
        ).scalar()
        
        # Build query with sorting
        query = select(Patient).where(Patient.doctor_id == decoded_token.get("user_id"))
        
        if hasattr(Patient, sort_by):
            sort_column = getattr(Patient, sort_by)
            if sort_order.lower() == 'desc':
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
                
        # Get paginated patients
        patients = db.execute(
            query.offset(offset).limit(per_page)
        ).scalars().all()
        
        # Convert patients to list of dictionaries
        patient_list = []
        for patient in patients:
            patient_dict = {
                "id": patient.id,
                "doctor_id": patient.doctor_id,
                "clinic_id": patient.clinic_id,
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
                "abha_id": patient.abha_id,
                "date_of_birth": patient.date_of_birth,
                "age": patient.age,
                "anniversary_date": patient.anniversary_date,
                "blood_group": patient.blood_group,
                "occupation": patient.occupation,
                "relationship": patient.relationship,
                "medical_history": patient.medical_history,
                "referred_by": patient.referred_by,
                "groups": patient.groups,
                "patient_notes": patient.patient_notes,
                "created_at": patient.created_at
            }
            patient_list.append(patient_dict)
        
        return {
            "patients": patient_list,
            "statistics": {
                "today": {
                    "count": today_stats or 0
                },
                "month": {
                    "count": month_stats or 0
                },
                "year": {
                    "count": year_stats or 0
                },
                "overall": {
                    "count": overall_stats or 0
                }
            },
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
    - Appointment history
    - Payment history
    - Invoices
    
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
                        "doctor_id": "uuid",
                        "clinic_id": "uuid",
                        "patient_number": "P12345",
                        "name": "John Doe",
                        "mobile_number": "+1234567890",
                        "contact_number": "+0987654321",
                        "email": "john@example.com",
                        "secondary_mobile": "+1122334455",
                        "gender": "male",
                        "address": "123 Main St",
                        "locality": "Downtown",
                        "city": "Metropolis",
                        "pincode": "123456",
                        "national_id": "ABC123456",
                        "abha_id": "ABHA123456",
                        "date_of_birth": "1988-01-01T00:00:00",
                        "age": "35",
                        "anniversary_date": "2010-06-15T00:00:00",
                        "blood_group": "O+",
                        "occupation": "Engineer",
                        "relationship": "Married",
                        "medical_history": "Hypertension",
                        "allergies": "Peanuts",
                        "habits": "Non-smoker",
                        "weight": "75",
                        "height": "180",
                        "referred_by": "Dr. Smith",
                        "groups": "Regular",
                        "patient_notes": "Regular checkup needed",
                        "created_at": "2023-01-01T10:00:00",
                        "appointments": [
                            {
                                "id": "uuid",
                                "date": "2023-02-15T14:00:00",
                                "status": "completed",
                                "reason": "Tooth pain",
                                 "payments": [
                            {
                                "id": "uuid",
                                "amount": 5000,
                                "payment_method": "card",
                                "status": "completed",
                                "date": "2023-02-15T15:30:00"
                            }
                        ],
                        "invoices": [
                            {
                                "id": "uuid",
                                "invoice_number": "INV-001",
                                "total_amount": 5000,
                                "date": "2023-02-15T15:00:00",
                                "items": [
                                    {
                                        "id": "uuid",
                                        "name": "Root Canal Treatment",
                                        "quantity": 1,
                                        "unit_price": 5000
                                    }
                                ]
                            }
                        ]
                            }
                        ],
                        "treatments": [
                            {
                                "id": "uuid",
                                "treatment_id": "uuid",
                                "name": "Root Canal",
                                "status": "completed",
                                "date": "2023-02-15T14:30:00"
                            }
                        ],
                        "clinical_notes": [
                            {
                                "id": "uuid",
                                "notes": "Patient reported tooth pain",
                                "created_at": "2023-02-10T09:15:00"
                            }
                        ],
                        "treatment_plans": [
                            {
                                "id": "uuid",
                                "name": "Dental Restoration Plan",
                                "status": "active",
                                "created_at": "2023-02-10T09:30:00"
                            }
                        ],
                        "completed_procedures": [
                            {
                                "id": "uuid",
                                "procedure_name": "Root Canal",
                                "unit_cost": 5000,
                                "quantity": 1,
                                "amount": 5000,
                                "procedure_description": "Root Canal Treatment",
                                "created_at": "2023-02-15T14:30:00",
                                "updated_at": "2023-02-15T14:30:00"
                            }
                        ]
                    }
                }
            }
        },
        400: {
            "description": "Bad Request - Missing patient ID",
            "content": {
                "application/json": {
                    "example": {"message": "Patient ID is required"}
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
        if not decoded_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"message": "Unauthorized"}
            )
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"message": "Unauthorized"}
            )
        
        if not patient_id:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"message": "Patient ID is required"}
            )
        
        # Get patient by ID
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == user.id
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
            "clinic_id": patient.clinic_id,
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
            "abha_id": patient.abha_id,
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            "age": patient.age,
            "anniversary_date": patient.anniversary_date.isoformat() if patient.anniversary_date else None,
            "blood_group": patient.blood_group,
            "occupation": patient.occupation,
            "relationship": patient.relationship,
            "medical_history": patient.medical_history,
            "referred_by": patient.referred_by,
            "groups": patient.groups,
            "patient_notes": patient.patient_notes,
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
        }

        treatments = []
        clinical_notes = []
        treatment_plans = []
        appointments = []
        payments = []
        invoices = []
        completed_procedures = []

        
        db_appointments = db.execute(
            select(Appointment).filter(
                Appointment.patient_id == patient_id,
                Appointment.doctor_id == user.id
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
                "notes": str(appointment.notes).split(",") if appointment.notes else [],
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

            db_treatments = db.execute(
                select(Treatment).filter(
                    Treatment.patient_id == patient_id,
                    Treatment.appointment_id == appointment.id
                )
            ).scalars().all()

            db_clinical_notes = db.execute(
                select(ClinicalNote).filter(
                    ClinicalNote.patient_id == patient_id,
                    ClinicalNote.appointment_id == appointment.id
                )
            ).scalars().all()

            db_treatment_plans = db.execute(
                select(TreatmentPlan).filter(
                    TreatmentPlan.patient_id == patient_id,
                    TreatmentPlan.appointment_id == appointment.id
                )
            ).scalars().all()

            db_payments = db.execute(
                select(Payment).filter(
                    Payment.patient_id == patient_id,
                    Payment.appointment_id == appointment.id
                )
            ).scalars().all()

            db_invoices = db.execute(
                select(Invoice).filter(
                    Invoice.patient_id == patient_id,
                    Invoice.appointment_id == appointment.id
                )
            ).scalars().all()
               
            db_completed_procedures = db.execute(
                select(CompletedProcedure).filter(
                    CompletedProcedure.appointment_id == appointment.id
                )
            ).scalars().all()
            
            for treatment in db_treatments:
                treatment_data = {
                    "id": treatment.id,
                    "treatment_date": treatment.treatment_date.isoformat() if treatment.treatment_date else None,
                    "treatment_name": treatment.treatment_name,
                    "tooth_number": treatment.tooth_number,
                    "treatment_notes": treatment.treatment_notes,
                    "quantity": treatment.quantity,
                    "unit_cost": treatment.unit_cost,
                    "amount": treatment.amount,
                    "discount": treatment.discount,
                    "discount_type": treatment.discount_type,
                    "doctor_id": treatment.doctor_id,
                    "created_at": treatment.created_at.isoformat() if treatment.created_at else None
                }
                treatments.append(treatment_data)

            for treatment_plan in db_treatment_plans:
                treatment_plan_data = {
                    "id": treatment_plan.id,
                    "date": treatment_plan.date.isoformat() if treatment_plan.date else None,
                    "created_at": treatment_plan.created_at.isoformat() if treatment_plan.created_at else None
                }

                treatment_plan_items = [
                    {
                        "id": item.id,
                        "treatment_name": item.treatment_name,
                        "unit_cost": item.unit_cost,
                        "quantity": item.quantity,
                        "discount": item.discount,
                        "discount_type": item.discount_type,
                        "amount": item.amount,
                        "treatment_description": item.treatment_description,
                        "tooth_diagram": item.tooth_diagram,
                    } for item in db.query(Treatment)
                    .filter(Treatment.treatment_plan_id == treatment_plan.id)
                ]

                treatment_plan_data["items"] = treatment_plan_items

                treatment_plans.append(treatment_plan_data)

            for clinical_note in db_clinical_notes:
                clinical_note_data = {
                    "id": clinical_note.id,
                    "complaints": [{
                        "id": complaint.id,
                        "complaint": complaint.complaint,
                        "created_at": complaint.created_at.isoformat() if complaint.created_at else None
                    } for complaint in clinical_note.complaints],
                    "diagnosis": [{ 
                        "id": diagnosis.id,
                        "diagnosis": diagnosis.diagnosis,
                        "created_at": diagnosis.created_at.isoformat() if diagnosis.created_at else None
                    } for diagnosis in clinical_note.diagnoses],
                    "vital_signs": [{
                        "id": vital_sign.id,
                        "vital_sign": vital_sign.vital_sign,
                        "created_at": vital_sign.created_at.isoformat() if vital_sign.created_at else None
                    } for vital_sign in clinical_note.vital_signs],
                    "created_at": clinical_note.created_at.isoformat() if clinical_note.created_at else None,
                    "attachments": [
                        {
                            "id": attachment.id,
                            "attachment": attachment.attachment,
                            "created_at": attachment.created_at.isoformat() if attachment.created_at else None
                        } for attachment in clinical_note.attachments
                    ],
                    "treatments": [
                        {
                            "id": treatment.id,
                            "name": treatment.name,
                            "created_at": treatment.created_at.isoformat() if treatment.created_at else None
                        } for treatment in clinical_note.treatments
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
                        } for medicine in clinical_note.medicines
                    ]
                }
                clinical_notes.append(clinical_note_data)     

            for payment in db_payments:
                payment_data = {
                    "id": payment.id,
                    "date": payment.date.isoformat() if payment.date else None,
                    "patient_id": payment.patient_id,
                    "doctor_id": payment.doctor_id,
                    "clinic_id": payment.clinic_id,
                    "invoice_id": payment.invoice_id,
                    "appointment_id": payment.appointment_id,
                    "patient_number": payment.patient_number,
                    "patient_name": payment.patient_name,
                    "receipt_number": payment.receipt_number,
                    "treatment_name": payment.treatment_name,
                    "amount_paid": payment.amount_paid,
                    "invoice_number": payment.invoice_number,
                    "notes": payment.notes,
                    "payment_mode": payment.payment_mode,
                    "status": payment.status,
                    "refund": payment.refund,
                    "refund_receipt_number": payment.refund_receipt_number,
                    "refunded_amount": payment.refunded_amount,
                    "cancelled": payment.cancelled,
                    "created_at": payment.created_at.isoformat() if payment.created_at else None,
                    "updated_at": payment.updated_at.isoformat() if payment.updated_at else None
                }
                payments.append(payment_data)

            for invoice in db_invoices:
                invoice_items = [
                    {
                        "id": item.id,
                        "invoice_id": item.invoice_id,
                        "treatment_name": item.treatment_name,
                        "unit_cost": item.unit_cost,
                        "quantity": item.quantity,
                        "discount": item.discount,
                        "discount_type": item.discount_type,
                        "type": item.type,
                        "invoice_level_tax_discount": item.invoice_level_tax_discount,
                        "tax_name": item.tax_name,
                        "tax_percent": item.tax_percent,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                        "updated_at": item.updated_at.isoformat() if item.updated_at else None
                    } for item in invoice.invoice_items
                ]
                invoice_data = {
                    "id": invoice.id,
                    "date": invoice.date.isoformat() if invoice.date else None,
                    "patient_id": invoice.patient_id,
                    "doctor_id": invoice.doctor_id,
                    "clinic_id": invoice.clinic_id,
                    "payment_id": invoice.payment_id,
                    "appointment_id": invoice.appointment_id,
                    "patient_number": invoice.patient_number,
                    "patient_name": invoice.patient_name,
                    "doctor_name": invoice.doctor_name,
                    "invoice_number": invoice.invoice_number,
                    "cancelled": invoice.cancelled,
                    "notes": invoice.notes,
                    "description": invoice.description,
                    "file_path": invoice.file_path,
                    "total_amount": invoice.total_amount,
                    "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
                    "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
                    "items": invoice_items
                }
                invoices.append(invoice_data)
            
            for completed_procedure in db_completed_procedures:
                completed_procedure_data = {
                    "id": completed_procedure.id,
                    "appointment_id": completed_procedure.appointment_id,
                    "doctor_id": completed_procedure.doctor_id,
                    "clinic_id": completed_procedure.clinic_id,
                    "procedure_name": completed_procedure.procedure_name,
                    "unit_cost": completed_procedure.unit_cost,
                    "quantity": completed_procedure.quantity,
                    "amount": completed_procedure.amount,
                    "procedure_description": completed_procedure.procedure_description,
                    "created_at": completed_procedure.created_at.isoformat() if completed_procedure.created_at else None,
                    "updated_at": completed_procedure.updated_at.isoformat() if completed_procedure.updated_at else None
                }
                completed_procedures.append(completed_procedure_data)

            appointment_data["treatments"] = treatments
            appointment_data["clinical_notes"] = clinical_notes
            appointment_data["treatment_plans"] = treatment_plans
            appointment_data["payments"] = payments
            appointment_data["invoices"] = invoices
            appointment_data["completed_procedures"] = completed_procedures
            appointments.append(appointment_data)
        
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
    summary="Search patients by name, mobile number, age, gender and other criteria",
    description="""
    Search and filter patients using various criteria.
    
    Available search filters:
    - name: Partial match on patient name
    - mobile_number: Partial match on mobile number 
    - min_age: Minimum age for filtering
    - max_age: Maximum age for filtering
    - date_of_birth: Exact date of birth (YYYY-MM-DD)
    - date_of_birth_after: Filter patients born after this date
    - date_of_birth_before: Filter patients born before this date
    - gender: Exact match (male/female/other)
    - abha_id: Partial match on ABHA ID
    - created_at_date: Filter patients created on a specific date (YYYY-MM-DD)
    - today: Boolean flag to filter patients created today (default: false)
    - recent: Boolean flag to get patients created in the last 7 days (default: false)
    
    Pagination parameters:
    - page: Page number (default: 1)
    - per_page: Results per page (default: 10, max: 100)
    - sort_by: Field to sort by (default: created_at)
    - sort_order: Sort direction (asc/desc, default: desc)
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "List of matching patients with pagination and statistics",
            "content": {
                "application/json": {
                    "example": {
                        "items": [{
                            "id": "uuid",
                            "name": "John Doe",
                            "mobile_number": "+1234567890", 
                            "gender": "male",
                            "age": "35",
                            "date_of_birth": "1988-01-01",
                            "abha_id": "1234567890",
                            "created_at": "2023-01-01T10:00:00"
                        }],
                        "pagination": {
                            "total": 100,
                            "page": 1,
                            "per_page": 10,
                            "pages": 10
                        },
                        "stats": {
                            "today": 5,
                            "this_month": 25,
                            "this_year": 150,
                            "overall": 500
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
async def search_patients(
    request: Request,
    name: Optional[str] = None,
    mobile_number: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    date_of_birth: Optional[datetime] = None,
    date_of_birth_after: Optional[datetime] = None,
    date_of_birth_before: Optional[datetime] = None,
    gender: Optional[Gender] = None,
    abha_id: Optional[str] = None,
    created_at_date: Optional[date] = None,
    today: bool = False,
    recent: bool = False,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="created_at", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort direction (asc/desc)"),
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        doctor_id = decoded_token.get("user_id")
        
        # Base query - use a join to ensure we get all patient fields
        query = select(Patient).where(Patient.doctor_id == doctor_id)
        
        # Add filters for each field if provided
        if name:
            query = query.where(func.lower(Patient.name).contains(func.lower(name)))
        if mobile_number:
            query = query.where(Patient.mobile_number.contains(mobile_number))
        if gender:
            query = query.where(Patient.gender == gender)
        if abha_id:
            query = query.where(Patient.abha_id.contains(abha_id))

        # Add age range filter - handle both string and integer age values
        if min_age is not None:
            # Try both numeric comparison and string pattern matching
            query = query.where(
                or_(
                    cast(Patient.age, Integer) >= min_age,
                    Patient.age.like(f"{min_age}%"),
                    Patient.age.like(f"%{min_age}%")
                )
            )
        if max_age is not None:
            query = query.where(
                or_(
                    cast(Patient.age, Integer) <= max_age,
                    func.length(Patient.age) <= len(str(max_age))
                )
            )

        # Add date of birth filters
        if date_of_birth:
            query = query.where(func.date(Patient.date_of_birth) == date_of_birth.date())
        if date_of_birth_after:
            query = query.where(func.date(Patient.date_of_birth) >= date_of_birth_after.date())
        if date_of_birth_before:
            query = query.where(func.date(Patient.date_of_birth) <= date_of_birth_before.date())
            
        # Add created_at date filters
        if today:
            today_date = datetime.now().date()
            today_start = datetime.combine(today_date, time.min)
            today_end = datetime.combine(today_date, time.max)
            query = query.where(Patient.created_at.between(today_start, today_end))
        elif recent:
            # Filter patients created in the last 7 days
            today_date = datetime.now().date()
            seven_days_ago = today_date.replace(day=today_date.day - 7)
            seven_days_ago_start = datetime.combine(seven_days_ago, time.min)
            today_end = datetime.combine(today_date, time.max)
            query = query.where(Patient.created_at.between(seven_days_ago_start, today_end))
        elif created_at_date:
            date_start = datetime.combine(created_at_date, time.min)
            date_end = datetime.combine(created_at_date, time.max)
            query = query.where(Patient.created_at.between(date_start, date_end))

        # Get total count for pagination before applying sorting and pagination
        count_query = select(func.count()).select_from(query.subquery())
        total = db.execute(count_query).scalar() or 0
        
        # Add sorting
        if recent:
            # Override sort settings for recent patients
            query = query.order_by(Patient.created_at.desc())
        elif hasattr(Patient, sort_by):
            sort_column = getattr(Patient, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        else:
            # Default sort if invalid column specified
            query = query.order_by(Patient.created_at.desc())
            
        # Add pagination
        query = query.offset((page - 1) * per_page).limit(per_page)
            
        # Execute query
        patients = db.execute(query).scalars().all()
        
        # Format patient data for response
        patient_list = []
        for patient in patients:
            patient_data = {
                "id": patient.id,
                "doctor_id": patient.doctor_id,
                "clinic_id": patient.clinic_id,
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
                "abha_id": patient.abha_id,
                "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
                "age": patient.age,
                "anniversary_date": patient.anniversary_date.isoformat() if patient.anniversary_date else None,
                "blood_group": patient.blood_group,
                "occupation": patient.occupation,
                "relationship": patient.relationship,
                "medical_history": patient.medical_history,
                "allergies": patient.allergies,
                "habits": patient.habits,
                "weight": patient.weight,
                "height": patient.height,
                "referred_by": patient.referred_by,
                "groups": patient.groups,
                "patient_notes": patient.patient_notes,
                "created_at": patient.created_at.isoformat() if patient.created_at else None
            }
            patient_list.append(patient_data)
        
        # Calculate total pages
        pages = (total + per_page - 1) // per_page if total else 0

        # Get statistics
        today_date = datetime.now().date()
        today_start = datetime.combine(today_date, time.min)
        today_end = datetime.combine(today_date, time.max)

        # Statistics queries
        total_count = db.execute(
            select(func.count(Patient.id))
            .where(Patient.doctor_id == doctor_id)
        ).scalar() or 0

        today_count = db.execute(
            select(func.count(Patient.id))
            .where(Patient.doctor_id == doctor_id)
            .where(Patient.created_at.between(today_start, today_end))
        ).scalar() or 0

        month_count = db.execute(
            select(func.count(Patient.id))
            .where(Patient.doctor_id == doctor_id)
            .where(Patient.created_at >= datetime.combine(today_date.replace(day=1), time.min))
        ).scalar() or 0

        year_count = db.execute(
            select(func.count(Patient.id))
            .where(Patient.doctor_id == doctor_id)
            .where(Patient.created_at >= datetime.combine(today_date.replace(month=1, day=1), time.min))
        ).scalar() or 0
        
        return {
            "items": patient_list,
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": pages
            },
            "stats": {
                "today": today_count,
                "this_month": month_count,
                "this_year": year_count,
                "overall": total_count
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
    - mobile_number: Primary contact number
    - contact_number: Secondary contact number
    - email: Email address
    - secondary_mobile: Alternative mobile number
    - gender: Gender (male/female/other)
    - date_of_birth: Date of birth (YYYY-MM-DD)
    - anniversary_date: Anniversary date (YYYY-MM-DD)
    - address: Full address
    - locality: Area/locality
    - city: City name
    - pincode: Postal code
    - blood_group: Blood group
    - occupation: Professional occupation
    - relationship: Relationship status
    - medical_history: Medical history notes
    - referred_by: Referral source
    - groups: Patient groups/categories
    - patient_notes: Additional notes
    - national_id: National ID number
    - abha_id: ABHA ID number
    - allergies: Patient's allergies
    - habits: Patient's habits or lifestyle factors
    - weight: Patient's weight in kg
    - height: Patient's height in cm
    - clinic_id: ID of the clinic where patient is registered
    
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
                            "contact_number": "+0987654321",
                            "gender": "male",
                            "age": "45",
                            "blood_group": "O+",
                            "address": "123 Main St",
                            "city": "Mumbai",
                            "pincode": "400001",
                            "medical_history": "No major issues",
                            "allergies": "Penicillin",
                            "habits": "Non-smoker",
                            "weight": 75,
                            "height": 180,
                            "created_at": "2023-01-01T10:00:00",
                            "updated_at": "2023-06-15T14:30:00"
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
            "description": "Unauthorized - Invalid or missing authentication token or clinic access",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "value": {"message": "Unauthorized"}
                        },
                        "unauthorized_clinic": {
                            "value": {"message": "You are not authorized to access this clinic"}
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
async def update_patient(
    request: Request,
    patient_id: str,
    patient_update: PatientUpdateSchema,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                content={"message": "Unauthorized"}
            )

        user = db.execute(select(User).filter(User.id == decoded_token.get("user_id"))).scalar_one_or_none()
        if not user:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                content={"message": "Unauthorized"}
            )
        
        # Get patient
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == user.id
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )
        
        # Check if clinic is associated with the doctor
        if patient_update.clinic_id:
            clinic = db.execute(
                select(Clinic).filter(
                    Clinic.id == patient_update.clinic_id,
                    Clinic.doctors.any(User.id == user.id)
                )
            ).scalar_one_or_none()
            
            if not clinic:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED, 
                    content={"message": "You are not authorized to access this clinic"}
                )

        # Update patient fields
        update_data = patient_update.dict(exclude_unset=True, exclude_none=True)
        for field, value in update_data.items():
            setattr(patient, field, value)
            
        # Update age if date_of_birth is updated
        if 'date_of_birth' in update_data and patient.date_of_birth is not None:
            patient.age = calculate_age(patient.date_of_birth)

        db.commit()
        
        # Convert patient to dictionary for response
        patient_dict = {
            "id": patient.id,
            "name": patient.name,
            "mobile_number": patient.mobile_number,
            "contact_number": patient.contact_number,
            "email": patient.email,
            "secondary_mobile": patient.secondary_mobile,
            "gender": patient.gender.value if patient.gender else None,
            "address": patient.address,
            "locality": patient.locality,
            "city": patient.city,
            "pincode": patient.pincode,
            "national_id": patient.national_id,
            "abha_id": patient.abha_id,
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            "age": patient.age,
            "anniversary_date": patient.anniversary_date.isoformat() if patient.anniversary_date else None,
            "blood_group": patient.blood_group,
            "occupation": patient.occupation,
            "relationship": patient.relationship,
            "medical_history": patient.medical_history,
            "allergies": patient.allergies,
            "habits": patient.habits,
            "weight": patient.weight,
            "height": patient.height,
            "referred_by": patient.referred_by,
            "groups": patient.groups,
            "patient_notes": patient.patient_notes,
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
        }
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "Patient updated successfully",
                "patient": patient_dict
            }
        )
        
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.get(
    "/get-health-info/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Get patient health information",
    description="""
    Retrieve health-related information for a specific patient.
    
    Path parameters:
    - patient_id: UUID of the patient
    
    Returns health information including:
    - allergies: Patient's allergies
    - habits: Patient's habits or lifestyle factors
    - weight: Patient's weight in kg
    - height: Patient's height in cm
    - medical_history: Previous medical conditions
    - blood_group: Patient's blood group
    
    Required headers:
    - Authorization: Bearer {access_token}
    """,
    responses={
        200: {
            "description": "Health information retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Health info fetched successfully",
                        "health_info": {
                            "allergies": "Penicillin, Peanuts",
                            "habits": "Smoking, Alcohol consumption",
                            "weight": 75.5,
                            "height": 175.0,
                            "medical_history": "Hypertension, Diabetes",
                            "blood_group": "O+"
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized access",
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
                    "example": {"message": "Internal server error: {error_details}"}
                }
            }
        }
    }
)
async def get_health_info(
    request: Request,
    patient_id: str,
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
        
        # Get patient
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == user.id
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )
        
        # Get all appointments for this patient
        health_info = {
            "allergies": patient.allergies,
            "habits": patient.habits,
            "weight": patient.weight,
            "height": patient.height,
            "medical_history": patient.medical_history,
            "blood_group": patient.blood_group,
        }
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "Health info fetched successfully", "health_info": health_info}
        )
        
    except SQLAlchemyError as e:
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
    clinic_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id")
        
        # Get patient
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == user_id
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )
        
        # check if clinic is associated with the doctor
        if clinic_id:
            clinic = db.execute(
                select(Clinic).filter(
                    Clinic.id == clinic_id,
                    Clinic.doctors.any(User.id == user_id)
                )
            ).scalar_one_or_none()
            
            if not clinic:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED, 
                    content={"message": "You are not authorized to access this clinic"}
                )

        # Delete all payments and invoices
        # First get all invoice IDs for this patient
        invoice_ids = [row[0] for row in db.query(Invoice.id).filter(Invoice.patient_id == patient_id).all()]
        
        # Delete invoice items for all patient's invoices
        if invoice_ids:
            db.query(InvoiceItem).filter(InvoiceItem.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
            
        # Delete payments
        db.query(Payment).filter(Payment.patient_id == patient_id).delete(synchronize_session=False)
        
        # Delete invoices
        db.query(Invoice).filter(Invoice.patient_id == patient_id).delete(synchronize_session=False)

        # Delete all treatments and treatment plans
        db.query(Treatment).filter(Treatment.patient_id == patient_id).delete(synchronize_session=False)
        db.query(TreatmentPlan).filter(TreatmentPlan.patient_id == patient_id).delete(synchronize_session=False)

        # Delete all X-rays and predictions
        xray_ids = [row[0] for row in db.query(XRay.id).filter(XRay.patient == patient_id).all()]
        if xray_ids:
            prediction_ids = [row[0] for row in db.query(Prediction.id).filter(Prediction.xray_id.in_(xray_ids)).all()]
            if prediction_ids:
                db.query(Legend).filter(Legend.prediction_id.in_(prediction_ids)).delete(synchronize_session=False)
            db.query(Prediction).filter(Prediction.xray_id.in_(xray_ids)).delete(synchronize_session=False)
        db.query(XRay).filter(XRay.patient == patient_id).delete(synchronize_session=False)

        # Delete all clinical notes and related data
        clinical_note_ids = [row[0] for row in db.query(ClinicalNote.id).filter(ClinicalNote.patient_id == patient_id).all()]
        if clinical_note_ids:
            db.query(Medicine).filter(Medicine.clinical_note_id.in_(clinical_note_ids)).delete(synchronize_session=False)
            db.query(ClinicalNoteTreatment).filter(ClinicalNoteTreatment.clinical_note_id.in_(clinical_note_ids)).delete(synchronize_session=False)
        db.query(ClinicalNote).filter(ClinicalNote.patient_id == patient_id).delete(synchronize_session=False)

        # Delete all appointments
        db.query(Appointment).filter(Appointment.patient_id == patient_id).delete(synchronize_session=False)

        # Finally delete the patient
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
    "/create-clinical-note/{patient_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Create a clinical note with complaints, diagnoses, vital signs, treatments, medicines and attachments",
    description="""
    Create a comprehensive clinical note for a patient including complaints, diagnoses, vital signs, and optional treatments, medicines and file attachments.
    
    **Path Parameters:**
    - patient_id: UUID of the patient
    
    **Query Parameters:**
    - clinic_id: UUID of the clinic where the note is being created
    - appointment_id (optional): UUID of the associated appointment
    
    **Form Data:**
    - complaints (optional): Patient's chief complaints
    - diagnoses (optional): Doctor's diagnoses
    - vital_signs (optional): Patient vital signs data in JSON format
        [
            temperature
            blood_pressure
            pulse
            respiratory_rate
        ]
    - notes (optional): Additional clinical notes
    - treatments (optional): JSON array of treatments
        [
            {
                "name": "Treatment name",           // Required\
            }
        ]
    - medicines (optional): JSON array of medicines
        [
            {
                "item_name": "Medicine name",        // Required
                "quantity": 1,                       // Optional, default: 1
                "price": 10.50,                      // Optional, default: 0
                "dosage": "1 tablet twice daily",    // Optional
                "instructions": "After meals",       // Optional
                "amount": 10.50                      // Optional, auto-calculated as price * quantity
            }
        ]
    - files (optional): List of file attachments (images, documents etc)
        - Supported formats: jpg, jpeg, png, pdf, doc, docx
        - Max file size: 5MB per file
        - Files are stored in uploads/medical_records/
    
    **Authentication:**
    - Required: Bearer token in Authorization header
    - Token must be for the doctor associated with the patient
    
    **Database Operations:**
    - Creates entries in clinical_notes table
    - Creates related entries in complaints, diagnoses, vital_signs tables
    - Optionally creates entries in notes, clinical_note_treatments, medicines, and clinical_note_attachments tables
    - All entries are properly linked with appropriate foreign keys
    
    **Notes:**
    - The doctor must have permission to access the specified clinic
    - File paths are stored in database, files saved to disk
    - Medicine amount is auto-calculated as price * quantity if not provided
    - All monetary values should be in the system's default currency
    """,
    responses={
        201: {
            "description": "Clinical note created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Clinical note created successfully",
                        "clinical_note_id": "550e8400-e29b-41d4-a716-446655440000"
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
                            "value": {"message": "Required fields missing: complaints, diagnoses, vital_signs"}
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
                        },
                        "unauthorized_clinic": {
                            "value": {"message": "You are not authorized to access this clinic"}
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
async def create_clinical_note(
    request: Request,
    patient_id: str,
    clinic_id: Optional[str] = None,
    appointment_id: Optional[str] = None,
    complaints: str = Form(None),
    diagnoses: str = Form(None),
    vital_signs: str = Form(None),
    notes: str = Form(None),
    treatments: str = Form(None),  # JSON string of treatments
    medicines: str = Form(None),   # JSON string of medicines
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db)
):
    try:
        # Verify user and get patient
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"message": "Invalid authentication token"}
            )
        
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == user.id
            )
        ).scalar_one_or_none()

        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )
        
        # check if clinic is associated with the doctor
        if clinic_id:
            clinic = db.execute(select(Clinic).filter(Clinic.id == clinic_id, Clinic.doctors.any(User.id == user.id))).scalar_one_or_none()
            if not clinic:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED, 
                    content={"message": "You are not authorized to access this clinic"}
                )
        
        # Check appointment only if appointment_id is provided
        appointment = None
        if appointment_id:
            appointment = db.execute(select(Appointment).filter(Appointment.id == appointment_id)).scalar_one_or_none()
            if not appointment:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"message": "Appointment not found"}
                )

        # Create medical record
        clinical_note_db = ClinicalNote(
            patient_id=patient.id,
            clinic_id=clinic.id if clinic else None,
            doctor_id=user.id,
            appointment_id=appointment.id if appointment else None,
            date=datetime.now().date()
        )

        db.add(clinical_note_db)
        db.commit()
        db.refresh(clinical_note_db)

        # Parse string inputs to lists
        complaints_list = json.loads(complaints) if complaints else None
        diagnoses_list = json.loads(diagnoses) if diagnoses else None
        vital_signs_list = json.loads(vital_signs) if vital_signs else None
        treatments_list = json.loads(treatments) if treatments else None
        medicines_list = json.loads(medicines) if medicines else None
        notes_list = json.loads(notes) if notes and notes.startswith("[") else [notes] if notes else None

        if complaints_list:
            for complaint in complaints_list:
                db_complaint = Complaint(
                    clinical_note_id=clinical_note_db.id,
                    complaint=complaint
                )
                db.add(db_complaint)

        if diagnoses_list:
            for diagnosis in diagnoses_list:
                db_diagnosis = Diagnosis(
                    clinical_note_id=clinical_note_db.id,
                    diagnosis=diagnosis
                )
                db.add(db_diagnosis)

        if vital_signs_list:
            # Process vital signs
            for vital_sign in vital_signs_list:
                db_vital_sign = VitalSign(
                    clinical_note_id=clinical_note_db.id,
                    vital_sign=vital_sign
                )
                db.add(db_vital_sign)
            
        # Handle file attachments
        if files:
            attachments = []
            os.makedirs("uploads/clinical_notes", exist_ok=True)
            
            for file in files:
                file_ext = os.path.splitext(str(file.filename))[1]
                file_path = f"uploads/clinical_notes/{generate_uuid()}{file_ext}"
                
                with open(file_path, "wb") as f:
                    f.write(await file.read())

                attachments.append(ClinicalNoteAttachment(
                    clinical_note_id=clinical_note_db.id,
                    attachment=file_path
                ))

            db.add_all(attachments)

        # Add treatments if provided
        if treatments:
            try:
                treatments_db = []
                for treatment in treatments_list:
                    treatment_db = ClinicalNoteTreatment(
                        clinical_note_id=clinical_note_db.id,
                        name=treatment.get("name", "")
                    )
                    treatments_db.append(treatment_db)
                
                if treatments_db:
                    db.add_all(treatments_db)
            except json.JSONDecodeError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"message": "Invalid JSON format for treatments"}
                )

        # Add medicines if provided
        if medicines:
            try:
                medicines_db = []
                for medicine in medicines_list:
                    quantity = int(medicine.get("quantity", 1))
                    price = float(medicine.get("price", 0))
                    # Calculate amount if not provided, otherwise use the provided amount
                    amount = float(medicine.get("amount", price * quantity))
                    
                    medicine_db = Medicine(
                        clinical_note_id=clinical_note_db.id,
                        item_name=medicine.get("item_name", ""),
                        quantity=quantity,
                        price=price,
                        amount=amount,
                        dosage=medicine.get("dosage"),
                        instructions=medicine.get("instructions")
                    )
                    medicines_db.append(medicine_db)
                
                if medicines_db:
                    db.add_all(medicines_db)
            except json.JSONDecodeError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"message": "Invalid JSON format for medicines"}
                )

        # Add notes if provided
        if notes_list:
            notes_db = []
            for note in notes_list:
                db_note = Notes(
                    clinical_note_id=clinical_note_db.id,
                    note=note
                )
                notes_db.append(db_note)
            
            if notes_db:
                db.add_all(notes_db)

        db.commit()
        
        return {
            "message": "Clinical note created successfully",
            "clinical_note_id": clinical_note_db.id
        }
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, 
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        db.rollback()  # Added rollback for any other exceptions
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )
    
@patient_router.get("/get-clinical-notes",
    response_model=dict,
    status_code=200,
    summary="Get clinical notes for a patient",
    description="""
    Retrieve all clinical notes for a specific patient.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Query parameters:
    - patient_id: UUID of the patient
    """,
    responses={
        200: {
            "description": "Clinical notes retrieved successfully",
            "content": {
                "application/json": {
                    "example": [{
                        "id": "uuid",
                        "patient_id": "uuid",
                        "doctor_id": "uuid",
                        "notes": "Patient examination notes",
                        "treatments": [{
                            "id": "uuid",
                            "name": "Treatment name"
                        }],
                        "medicines": [{
                            "id": "uuid",
                            "item_name": "Medicine name",
                            "quantity": 1,
                            "price": 100,
                            "amount": 100,
                            "dosage": "1-0-1",
                            "instructions": "After food"
                        }],
                        "attachments": [],
                        "vital_signs": [],
                        "complaints": [],
                        "diagnoses": [],
                        "created_at": "2023-01-01T00:00:00"
                    }]
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
async def get_clinical_notes(
    request: Request,
    patient_id: str,
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

        # Get clinical notes
        clinical_notes = db.query(ClinicalNote).filter_by(patient_id=patient.id).order_by(ClinicalNote.created_at.desc()).all()

        # Get additional data for each clinical note
        for note in clinical_notes:
            note.treatments = db.query(ClinicalNoteTreatment).filter_by(clinical_note_id=note.id).all()
            note.medicines = db.query(Medicine).filter_by(clinical_note_id=note.id).all()
            note.attachments = db.query(ClinicalNoteAttachment).filter_by(clinical_note_id=note.id).all()
            note.vital_signs = db.query(VitalSign).filter_by(clinical_note_id=note.id).all()
            note.complaints = db.query(Complaint).filter_by(clinical_note_id=note.id).all()
            note.diagnoses = db.query(Diagnosis).filter_by(clinical_note_id=note.id).all()

        return clinical_notes
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )
    