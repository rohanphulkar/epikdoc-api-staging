from fastapi import APIRouter, Depends, Request, BackgroundTasks, Body
from fastapi.responses import JSONResponse
from db.db import get_db
from .models import Prediction, Label, DeletedLabel
from sqlalchemy.orm import Session
from .schema import PredictionResponse, LabelResponse, LabelCreateAndUpdate
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
from decouple import config
from patients.model import PatientXray
from predict.routes import hex_to_bgr, colormap

# Initialize the API router
epikdoc_router = APIRouter()

def update_image_url(url: str, request: Request):
    base_url = str(request.base_url).rstrip('/')
    return f"{base_url}/{url}"

# Create a new prediction
@epikdoc_router.post("/create-prediction/",
    response_model=dict,
    status_code=200,
    summary="Create a new prediction for an uploaded X-ray image",
    description="""
    This endpoint allows a user to upload an X-ray image and receive a prediction based on the image content. The prediction process involves several steps, including image processing and model prediction.

    **Required Parameters:**
    - `is_opg`: A boolean indicating if the uploaded image is an OPG (Orthopantomogram) image.

    **Required Body:**
    - `image`: The X-ray image file to be uploaded. This file must be included in the form data.

    **Process:**
    1. Loads the uploaded X-ray image from the request.
    2. Runs the prediction model based on the image type (OPG or other).
    3. Generates an annotated image that highlights the predictions made by the model.
    4. Saves the prediction results, including the original image path, annotated image path, and prediction details, to the database.

    **Responses:**
    - `200`: `{"description": "Prediction created successfully"}` - Indicates that the prediction was successfully created and returned.
    - `400`: `{"description": "Invalid image or parameters"}` - Indicates that the request was malformed or missing required data.
    - `500`: `{"description": "Internal server error"}` - Indicates that an unexpected error occurred during processing.
    """
)
async def create_prediction(request: Request, is_opg: bool=False, db: Session = Depends(get_db)):
    try:        
        # Load the uploaded image from the request form
        form = await request.form()
        image_file = form.get("image")
        
        # Validate that an image file was provided
        if not image_file:
            return JSONResponse(status_code=400, content={"error": "Image file is required"})
        
        # Save the uploaded image temporarily to a specified directory
        image_path = os.path.join("uploads", "epikdoc", image_file.filename)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        with open(image_path, "wb") as f:
            f.write(await image_file.read())
        
        # Attempt to run the prediction model based on the uploaded image
        try:
            rf = Roboflow(api_key=config("ROBOFLOW_API_KEY"))
            workspace = rf.workspace()
            project_name = "opg-instance-segmentation-copy" if is_opg else "stage-1-launch"
            project = workspace.project(project_name)
            model = project.version(1).model
            prediction_result = model.predict(image_path, confidence=1)
                
            # Check if the prediction was successful
            if not prediction_result:
                return JSONResponse(status_code=500, content={"error": "Prediction failed"})
                
            # Convert the prediction result to JSON format for further processing
            prediction_json = prediction_result.json()
            prediction_str = json.dumps(prediction_json)
            
        except Exception as e:
            print("Exception error: ", str(e))
            return JSONResponse(status_code=500, content={"error": f"Model prediction failed: {str(e)}"})

        # Generate an annotated image based on the prediction results
        try:
            image = cv2.imread(image_path)
            if image is None:
                return JSONResponse(status_code=400, content={"error": "Failed to load image"})

            # Extract labels from the prediction results and create detections
            labels = [item["class"] for item in prediction_json["predictions"]]
            _, hex_codes = colormap(labels)
            annotated_image = image.copy()
            label_boxes = []

            # Helper function to check if two bounding boxes overlap
            def check_overlap(box1, box2):
                return not (box1['x2'] < box2['x1'] or 
                          box1['x1'] > box2['x2'] or 
                          box1['y2'] < box2['y1'] or 
                          box1['y1'] > box2['y2'])
            
            # Process each prediction to draw bounding boxes and labels
            for pred in prediction_json["predictions"]:
                label = pred["class"]
                hex_color = hex_codes[label]
                bgr_color = hex_to_bgr(hex_color)
                
                # If the prediction includes points, draw the polygon on the image
                if "points" in pred:
                    points = np.array([[int(p["x"]), int(p["y"])] for p in pred["points"]], dtype=np.int32)
                    mask = np.zeros(image.shape[:2], dtype=np.uint8)
                    cv2.fillPoly(mask, [points], (1, 1, 1))
                    overlay = annotated_image.copy()
                    overlay[mask == 1] = bgr_color
                    alpha = 0.4
                    annotated_image = cv2.addWeighted(overlay, alpha, annotated_image, 1 - alpha, 0)
                
                # Calculate the position for the label text
                x = int(pred["x"] - pred["width"]/2)
                y = int(pred["y"] - pred["height"]/2)
                label_text = f"{label}"
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
                
                # Adjust label position if it overlaps with existing labels
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
                bg_pts = np.array([
                    [label_box['x1'], label_box['y1']],
                    [label_box['x2'], label_box['y1']],
                    [label_box['x2'], label_box['y2']],
                    [label_box['x1'], label_box['y2']]
                ], dtype=np.int32)
                
                # Draw the background for the label text
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

            # Enhance the annotated image for better visibility
            annotated_image = cv2.convertScaleAbs(annotated_image, alpha=1.1, beta=5)
            annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))
            if annotated_image_pil.mode == 'RGBA':
                annotated_image_pil = annotated_image_pil.convert('RGB')
                
            # Generate a unique filename for the annotated image
            current_datetime = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            random_number = random.randint(1000, 9999)
            random_filename = f"{current_datetime}-{random_number}.jpeg"
            output_dir = os.path.join("uploads", "epikdoc", "analyzed")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, random_filename)
            annotated_image_pil.save(output_path, 
                                   optimize=True, 
                                   quality=98,  
                                   subsampling=0)  
                                   
        except Exception as e:
            print("Exception error: ", str(e))
            return JSONResponse(status_code=500, content={"error": f"Image annotation failed: {str(e)}"})

        # Save the prediction results to the database
        try:
            class_percentages = calculate_class_percentage(prediction_json)
            prediction = Prediction(
                original_image=image_path,
                predicted_image=output_path,
                is_annotated=True,
                prediction=prediction_str
            )
            db.add(prediction)
            db.commit()

            # Create label entries for each class detected in the prediction
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

            # Use update_image_url function to prepare the response data for the created prediction
            prediction_data = {
                "original_image": update_image_url(prediction.original_image, request),
                "is_annotated": prediction.is_annotated,
                "predicted_image": update_image_url(prediction.predicted_image, request),
                "notes": prediction.notes
            }

            # Prepare the legends for the response
            legends = [{
                "name": legend.name,
                "percentage": legend.percentage,
                "include": legend.include,
                "color_hex": legend.color_hex
            } for legend in labels]
            
            return JSONResponse(status_code=200, content={
                "message": "Prediction created successfully",
                "prediction": prediction_data,
                "legends": legends
            })
            
        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"error": f"Database operation failed: {str(e)}"})
            
    except Exception as e:
        print("Exception error: ", str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})

# get a prediction by id
@epikdoc_router.get("/get-prediction/{prediction_id}",
    response_model=dict,
    status_code=200,
    summary="Get prediction details", 
    description="""
    Retrieve detailed information about a specific prediction based on its unique identifier (UUID).
    
    This endpoint provides comprehensive data regarding the prediction, including the original and predicted images, 
    as well as the associated labels with their respective confidence scores.

    Required parameters:
    - **prediction_id**: UUID of the prediction (string) - The unique identifier for the prediction you wish to retrieve.

    Required headers:
    - **Authorization**: Bearer token from login (string) - A valid token that grants access to the prediction data.

    Returns:
    - **prediction**: Full prediction object containing details such as:
        - `original_image`: URL of the original image used for prediction.
        - `is_annotated`: Boolean indicating if the prediction has been annotated.
        - `predicted_image`: URL of the image generated after prediction.
        - `notes`: Any additional notes related to the prediction.
    - **previous_predictions**: List of previous predictions made for the same patient, excluding the current one.
    - **labels**: List of detected labels with their confidence scores, including:
        - `name`: The name of the detected label.
        - `percentage`: Confidence score of the label.
        - `include`: Boolean indicating if the label is included in the analysis.
        - `color_hex`: Hexadecimal color code associated with the label.
    """,
    responses={
        200: {"description": "Prediction details retrieved successfully"},
        404: {"description": "Prediction not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_prediction(request: Request, prediction_id: str, db: Session = Depends(get_db)):
    try:        
        prediction = db.query(Prediction).filter(Prediction.id == prediction_id).first()
        
        if not prediction:
            return JSONResponse(status_code=404, content={"error": "Prediction not found"})

        # Get base URL without trailing slash
        base_url = str(request.base_url).rstrip('/')
            
        # Create relative URLs for images
        original_image_url = update_image_url(prediction.original_image, request)
        predicted_image_url = update_image_url(prediction.predicted_image, request) if prediction.predicted_image else None

        # Create a copy of prediction to avoid modifying the DB object
        prediction_response = PredictionResponse.from_orm(prediction)
        prediction_response.original_image = original_image_url
        prediction_response.predicted_image = predicted_image_url

        # Fetch all previous predictions excluding the current one
        previous_predictions = db.query(Prediction).filter(
            Prediction.id != prediction_id
        ).order_by(Prediction.created_at.desc()).all()
        
        # Process previous predictions
        previous_predictions_response = []
        for prev in previous_predictions:
            prev_response = PredictionResponse.from_orm(prev)
            prev_response.original_image = update_image_url(prev.original_image, request)
            prev_response.predicted_image = update_image_url(prev.predicted_image, request) if prev.predicted_image else None
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
    

@epikdoc_router.get("/exclude-legend/{legend_id}",
    status_code=200,
    summary="Exclude a legend from predictions",
    description="""
    This endpoint allows users to exclude a specific legend identified by its unique ID. 
    When a legend is excluded, it will no longer be considered in the predictions associated 
    with it. This action is useful for managing legends that may have been incorrectly 
    included or are no longer relevant.

    **Path Parameters**:
    - `legend_id` (string): The unique identifier of the legend to be excluded.

    **Responses**:
    - **200**: Indicates that the legend has been successfully excluded from the predictions.
    - **404**: Indicates that the specified legend ID does not exist in the database.
    - **500**: Indicates an internal server error occurred during the processing of the request.
    """,
    responses={
        200: {"description": "Legend excluded successfully"},
        404: {"description": "Legend not found"},
        500: {"description": "Internal server error"}
    }
)
async def exclude_legend(request: Request, legend_id: str, db: Session = Depends(get_db)):
    try:
        label = db.query(Label).filter(Label.id == legend_id).first()
        
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

        new_annotated_image = update_image_url(prediction.predicted_image, request) if prediction.predicted_image else None
        
        return JSONResponse(status_code=200, content={
            "message": "Label marked as excluded successfully",
            "annotated_image": new_annotated_image
        })

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@epikdoc_router.get("/include-legend/{legend_id}",
    status_code=200, 
    summary="Include a previously excluded legend",
    description="""
    This endpoint allows users to include a previously excluded legend by its unique identifier (ID). 
    When a legend is included, it is marked as active and any associated data is restored. 
    The process involves checking for the existence of the legend and its related prediction, 
    as well as handling any necessary cleanup of old annotated images.

    **Path Parameters:**
    - `legend_id` (str): The unique identifier of the legend to be included.

    **Responses:**
    - **200 OK**: The legend was successfully included, and the system has updated its status.
    - **404 Not Found**: The specified legend or its associated prediction could not be found.
    - **500 Internal Server Error**: An error occurred while processing the request, which may include issues with database transactions or JSON parsing.
    """,
    responses={
        200: {"description": "Legend included successfully"},
        404: {"description": "Legend or prediction not found"},
        500: {"description": "An error occurred while processing the request"}
    }
)
async def include_legend(request: Request, legend_id: str, db: Session = Depends(get_db)):
    try:
        label = db.query(Label).filter(Label.id == legend_id).first()
        
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
        deleted_label = db.query(DeletedLabel).filter(DeletedLabel.label_id == legend_id).first()
        
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

        new_annotated_image = update_image_url(prediction.predicted_image, request) if prediction.predicted_image else None

        print("new_annotated_image", new_annotated_image)
        
        return JSONResponse(status_code=200, content={
            "message": "Label marked as included successfully",
            "annotated_image": new_annotated_image
        })

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})
# Incorrect detection
@epikdoc_router.patch("/update-legend/{legend_id}",
    status_code=200,
    summary="Update an incorrect detection",
    description="""
    Update an existing legend identified by the legend_id. 
    This endpoint allows users to modify legend attributes such as 
    name and color. Only fields that are provided in the request 
    will be updated, enabling partial updates. 
    Upon successful update, the endpoint returns the updated legend 
    object, which includes the new attributes.
    
    **Request Body**: 
    - `name` (string, optional): The new name for the legend.
    - `color_hex` (string, optional): The new color in hexadecimal format.

    **Responses**:
    - 200: Returns the updated legend object with the new attributes.
    - 404: Legend not found - The specified legend_id does not exist.
    - 500: Internal server error - An unexpected error occurred during processing.
    """,
    responses={
        200: {"description": "Legend updated successfully", "model": LabelResponse},
        404: {"description": "Legend not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_label(
    request: Request,
    legend_id: str,
    label: LabelCreateAndUpdate,
    db: Session = Depends(get_db)
):
    try:
        # Get existing label
        existing_label = db.query(Label).filter(Label.id == legend_id).first()
        
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

            output_dir = os.path.join("uploads", "epikdoc", "analyzed")
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

        new_annotated_image = update_image_url(prediction.predicted_image, request) if prediction.predicted_image else None

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
    
# Missing detection
@epikdoc_router.post("/add-missing-legend/{prediction_id}",
    status_code=201,
    summary="Create a new label for a prediction",
    description="""
    This endpoint allows doctors to create a new label for a specific prediction. 
    The label will be linked to the provided prediction ID and will include details 
    such as the label name, color, and default percentage. The label is created 
    based on the annotations provided in the request body. Upon successful creation, 
    the complete label object, including its ID, name, percentage, prediction ID, 
    inclusion status, creation and update timestamps, and the URL of the annotated 
    image, will be returned in the response.
    """,
    responses={
        201: {"description": "Label created successfully", "model": LabelResponse},
        404: {"description": "Prediction not found - The specified prediction ID does not exist"},
        500: {"description": "Internal server error - An unexpected error occurred while processing the request"}
    }
)
async def add_label(
    request: Request,
    prediction_id: str,
    annotations: List[dict] = Body(...),
    db: Session = Depends(get_db)
):
    try:
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

        new_annotated_image = update_image_url(prediction.predicted_image, request) if prediction.predicted_image else None

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
