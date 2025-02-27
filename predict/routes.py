from fastapi import APIRouter, Depends, Request, BackgroundTasks, Body
from fastapi.responses import JSONResponse
from db.db import get_db
from .model import Prediction, Label, DeletedLabel
from sqlalchemy.orm import Session
from .schema import PredictionResponse, LabelResponse, AddNotesRequest, LabelCreateAndUpdate, NewImageAnnotation
from typing import List
from utils.auth import verify_token
from utils.prediction import calculate_class_percentage
from auth.model import User
from patients.model import Patient
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
from patients.model import PatientXray
from utils.report import report_generate, create_dental_radiology_report, send_email_with_attachment
from dateutil.utils import today
from sqlalchemy import select, delete

def hex_to_bgr(hex_color):
    """Convert hex color to BGR tuple"""
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return (rgb[2], rgb[1], rgb[0])  # Convert RGB to BGR

def colormap(labels):
    classes = {
        "Attrited Enamel": '#00CED1',
        "Bone": '#AFEEEE',
        "Bone level": '#ADD8E6',
        "BoneLoss-InterRadicular": '#800020',
        "Boneloss-Interdental": '#800020',
        "CEJ": '#FFC0CB',
        "Calculus": '#4B0082',
        "Caries": '#008080',
        "ConeCut": '#AFEEEE',
        "Crown Prosthesis": '#C0C0C0',
        "Enamel": '#FFB6C1',
        "Impacted Molar": '#E6E6FA',
        "Implant": '#FFD700',
        "Incisor": '#FFFFE0',
        "InfAlvNrv": '#4169E1',
        "Mandibular Canine": '#90EE90',
        "Mandibular Molar": '#90EE90',
        "Mandibular Premolar": '#E6E6FA',
        "Mandibular Tooth": '#CCFF99',
        "Maxilary Canine": '#ADD8E6',
        "Maxilary Premolar": '#FFDAB9',
        "Maxillary Molar": '#87CEEB',
        "Maxillary Tooth": '#FFC0CB',
        "Missing Tooth": '#4169E1',
        "Obturated Canal": '#FF8C00',
        "Open Margin": '#8B4513',
        "OverHanging Restoration": '#191970',
        "Periapical Pathology": '#DC143C',
        "Pulp": '#FFA07A',
        "Restoration": '#FFBF00',
        "Root Stump": '#FF8C00',
        "Sinus": '#AFEEEE',
        "cr": '#008080',
        "crown length": '#8B4513',
        "im": '#FFD700',
        "nrv": '#FF8C00',
        "10": '#FFA07A',
        "11": '#FFB6C1',
        "12": '#87CEEB',
        "13": '#FFC0CB',
        "14": '#4169E1',
        "15": '#8B4513',
        "16": '#90EE90',
        "17": '#4B0082',
        "18": '#800020',
        "19": '#FF8C00',
        "20": '#DC143C',
        "21": '#00CED1',
        "22": '#AFEEEE',
        "23": '#800020',
        "24": '#FFDAB9',
        "25": '#DB7093',
        "26": '#FFD700',
        "27": '#E6E6FA',
        "28": '#CCFF99',
        "29": '#8622FF',
        "30": '#FE0056',
        "31": '#DC143C',
        "32": '#FF8C00',
        "4": '#CCFF99',
        "5": '#8622FF',
        "6": '#FE0056',
        "7": '#DC143C',
        "8": '#FF8C00',
        "9": '#008080',
        "Impacted Incisors": '#90EE90',
        "Impacted Molar": '#FFC0CB',
        "Inf Alv Nrv": '#87CEEB',
        "License- CC BY 4-0": '#008080',
        "Mandibular Fracture": '#4169E1',
        "Provided by a Roboflow user": '#FFA07A',
        "cone cut": '#4B0082',
        "https-universe-roboflow-com-salud360-dental-qbbud": '#FFB6C1',
        "pathology": '#8B4513',
    }
    
    colors = []
    hex_codes = {}
    for label in labels:
        if label in classes:
            colors.append(classes[label])
            hex_codes[label] = classes[label]
        else:
            # Default color for unknown classes
            colors.append('#FFFFFF')
            hex_codes[label] = '#FFFFFF'
    return colors, hex_codes

prediction_router = APIRouter()

@prediction_router.get("/get-predictions/{patient_id}",
    response_model=List[PredictionResponse],
    status_code=200,
    summary="Get patient predictions",
    description="""
    Get all predictions for a specific patient
    
    Required parameters:
    - patient_id: UUID of the patient
    
    Returns list of predictions with:
    - id: Prediction UUID
    - patient: Patient UUID
    - original_image: Path to original X-ray
    - predicted_image: Path to annotated prediction image
    - is_annotated: Whether prediction has been annotated
    - created_at: Creation timestamp
    - updated_at: Last update timestamp
    """,
    responses={
        200: {"description": "List of predictions retrieved successfully"},
        500: {"description": "Internal server error"}
    }
)
async def get_predictions(patient_id: str, db: Session = Depends(get_db)):
    try:        
        predictions = db.query(Prediction).filter(Prediction.patient == patient_id).all()
        return predictions
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.get("/get-prediction/{prediction_id}",
    response_model=dict,
    status_code=200,
    summary="Get prediction details", 
    description="""
    Get detailed information about a specific prediction    
    
    Required parameters:
    - prediction_id: UUID of the prediction
    
    Required headers:
    - Authorization: Bearer token from login
    
    Returns prediction details with:
    - prediction: Full prediction object
    - labels: List of detected labels with confidence scores
    """,
    responses={
        200: {"description": "Prediction details retrieved successfully"},
        404: {"description": "Prediction not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_prediction(request: Request, prediction_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)

        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})
        
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})

        # Get base URL without trailing slash
        base_url = str(request.base_url).rstrip('/')

        patient = db.query(Patient).filter(Patient.id == prediction.patient).first()

        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
            
        # Create relative URLs for images
        original_image_url = f"{base_url}/{prediction.original_image}"
        predicted_image_url = f"{base_url}/{prediction.predicted_image}" if prediction.predicted_image else None

        # Create a copy of prediction to avoid modifying the DB object
        prediction_response = PredictionResponse.from_orm(prediction)

        prediction_response.original_image = original_image_url
        prediction_response.predicted_image = predicted_image_url
        prediction_response.patient = {
            "id": patient.id,
            "name": patient.first_name + " " + patient.last_name,
            "gender": patient.gender,
            "phone": patient.phone,
            "email": patient.email,
        }

        # Fetch all previous predictions excluding the current one
        previous_predictions = db.query(Prediction).filter(
            Prediction.patient == prediction.patient,
            Prediction.id != prediction_id
        ).order_by(Prediction.created_at.desc()).all()
        
        # Process previous predictions
        previous_predictions_response = []
        for prev in previous_predictions:
            prev_response = PredictionResponse.from_orm(prev)
            prev_response.original_image = f"{base_url}/{prev.original_image}"
            prev_response.predicted_image = f"{base_url}/{prev.predicted_image}" if prev.predicted_image else None
            previous_predictions_response.append(prev_response)
        
        labels = db.query(Label).filter(Label.prediction_id == prediction_id).all()
        
        prediction_data = {
            "prediction": prediction_response,
            "previous_predictions": previous_predictions_response,
            "labels": [LabelResponse.from_orm(label) for label in labels]
        }
        
        return prediction_data
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
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
        decoded_token = verify_token(request)

        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()

        if not user or str(user.user_type) != "doctor" :
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})
        
        # Validate and get X-ray
        if not xray_id:
            return JSONResponse(status_code=400, content={"error": "X-ray ID is required"})
        
        xray = db.query(PatientXray).filter(PatientXray.id == xray_id).first()
        
        if not xray:
            return JSONResponse(status_code=400, content={"error": "X-ray not found"})
        
        # Validate image exists
        if not os.path.exists(str(xray.original_image)):
            return JSONResponse(status_code=400, content={"error": "X-ray image file not found"})
            
        # Run prediction model based on xray type
        try:
            rf = Roboflow(api_key=config("ROBOFLOW_API_KEY"))
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
                return JSONResponse(status_code=500, content={"error": "Prediction failed"})
                
            prediction_json = prediction_result.json()
            
            # Store prediction data with sequential class_ids
            prediction_str = json.dumps(prediction_json)
            
        except Exception as e:
            print("Exception error: ", str(e))
            return JSONResponse(status_code=500, content={"error": f"Model prediction failed: {str(e)}"})

        # Generate annotated image
        try:
            image = cv2.imread(str(xray.original_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            # Extract labels and create detections
            labels = [item["class"] for item in prediction_json["predictions"]]
            
            # Get colors for each label
            _, hex_codes = colormap(labels)
            
            # Create output image
            annotated_image = image.copy()
            
            # Store label positions to check for overlaps
            label_boxes = []
            
            # Helper function to check if two boxes overlap
            def check_overlap(box1, box2):
                return not (box1['x2'] < box2['x1'] or 
                          box1['x1'] > box2['x2'] or 
                          box1['y2'] < box2['y1'] or 
                          box1['y1'] > box2['y2'])
            
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
                    
                    # Apply colored mask without border
                    overlay = annotated_image.copy()
                    overlay[mask == 1] = bgr_color
                    alpha = 0.4  # Reduced opacity for better visibility
                    annotated_image = cv2.addWeighted(overlay, alpha, annotated_image, 1 - alpha, 0)
                
                # Add improved label text
                x = int(pred["x"] - pred["width"]/2)
                y = int(pred["y"] - pred["height"]/2)
                confidence = pred.get("confidence", 1.0)
                label_text = f"{label}"
                
                # Get text size for background
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.7
                thickness = 2
                (text_width, text_height), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
                
                # Calculate label box coordinates
                padding = 5
                label_box = {
                    'x1': x - padding,
                    'y1': y - text_height - 2*padding,
                    'x2': x + text_width + padding,
                    'y2': y + padding
                }
                
                # Check for overlaps and adjust position if needed
                overlap_count = 0
                while any(check_overlap(label_box, existing_box) for existing_box in label_boxes):
                    # Alternate between moving up and right to avoid clustering
                    if overlap_count % 2 == 0:
                        # Move up
                        y -= (text_height + 2*padding + 5)
                        label_box['y1'] = y - text_height - 2*padding
                        label_box['y2'] = y + padding
                    else:
                        # Move right
                        x += (text_width + 2*padding + 5)
                        label_box['x1'] = x - padding
                        label_box['x2'] = x + text_width + padding
                    
                    overlap_count += 1
                    
                    # Prevent infinite loop by limiting iterations
                    if overlap_count > 10:
                        break
                
                # Add the final position to label_boxes
                label_boxes.append(label_box)
                
                # Draw text background with rounded corners
                bg_pts = np.array([
                    [label_box['x1'], label_box['y1']],
                    [label_box['x2'], label_box['y1']],
                    [label_box['x2'], label_box['y2']],
                    [label_box['x1'], label_box['y2']]
                ], dtype=np.int32)
                
                # Draw semi-transparent background
                overlay_bg = annotated_image.copy()
                cv2.fillPoly(overlay_bg, [bg_pts], (0, 0, 0))
                annotated_image = cv2.addWeighted(overlay_bg, 0.7, annotated_image, 0.3, 0)
                
                # Draw text with improved visibility
                cv2.putText(annotated_image, 
                          label_text,
                          (x, y),
                          font,
                          font_scale,
                          bgr_color,
                          thickness,
                          cv2.LINE_AA)

            # Apply subtle image enhancements
            annotated_image = cv2.convertScaleAbs(annotated_image, alpha=1.1, beta=5)  # Contrast and brightness
            
            # Convert to PIL and save
            annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
            if annotated_image_pil.mode == 'RGBA':
                annotated_image_pil = annotated_image_pil.convert('RGB')
                
            current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            random_number = random.randint(1000, 9999)
            random_filename = f"{current_datetime}-{random_number}.jpeg"

            output_dir = os.path.join("uploads", "analyzed")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, random_filename)
            
            # Save with high quality
            annotated_image_pil.save(output_path, 
                                   optimize=True, 
                                   quality=98,  # High quality
                                   subsampling=0)  # Better color accuracy
                                   
        except Exception as e:
            print("Exception error: ", str(e))
            return JSONResponse(status_code=500, content={"error": f"Image annotation failed: {str(e)}"})

        # Save prediction results
        try:
            class_percentages = calculate_class_percentage(prediction_json)
            
            prediction = Prediction(
                patient=xray.patient,
                original_image=xray.original_image,
                predicted_image=output_path,
                is_annotated=True,
                prediction=prediction_str,
                xray_id=xray.id
            )
            db.add(prediction)
            db.commit()

            # Bulk insert labels with hex colors
            labels = [
                Label(
                    prediction_id=prediction.id,
                    name=class_name,
                    percentage=percentage,
                    include=True,
                    color_hex=hex_codes.get(class_name, '#FFFFFF')
                )
                for class_name, percentage in class_percentages.items()
            ]
            db.add_all(labels)
            db.commit()

            # Update patient xray with annotated image
            xray.annotated_image = output_path
            xray.prediction_id = str(prediction.id)
            db.commit()

            user.credits -= 1
            user.used_credits += 1
            db.commit()

            annotated_image_url = f"{request.base_url}{prediction.predicted_image}" if prediction.predicted_image else None
            
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
    
@prediction_router.delete("/delete-prediction/{prediction_id}",
    status_code=200,
    summary="Delete a prediction",
    description="""
    Delete a prediction by its ID
    """,
    responses={
        200: {"description": "Prediction deleted successfully"},
        404: {"description": "Prediction not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_prediction(prediction_id: str, db: Session = Depends(get_db)):
    try:
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})
        
        db.delete(prediction)
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Prediction deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

async def generate_and_send_report(
    prediction_id: str,
    user: User,
    patient: Patient,
    findings: str,
    notes: str,
    db: Session
):
    """Background task to generate and send the report"""
    try:
        report_content = report_generate(
            prediction_str=findings,
            notes=notes,
            doctor_name=user.name,
            doctor_email=user.email,
            doctor_phone=user.phone,
            patient_name=f"{patient.first_name} {patient.last_name}",
            patient_age=patient.age,
            patient_gender=patient.gender,
            patient_phone=patient.phone,
            date=today().strftime("%Y-%m-%d")
        )

        if isinstance(report_content, JSONResponse):
            return

        # Create PDF report
        report_pdf = create_dental_radiology_report(
            patient_name=f"{patient.first_name} {patient.last_name}",
            report_content=report_content
        )
        
        if not report_pdf:
            return

        # Send email with report
        send_email_with_attachment(
            to_email=user.email,
            patient_name=f"{patient.first_name} {patient.last_name}",
            pdf_file_path=report_pdf
        )

    except Exception:
        pass
    
@prediction_router.get("/make-report/{prediction_id}",
    status_code=200,
    summary="Generate dental radiology report",
    description="""
    Generate a detailed dental radiology report for a prediction, including analysis and recommendations.
    The report will be emailed to the doctor.
    
    Required:
    - prediction_id: UUID of the prediction
    - Authorization header with doctor's token
    """,
    responses={
        200: {"description": "Report generation started"},
        401: {"description": "Unauthorized - must be a doctor"},
        404: {"description": "Prediction or patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def make_report(
    request: Request,
    prediction_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    try:
        # Verify doctor authorization
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Invalid or missing token"})
            
        user = db.query(User).filter(
            User.id == decoded_token.get("user_id"),
            User.user_type == "doctor"
        ).first()
        
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})

        # Get prediction with labels
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})

        # Get patient details
        patient = db.query(Patient).filter(Patient.id == prediction.patient).first()
        
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})

        # Get prediction labels and format findings
        labels = db.query(Label).filter(
            Label.prediction_id == prediction_id,
            Label.include == True
        ).all()
        
        if not labels:
            return JSONResponse(status_code=404, content={"error": "No findings available for this prediction"})

        findings = "\n".join([
            f"{label.name}: {label.percentage:.1f}% confidence" 
            for label in labels
        ])


        # Add report generation to background tasks
        background_tasks.add_task(
            generate_and_send_report,
            prediction_id=prediction_id,
            user=user,
            patient=patient,
            findings=findings,
            notes=str(prediction.notes) if prediction.notes else "",
            db=db
        )

        return JSONResponse(
            status_code=200,
            content={
                "message": "Report generation started. You will receive an email when ready.",
                "email": user.email
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Unexpected error: {str(e)}"}
        )

@prediction_router.delete("/delete-label/{label_id}",
    status_code=200,
    summary="Delete a label",
    description="""
    Delete a label by its ID
    """,
    responses={
        200: {"description": "Label deleted successfully"},
        404: {"description": "Label not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_label(request: Request, label_id: str, db: Session = Depends(get_db)):
    try:
        # Verify doctor authorization
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Invalid or missing token"})
            
        user = db.query(User).filter(
            User.id == decoded_token.get("user_id"),
            User.user_type == "doctor"
        ).first()
        
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})

        label = db.query(Label).filter(Label.id == label_id).first()
        
        if not label:
            return JSONResponse(status_code=404, content={"error": "Label not found"})
        
        prediction = db.query(Prediction).filter(Prediction.id == label.prediction_id).first()
        
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})

        # Delete old annotated image if it exists
        if prediction.predicted_image and os.path.exists(prediction.predicted_image):
            os.remove(prediction.predicted_image)

        # Mark label as not included
        label.include = False
        db.commit()

        # Parse prediction JSON string properly
        try:
            prediction_json = json.loads(prediction.prediction)
        except json.JSONDecodeError:
            return JSONResponse(status_code=500, content={"error": "Invalid prediction JSON format"})

        # Get all labels for this prediction that are still included
        included_labels = db.query(Label).filter(
            Label.prediction_id == prediction.id,
            Label.include == True
        ).all()

        included_label_names = [label.name for label in included_labels]

        # Filter predictions to only included labels
        remaining_predictions = [
            pred for pred in prediction_json["predictions"]
            if pred["class"] in included_label_names
        ]

        # Get removed prediction data
        removed_predictions = [
            pred for pred in prediction_json["predictions"]
            if pred["class"] == label.name
        ]

        # Save excluded label data
        deleted_label = DeletedLabel(
            label_id=label.id,
            prediction_data=json.dumps(removed_predictions)
        )
        db.add(deleted_label)
        db.commit()
        
        prediction_json["predictions"] = remaining_predictions
        prediction.prediction = json.dumps(prediction_json)

        # Regenerate annotated image if there are remaining predictions
        if prediction_json["predictions"]:
            try:
                image = cv2.imread(str(prediction.original_image))
                if image is None:
                    return JSONResponse(status_code=400, content={"error": "Failed to load image"})

                # Extract labels and create detections
                labels = [item["class"] for item in prediction_json["predictions"]]
                
                # Get colors for each label
                _, hex_codes = colormap(labels)
                
                # Create output image
                annotated_image = image.copy()
                
                # Store label positions to check for overlaps
                label_boxes = []
                
                # Helper function to check if two boxes overlap
                def check_overlap(box1, box2):
                    return not (box1['x2'] < box2['x1'] or 
                              box1['x1'] > box2['x2'] or 
                              box1['y2'] < box2['y1'] or 
                              box1['y1'] > box2['y2'])
                
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
                        
                        # Apply colored mask without border
                        overlay = annotated_image.copy()
                        overlay[mask == 1] = bgr_color
                        alpha = 0.4  # Reduced opacity for better visibility
                        annotated_image = cv2.addWeighted(overlay, alpha, annotated_image, 1 - alpha, 0)
                    
                    # Add improved label text
                    x = int(pred["x"] - pred["width"]/2)
                    y = int(pred["y"] - pred["height"]/2)
                    confidence = pred.get("confidence", 1.0)
                    label_text = f"{label}"
                    
                    # Get text size for background
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.7
                    thickness = 2
                    (text_width, text_height), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
                    
                    # Calculate label box coordinates
                    padding = 5
                    label_box = {
                        'x1': x - padding,
                        'y1': y - text_height - 2*padding,
                        'x2': x + text_width + padding,
                        'y2': y + padding
                    }
                    
                    # Check for overlaps and adjust position if needed
                    while any(check_overlap(label_box, existing_box) for existing_box in label_boxes):
                        # Move the label up by the height of the text box plus some spacing
                        y -= (text_height + 2*padding + 5)
                        label_box['y1'] = y - text_height - 2*padding
                        label_box['y2'] = y + padding
                    
                    # Add the final position to label_boxes
                    label_boxes.append(label_box)
                    
                    # Draw text background with rounded corners
                    bg_pts = np.array([
                        [label_box['x1'], label_box['y1']],
                        [label_box['x2'], label_box['y1']],
                        [label_box['x2'], label_box['y2']],
                        [label_box['x1'], label_box['y2']]
                    ], dtype=np.int32)
                    
                    # Draw semi-transparent background
                    overlay_bg = annotated_image.copy()
                    cv2.fillPoly(overlay_bg, [bg_pts], (0, 0, 0))
                    annotated_image = cv2.addWeighted(overlay_bg, 0.7, annotated_image, 0.3, 0)
                    
                    # Draw text with improved visibility
                    cv2.putText(annotated_image, 
                              label_text,
                              (x, y),
                              font,
                              font_scale,
                              bgr_color,
                              thickness,
                              cv2.LINE_AA)

                # Apply subtle image enhancements
                annotated_image = cv2.convertScaleAbs(annotated_image, alpha=1.1, beta=5)
                
                # Convert to PIL and save
                annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
                if annotated_image_pil.mode == 'RGBA':
                    annotated_image_pil = annotated_image_pil.convert('RGB')
                    
                current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                random_number = random.randint(1000, 9999)
                random_filename = f"{current_datetime}-{random_number}.jpeg"

                output_dir = os.path.join("uploads", "analyzed")
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir, random_filename)
                
                # Save with high quality
                annotated_image_pil.save(output_path, 
                                       optimize=True, 
                                       quality=98,
                                       subsampling=0)

                # Update prediction with new image path
                prediction.predicted_image = output_path
                
                # Update xray with new annotated image
                xray = db.query(PatientXray).filter(PatientXray.prediction_id == prediction.id).first()
                
                if xray:
                    xray.annotated_image = output_path

                db.commit()

            except Exception as e:
                db.rollback()
                return JSONResponse(status_code=500, content={"error": f"Error processing image: {str(e)}"})

        new_annotated_image = f"{request.base_url}{prediction.predicted_image}" if prediction.predicted_image else None
        
        return JSONResponse(status_code=200, content={
            "message": "Label marked as excluded successfully",
            "annotated_image": new_annotated_image
        })

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@prediction_router.get("/include-label/{label_id}",
    status_code=200, 
    summary="Include a label",
    description="""
    Include a previously excluded label by its ID
    """,
    responses={
        200: {"description": "Label included successfully"},
        404: {"description": "Label not found"},
        500: {"description": "Internal server error"}
    }
)
async def include_label(request: Request, label_id: str, db: Session = Depends(get_db)):
    try:
        # Verify doctor authorization
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Invalid or missing token"})
            
        user = db.query(User).filter(
            User.id == decoded_token.get("user_id"),
            User.user_type == "doctor"
        ).first()
        
        if not user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized - must be a doctor"})

        label = db.query(Label).filter(Label.id == label_id).first()
        
        if not label:
            return JSONResponse(status_code=404, content={"error": "Label not found"})
        
        prediction = db.query(Prediction).filter(Prediction.id == label.prediction_id).first()
        
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})

        # Delete old annotated image if it exists
        if prediction.predicted_image and os.path.exists(prediction.predicted_image):
            os.remove(prediction.predicted_image)

        # Mark label as included
        label.include = True
        db.commit()

        # Get deleted label data
        deleted_label = db.query(DeletedLabel).filter(DeletedLabel.label_id == label_id).first()
        
        if not deleted_label:
            return JSONResponse(status_code=404, content={"error": "Deleted label data not found"})

        # Parse prediction JSON strings
        try:
            prediction_json = json.loads(prediction.prediction)
            deleted_predictions = json.loads(deleted_label.prediction_data)
        except json.JSONDecodeError:
            return JSONResponse(status_code=500, content={"error": "Invalid prediction JSON format"})

        # Combine current and deleted predictions
        all_predictions = prediction_json["predictions"] + deleted_predictions
            
        prediction_json["predictions"] = all_predictions
        prediction.prediction = json.dumps(prediction_json)

        # Delete the deleted label record
        db.delete(deleted_label)
        db.commit()

        # Regenerate annotated image
        try:
            image = cv2.imread(str(prediction.original_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            # Extract labels and create detections
            labels = [item["class"] for item in prediction_json["predictions"]]
            
            # Get colors for each label
            _, hex_codes = colormap(labels)
            
            # Create output image
            annotated_image = image.copy()
            
            # Store label positions to check for overlaps
            label_boxes = []
            
            # Helper function to check if two boxes overlap
            def check_overlap(box1, box2):
                return not (box1['x2'] < box2['x1'] or 
                          box1['x1'] > box2['x2'] or 
                          box1['y2'] < box2['y1'] or 
                          box1['y1'] > box2['y2'])
            
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
                    
                    # Apply colored mask without border
                    overlay = annotated_image.copy()
                    overlay[mask == 1] = bgr_color
                    alpha = 0.4  # Reduced opacity for better visibility
                    annotated_image = cv2.addWeighted(overlay, alpha, annotated_image, 1 - alpha, 0)
                
                # Add improved label text
                x = int(pred["x"] - pred["width"]/2)
                y = int(pred["y"] - pred["height"]/2)
                confidence = pred.get("confidence", 1.0)
                label_text = f"{label}"
                
                # Get text size for background
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.7
                thickness = 2
                (text_width, text_height), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
                
                # Calculate label box coordinates
                padding = 5
                label_box = {
                    'x1': x - padding,
                    'y1': y - text_height - 2*padding,
                    'x2': x + text_width + padding,
                    'y2': y + padding
                }
                
                # Check for overlaps and adjust position if needed
                while any(check_overlap(label_box, existing_box) for existing_box in label_boxes):
                    # Move the label up by the height of the text box plus some spacing
                    y -= (text_height + 2*padding + 5)
                    label_box['y1'] = y - text_height - 2*padding
                    label_box['y2'] = y + padding
                
                # Add the final position to label_boxes
                label_boxes.append(label_box)
                
                # Draw text background with rounded corners
                bg_pts = np.array([
                    [label_box['x1'], label_box['y1']],
                    [label_box['x2'], label_box['y1']],
                    [label_box['x2'], label_box['y2']],
                    [label_box['x1'], label_box['y2']]
                ], dtype=np.int32)
                
                # Draw semi-transparent background
                overlay_bg = annotated_image.copy()
                cv2.fillPoly(overlay_bg, [bg_pts], (0, 0, 0))
                annotated_image = cv2.addWeighted(overlay_bg, 0.7, annotated_image, 0.3, 0)
                
                # Draw text with improved visibility
                cv2.putText(annotated_image, 
                          label_text,
                          (x, y),
                          font,
                          font_scale,
                          bgr_color,
                          thickness,
                          cv2.LINE_AA)

            # Apply subtle image enhancements
            annotated_image = cv2.convertScaleAbs(annotated_image, alpha=1.1, beta=5)
            
            # Convert to PIL and save
            annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
            if annotated_image_pil.mode == 'RGBA':
                annotated_image_pil = annotated_image_pil.convert('RGB')
                
            current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            random_number = random.randint(1000, 9999)
            random_filename = f"{current_datetime}-{random_number}.jpeg"

            output_dir = os.path.join("uploads", "analyzed")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, random_filename)
            
            # Save with high quality
            annotated_image_pil.save(output_path, 
                                   optimize=True, 
                                   quality=98,
                                   subsampling=0)

            # Update prediction with new image path
            prediction.predicted_image = output_path
            
            # Update xray with new annotated image
            xray = db.query(PatientXray).filter(PatientXray.prediction_id == prediction.id).first()
            
            if xray:
                xray.annotated_image = output_path

            db.commit()

        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Error processing image: {str(e)}"})

        new_annotated_image = f"{request.base_url}{prediction.predicted_image}" if prediction.predicted_image else None

        print("new_annotated_image", new_annotated_image)
        
        return JSONResponse(status_code=200, content={
            "message": "Label marked as included successfully",
            "annotated_image": new_annotated_image
        })

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.post("/add-notes/{prediction_id}",
    status_code=200,
    summary="Add notes to a prediction",
    description="""
    Add notes to a prediction by its ID
    """,
    responses={
        200: {"description": "Notes added successfully"},
        404: {"description": "Prediction not found"},
        500: {"description": "Internal server error"}
    }
)
async def add_notes(request: Request, prediction_id: str, add_notes_request: AddNotesRequest, db: Session = Depends(get_db)):
    try:
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})
        
        prediction.notes = add_notes_request.notes
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Notes added successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@prediction_router.post("/create-label/{prediction_id}",
    status_code=201,
    summary="Create a new label for a prediction",
    description="""
    Create a new label for a prediction. Only doctors can create labels.
    The label will be associated with the specified prediction.
    Returns the complete label object.
    """,
    responses={
        201: {"description": "Label created successfully", "model": LabelResponse},
        401: {"description": "Unauthorized - Invalid token or not a doctor"},
        404: {"description": "Prediction not found"},
        500: {"description": "Internal server error"}
    }
)
async def add_label(
    request: Request,
    prediction_id: str,
    annotations: List[dict] = Body(...),
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
        new_label = Label(
            name=annotations[0]["text"],
            prediction_id=prediction_id,
            include=True,
            percentage=0.0,  # Default percentage
            color_hex=annotations[0]["color"]
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
            orig_x = annotation["x"]
            orig_y = annotation["y"]
            orig_width = annotation["width"]
            orig_height = annotation["height"]

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
                "class": annotation["text"],
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
            bgr_color = hex_to_bgr(annotation["color"])
            
            # Draw rectangle for the new annotation
            cv2.rectangle(annotated_image,
                        (scaled_x, scaled_y),
                        (scaled_x + scaled_width, scaled_y + scaled_height),
                        bgr_color,
                        2)
            
            # Add label text
            label_text = annotation["text"]
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
            xray = db.query(PatientXray).filter(PatientXray.prediction_id == prediction.id).first()
            if xray:
                xray.annotated_image = output_path
            db.commit()

        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Error processing image: {str(e)}"})

        new_annotated_image = f"{request.base_url}{prediction.predicted_image}" if prediction.predicted_image else None

        # Convert to response dict
        response_dict = {
            "id": new_label.id,
            "name": new_label.name,
            "percentage": new_label.percentage,
            "prediction_id": new_label.prediction_id,
            "include": new_label.include,
            "created_at": new_label.created_at.isoformat(),
            "updated_at": new_label.updated_at.isoformat(),
            "annotated_image": new_annotated_image,
            "color_hex": new_label.color_hex
        }

        return JSONResponse(
            status_code=201,
            content=response_dict
        )

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@prediction_router.patch("/update-label/{label_id}",
    status_code=200,
    summary="Update a label",
    description="""
    Update an existing label. Only doctors can update labels.
    Allows partial updates of label fields.
    Returns the updated label object.
    """,
    responses={
        200: {"description": "Label updated successfully", "model": LabelResponse},
        401: {"description": "Unauthorized - Invalid token or not a doctor"},
        404: {"description": "Label not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_label(
    request: Request,
    label_id: str,
    label: LabelCreateAndUpdate,
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

        # Get existing label
        existing_label = db.query(Label).filter(Label.id == label_id).first()
        
        if not existing_label:
            return JSONResponse(status_code=404, content={"error": "Label not found"})

        # Update only provided fields
        if label.name is not None:
            existing_label.name = label.name
            existing_label.color_hex = label.color_hex

        # Get prediction to update annotation
        prediction = db.query(Prediction).filter(Prediction.id == existing_label.prediction_id).first()
        
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})

        # Update annotation with updated label
        try:
            image = cv2.imread(str(prediction.original_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            prediction_json = json.loads(prediction.prediction)
            
            # Update label name in predictions
            for pred in prediction_json["predictions"]:
                if pred["class"] == existing_label.name:
                    pred["class"] = label.name
                    
            # Update prediction JSON in database
            prediction.prediction = json.dumps(prediction_json)
            
            labels = [item["class"] for item in prediction_json["predictions"]]
            _, hex_codes = colormap(labels)
            
            # Override color for updated label
            hex_codes[label.name] = label.color_hex
            
            annotated_image = image.copy()
            label_boxes = []
            
            def check_overlap(box1, box2):
                return not (box1['x2'] < box2['x1'] or 
                          box1['x1'] > box2['x2'] or 
                          box1['y2'] < box2['y1'] or 
                          box1['y1'] > box2['y2'])

            for pred in prediction_json["predictions"]:
                label_name = pred["class"]
                hex_color = hex_codes[label_name]
                bgr_color = hex_to_bgr(hex_color)
                
                if "points" in pred:
                    points = np.array([[int(p["x"]), int(p["y"])] for p in pred["points"]], dtype=np.int32)
                    mask = np.zeros(image.shape[:2], dtype=np.uint8)
                    cv2.fillPoly(mask, [points], (1, 1, 1))
                    
                    overlay = annotated_image.copy()
                    overlay[mask == 1] = bgr_color
                    alpha = 0.4
                    annotated_image = cv2.addWeighted(overlay, alpha, annotated_image, 1 - alpha, 0)
                
                x = int(pred["x"] - pred["width"]/2)
                y = int(pred["y"] - pred["height"]/2)
                label_text = f"{label_name}"
                
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.7
                thickness = 2
                (text_width, text_height), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
                
                padding = 5
                label_box = {
                    'x1': x - padding,
                    'y1': y - text_height - 2*padding,
                    'x2': x + text_width + padding,
                    'y2': y + padding
                }
                
                while any(check_overlap(label_box, existing_box) for existing_box in label_boxes):
                    y -= (text_height + 2*padding + 5)
                    label_box['y1'] = y - text_height - 2*padding
                    label_box['y2'] = y + padding
                
                label_boxes.append(label_box)
                
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
            xray = db.query(PatientXray).filter(PatientXray.prediction_id == prediction.id).first()
            if xray:
                xray.annotated_image = output_path
            db.commit()

        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Error processing image: {str(e)}"})

        db.commit()
        db.refresh(existing_label)

        new_annotated_image = f"{request.base_url}{prediction.predicted_image}" if prediction.predicted_image else None

        # Convert to response dict
        response_dict = {
            "id": existing_label.id,
            "name": existing_label.name,
            "percentage": existing_label.percentage,
            "prediction_id": existing_label.prediction_id,
            "include": existing_label.include,
            "color_hex": existing_label.color_hex,
            "created_at": existing_label.created_at.isoformat(),
            "updated_at": existing_label.updated_at.isoformat(),
            "annotated_image": new_annotated_image
        }

        return JSONResponse(
            status_code=200,
            content=response_dict
        )

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@prediction_router.get("/reset-analysis/{xray_id}",
    status_code=200,
    summary="Reset analysis",
    description="""
    Reset analysis for a prediction.
    """,
    responses={
        200: {"description": "Analysis reset successfully"},
        404: {"description": "Prediction not found"},
        500: {"description": "Internal server error"}
    }
)
async def reset_analysis(request: Request, xray_id: str, db: Session = Depends(get_db)):
    try:
        xray = db.query(PatientXray).filter(PatientXray.id == xray_id).first()
        if not xray:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})
        
        prediction = db.query(Prediction).filter(Prediction.xray_id == xray.id).first()
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})
        
         # Validate image exists
        if not os.path.exists(str(xray.original_image)):
            return JSONResponse(status_code=400, content={"error": "X-ray image file not found"})
            
        # Run prediction model based on xray type
        try:
            rf = Roboflow(api_key=config("ROBOFLOW_API_KEY"))
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
                return JSONResponse(status_code=500, content={"error": "Prediction failed"})
                
            prediction_json = prediction_result.json()
            
            # Store prediction data with sequential class_ids
            prediction_str = json.dumps(prediction_json)
            
        except Exception as e:
            print("Exception error: ", str(e))
            return JSONResponse(status_code=500, content={"error": f"Model prediction failed: {str(e)}"})

        # Generate annotated image
        try:
            image = cv2.imread(str(xray.original_image))
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            # Extract labels and create detections
            labels = [item["class"] for item in prediction_json["predictions"]]
            
            # Get colors for each label
            _, hex_codes = colormap(labels)
            
            # Create output image
            annotated_image = image.copy()
            
            # Store label positions to check for overlaps
            label_boxes = []
            
            # Helper function to check if two boxes overlap
            def check_overlap(box1, box2):
                return not (box1['x2'] < box2['x1'] or 
                          box1['x1'] > box2['x2'] or 
                          box1['y2'] < box2['y1'] or 
                          box1['y1'] > box2['y2'])
            
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
                    
                    # Apply colored mask without border
                    overlay = annotated_image.copy()
                    overlay[mask == 1] = bgr_color
                    alpha = 0.4  # Reduced opacity for better visibility
                    annotated_image = cv2.addWeighted(overlay, alpha, annotated_image, 1 - alpha, 0)
                
                # Add improved label text
                x = int(pred["x"] - pred["width"]/2)
                y = int(pred["y"] - pred["height"]/2)
                confidence = pred.get("confidence", 1.0)
                label_text = f"{label}"
                
                # Get text size for background
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.7
                thickness = 2
                (text_width, text_height), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
                
                # Calculate label box coordinates
                padding = 5
                label_box = {
                    'x1': x - padding,
                    'y1': y - text_height - 2*padding,
                    'x2': x + text_width + padding,
                    'y2': y + padding
                }
                
                # Check for overlaps and adjust position if needed
                overlap_count = 0
                while any(check_overlap(label_box, existing_box) for existing_box in label_boxes):
                    # Alternate between moving up and right to avoid clustering
                    if overlap_count % 2 == 0:
                        # Move up
                        y -= (text_height + 2*padding + 5)
                        label_box['y1'] = y - text_height - 2*padding
                        label_box['y2'] = y + padding
                    else:
                        # Move right
                        x += (text_width + 2*padding + 5)
                        label_box['x1'] = x - padding
                        label_box['x2'] = x + text_width + padding
                    
                    overlap_count += 1
                    
                    # Prevent infinite loop by limiting iterations
                    if overlap_count > 10:
                        break
                
                # Add the final position to label_boxes
                label_boxes.append(label_box)
                
                # Draw text background with rounded corners
                bg_pts = np.array([
                    [label_box['x1'], label_box['y1']],
                    [label_box['x2'], label_box['y1']],
                    [label_box['x2'], label_box['y2']],
                    [label_box['x1'], label_box['y2']]
                ], dtype=np.int32)
                
                # Draw semi-transparent background
                overlay_bg = annotated_image.copy()
                cv2.fillPoly(overlay_bg, [bg_pts], (0, 0, 0))
                annotated_image = cv2.addWeighted(overlay_bg, 0.7, annotated_image, 0.3, 0)
                
                # Draw text with improved visibility
                cv2.putText(annotated_image, 
                          label_text,
                          (x, y),
                          font,
                          font_scale,
                          bgr_color,
                          thickness,
                          cv2.LINE_AA)

            # Apply subtle image enhancements
            annotated_image = cv2.convertScaleAbs(annotated_image, alpha=1.1, beta=5)  # Contrast and brightness
            
            # Convert to PIL and save
            annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
            if annotated_image_pil.mode == 'RGBA':
                annotated_image_pil = annotated_image_pil.convert('RGB')
                
            current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            random_number = random.randint(1000, 9999)
            random_filename = f"{current_datetime}-{random_number}.jpeg"

            output_dir = os.path.join("uploads", "analyzed")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, random_filename)
            
            # Save with high quality
            annotated_image_pil.save(output_path, 
                                   optimize=True, 
                                   quality=98,  # High quality
                                   subsampling=0)  # Better color accuracy
                                   
        except Exception as e:
            print("Exception error: ", str(e))
            return JSONResponse(status_code=500, content={"error": f"Image annotation failed: {str(e)}"})

        # Save prediction results
        try:
            class_percentages = calculate_class_percentage(prediction_json)
            
            # Delete existing labels and their references in deleted_labels
            existing_labels = db.query(Label).filter(Label.prediction_id == prediction.id).all()
            for label in existing_labels:
                # First delete references in deleted_labels
                db.query(DeletedLabel).filter(DeletedLabel.label_id == label.id).delete()
            # Then delete the labels
            db.query(Label).filter(Label.prediction_id == prediction.id).delete()
            db.commit()

            prediction.predicted_image = output_path
            prediction.is_annotated = True
            prediction.prediction = prediction_str
            db.commit()
            
            # Create and insert labels one by one
            created_labels = []
            for class_name, percentage in class_percentages.items():
                label = Label(
                    prediction_id=prediction.id,
                    name=class_name,
                    percentage=percentage,
                    include=True,
                    color_hex=hex_codes.get(class_name, '#FFFFFF')
                )
                db.add(label)
                db.commit()
                db.refresh(label)
                created_labels.append(label)

            # Update patient xray with annotated image
            xray.annotated_image = output_path
            xray.prediction_id = str(prediction.id)
            db.commit()

            base_url = str(request.base_url).rstrip('/')

            annotated_image = f"{base_url}/{output_path}"
            
            return JSONResponse(status_code=200, content={
                "message": "Prediction created successfully",
                "prediction_id": prediction.id,
                "labels": [{
                    "id": label.id,
                    "name": label.name,
                    "percentage": label.percentage,
                    "include": label.include,
                    "color_hex": label.color_hex
                } for label in created_labels],
                "annotated_image": annotated_image
            })
            
        except Exception as e:
            db.rollback()
            print("Exception error: ", str(e))
            return JSONResponse(status_code=500, content={"error": f"Database operation failed: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
