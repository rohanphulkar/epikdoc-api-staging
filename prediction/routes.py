from fastapi import APIRouter, Depends, Request, BackgroundTasks, Body, UploadFile, File
from fastapi.responses import JSONResponse
from db.db import get_db
from utils import prediction
from .models import XRay, Prediction, Legend, DeletedLegend
from sqlalchemy.orm import Session
from .schemas import XRayResponse, PredictionResponse, LabelResponse, AddNotesRequest, LabelCreateAndUpdate, NewImageAnnotation
from typing import List
from utils.auth import verify_token
from utils.prediction import calculate_class_percentage, hex_to_bgr, colormap
from auth.models import User
from patient.models import Patient
from roboflow import Roboflow
import supervision as sv
from PIL import Image
import cv2
import numpy as np
import random, os
import datetime
import json
import colorsys
from decouple import config
from utils.report import report_generate, create_dental_radiology_report, send_email_with_attachment
from dateutil.utils import today
from sqlalchemy import select, delete

def update_image_url(url: str, request: Request):
    base_url = str(request.base_url).rstrip('/')
    return f"{base_url}/{url}"

prediction_router = APIRouter()

@prediction_router.post(
    "/upload-xray/{patient_id}",
    status_code=201,
    summary="Upload X-Ray Image",
    description="Upload an X-Ray image file for a specific patient",
    response_description="X-Ray upload confirmation with X-Ray ID",
    responses={
        201: {
            "description": "X-Ray uploaded successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "X-Ray uploaded successfully",
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token or user not found",
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
            "description": "Server error",
            "content": {
                "application/json": {
                    "example": {"message": "Server error: {error_message}"}
                }
            }
        }
    }
)
async def upload_xray(
    request: Request,
    patient_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # Verify authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Invalid or missing authentication token"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "User not found"})
        
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})
        
        # Create uploads directory if it doesn't exist
        os.makedirs("uploads/xrays", exist_ok=True)
        
        # Save file with unique name to prevent overwrites
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{timestamp}_{file.filename}"
        file_path = f"uploads/xrays/{file_name}"
        
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        # Save X-Ray record to database
        xray = XRay(
            patient=patient_id,
            original_image=file_path,
        )
        db.add(xray)
        db.commit()
        
        return JSONResponse(
            status_code=201, 
            content={
                "message": "X-Ray uploaded successfully",
            }
        )
    
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Server error: {str(e)}"})

@prediction_router.get(
    "/get-xrays/{patient_id}",
    status_code=200,
    summary="Get X-Ray Images for a Patient",
    description="""
    Retrieve all X-Ray images for a specific patient.
    
    Path parameters:
    - patient_id: ID of the patient to get X-Rays for
    
    Required headers:
    - Authorization: Bearer token from user login
    
    Returns a list of X-Ray records with their metadata and image paths.
    """,
    response_model=list[XRayResponse],
    responses={
        200: {
            "description": "X-Ray images retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "X-Ray images retrieved successfully",
                        "xrays": [
                            {
                                "id": "uuid",
                                "patient": "patient_id",
                                "original_image": "path/to/image.jpg",
                                "predicted_image": "path/to/predicted.jpg",
                                "is_annotated": False,
                                "created_at": "2023-01-01T00:00:00",
                                "updated_at": "2023-01-01T00:00:00"
                            }
                        ]
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_xrays(request: Request, patient_id: str, db: Session = Depends(get_db)):
    try:
        # Verify authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Invalid or missing authentication token"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "User not found"})
        
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})
        
        xrays = db.query(XRay).filter(XRay.patient == patient.id).order_by(XRay.created_at.desc()).all()
        xray_responses = [XRayResponse.model_validate(xray) for xray in xrays]
        
        return JSONResponse(status_code=200, content={
            "message": "X-Ray images retrieved successfully",
            "xrays": [xray.model_dump() for xray in xray_responses]
        })
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Internal server error: {str(e)}"})
    
@prediction_router.delete(
    "/delete-xray/{xray_id}",
    status_code=200,
    summary="Delete an X-Ray Image",
    description="Delete an X-Ray image by its ID",
    responses={
        200: {
            "description": "X-Ray image deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "X-Ray image deleted successfully"
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "X-Ray image not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_xray(request: Request, xray_id: str, db: Session = Depends(get_db)):
    try:
        # Verify authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Invalid or missing authentication token"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "User not found"})
        
        xray = db.query(XRay).filter(XRay.id == xray_id).first()
        if not xray:
            return JSONResponse(status_code=404, content={"message": "X-Ray image not found"})
        
        db.delete(xray)
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "X-Ray image deleted successfully"})
    
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Internal server error: {str(e)}"})
    
def process_prediction_model(xray, rf):
    """Run prediction model based on xray type"""
    workspace = rf.workspace()
    if xray.is_opg:
        project = workspace.project("opg-instance-segmentation-copy")
        model = project.version(1).model
        prediction_result = model.predict(str(xray.original_image), confidence=1)
    else:
        project = workspace.project("stage-1-launch")
        model = project.version(1).model
        prediction_result = model.predict(str(xray.original_image), confidence=1)
        
    if not prediction_result:
        raise Exception("Prediction failed")
        
    return prediction_result.json()

def check_overlap(box1, box2):
    """Check if two label boxes overlap"""
    return not (box1['x2'] < box2['x1'] or 
              box1['x1'] > box2['x2'] or 
              box1['y2'] < box2['y1'] or 
              box1['y1'] > box2['y2'])

def generate_annotated_image(image, prediction_json, hex_codes):
    """Generate annotated image with labels and masks"""
    annotated_image = image.copy()
    label_boxes = []
    
    # Process each prediction
    for pred in prediction_json["predictions"]:
        label = pred["class"]
        hex_color = hex_codes[label]
        bgr_color = hex_to_bgr(hex_color)
        
        # Draw mask if points are available
        if "points" in pred:
            points = np.array([[int(p["x"]), int(p["y"])] for p in pred["points"]], dtype=np.int32)
            mask = np.zeros(image.shape[:2], dtype=np.uint8)
            cv2.fillPoly(mask, [points], (1, 1, 1))
            
            overlay = annotated_image.copy()
            overlay[mask == 1] = bgr_color
            alpha = 0.4
            annotated_image = cv2.addWeighted(overlay, alpha, annotated_image, 1 - alpha, 0)
        
        # Add label text
        x = int(pred["x"] - pred["width"]/2)
        y = int(pred["y"] - pred["height"]/2)
        label_text = f"{label}"
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.7
        thickness = 2
        (text_width, text_height), _ = cv2.getTextSize(label_text, font, font_scale, thickness)
        
        padding = 5
        label_box = {
            'x1': x - padding,
            'y1': y - text_height - 2*padding,
            'x2': x + text_width + padding,
            'y2': y + padding
        }
        
        # Handle overlapping labels
        overlap_count = 0
        while any(check_overlap(label_box, existing_box) for existing_box in label_boxes):
            if overlap_count % 2 == 0:
                y -= (text_height + 2*padding + 5)
                label_box['y1'] = y - text_height - 2*padding
                label_box['y2'] = y + padding
            else:
                x += (text_width + 2*padding + 5)
                label_box['x1'] = x - padding
                label_box['x2'] = x + text_width + padding
            
            overlap_count += 1
            if overlap_count > 10:
                break
        
        label_boxes.append(label_box)
        
        # Draw text background
        bg_pts = np.array([
            [label_box['x1'], label_box['y1']],
            [label_box['x2'], label_box['y1']],
            [label_box['x2'], label_box['y2']],
            [label_box['x1'], label_box['y2']]
        ], dtype=np.int32)
        
        overlay_bg = annotated_image.copy()
        cv2.fillPoly(overlay_bg, [bg_pts], (0, 0, 0))
        annotated_image = cv2.addWeighted(overlay_bg, 0.7, annotated_image, 0.3, 0)
        
        cv2.putText(annotated_image, 
                  label_text,
                  (x, y),
                  font,
                  font_scale,
                  bgr_color,
                  thickness,
                  cv2.LINE_AA)

    annotated_image = cv2.convertScaleAbs(annotated_image, alpha=1.1, beta=5)
    return annotated_image

def save_prediction_results(db, xray, prediction_str, output_path, class_percentages, hex_codes, user):
    """Save prediction results to database"""
    prediction = Prediction(
        xray_id=xray.id,
        prediction=prediction_str
    )
    db.add(prediction)
    db.commit()

    legends = [
        Legend(
            prediction_id=prediction.id,
            name=class_name,
            percentage=percentage,
            include=True,
            color_hex=hex_codes.get(class_name, '#FFFFFF')
        )
        for class_name, percentage in class_percentages.items()
    ]
    db.add_all(legends)
    db.commit()

    xray.predicted_image = output_path
    xray.prediction_id = prediction.id
    xray.is_annotated = True
    db.commit()

    user.credits -= 1
    user.used_credits += 1
    db.commit()

    return prediction

@prediction_router.get("/create-prediction/{xray_id}",
    response_model=dict,
    status_code=200,
    summary="Create new prediction",
    description="""
    Create a new prediction for an X-ray image
    
    Required parameters:
    - xray_id: UUID of the X-ray image
    
    Required headers:
    - Authorization: Bearer token from login
    
    Process:
    1. Validates user authorization
    2. Loads X-ray image
    3. Runs prediction model
    4. Generates annotated image
    5. Saves prediction results
    """,
    responses={
        200: {"description": "Prediction created successfully"},
        400: {"description": "Invalid X-ray ID or image"},
        401: {"description": "Unauthorized - Invalid token or not a doctor"},
        500: {"description": "Internal server error"}
    }
)
async def create_prediction(request: Request, xray_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})

        # Validate xray
        if not xray_id:
            return JSONResponse(status_code=400, content={"error": "X-ray ID is required"})
        xray = db.query(XRay).filter(XRay.id == xray_id).first()
        if not xray:
            return JSONResponse(status_code=400, content={"error": "X-ray not found"})
        if not os.path.exists(str(xray.original_image)):
            return JSONResponse(status_code=400, content={"error": "X-ray image file not found"})

        # Run prediction model
        try:
            rf = Roboflow(api_key=config("ROBOFLOW_API_KEY"))
            prediction_json = process_prediction_model(xray, rf)
            prediction_str = json.dumps(prediction_json)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Model prediction failed: {str(e)}"})

        # Generate annotated image
        try:
            image = cv2.imread(str(xray.original_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            labels = [item["class"] for item in prediction_json["predictions"]]
            _, hex_codes = colormap(labels)
            
            annotated_image = generate_annotated_image(image, prediction_json, hex_codes)
            
            # Save annotated image
            annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
            if annotated_image_pil.mode == 'RGBA':
                annotated_image_pil = annotated_image_pil.convert('RGB')
                
            current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            random_number = random.randint(1000, 9999)
            random_filename = f"{current_datetime}-{random_number}.jpeg"

            output_dir = os.path.join("uploads", "analyzed")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, random_filename)
            
            annotated_image_pil.save(output_path, optimize=True, quality=98, subsampling=0)
                                   
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Image annotation failed: {str(e)}"})

        # Save results
        try:
            class_percentages = calculate_class_percentage(prediction_json)
            prediction = save_prediction_results(db, xray, prediction_str, output_path, class_percentages, hex_codes, user)
            annotated_image_url = update_image_url(prediction.predicted_image, request) if prediction.predicted_image else None
            
            return JSONResponse(status_code=200, content={
                "message": "Prediction created successfully",
                "prediction_id": prediction.id,
                "annotated_image": annotated_image_url
            })
            
        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Database operation failed: {str(e)}"})
            
    except Exception as e:
        print("Exception error: ", str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.get("/get-prediction/{prediction_id}",
    response_model=dict,
    status_code=200,
    summary="Get prediction details",
    description="""
    Retrieve details of a prediction by its ID

    Required parameters:
    - prediction_id: UUID of the prediction
    
    Required headers:
    - Authorization: Bearer token from login
    
    Process:
    1. Validates user authorization
    2. Loads prediction details
    3. Returns prediction details
    """,
    responses={
        200: {"description": "Prediction details retrieved successfully"},
        400: {"description": "Invalid prediction ID"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def get_prediction(request: Request, prediction_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Validate prediction
        if not prediction_id:
            return JSONResponse(status_code=400, content={"error": "Prediction ID is required"})
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=400, content={"error": "Prediction not found"})
        
        xray = db.query(XRay).filter(XRay.id == prediction.xray_id).first()
        if not xray:
            return JSONResponse(status_code=400, content={"error": "X-ray not found"})
        # Load legends
        legends = db.query(Legend).filter(Legend.prediction_id == prediction_id).all()
        legend_details = [
            {
                "id": legend.id,
                "name": legend.name,
                "percentage": legend.percentage,
                "include": legend.include,
                "color_hex": legend.color_hex
            }
            for legend in legends
        ]

        prediction_details = {
            "id": prediction.id,
            "xray_id": prediction.xray_id,
            "prediction": prediction.prediction,
            "notes": prediction.notes,
            "original_image": xray.original_image,
            "predicted_image": xray.predicted_image,
            "legends": legend_details,
            "created_at": prediction.created_at,
            "updated_at": prediction.updated_at
        }
        
        return JSONResponse(status_code=200, content={
            "message": "Prediction details retrieved successfully",
            "prediction": prediction_details
        })
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.post("/add-notes/{prediction_id}",
    response_model=dict,
    status_code=200,
    summary="Add notes to a prediction",
    description="""
    Add notes to a prediction by its ID

    Required parameters:
    - prediction_id: UUID of the prediction
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Notes added successfully"},
        400: {"description": "Invalid prediction ID"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def add_notes(request: Request, prediction_id: str, notes: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Validate prediction
        if not prediction_id:
            return JSONResponse(status_code=400, content={"error": "Prediction ID is required"})
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=400, content={"error": "Prediction not found"})

        # Update notes
        prediction.notes = notes
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Notes added successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.delete("/delete-prediction/{prediction_id}",
    response_model=dict,
    status_code=200,
    summary="Delete a prediction",
    description="""
    Delete a prediction by its ID

    Required parameters:
    - prediction_id: UUID of the prediction
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Prediction deleted successfully"},
        400: {"description": "Invalid prediction ID"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def delete_prediction(request: Request, prediction_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Validate prediction
        if not prediction_id:
            return JSONResponse(status_code=400, content={"error": "Prediction ID is required"})
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=400, content={"error": "Prediction not found"})
        
        db.delete(prediction)
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Prediction deleted successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.get("/reset-prediction/{prediction_id}",
    response_model=dict,
    status_code=200,
    summary="Reset a prediction",
    description="""
    Reset a prediction by its ID

    Required parameters:
    - prediction_id: UUID of the prediction
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Prediction reset successfully"},
        400: {"description": "Invalid prediction ID"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def reset_prediction(request: Request, prediction_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Validate prediction
        if not prediction_id:
            return JSONResponse(status_code=400, content={"error": "Prediction ID is required"})
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=400, content={"error": "Prediction not found"})
        
        xray = db.query(XRay).filter(XRay.id == prediction.xray_id).first()
        if not xray:
            return JSONResponse(status_code=400, content={"error": "X-ray not found"})
        
        if not os.path.exists(str(xray.original_image)):
            return JSONResponse(status_code=400, content={"error": "X-ray image file not found"})

        # Delete old prediction and legends
        old_legends = db.query(Legend).filter(Legend.prediction_id == prediction_id).all()
        for legend in old_legends:
            db.delete(legend)
        db.delete(prediction)
        db.commit()

        # Run prediction model
        try:
            rf = Roboflow(api_key=config("ROBOFLOW_API_KEY"))
            prediction_json = process_prediction_model(xray, rf)
            prediction_str = json.dumps(prediction_json)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Model prediction failed: {str(e)}"})

        # Generate annotated image
        try:
            image = cv2.imread(str(xray.original_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            labels = [item["class"] for item in prediction_json["predictions"]]
            _, hex_codes = colormap(labels)
            
            annotated_image = generate_annotated_image(image, prediction_json, hex_codes)
            
            # Save annotated image
            annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
            if annotated_image_pil.mode == 'RGBA':
                annotated_image_pil = annotated_image_pil.convert('RGB')
                
            current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            random_number = random.randint(1000, 9999)
            random_filename = f"{current_datetime}-{random_number}.jpeg"

            output_dir = os.path.join("uploads", "analyzed")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, random_filename)
            
            # Delete old predicted image if it exists
            if xray.predicted_image and os.path.exists(str(xray.predicted_image)):
                os.remove(str(xray.predicted_image))
                
            annotated_image_pil.save(output_path, optimize=True, quality=98, subsampling=0)
                                   
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Image annotation failed: {str(e)}"})

        # Save results
        try:
            class_percentages = calculate_class_percentage(prediction_json)
            new_prediction = save_prediction_results(db, xray, prediction_str, output_path, class_percentages, hex_codes, user)
            annotated_image_url = update_image_url(new_prediction.predicted_image, request) if new_prediction.predicted_image else None
            
            return JSONResponse(status_code=200, content={
                "message": "Prediction reset successfully",
                "prediction_id": new_prediction.id,
                "annotated_image": annotated_image_url
            })
            
        except Exception as e:
            db.rollback()
            if os.path.exists(output_path):
                os.remove(output_path)
            return JSONResponse(status_code=500, content={"error": f"Database operation failed: {str(e)}"})
    
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@prediction_router.get("/include-legend/{legend_id}",
    response_model=dict,
    status_code=200,
    summary="Include a legend",
    description="""
    Include a legend by its ID

    Required parameters:
    - legend_id: UUID of the legend
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Legend included successfully"},
        400: {"description": "Invalid legend ID"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def include_legend(request: Request, legend_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Validate legend
        if not legend_id:
            return JSONResponse(status_code=400, content={"error": "Legend ID is required"})
        legend = db.query(Legend).filter(Legend.id == legend_id).first()
        if not legend:
            return JSONResponse(status_code=400, content={"error": "Legend not found"})
        
        # Update legend inclusion
        legend.include = True
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Legend included successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.get("/exclude-legend/{legend_id}",
    response_model=dict,
    status_code=200,
    summary="Exclude a legend",
    description="""
    Exclude a legend by its ID

    Required parameters:
    - legend_id: UUID of the legend
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Legend excluded successfully"},
        400: {"description": "Invalid legend ID"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def exclude_legend(request: Request, legend_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        # Validate legend
        if not legend_id:
            return JSONResponse(status_code=400, content={"error": "Legend ID is required"})
        legend = db.query(Legend).filter(Legend.id == legend_id).first()
        if not legend:
            return JSONResponse(status_code=400, content={"error": "Legend not found"})
        
        # Update legend inclusion
        legend.include = False
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Legend excluded successfully"})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@prediction_router.post("/update-legend/{legend_id}",
    response_model=dict,
    status_code=200,
    summary="Update a legend",
    description="""
    Update a legend by its ID

    Required parameters:
    - legend_id: UUID of the legend
    - legend: LabelCreateAndUpdate
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Legend updated successfully"},
        400: {"description": "Invalid legend ID"},
        401: {"description": "Unauthorized - Invalid token or not a doctor"},
        500: {"description": "Internal server error"}
    }
)
async def update_legend(request: Request, legend_id: str, legend: LabelCreateAndUpdate, db: Session = Depends(get_db)):
    try:
        # Verify authentication token
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Invalid or missing token"})
            
        # Check if user is a doctor
        user = db.query(User).filter(User.id == decoded_token.get("id")).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})

        # Get existing legend
        existing_legend = db.query(Legend).filter(Legend.id == legend_id).first()
        if not existing_legend:
            return JSONResponse(status_code=404, content={"error": "Legend not found"})

        # Update legend fields
        if legend.name is not None:
            existing_legend.name = legend.name
            existing_legend.color_hex = legend.color_hex

        # Get prediction and xray to update annotation
        prediction = db.query(Prediction).filter(Prediction.id == existing_legend.prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})
            
        xray = db.query(XRay).filter(XRay.id == prediction.xray_id).first()
        if not xray:
            return JSONResponse(status_code=404, content={"error": "X-ray not found"})

        # Update annotation with updated legend
        try:
            image = cv2.imread(str(xray.original_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            prediction_json = json.loads(prediction.prediction)
            
            # Update legend name in predictions
            for pred in prediction_json["predictions"]:
                if pred["class"] == existing_legend.name:
                    pred["class"] = legend.name
                    
            # Update prediction JSON in database
            prediction.prediction = json.dumps(prediction_json)
            
            labels = [item["class"] for item in prediction_json["predictions"]]
            _, hex_codes = colormap(labels)
            
            # Override color for updated legend
            hex_codes[legend.name] = legend.color_hex
            
            annotated_image = generate_annotated_image(image, prediction_json, hex_codes)
            
            # Save annotated image
            annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
            if annotated_image_pil.mode == 'RGBA':
                annotated_image_pil = annotated_image_pil.convert('RGB')
                
            current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            random_number = random.randint(1000, 9999)
            random_filename = f"{current_datetime}-{random_number}.jpeg"

            output_dir = os.path.join("uploads", "analyzed")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, random_filename)
            
            annotated_image_pil.save(output_path, optimize=True, quality=98, subsampling=0)
            
            xray.predicted_image = output_path
            xray.is_annotated = True
            db.commit()

        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Error processing image: {str(e)}"})

        db.commit()
        db.refresh(existing_legend)

        annotated_image_url = update_image_url(xray.predicted_image, request) if xray.predicted_image else None

        # Convert to response dict
        response_dict = {
            "id": existing_legend.id,
            "name": existing_legend.name,
            "percentage": existing_legend.percentage,
            "prediction_id": existing_legend.prediction_id,
            "include": existing_legend.include,
            "color_hex": existing_legend.color_hex,
            "created_at": existing_legend.created_at.isoformat(),
            "updated_at": existing_legend.updated_at.isoformat(),
            "annotated_image": annotated_image_url
        }

        return JSONResponse(
            status_code=200,
            content=response_dict
        )

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@prediction_router.post("/add-missing-legends/{prediction_id}",
    response_model=dict,
    status_code=201,
    summary="Add missing legends to a prediction",
    description="""
    Add missing legends to a prediction by its ID
    
    Required parameters:
    - prediction_id: UUID of the prediction
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        201: {"description": "Missing legends added successfully"},
        400: {"description": "Invalid prediction ID"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Prediction not found"},
        500: {"description": "Internal server error"}
    }
)
async def add_missing_legends(
    request: Request,
    prediction_id: str,
    annotations: List[NewImageAnnotation] = Body(...),
    db: Session = Depends(get_db)
):
    try:
        # Verify authentication token
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Invalid or missing token"})
            
        # Check if user is a doctor
        user = db.query(User).filter(
            User.id == decoded_token.get("user_id"),
            User.user_type == "doctor"
        ).first()
        
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})
        
        # Get prediction
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})

        # Create new label only for the new annotation
        new_label = Legend(
            name=annotations[0].text,
            prediction_id=prediction_id,
            include=True,
            percentage=0.0,  # Default percentage
            color_hex=annotations[0].color
        )
        db.add(new_label)
        db.commit()
        db.refresh(new_label)

        # Update annotation with new label
        try:
            image = cv2.imread(str(prediction.predicted_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            image_height, image_width = image.shape[:2]
            prediction_json = json.loads(prediction.prediction)
            
            # Calculate actual coordinates based on image dimensions
            annotation = annotations[0]  # Only process the new annotation
            
            # Get original coordinates from frontend (480x400 viewport)
            orig_x = annotation.x
            orig_y = annotation.y
            orig_width = annotation.width
            orig_height = annotation.height

            # Calculate scaling factors
            scale_x = image_width / 480  # Frontend default width
            scale_y = image_height / 400  # Frontend default height

            # Scale coordinates to actual image dimensions
            scaled_x = int(orig_x * scale_x)
            scaled_y = int(orig_y * scale_y)
            scaled_width = int(orig_width * scale_x)
            scaled_height = int(orig_height * scale_y)

            # Add new label to predictions with scaled coordinates
            new_prediction = {
                "class": annotation.text,
                "x": scaled_x,
                "y": scaled_y,
                "width": scaled_width,
                "height": scaled_height,
                "points": []
            }
            prediction_json["predictions"].append(new_prediction)

            # Update prediction JSON in database
            prediction.prediction = json.dumps(prediction_json)
            
            annotated_image = image.copy()
            
            # Only draw the new annotation
            bgr_color = hex_to_bgr(annotation.color)
            
            # Draw rectangle for the new annotation
            cv2.rectangle(annotated_image,
                        (scaled_x, scaled_y),
                        (scaled_x + scaled_width, scaled_y + scaled_height),
                        bgr_color,
                        2)
            
            # Add label text
            label_text = annotation.text
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.7 * min(image_width/800, image_height/600)
            thickness = max(1, int(2 * min(image_width/800, image_height/600)))
            
            (text_width, text_height), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
            
            padding = int(5 * min(image_width/800, image_height/600))
            text_x = scaled_x
            text_y = scaled_y - padding
            
            # Ensure text stays within image bounds
            if text_y - text_height < 0:
                text_y = scaled_y + scaled_height + text_height + padding
            
            # Draw text background
            bg_pts = np.array([
                [text_x - padding, text_y - text_height - padding],
                [text_x + text_width + padding, text_y - text_height - padding],
                [text_x + text_width + padding, text_y + padding],
                [text_x - padding, text_y + padding]
            ], dtype=np.int32)
            
            cv2.fillPoly(annotated_image, [bg_pts], (0, 0, 0))
            
            # Draw text
            cv2.putText(annotated_image,
                      label_text,
                      (text_x, text_y),
                      font,
                      font_scale,
                      bgr_color,
                      thickness,
                      cv2.LINE_AA)

            # Save annotated image
            annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
            if annotated_image_pil.mode == 'RGBA':
                annotated_image_pil = annotated_image_pil.convert('RGB')
                
            current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            random_number = random.randint(1000, 9999)
            random_filename = f"{current_datetime}-{random_number}.jpeg"

            output_dir = os.path.join("uploads", "analyzed")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, random_filename)
            
            annotated_image_pil.save(output_path, optimize=True, quality=98, subsampling=0)
            
            prediction.predicted_image = output_path
            xray = db.query(XRay).filter(XRay.id == prediction.xray_id).first()
            if xray:
                xray.predicted_image = output_path
                xray.is_annotated = True
            db.commit()

        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Error processing image: {str(e)}"})

        new_annotated_image = update_image_url(prediction.predicted_image, request) if prediction.predicted_image else None

        # Convert to response dict
        response_dict = {
            "id": new_label.id,
            "name": new_label.name,
            "percentage": new_label.percentage,
            "prediction_id": new_label.prediction_id,
            "include": new_label.include,
            "color_hex": new_label.color_hex,
            "created_at": new_label.created_at.isoformat(),
            "updated_at": new_label.updated_at.isoformat(),
            "annotated_image": new_annotated_image
        }

        return JSONResponse(
            status_code=201,
            content=response_dict
        )

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})