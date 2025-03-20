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
from catalog.routes import catalog_router
from suggestion.routes import suggestion_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("uvicorn")

# Initialize FastAPI app with metadata
app = FastAPI(
    title="Epikdoc API",
    description="""
    Epikdoc is a comprehensive healthcare management platform that leverages artificial intelligence to enhance medical workflows and patient care.
    
    Key Features:
    - Intelligent patient record management and scheduling
    - Advanced AI-powered medical image analysis and diagnostics
    - Comprehensive reporting and analytics dashboard
    - HIPAA-compliant secure data handling and storage
    - Automated patient notifications and reminders
    - Integrated billing and payment processing
    - Staff management and role-based access control
    - Real-time collaboration tools for healthcare teams
    
    The platform is designed to streamline healthcare operations while improving diagnostic accuracy and patient outcomes.
    For detailed API documentation, integration guides, and usage examples, please refer to our comprehensive documentation.
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "auth", "description": "Authentication, authorization and user management"},
        {"name": "patients", "description": "Patient records, history and document management"},
        {"name": "appointments", "description": "Appointment scheduling, reminders and calendar management"},
        {"name": "payments", "description": "Payment processing, invoicing and financial reporting"},
        {"name": "predictions", "description": "AI-powered medical image analysis and diagnostic predictions"},
        {"name": "catalog", "description": "Catalog of treatments, procedures and services"},
        {"name": "suggestion", "description": "Personalized recommendations based on user preferences"},
        {"name": "staff", "description": "Staff management, roles and access control"},
    ],
    terms_of_service="https://www.epikdoc.com/terms",
    license_info={
        "name": "Epikdoc Professional License",
        "url": "https://epikdoc.com/license"
    },
    contact={
        "name": "Epikdoc Technical Support",
        "url": "https://support.epikdoc.com",
        "email": "support@epikdoc.com"
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

app.include_router(user_router, prefix=f"/user", tags=["auth"])
app.include_router(patient_router, prefix=f"/patients", tags=["patients"])
app.include_router(prediction_router, prefix=f"/predictions", tags=["predictions"])
app.include_router(payment_router, prefix=f"/payments", tags=["payments"])
app.include_router(appointment_router, prefix=f"/appointments", tags=["appointments"])
app.include_router(staff_router, prefix=f"/staff", tags=["staff"])
app.include_router(catalog_router, prefix=f"/catalog", tags=["catalog"])
app.include_router(suggestion_router, prefix=f"/suggestion", tags=["suggestion"])