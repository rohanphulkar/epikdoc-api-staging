from fastapi import APIRouter, Request, Depends, File, UploadFile, status, Form
from sqlalchemy.orm import Session
from .schemas import *
from .models import *
from db.db import get_db
from auth.models import User
from fastapi.responses import JSONResponse
from utils.auth import verify_token
from sqlalchemy import insert, select, update, delete
import os
from sqlalchemy.exc import SQLAlchemyError
from PIL import Image
import io
import numpy as np
import json
from datetime import datetime
from typing import Optional, List
from appointment.models import Appointment

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
    response_description="Patient created successfully",
    responses={
        201: {"description": "Patient created successfully"},
        400: {"description": "Invalid request data or database error"},
        401: {"description": "Unauthorized access"},
        500: {"description": "Internal server error"}
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
    summary="Get all patients",
    description="""
    Get all patients associated with the authenticated doctor.
    
    Required headers:
    - Authorization: Bearer {access_token}
    
    Returns array of patient records including:
    - Basic info (name, age, gender)
    - Contact details (phone, email, address)
    - Medical details (blood group, history)
    - Other metadata (created date, notes)
    """,
    responses={
        200: {
            "description": "All patients retrieved successfully",
            "content": {
                "application/json": {
                    "example": [{
                        "id": "uuid",
                        "name": "John Doe",
                        "mobile_number": "+1234567890",
                        "email": "john@example.com",
                        "gender": "male",
                        "age": 35,
                        "blood_group": "O+",
                        "created_at": "2023-01-01T00:00:00"
                    }]
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
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error: {error details}"}
                }
            }
        }
    }
)
async def get_all_patients(
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get all patients for the authenticated doctor
        patients = db.execute(
            select(Patient).where(Patient.doctor_id == decoded_token.get("user_id"))
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
        
        return patient_list
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
    response_description="Patient retrieved successfully",
    responses={
        200: {"description": "Patient retrieved successfully"},
        401: {"description": "Unauthorized access"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
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
                "treatment_date": treatment.treatment_date,
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

@patient_router.get("/search", status_code=status.HTTP_200_OK, response_description="Search patients by name, mobile, ID, email, gender and age range", responses={
    200: {"description": "Returns list of matching patients"},
    401: {"description": "Unauthorized - Invalid or missing authentication token"},
    500: {"description": "Internal server error - Database or server-side error"}
})
async def search_patients(
    request: Request,
    search_query: Optional[str] = None,
    gender: Optional[Gender] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
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
            query = query.filter(Patient.gender == gender)
            
        # Add age filter if provided
        if min_age:
            from sqlalchemy import cast, Integer
            query = query.filter(cast(Patient.age, Integer) >= min_age)
        if max_age:
            from sqlalchemy import cast, Integer
            query = query.filter(cast(Patient.age, Integer) <= max_age)
            
        # Execute query
        patients = db.execute(query).scalars().all()
        
        return patients
        
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
    response_description="Updates an existing patient's information",
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
            "description": "Patient with specified ID not found or does not belong to authenticated doctor",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        },
        500: {
            "description": "Internal server error occurred while processing request",
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
    response_description="Delete a patient record from the system",
    responses={
        200: {
            "description": "Patient deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Patient deleted successfully"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized access - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Invalid or expired token"
                    }
                }
            }
        },
        404: {
            "description": "Patient not found - No patient exists with the provided ID for the authenticated doctor",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Patient not found"
                    }
                }
            }
        },
        500: {
            "description": "Internal server error - Database error or unexpected server error",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Internal server error: error details"
                    }
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
    
    Required parameters:
    - patient_id (path): ID of the patient
    - complaint (form): Chief complaint text
    - diagnosis (form): Doctor's diagnosis text
    - vital_signs (form): Patient vital signs data
    
    Optional parameters:
    - treatments (form): JSON string containing list of treatments
        [
            {
                "name": "Treatment name"
            }
        ]
    - medicines (form): JSON string containing list of medicines with details
        [
            {
                "name": "Medicine name",
                "quantity": 1,
                "price": 0.0,
                "dosage": "Dosage instructions", 
                "instructions": "Usage instructions"
            }
        ]
    - files (form): List of file attachments (images, documents etc)
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        201: {
            "description": "Medical record created successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Medical record created successfully"}
                }
            }
        },
        400: {
            "description": "Invalid request data",
            "content": {
                "application/json": {
                    "example": {"message": "Invalid request data"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing token",
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
                    "example": {"message": "Internal server error"}
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