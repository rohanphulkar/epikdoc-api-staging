from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from auth.routes import user_router
from patients.routes import patient_router
from payment.routes import payment_router
from predict.routes import prediction_router
from contact.routes import contact_router
from db.db import Base, engine
from typing import List
from feedback.routes import feedback_router
from admin.routes import admin_router
from support.routes import support_router
from epikdoc.routes import epikdoc_router
from appointment.route import appointment_router
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn")


app = FastAPI(
    title="Backupdoc API",
    description="API for Backupdoc AI - AI-powered medical diagnosis assistance",
    license_info={
        "name": "Backupdoc AI", 
        "url": "https://backupdoc.ai"
    },
    version="1.0.2",
    openapi_tags=[
        {
            "name": "user",
            "description": "User authentication, profile management and settings"
        },
        {
            "name": "patient", 
            "description": "Patient records, medical history and document management"
        },
        {
            "name": "predict",
            "description": "AI-powered medical diagnosis predictions and analysis"
        },
        {
            "name": "payment",
            "description": "Subscription plans, payments and billing management"
        },
        {
            "name": "contact",
            "description": "Support tickets and customer service inquiries"
        },
        {
            "name": "feedback",
            "description": "User feedback, reviews and suggestions"
        },
        {
            "name": "admin",
            "description": "Administrative controls and system management"
        },
        {
            "name": "support",
            "description": "Support tickets and customer service inquiries"
        },
        {
            "name": "epikdoc",
            "description": "Integration APIs for EpikDoc AI"
        },
        {
            "name": "appointment",
            "description": "Appointment management"
        }
    ],
    docs_url="/redoc",
    redoc_url="/docs",
    terms_of_service="https://www.backupdoc.ai/terms-and-conditions",
    contact={
        "name": "Backupdoc Support",
        "url": "https://backupdoc.ai/contact",
        "email": "support@backupdoc.ai"
    },
)

class CustomCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
    
@app.options("/{full_path:path}")
async def preflight(full_path: str):
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*"
    }
    return JSONResponse(content=None, headers=headers)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change this to specific origins if needed
    allow_credentials=False,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

Base.metadata.create_all(bind=engine)

app.mount("/uploads", StaticFiles(directory="uploads"), name="profile_pictures")

@app.get("/")
async def root():
    return RedirectResponse(url="/docs")

app.include_router(user_router, prefix="/user", tags=["user"])
app.include_router(patient_router, prefix="/patient", tags=["patient"])
app.include_router(prediction_router, prefix="/predict", tags=["predict"])
app.include_router(payment_router, tags=["payment"])
app.include_router(contact_router, tags=["contact"])
app.include_router(feedback_router, prefix="/feedback", tags=["feedback"])
app.include_router(support_router, prefix="/support", tags=["support"])
app.include_router(admin_router)
app.include_router(epikdoc_router, prefix="/epikdoc", tags=["epikdoc"])
app.include_router(appointment_router, prefix="/appointment", tags=["appointment"])

# Store active WebSocket connections
active_connections: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        print(f"User disconnected")

@app.get("/trigger-clear") 
async def trigger_clear():
    """
    Sends a clear signal to all connected WebSocket clients
    to clear their local storage and cookies.
    """
    # Broadcast clear message to all connected clients
    for connection in active_connections:
        try:
            await connection.send_json({"type": "clear_data"})
        except:
            # Remove dead connections
            active_connections.remove(connection)
    
    return {"status": "success", "message": "Clear signal sent to all clients"}