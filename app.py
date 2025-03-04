# Import required packages and modules
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import os

# Import local modules
from db.db import Base, engine

# import routers
from auth.routes import user_router
from patient.routes import patient_router
from prediction.routes import prediction_router
from payment.routes import payment_router
from appointment.routes import appointment_router
from staff.routes import staff_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("uvicorn")

# Initialize FastAPI app with metadata
app = FastAPI(
    title="EpikdocAI API",
    description="""
    EpikdocAI is an advanced medical CRM powered by artificial intelligence.
    
    Key Features:
    - Patient management and scheduling
    - AI-powered medical image analysis 
    - Automated reporting and analytics
    - Secure data handling and storage
    - Real-time notifications
    
    For detailed API documentation and usage examples, please visit our documentation.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "auth", "description": "Authentication and user management"},
        {"name": "patients", "description": "Patient records and management"},
        {"name": "appointments", "description": "Appointment scheduling and management"},
        {"name": "payments", "description": "Payment processing and invoicing"},
        {"name": "predictions", "description": "AI-powered analysis and predictions"},
        {"name": "staff", "description": "Staff management and permissions"}
    ],
    terms_of_service="https://www.epikdoc.com/terms-and-conditions",
    license_info={
        "name": "EpikdocAI Enterprise License",
        "url": "https://epikdoc.com/license"
    },
    contact={
        "name": "EpikdocAI Support Team",
        "url": "https://epikdoc.com/support",
        "email": "support@backupdoc.ai"
    }
)

# Custom CORS middleware class
class CustomCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

# Handle preflight OPTIONS requests    
@app.options("/{full_path:path}")
async def preflight(full_path: str):
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }
    return JSONResponse(content=None, headers=headers)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure specific origins in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create database tables
Base.metadata.create_all(bind=engine)

# Ensure uploads directory exists
os.makedirs("uploads", exist_ok=True)

# Mount static files directory
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Root endpoint redirects to docs
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")

# Include routers with versioning
api_prefix = "/api/v1"
app.include_router(user_router, prefix=f"{api_prefix}/users", tags=["auth"])
app.include_router(patient_router, prefix=f"{api_prefix}/patients", tags=["patients"])
app.include_router(prediction_router, prefix=f"{api_prefix}/predictions", tags=["predictions"])
app.include_router(payment_router, prefix=f"{api_prefix}/payments", tags=["payments"])
app.include_router(appointment_router, prefix=f"{api_prefix}/appointments", tags=["appointments"])
app.include_router(staff_router, prefix=f"{api_prefix}/staff", tags=["staff"])
