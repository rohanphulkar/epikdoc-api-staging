from fastapi import APIRouter, Request, Depends, File, UploadFile, status
from sqlalchemy.orm import Session
from .schema import PatientCreateSchema, PatientUpdateSchema, XraySchema
from .model import Patient, PatientXray, Gender, MedicalRecord, Treatment, Medicine, MedicalRecordAttachment
from db.db import get_db
from auth.model import User
from fastapi.responses import JSONResponse
from utils.auth import get_current_user, verify_token
from sqlalchemy import insert, select, update, delete
import os
from predict.model import Prediction, Label
from sqlalchemy.exc import SQLAlchemyError
from PIL import Image
import io
import numpy as np
import pydicom
from datetime import datetime
from typing import Optional, List
patient_router = APIRouter()

@patient_router.get("/search",
    response_model=dict,
    status_code=200,
    summary="Search patients",
    description="""
    Search patients by name, phone number, or gender. Returns matching patients for the logged in doctor.
    
    Required parameters:
    - query: Optional search term to match against patient name or phone
    - gender: Optional gender filter (values: "male", "female", "other")
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Patients retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def search_patients(request: Request, query: str = None, gender: str = None, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})

        # Initialize search conditions
        search_conditions = []

        # If query is provided, split it into words and create search conditions for each word
        if query:
            search_terms = query.split()
            for term in search_terms:
                search_conditions.append(
                    (
                        Patient.first_name.ilike(f"%{term}%") |
                        Patient.last_name.ilike(f"%{term}%") |
                        Patient.phone.ilike(f"%{term}%") |
                        Patient.email.ilike(f"%{term}%")
                    )
                )

        # Search patients belonging to current doctor
        stmt = (
            select(Patient)
            .where(
                Patient.doctor_id == current_user,
                *search_conditions  # Unpack all search conditions
            )
        )

        # Apply gender filter if provided
        if gender in ["male", "female"]:
            stmt = stmt.where(Patient.gender == gender)

        result = db.execute(stmt)
        patients = result.scalars().all()
        return JSONResponse(
            status_code=200, 
            content={
                "patients": [
                    {
                        "id": p.id,
                        "first_name": p.first_name,
                        "last_name": p.last_name,
                        "phone": p.phone,
                        "email": p.email,
                        "date_of_birth": p.date_of_birth.strftime("%Y-%m-%d"),
                        "gender": p.gender.value,
                        "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                    } 
                    for p in patients
                ]
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@patient_router.get("/validate-patient/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Validate patient",
    description="""
    Validate a patient by ID
    """,
    responses={
        200: {"description": "Patient validated successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def validate_patient(request: Request, patient_id: str, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        stmt = select(Patient).where(Patient.id == patient_id)
        result = db.execute(stmt)
        patient = result.scalar_one_or_none()
        
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
        
        return JSONResponse(status_code=200, content={"patient": {
            "id": patient.id,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "phone": patient.phone,
            "email": patient.email,
            "date_of_birth": patient.date_of_birth.strftime("%Y-%m-%d"),
            "created_at": patient.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": patient.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        }})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
        

@patient_router.post("/create",
    response_model=dict,
    status_code=201,
    summary="Create a new patient",
    description="""
    Create a new patient record with first name, last name, phone, date_of_birth and gender
    
    Required fields:
    - first_name: Patient's first name
    - last_name: Patient's last name 
    - phone: Valid phone number
    - date_of_birth: Patient's date of birth (YYYY-MM-DD)
    - gender: One of ["male", "female", "other"]
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        201: {"description": "Patient created successfully"},
        400: {"description": "Bad request - Invalid input"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def create_patient(request: Request, patient: PatientCreateSchema, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        if not all([patient.first_name, patient.last_name, patient.phone, patient.date_of_birth, patient.gender, patient.email]):
            return JSONResponse(status_code=400, content={"error": "All fields are required"})
        
        # Check if patient already exists
        stmt = select(Patient).where((Patient.phone == patient.phone) | (Patient.email == patient.email))
        result = db.execute(stmt)
        existing_patient = result.scalar_one_or_none()
        
        if existing_patient:
            return JSONResponse(status_code=400, content={"error": "Patient already exists with this phone number"})
        
        stmt = insert(Patient).values(doctor_id=current_user, **patient.model_dump())
        result = db.execute(stmt)

        # Get the newly created patient
        stmt = select(Patient).where(Patient.id == result.inserted_primary_key[0])
        result = db.execute(stmt)
        new_patient = result.scalar_one()
      
        return JSONResponse(status_code=201, content={"message": "Patient created successfully", "patient": {
            "id": new_patient.id,
            "first_name": new_patient.first_name,
            "last_name": new_patient.last_name,
            "phone": new_patient.phone,
            "email": new_patient.email,
            "date_of_birth": new_patient.date_of_birth.strftime("%Y-%m-%d"),
            "gender": new_patient.gender.value,
            "created_at": new_patient.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": new_patient.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        }})
    except SQLAlchemyError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@patient_router.get("/all",
    response_model=dict,
    status_code=200, 
    summary="Get all patients",
    description="""
    Get list of all patients in the system
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "List of patients retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def get_all_patients(request: Request, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        stmt = select(Patient)
        result = db.execute(stmt)
        patients = result.scalars().all()

        today_patients = [p for p in patients if p.created_at.date() == datetime.now().date()]
        this_month_patients = [p for p in patients if p.created_at.date() >= datetime.now().date().replace(day=1)]
        this_year_patients = [p for p in patients if p.created_at.date() >= datetime.now().date().replace(month=1, day=1)]
        total_patients = len(patients)
        
        return JSONResponse(status_code=200, content={"patients": [
            {
                "id": p.id,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "phone": p.phone,
                "email": p.email,
                "date_of_birth": p.date_of_birth.strftime("%Y-%m-%d"),
                "gender": p.gender.value,
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            } for p in patients
        ], "today_patients": len(today_patients), "this_month_patients": len(this_month_patients), "this_year_patients": len(this_year_patients), "total_patients": total_patients})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": "Error getting patients", "error": str(e)})
    
@patient_router.get("/details/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get patient details",
    description="""
    Get details of a specific patient by ID
    
    Required parameters:
    - patient_id: UUID of the patient
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Patient details retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_patient(request: Request, patient_id: str, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        stmt = select(User).where(User.id == current_user)
        result = db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        stmt = select(Patient).where(Patient.id == patient_id)
        result = db.execute(stmt)
        patient = result.scalar_one_or_none()
        
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
            
        return JSONResponse(status_code=200, content={"patient": {
            "id": patient.id,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "phone": patient.phone,
            "email": patient.email,
            "date_of_birth": patient.date_of_birth.strftime("%Y-%m-%d"),
            "gender": patient.gender.value,
            "created_at": patient.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": patient.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        }, "doctor": {
            "id": user.id,
            "credits": user.credits
        }})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": "Error getting patient", "error": str(e)})
    
@patient_router.get("/doctor",
    response_model=dict,
    status_code=200,
    summary="Get doctor's patients",
    description="""
    Get all patients assigned to the authenticated doctor
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Doctor's patients retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def get_patient_by_doctor(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_user = verify_token(request)

        if not decoded_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        user_id = decoded_user['user_id']

        stmt = select(User).where(User.id == user_id)
        result = db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        stmt = select(Patient).where(Patient.doctor_id == user_id).order_by(Patient.created_at.desc())
        result = db.execute(stmt)
        patients = result.scalars().all()
        
        if not patients:
            return JSONResponse(status_code=200, content={"patients": []})
            
        return JSONResponse(status_code=200, content={"patients": [
            {
                "id": p.id,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "phone": p.phone,
                "email": p.email,
                "date_of_birth": p.date_of_birth.strftime("%Y-%m-%d"),
                "gender": p.gender.value,
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            } for p in patients
        ]})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": "Error getting patients", "error": str(e)})

@patient_router.patch("/update/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Update patient details",
    description="""
    Update details of a specific patient
    
    Optional fields (at least one required):
    - first_name: Patient's first name
    - last_name: Patient's last name
    - phone: Valid phone number
    - date_of_birth: Patient's date of birth (YYYY-MM-DD)
    - gender: One of ["male", "female", "other"]
    
    Required parameters:
    - patient_id: UUID of the patient
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Patient updated successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_patient(request: Request, patient_id: str, patient: PatientUpdateSchema, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        # Check if patient exists
        stmt = select(Patient).where(Patient.id == patient_id)
        result = db.execute(stmt)
        existing_patient = result.scalar_one_or_none()
        
        if not existing_patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
        
        # partial update
        stmt = update(Patient).where(Patient.id == patient_id).values(**patient.model_dump(exclude_unset=True))
        db.execute(stmt)
        return JSONResponse(status_code=200, content={"message": "Patient updated successfully"})
    except SQLAlchemyError as e:
        return JSONResponse(status_code=500, content={"message": "Error updating patient", "error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": "Error updating patient", "error": str(e)})

@patient_router.delete("/delete/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Delete patient",
    description="""
    Delete a specific patient record
    
    Required parameters:
    - patient_id: UUID of the patient
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Patient deleted successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_patient(request: Request, patient_id: str, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        # Check if patient exists and get patient record
        stmt = select(Patient).where(Patient.id == patient_id)
        result = db.execute(stmt)
        existing_patient = result.scalar_one_or_none()
        
        if not existing_patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
            
        # Delete all associated records in a transaction
        try:
            # Delete all x-rays for this patient
            x_ray_stmt = delete(PatientXray).where(PatientXray.patient == patient_id)
            db.execute(x_ray_stmt)

            # Get and delete all labels for patient's predictions
            pred_stmt = select(Prediction).where(Prediction.patient == patient_id)
            result = db.execute(pred_stmt)
            predictions = result.scalars().all()
            
            for prediction in predictions:
                label_stmt = delete(Label).where(Label.prediction_id == prediction.id)
                db.execute(label_stmt)

            # Delete all predictions
            pred_stmt = delete(Prediction).where(Prediction.patient == patient_id)
            db.execute(pred_stmt)
            
            # Finally delete the patient
            patient_stmt = delete(Patient).where(Patient.id == patient_id)
            db.execute(patient_stmt)
            
            return JSONResponse(status_code=200, content={"message": "Patient deleted successfully"})
            
        except SQLAlchemyError as e:
            raise e
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": "Error deleting patient", "error": str(e)})

def dicom_to_jpg(dicom_path):
    """
    Converts a DICOM file to a JPEG image.

    Args:
        dicom_path: Path to the input DICOM file or file-like object.

    Returns:
        PIL Image object in RGB mode.
    """
    try:
        # Load the DICOM file
        dicom_data = pydicom.dcmread(dicom_path)
        
        # Extract pixel data and normalize it to 8-bit
        pixel_array = dicom_data.pixel_array
        pixel_array = pixel_array.astype(float)
        
        # Normalize to 0-255 range
        if pixel_array.max() != pixel_array.min():
            pixel_array = ((pixel_array - pixel_array.min()) * 255.0 / 
                         (pixel_array.max() - pixel_array.min()))
        else:
            pixel_array = np.zeros_like(pixel_array)
        pixel_array = np.uint8(pixel_array)
        
        # Convert to PIL Image
        image = Image.fromarray(pixel_array)
        
        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')
            
        return image
        
    except Exception as e:
        raise ValueError(f"Error converting DICOM to JPEG: {str(e)}")

@patient_router.post("/upload-xray/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Upload patient X-ray",
    description="""
    Upload an X-ray image for a specific patient
    
    Required parameters:
    - patient_id: UUID of the patient
    
    Required form data:
    - file: X-ray image file (jpg, png, dicom etc)
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "X-ray uploaded successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient or user not found"},
        500: {"description": "Internal server error"}
    }
)
async def upload_xray(
    request: Request, 
    patient_id: str,
    is_opg: bool = False,
    file: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        stmt = select(User).where(User.id == current_user)
        result = db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        stmt = select(Patient).where(Patient.id == patient_id)
        result = db.execute(stmt)
        patient = result.scalar_one_or_none()
        
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})

        # Create uploads directory if it doesn't exist
        os.makedirs("uploads/original", exist_ok=True)
            
        # Extract original file extension
        original_filename = file.filename
        if original_filename:
            _, file_extension = os.path.splitext(original_filename)
            file_extension = file_extension.lower()
        else:
            file_extension = '.jpeg'
        
        # If no extension found, default to .jpg
        if not file_extension:
            file_extension = '.jpeg'
            
        # Generate UUID filename with extension
        filename = f"{os.urandom(16).hex()}{file_extension}"
        file_path = os.path.join("uploads/original", f"compressed_{filename}")

        # Read file contents
        contents = await file.read()

        # Load and compress the image
        image = Image.open(io.BytesIO(contents))
        
        # Convert to RGB if needed
        image = image.convert("RGB")
        
        # Calculate new dimensions while maintaining aspect ratio
        width, height = image.size
        max_size = 1280  # Maximum dimension for either width or height
        
        if width > height:
            new_width = min(width, max_size)
            new_height = int((height * new_width) / width)
        else:
            new_height = min(height, max_size)
            new_width = int((width * new_height) / height)
            
        # Resize image maintaining aspect ratio
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Save compressed image
        image.save(file_path, format="JPEG", optimize=True, quality=80)

        xray = PatientXray(patient=patient.id, original_image=file_path, is_opg=is_opg)
        db.add(xray)
        
        return JSONResponse(status_code=200, content={"message": "X-ray uploaded successfully"})
    except SQLAlchemyError as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@patient_router.get("/xray/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get patient X-ray",
    description="""
    Get all X-ray images for a specific patient
    
    Required parameters:
    - patient_id: UUID of the patient
    """,
    responses={
        200: {"description": "X-ray images retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient or user not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_xray(request: Request, patient_id: str, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        stmt = select(PatientXray).where(PatientXray.patient == patient_id).order_by(PatientXray.created_at.desc())
        result = db.execute(stmt)
        xrays = result.scalars().all()

        return JSONResponse(status_code=200, content={"xrays": [
            {
                "id": x.id, 
                "original_image": f"{request.base_url}{x.original_image}",
                "annotated_image": f"{request.base_url}{x.annotated_image}" if x.annotated_image else None,
                "prediction_id": x.prediction_id if x.prediction_id else None
            } for x in xrays
        ]})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@patient_router.patch("/update-xray-image/{xray_id}",
    response_model=dict,
    status_code=200,
    summary="Update patient X-ray image",
    description="""
    Update a specific patient X-ray image
    """,
    responses={
        200: {"description": "X-ray image updated successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "X-ray image not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_xray_image(request: Request, xray_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        stmt = select(PatientXray).where(PatientXray.id == xray_id)
        result = db.execute(stmt)
        xray = result.scalar_one_or_none()
        
        if not xray:
            return JSONResponse(status_code=404, content={"error": "X-ray image not found"})
        
        # delete existing original image
        if xray.original_image and os.path.exists(xray.original_image):
            os.remove(xray.original_image)
        
        # Get file extension, defaulting to .jpg if none or if filename is None
        file_extension = '.jpg'
        if file.filename:
            _, ext = os.path.splitext(file.filename)
            if ext:
                file_extension = ext.lower()
            
        # Generate UUID filename with extension
        filename = f"{os.urandom(16).hex()}{file_extension}"
        
        # Ensure uploads/original directory exists
        os.makedirs("uploads/original", exist_ok=True)
        
        file_path = f"uploads/original/{filename}"
        
        # Read file content and write to new path
        file_content = await file.read()
        with open(file_path, "wb") as f:
            f.write(file_content)

        xray.original_image = file_path
        db.commit()

        return JSONResponse(status_code=200, content={"message": "X-ray image updated successfully"})
    except SQLAlchemyError as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@patient_router.post("/create-medical-record/{patient_id}",
    response_model=dict,
    status_code=201,
    summary="Create medical record for a patient",
    description="""
    Create a complete medical record for a specific patient including:
    - Basic medical information (complaints, diagnosis, vital signs)
    - Treatment plans
    - Prescribed medicines
    - Optional file attachments
    
    Required fields in request body:
    - complaints: Patient's reported symptoms and concerns
    - diagnosis: Doctor's diagnosis
    - vital_signs: Patient's vital measurements
    - treatments: List of treatments, each containing:
        - name: Name/description of the treatment
    - medicines: List of prescribed medicines, each containing:
        - item: Medicine name
        - price: Unit price
        - dosage: Dosage amount
        - instraction: When to take ("before_meal", "after_meal", "on_empty_stomach", etc)
        - quantity: Number of units
        - amount: Total cost
        
    Optional:
    - files: List of file attachments (images, documents etc)
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        201: {"description": "Medical record created successfully"},
        400: {"description": "Bad request - Invalid input data"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def create_medical_record(
    request: Request,
    patient_id: str,
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        # Check if patient exists
        stmt = select(Patient).where(
            Patient.id == patient_id,
            Patient.doctor_id == current_user
        )
        result = db.execute(stmt)
        patient = result.scalar_one_or_none()
        
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})

        # Parse request body
        body = await request.json()

        # Create medical record
        medical_record = MedicalRecord(
            patient_id=patient.id,
            complaints=body.get("complaints"),
            diagnosis=body.get("diagnosis"),
            vital_signs=body.get("vital_signs")
        )
        db.add(medical_record)
        db.flush()  # Get ID without committing

        # Add treatments
        treatments = body.get("treatments", [])
        for treatment in treatments:
            treatment_record = Treatment(
                medical_record_id=medical_record.id,
                name=treatment.get("name")
            )
            db.add(treatment_record)
        
        # Add medicines
        medicines = body.get("medicines", [])
        for medicine in medicines:
            medicine_record = Medicine(
                medical_record_id=medical_record.id,
                item=medicine.get("item"),
                price=float(medicine.get("price", 0)),
                dosage=int(medicine.get("dosage", 0)),
                instraction=medicine.get("instraction"),
                quantity=int(medicine.get("quantity", 0)),
                amount=float(medicine.get("amount", 0))
            )
            db.add(medicine_record)
            
        # Handle file attachments
        if files:
            # Ensure upload directory exists
            upload_dir = "uploads/medical-record-attachments"
            os.makedirs(upload_dir, exist_ok=True)
            
            for file in files:
                if file.filename:
                    # Generate unique filename
                    file_ext = os.path.splitext(file.filename)[1]
                    unique_filename = f"{os.urandom(16).hex()}{file_ext}"
                    file_path = os.path.join(upload_dir, unique_filename)
                    
                    # Save file
                    file_content = await file.read()
                    with open(file_path, "wb") as f:
                        f.write(file_content)
                    
                    # Create attachment record
                    attachment_record = MedicalRecordAttachment(
                        medical_record_id=medical_record.id,
                        file=file_path
                    )
                    db.add(attachment_record)

        # Commit all changes
        db.commit()
            
        return JSONResponse(
            status_code=201,
            content={
                "message": "Medical record created successfully",
                "record_id": medical_record.id
            }
        )
    
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": f"Server error: {str(e)}"})
    
@patient_router.get("/medical-records/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get all medical records for a patient",
    description="""
    Get all medical records for a specific patient
    
    Required parameters:
    - patient_id: UUID of the patient
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Medical records retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_medical_records(request: Request, patient_id: str, db: Session = Depends(get_db)):
    try:
        # Verify user authentication
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        # Check if patient exists and belongs to current doctor
        stmt = select(Patient).where(
            Patient.id == patient_id,
        )
        result = db.execute(stmt)
        patient = result.scalar_one_or_none()
        
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
        
        # Get medical records with treatments in a single query
        stmt = (
            select(MedicalRecord, Treatment)
            .outerjoin(Treatment, MedicalRecord.id == Treatment.medical_record_id)
            .where(MedicalRecord.patient_id == patient_id)
            .order_by(MedicalRecord.created_at.desc())
        )
        result = db.execute(stmt)
        records = result.all()

        # Group treatments by medical record
        medical_records_dict = {}
        for record, treatment in records:
            if record.id not in medical_records_dict:
                medical_records_dict[record.id] = {
                    "id": record.id,
                    "complaints": record.complaints,
                    "diagnosis": record.diagnosis,
                    "created_at": record.created_at.isoformat(),
                    "treatments": []
                }
            if treatment:
                medical_records_dict[record.id]["treatments"].append({
                    "id": treatment.id,
                    "name": treatment.name
                })

        return JSONResponse(status_code=200, content={
            "message": "Medical records retrieved successfully",
            "medical_records": list(medical_records_dict.values())
        })

    except SQLAlchemyError as e:
        return JSONResponse(status_code=500, content={"error": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Server error: {str(e)}"})
        
@patient_router.get("/medical-record/{medical_record_id}",
    response_model=dict,
    status_code=200,
    summary="Get medical record details",
    description="""
    Get complete details of a specific medical record by ID including patient info, treatments, medicines and attachments.

    Required parameters:
    - medical_record_id: UUID of the medical record
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Medical record details retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Medical record not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_medical_record(request: Request, medical_record_id: str, db: Session = Depends(get_db)):
    try:
        # Verify user authentication
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})

        # Get medical record with related patient info
        stmt = (
            select(MedicalRecord, Patient)
            .join(Patient, MedicalRecord.patient_id == Patient.id)
            .where(
                MedicalRecord.id == medical_record_id,
                Patient.doctor_id == current_user
            )
        )
        result = db.execute(stmt)
        record = result.first()

        if not record:
            return JSONResponse(status_code=404, content={"error": "Medical record not found"})

        medical_record, patient = record

        # Get all related treatments
        treatments = db.query(Treatment).filter(
            Treatment.medical_record_id == medical_record.id
        ).all()

        # Get all related medicines
        medicines = db.query(Medicine).filter(
            Medicine.medical_record_id == medical_record.id
        ).all()

        # Get all related attachments
        attachments = db.query(MedicalRecordAttachment).filter(
            MedicalRecordAttachment.medical_record_id == medical_record.id
        ).all()

        return JSONResponse(status_code=200, content={
            "message": "Medical record details retrieved successfully",
            "medical_record": {
                "id": medical_record.id,
                "created_at": medical_record.created_at.isoformat(),
                "updated_at": medical_record.updated_at.isoformat(),
                "complaints": medical_record.complaints,
                "diagnosis": medical_record.diagnosis,
                "vital_signs": medical_record.vital_signs,
                "patient": {
                    "id": patient.id,
                    "first_name": patient.first_name,
                    "last_name": patient.last_name,
                    "email": patient.email,
                    "phone": patient.phone,
                    "gender": patient.gender.value,
                    "date_of_birth": patient.date_of_birth.isoformat()
                },
                "treatments": [
                    {
                        "id": treatment.id,
                        "name": treatment.name,
                        "created_at": treatment.created_at.isoformat()
                    } for treatment in treatments
                ],
                "medicines": [
                    {
                        "id": medicine.id,
                        "item": medicine.item,
                        "price": float(medicine.price),
                        "dosage": medicine.dosage,
                        "instraction": medicine.instraction.value,
                        "quantity": medicine.quantity,
                        "amount": float(medicine.amount),
                        "created_at": medicine.created_at.isoformat()
                    } for medicine in medicines
                ],
                "attachments": [
                    {
                        "id": attachment.id,
                        "file": f"{request.base_url}{attachment.file}",
                        "created_at": attachment.created_at.isoformat()
                    } for attachment in attachments
                ]
            }
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=400, content={"error": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Server error: {str(e)}"})
