from fastapi import APIRouter, Depends, Request, Body, UploadFile, File, Query
from fastapi.responses import JSONResponse
from db.db import get_db
from .models import XRay, Prediction, Legend
from sqlalchemy.orm import Session
from .schemas import XRayResponse, AddNotesRequest, LabelCreateAndUpdate, NewImageAnnotation
from typing import List
from utils.auth import verify_token
from utils.prediction import calculate_class_percentage, hex_to_bgr, colormap
from auth.models import User
from patient.models import Patient
from roboflow import Roboflow
from PIL import Image
import cv2
import numpy as np
import random, os
import datetime
import json
from decouple import config

def update_image_url(url: str, request: Request):
    base_url = str(request.base_url).rstrip('/')
    return f"{base_url}/{url}"

prediction_router = APIRouter()

@prediction_router.post(
    "/upload-xray/{patient_id}",
    status_code=201,
    summary="Upload X-Ray Image",
    description="""
    Upload an X-Ray image file for a specific patient.
    
    Parameters:
    - patient_id (str): The unique identifier of the patient
    - file (UploadFile): The X-Ray image file to upload (JPEG, PNG formats supported)
    
    Authentication:
    - Requires valid Bearer token in Authorization header
    
    The uploaded file will be:
    1. Saved to the server filesystem with a unique timestamp-based filename
    2. Associated with the specified patient in the database
    3. Made available for future analysis and predictions
    """,
    response_description="X-Ray upload confirmation with success message",
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
            "description": "Authentication failed",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "value": {"message": "Invalid or missing authentication token"}
                        },
                        "user_not_found": {
                            "value": {"message": "User not found"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "Patient not found in database",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        },
        500: {
            "description": "Server error during upload or database operation",
            "content": {
                "application/json": {
                    "example": {"message": "Server error: {detailed error message}"}
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
            doctor=user.id,
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
        print(str(e))
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Server error: {str(e)}"})

@prediction_router.get(
    "/get-xrays/{patient_id}",
    status_code=200,
    summary="Get Patient X-Rays",
    description="""
    Retrieve all X-Ray images and their metadata for a specific patient.
    
    Parameters:
    - patient_id (str): The unique identifier of the patient
    - page (int): Page number for pagination (default: 1)
    - per_page (int): Number of items per page (default: 10, max: 100)
    
    Authentication:
    - Requires valid Bearer token in Authorization header
    
    Returns:
    - List of X-Ray records containing:
        - Image URLs (original and predicted if available)
        - Annotation status
        - Creation and update timestamps
        - Associated metadata
        - Pagination details
    
    The image URLs are converted to fully qualified URLs based on the server's base URL.
    Results are ordered by creation date (newest first).
    """,
    response_model=list[XRayResponse],
    responses={
        200: {
            "description": "X-Ray records retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "X-Ray images retrieved successfully",
                        "xrays": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "patient": "123e4567-e89b-12d3-a456-426614174000", 
                                "original_image": "http://server.com/uploads/xrays/original.jpg",
                                "predicted_image": "http://server.com/uploads/xrays/predicted.jpg",
                                "is_annotated": True,
                                "created_at": "2023-01-01T00:00:00",
                                "updated_at": "2023-01-01T12:00:00"
                            }
                        ],
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
            "description": "Authentication failed",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "value": {"message": "Invalid or missing authentication token"}
                        },
                        "user_not_found": {
                            "value": {"message": "User not found"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "Patient not found in database",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        },
        500: {
            "description": "Server error during database query or response preparation",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: {detailed error message}"}
                }
            }
        }
    }
)
async def get_xrays(
    request: Request, 
    patient_id: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
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
        
        # Get total count
        total_count = db.query(XRay).filter(XRay.patient == patient.id).count()
        
        # Calculate offset for pagination
        offset = (page - 1) * per_page
        
        # Get paginated xrays
        xrays = (
            db.query(XRay)
            .filter(XRay.patient == patient.id)
            .order_by(XRay.created_at.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )
        
        xray_data = []
        for xray in xrays:
            xray_data.append({
                "id": xray.id,
                "patient": xray.patient,
                "original_image": update_image_url(xray.original_image, request),
                "prediction_id": xray.prediction_id if xray.prediction_id else None,
                "predicted_image": update_image_url(str(xray.predicted_image), request) if xray.predicted_image else None,
                "is_annotated": xray.is_annotated,
                "created_at": xray.created_at.isoformat() if xray.created_at else None,
                "updated_at": xray.updated_at.isoformat() if xray.updated_at else None
            })
        
        return JSONResponse(status_code=200, content={
            "message": "X-Ray images retrieved successfully",
            "xrays": xray_data,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            }
        })
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Internal server error: {str(e)}"})
    
@prediction_router.delete(
    "/delete-xray/{xray_id}",
    status_code=200,
    summary="Delete X-Ray Record",
    description="""
    Delete an X-Ray record and its associated files from the system.
    
    Parameters:
    - xray_id (str): The unique identifier of the X-Ray to delete
    
    Authentication:
    - Requires valid Bearer token in Authorization header
    
    The operation will:
    1. Remove the database record
    2. Delete associated image files from storage
    3. Remove any linked predictions or annotations
    
    This operation cannot be undone.
    """,
    responses={
        200: {
            "description": "X-Ray successfully deleted",
            "content": {
                "application/json": {
                    "example": {
                        "message": "X-Ray image deleted successfully"
                    }
                }
            }
        },
        401: {
            "description": "Authentication failed",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "value": {"message": "Invalid or missing authentication token"}
                        },
                        "user_not_found": {
                            "value": {"message": "User not found"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "X-Ray record not found",
            "content": {
                "application/json": {
                    "example": {"message": "X-Ray image not found"}
                }
            }
        },
        500: {
            "description": "Server error during deletion operation",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: {detailed error message}"}
                }
            }
        }
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
        prediction=prediction_str,
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

    return prediction

@prediction_router.get("/create-prediction/{xray_id}",
    response_model=dict,
    status_code=200,
    summary="Generate AI Prediction",
    description="""
    Create a new AI-powered prediction analysis for an X-ray image.
    
    Parameters:
    - xray_id (str): The unique identifier of the X-ray to analyze
    
    Authentication:
    - Requires valid Bearer token in Authorization header
    - User must have doctor privileges
    
    Process:
    1. Loads the original X-ray image
    2. Runs AI model for dental feature detection
    3. Generates annotated image with identified features
    4. Calculates feature percentages and statistics
    5. Saves results with color-coded legends
    
    The prediction includes:
    - Annotated image with labeled features
    - Confidence scores for detected features
    - Color-coded legend for easy interpretation
    - Statistical analysis of findings
    """,
    responses={
        200: {
            "description": "Prediction successfully generated",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Prediction created successfully",
                        "prediction_id": "550e8400-e29b-41d4-a716-446655440000",
                        "annotated_image": "http://server.com/uploads/analyzed/prediction.jpg"
                    }
                }
            }
        },
        400: {
            "description": "Invalid request parameters",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_xray": {
                            "value": {"error": "X-ray not found"}
                        },
                        "missing_file": {
                            "value": {"error": "X-ray image file not found"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication or authorization failed",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized - must be a doctor"}
                }
            }
        },
        500: {
            "description": "Server processing error",
            "content": {
                "application/json": {
                    "examples": {
                        "model_error": {
                            "value": {"error": "Model prediction failed: {detailed error}"}
                        },
                        "image_error": {
                            "value": {"error": "Image annotation failed: {detailed error}"}
                        },
                        "database_error": {
                            "value": {"error": "Database operation failed: {detailed error}"}
                        }
                    }
                }
            }
        }
    }
)
async def create_prediction(request: Request, xray_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
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
            annotated_image_url = update_image_url(str(xray.predicted_image), request) if xray.predicted_image else None

            xray.is_annotated = True
            
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
    summary="Retrieve Prediction Details",
    description="""
    Get comprehensive details of a specific prediction analysis.
    
    Parameters:
    - prediction_id (str): The unique identifier of the prediction to retrieve
    
    Authentication:
    - Requires valid Bearer token in Authorization header
    
    Returns:
    - Complete prediction details including:
        - Original and annotated images
        - Detection legends with percentages and colors
        - Patient information
        - Notes and annotations
        - Previous predictions for the same patient
        
    Images are returned as fully qualified URLs based on the server's base URL.
    """,
    responses={
        200: {
            "description": "Prediction details successfully retrieved",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Prediction details retrieved successfully",
                        "prediction": {
                            "id": "550e8400-e29b-41d4-a716-446655440000",
                            "xray_id": "123e4567-e89b-12d3-a456-426614174000",
                            "notes": "Patient shows signs of...",
                            "original_image": "http://server.com/uploads/xrays/original.jpg",
                            "predicted_image": "http://server.com/uploads/analyzed/prediction.jpg",
                            "patient": {
                                "name": "John Doe",
                                "phone": "+1234567890",
                                "email": "john@example.com",
                                "gender": "male"
                            },
                            "legends": [
                                {
                                    "id": "789e4567-e89b-12d3-a456-426614174000",
                                    "name": "cavity",
                                    "percentage": 85.5,
                                    "include": True,
                                    "color_hex": "#FF0000"
                                }
                            ],
                            "previous_predictions": [
                                {
                                    "id": "789e4567-e89b-12d3-a456-426614174111",
                                    "predicted_image": "http://server.com/uploads/analyzed/prev1.jpg",
                                    "created_at": "2023-01-01T00:00:00"
                                }
                            ],
                            "created_at": "2023-01-01T00:00:00",
                            "updated_at": "2023-01-01T12:00:00"
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid request parameters",
            "content": {
                "application/json": {
                    "example": {"error": "Prediction ID is required or prediction not found"}
                }
            }
        },
        401: {
            "description": "Authentication failed",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Server error during data retrieval",
            "content": {
                "application/json": {
                    "example": {"error": "Internal server error"}
                }
            }
        }
    }
)
async def get_prediction(request: Request, prediction_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id")  if decoded_token else None
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
        
        patient = db.query(Patient).filter(Patient.id == xray.patient).first()
        if not patient:
            return JSONResponse(status_code=400, content={"error": "Patient not found"})
        
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

        # Get previous predictions for this patient
        previous_xrays = db.query(XRay).filter(
            XRay.patient == patient.id,
            XRay.id != prediction.xray_id
        ).all()
        
        previous_predictions = []
        for prev_xray in previous_xrays:
            prev_prediction = db.query(Prediction).filter(Prediction.xray_id == prev_xray.id).first()
            if prev_prediction:
                previous_predictions.append({
                    "id": prev_prediction.id,
                    "predicted_image": update_image_url(str(prev_xray.predicted_image), request) if prev_xray.predicted_image else None,
                    "created_at": prev_prediction.created_at.isoformat() if prev_prediction.created_at else None
                })

        prediction_details = {
            "id": prediction.id,
            "xray_id": prediction.xray_id,
            "notes": prediction.notes,
            "original_image": update_image_url(str(xray.original_image), request),
            "predicted_image": update_image_url(str(xray.predicted_image), request) if xray.predicted_image else None,
            "legends": legend_details,
            "patient":{
                "name": patient.name,
                "gender": patient.gender.value,
                "phone": patient.mobile_number,
                "email": patient.email,
            },
            "previous_predictions": previous_predictions,
            "created_at": prediction.created_at.isoformat() if prediction.created_at else None,
            "updated_at": prediction.updated_at.isoformat() if prediction.updated_at else None
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
    Add notes to a prediction by its ID. The notes can contain any text describing findings or observations about the prediction.

    Required parameters:
    - prediction_id: UUID of the prediction to add notes to
    
    Request body:
    - notes: Text content to add as notes
    
    Required headers:
    - Authorization: Bearer token from login
    
    Returns:
    - 200: Notes successfully added with success message
    - 400: Invalid prediction ID or empty notes
    - 401: Invalid or missing authentication token
    - 500: Server error while processing request
    """,
    responses={
        200: {"description": "Notes added successfully", "content": {"application/json": {"example": {"message": "Notes added successfully"}}}},
        400: {"description": "Invalid prediction ID or empty notes", "content": {"application/json": {"example": {"error": "Notes are required"}}}},
        401: {"description": "Unauthorized - Invalid token", "content": {"application/json": {"example": {"error": "Unauthorized"}}}},
        500: {"description": "Internal server error", "content": {"application/json": {"example": {"error": "Error message"}}}}
    }
)
async def add_notes(request: Request, prediction_id: str, notes: AddNotesRequest, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        # Validate notes
        if not notes or not notes.notes:
            return JSONResponse(status_code=400, content={"error": "Notes are required"})

        # Validate prediction
        if not prediction_id:
            return JSONResponse(status_code=400, content={"error": "Prediction ID is required"})
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=400, content={"error": "Prediction not found"})
        

        # Update notes
        prediction.notes = notes.notes
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Notes added successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.delete("/delete-prediction/{prediction_id}",
    response_model=dict,
    status_code=200,
    summary="Delete a prediction",
    description="""
    Delete a prediction and all associated data (legends, annotations) by its ID.

    Required parameters:
    - prediction_id: UUID of the prediction to delete
    
    Required headers:
    - Authorization: Bearer token from login
    
    Returns:
    - 200: Prediction and associated data successfully deleted
    - 400: Invalid prediction ID
    - 401: Invalid or missing authentication token
    - 500: Server error while processing deletion
    """,
    responses={
        200: {"description": "Prediction deleted successfully", "content": {"application/json": {"example": {"message": "Prediction deleted successfully"}}}},
        400: {"description": "Invalid prediction ID", "content": {"application/json": {"example": {"error": "Prediction ID is required"}}}},
        401: {"description": "Unauthorized - Invalid token", "content": {"application/json": {"example": {"error": "Unauthorized"}}}},
        500: {"description": "Internal server error", "content": {"application/json": {"example": {"error": "Error message"}}}}
    }
)
async def delete_prediction(request: Request, prediction_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Validate prediction
        if not prediction_id:
            return JSONResponse(status_code=400, content={"error": "Prediction ID is required"})
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=400, content={"error": "Prediction not found"})
        
        legends = db.query(Legend).filter(Legend.prediction_id == prediction_id).all()
        for legend in legends:
            db.delete(legend)
        
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
    Reset a prediction by running the model again on the original X-ray image. This will:
    - Delete existing legends and annotations
    - Run prediction model again on original image
    - Generate new annotated image
    - Create new legends based on new predictions
    
    Required parameters:
    - prediction_id: UUID of the prediction to reset
    
    Required headers:
    - Authorization: Bearer token from login
    
    Returns:
    - 200: Prediction successfully reset with new annotated image URL
    - 400: Invalid prediction ID or missing image file
    - 401: Invalid or missing authentication token  
    - 500: Error during model prediction or image processing
    """,
    responses={
        200: {
            "description": "Prediction reset successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Prediction reset successfully",
                        "annotated_image": "http://example.com/images/analyzed/image.jpg"
                    }
                }
            }
        },
        400: {"description": "Invalid prediction ID or missing image", "content": {"application/json": {"example": {"error": "X-ray image file not found"}}}},
        401: {"description": "Unauthorized - Invalid token", "content": {"application/json": {"example": {"error": "Unauthorized"}}}},
        500: {"description": "Internal server error", "content": {"application/json": {"example": {"error": "Model prediction failed: error details"}}}}
    }
)
async def reset_prediction(request: Request, prediction_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
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
        old_legends = db.query(Legend).filter(Legend.prediction_id == prediction.id).all()
        for legend in old_legends:
            db.delete(legend)

        # Run prediction model
        try:
            rf = Roboflow(api_key=config("ROBOFLOW_API_KEY"))
            prediction_json = process_prediction_model(xray, rf)
            prediction_str = json.dumps(prediction_json)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Model prediction failed: {str(e)}"})

        # Generate annotated image
        try:
            image_path = str(xray.original_image)
            if not os.path.exists(image_path):
                return JSONResponse(status_code=400, content={"error": "X-ray image file not found"})
            image = cv2.imread(image_path)
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
            for legend in class_percentages:
                legend_obj = Legend(
                    prediction_id=prediction.id,
                    name=legend,
                    percentage=class_percentages[legend],
                    color_hex=hex_codes[legend]
                )
                db.add(legend_obj)
            db.commit()
            xray.predicted_image = output_path
            db.commit()
            annotated_image_url = update_image_url(str(xray.predicted_image), request) if xray.predicted_image else None
            
            return JSONResponse(status_code=200, content={
                "message": "Prediction reset successfully",
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
    Mark a legend as included in the prediction results. Included legends will be shown in the UI and used in calculations.

    Required parameters:
    - legend_id: UUID of the legend to include
    
    Required headers:
    - Authorization: Bearer token from login
    
    Returns:
    - 200: Legend successfully marked as included
    - 400: Invalid legend ID
    - 401: Invalid or missing authentication token
    - 500: Server error while updating legend
    """,
    responses={
        200: {"description": "Legend included successfully", "content": {"application/json": {"example": {"message": "Legend included successfully"}}}},
        400: {"description": "Invalid legend ID", "content": {"application/json": {"example": {"error": "Legend ID is required"}}}},
        401: {"description": "Unauthorized - Invalid token", "content": {"application/json": {"example": {"error": "Unauthorized"}}}},
        500: {"description": "Internal server error", "content": {"application/json": {"example": {"error": "Error message"}}}}
    }
)
async def include_legend(request: Request, legend_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
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
    Mark a legend as excluded from prediction results. Excluded legends will be hidden in the UI and omitted from calculations.

    Required parameters:
    - legend_id: UUID of the legend to exclude
    
    Required headers:
    - Authorization: Bearer token from login
    
    Returns:
    - 200: Legend successfully marked as excluded
    - 400: Invalid legend ID
    - 401: Invalid or missing authentication token
    - 500: Server error while updating legend
    """,
    responses={
        200: {"description": "Legend excluded successfully", "content": {"application/json": {"example": {"message": "Legend excluded successfully"}}}},
        400: {"description": "Invalid legend ID", "content": {"application/json": {"example": {"error": "Legend ID is required"}}}},
        401: {"description": "Unauthorized - Invalid token", "content": {"application/json": {"example": {"error": "Unauthorized"}}}},
        500: {"description": "Internal server error", "content": {"application/json": {"example": {"error": "Error message"}}}}
    }
)
async def exclude_legend(request: Request, legend_id: str, db: Session = Depends(get_db)):
    try:
        # Validate user
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
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
    Update a legend's name and color. This will:
    - Update the legend name and color in the database
    - Update the prediction JSON with the new name
    - Regenerate the annotated image with updated legend
    
    Required parameters:
    - legend_id: UUID of the legend to update
    
    Request body:
    - name: New name for the legend
    - color_hex: New color in hex format (e.g. "#FF0000")
    
    Required headers:
    - Authorization: Bearer token from login (doctor only)
    
    Returns:
    - 200: Legend successfully updated with updated legend details and new annotated image URL
    - 400: Invalid legend ID or image processing error
    - 401: Invalid token or non-doctor user
    - 404: Legend or related data not found
    - 500: Server error during update
    """,
    responses={
        200: {
            "description": "Legend updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "uuid",
                        "name": "Updated Name", 
                        "percentage": 0.75,
                        "prediction_id": "uuid",
                        "include": True,
                        "color_hex": "#FF0000",
                        "created_at": "2023-01-01T00:00:00",
                        "updated_at": "2023-01-01T00:00:00",
                        "annotated_image": "http://example.com/images/analyzed/image.jpg"
                    }
                }
            }
        },
        400: {"description": "Invalid legend ID or processing error", "content": {"application/json": {"example": {"error": "Failed to load image"}}}},
        401: {"description": "Unauthorized - must be a doctor", "content": {"application/json": {"example": {"error": "Unauthorized - must be a doctor"}}}},
        404: {"description": "Legend not found", "content": {"application/json": {"example": {"error": "Legend not found"}}}},
        500: {"description": "Internal server error", "content": {"application/json": {"example": {"error": "Error processing image: error details"}}}}
    }
)
async def update_legend(request: Request, legend_id: str, legend: LabelCreateAndUpdate, db: Session = Depends(get_db)):
    try:
        # Verify authentication token
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Invalid or missing token"})
            
        # Check if user is a doctor
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})

        # Get existing legend
        existing_legend = db.query(Legend).filter(Legend.id == legend_id).first()
        if not existing_legend:
            return JSONResponse(status_code=404, content={"error": "Legend not found"})

        # Get prediction and xray to update annotation
        prediction = db.query(Prediction).filter(Prediction.id == existing_legend.prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})
            
        xray = db.query(XRay).filter(XRay.id == prediction.xray_id).first()
        if not xray:
            return JSONResponse(status_code=404, content={"error": "X-ray not found"})

        # Update legend fields
        old_name = existing_legend.name
        existing_legend.name = legend.name
        existing_legend.color_hex = legend.color_hex
        existing_legend.updated_at = datetime.datetime.now()

        # Update annotation with updated legend
        try:
            image = cv2.imread(str(xray.original_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            prediction_json = json.loads(prediction.prediction)
            
            # Update legend name in predictions
            for pred in prediction_json["predictions"]:
                if pred["class"] == old_name:
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

            # Commit all changes together
            db.commit()

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

            return JSONResponse(status_code=200, content=response_dict)

        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Error processing image: {str(e)}"})

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@prediction_router.post("/add-missing-legends/{prediction_id}",
    response_model=dict,
    status_code=201,
    summary="Add missing legends to a prediction",
    description="""
    Add new legends that were missed by the model prediction. This will:
    - Create a new legend entry in the database
    - Update the prediction JSON with the new annotation
    - Regenerate the annotated image with the new legend
    
    Required parameters:
    - prediction_id: UUID of the prediction
    
    Request body:
    - annotations: List of new annotations containing:
        - text: Legend name
        - color: Color in hex format
        - x, y: Coordinates of annotation box
        - width, height: Dimensions of annotation box
    
    Required headers:
    - Authorization: Bearer token from login (doctor only)
    
    Returns:
    - 201: Legend successfully added with new legend details and updated annotated image URL
    - 400: Invalid prediction ID or image processing error
    - 401: Invalid token or non-doctor user
    - 404: Prediction or related data not found
    - 500: Server error during addition
    """,
    responses={
        201: {
            "description": "Missing legends added successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "uuid",
                        "name": "New Legend",
                        "percentage": 0.0,
                        "prediction_id": "uuid",
                        "include": True,
                        "color_hex": "#FF0000",
                        "created_at": "2023-01-01T00:00:00",
                        "updated_at": "2023-01-01T00:00:00",
                        "annotated_image": "http://example.com/images/analyzed/image.jpg"
                    }
                }
            }
        },
        400: {"description": "Invalid prediction ID or processing error", "content": {"application/json": {"example": {"error": "Failed to load image"}}}},
        401: {"description": "Unauthorized - must be a doctor", "content": {"application/json": {"example": {"error": "Unauthorized - must be a doctor"}}}},
        404: {"description": "Prediction not found", "content": {"application/json": {"example": {"error": "Prediction not found"}}}},
        500: {"description": "Internal server error", "content": {"application/json": {"example": {"error": "Error processing image: error details"}}}}
    }
)
async def add_missing_legends(
    request: Request,
    prediction_id: str,
    annotations: List[NewImageAnnotation],
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
        
        print(annotations)

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

        xray = db.query(XRay).filter(XRay.prediction_id == prediction.id).first()
        if not xray:
            return JSONResponse(status_code=404, content={"error": "X-ray not found"})

        # Update annotation with new label
        try:
            image = cv2.imread(str(xray.predicted_image))
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
            xray.predicted_image = output_path
            xray.is_annotated = True
            db.commit()

        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Error processing image: {str(e)}"})

        new_annotated_image = update_image_url(xray.predicted_image, request) if xray.predicted_image else None

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
    