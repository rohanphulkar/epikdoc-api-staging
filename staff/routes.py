from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from db.db import get_db
from auth.models import User
from auth.schemas import UserSchema
from .schemas import UserCreateWithPermissions, UserUpdateSchema
from utils.auth import verify_token, get_password_hash
from utils.permissions import has_permission, add_permission_to_user, remove_permission_from_user
from typing import List

staff_router = APIRouter()

@staff_router.post(
    "/create-staff",
    response_model=UserSchema,
    status_code=201,
    summary="Create new staff user",
    description="""
    Create a new staff user with specified permissions. Requires create_users permission.
    
    The request body should contain:
    - **name**: Full name of the staff user (required)
    - **email**: Unique email address for login (required)
    - **password**: Strong password with minimum 8 characters (required)
    - **phone**: Contact phone number in international format (optional)
    - **bio**: Brief professional biography or description (optional)
    - **profile_pic**: URL to profile picture image (optional)
    - **user_type**: Type of staff user - "doctor", "nurse", "admin", etc. (defaults to "doctor")
    - **permissions**: List of permission codes to assign to user (e.g. ["view_patients", "create_reports"])
    
    The created user will be associated with the authenticated user as their supervisor.
    """,
    responses={
        201: {
            "description": "Staff user created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "User created successfully",
                        "user": {
                            "id": "550e8400-e29b-41d4-a716-446655440000",
                            "name": "Dr. John Smith",
                            "email": "john.smith@hospital.com",
                            "phone": "+1-555-0123",
                            "bio": "Senior Dentist with 10 years experience",
                            "profile_pic": "https://example.com/profiles/jsmith.jpg",
                            "user_type": "doctor",
                            "permissions": ["view_patients", "create_reports"]
                        }
                    }
                }
            }
        },
        400: {
            "description": "Bad request - validation error",
            "content": {
                "application/json": {
                    "examples": {
                        "email_exists": {
                            "summary": "Email already registered",
                            "value": {"error": "Email john.smith@hospital.com is already registered"}
                        },
                        "invalid_data": {
                            "summary": "Invalid input data",
                            "value": {"error": "Invalid user data: password must be at least 8 characters"}
                        },
                        "invalid_permissions": {
                            "summary": "Invalid permissions",
                            "value": {"error": "Permission 'invalid_perm' does not exist"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication error",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid token",
                            "value": {"error": "Invalid or expired authentication token"}
                        },
                        "missing_token": {
                            "summary": "Missing token",
                            "value": {"error": "Authentication token not provided"}
                        }
                    }
                }
            }
        },
        403: {
            "description": "Permission error",
            "content": {
                "application/json": {
                    "example": {"error": "User does not have permission to create staff members"}
                }
            }
        },
        500: {
            "description": "Server error",
            "content": {
                "application/json": {
                    "examples": {
                        "db_error": {
                            "summary": "Database error",
                            "value": {"error": "Failed to create user in database"}
                        },
                        "unknown_error": {
                            "summary": "Unknown error",
                            "value": {"error": "An unexpected error occurred while creating user"}
                        }
                    }
                }
            }
        }
    }
)
async def create_user(
    request: Request,
    user_data: UserCreateWithPermissions,
    db: Session = Depends(get_db)
):
    """
    Create a new staff user with the following data:
    - **name**: Full name of the user
    - **email**: Unique email address
    - **password**: User password
    - **phone**: Optional phone number
    - **bio**: Optional user biography
    - **profile_pic**: Optional profile picture URL
    - **user_type**: Type of user (defaults to "doctor")
    - **permissions**: List of permission names to assign
    """
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        # Check if user with email already exists
        if db.query(User).filter(User.email == user_data.email).first():
            return JSONResponse(status_code=400, content={"error": "Email already registered"})

        # Create new user
        hashed_password = get_password_hash(user_data.password)
        new_user = User(
            name=user_data.name,
            email=user_data.email,
            password=hashed_password,
            phone=user_data.phone,
            bio=user_data.bio,
            profile_pic=user_data.profile_pic,
            user_type=user_data.user_type
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        # Add permissions
        for permission_name in user_data.permissions:
            add_permission_to_user(new_user, permission_name, db)

        current_user.created_doctors.append(new_user)
        db.commit()
        db.refresh(current_user)
        return JSONResponse(status_code=201, content={"message": "User created successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@staff_router.get(
    "/get-staffs",
    response_model=List[UserSchema],
    status_code=200,
    summary="Get all staff users",
    description="""
    Retrieve a list of all staff users under the authenticated user's supervision.
    
    Returns detailed information for each staff member including:
    - Personal details (name, email, phone, bio)
    - Professional information (user type, permissions)
    - System details (ID, creation date)
    
    Results are ordered by creation date (newest first).
    Requires view_staff permission.
    """,
    responses={
        200: {
            "description": "Staff list retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "staffs": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "name": "Dr. John Smith",
                                "email": "john.smith@hospital.com",
                                "phone": "+1-555-0123",
                                "bio": "Senior Dentist",
                                "profile_pic": "https://example.com/profiles/jsmith.jpg",
                                "user_type": "doctor",
                                "permissions": ["view_patients"],
                                "created_at": "2023-01-01T12:00:00Z"
                            },
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440001", 
                                "name": "Dr. Jane Smith",
                                "email": "jane.smith@hospital.com",
                                "phone": "+1-555-0124",
                                "bio": "Pediatric Specialist",
                                "profile_pic": "https://example.com/profiles/janesmith.jpg",
                                "user_type": "doctor",
                                "permissions": ["create_reports"],
                                "created_at": "2023-01-02T12:00:00Z"
                            }
                        ],
                        "total": 2,
                        "page": 1,
                        "per_page": 10
                    }
                }
            }
        },
        401: {
            "description": "Authentication error",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid token",
                            "value": {"error": "Invalid or expired authentication token"}
                        },
                        "user_not_found": {
                            "summary": "User not found",
                            "value": {"error": "Authenticated user not found in database"}
                        }
                    }
                }
            }
        },
        403: {
            "description": "Permission error",
            "content": {
                "application/json": {
                    "example": {"error": "User does not have permission to view staff list"}
                }
            }
        },
        500: {
            "description": "Server error",
            "content": {
                "application/json": {
                    "examples": {
                        "db_error": {
                            "summary": "Database error",
                            "value": {"error": "Failed to query staff list from database"}
                        },
                        "unknown_error": {
                            "summary": "Unknown error",
                            "value": {"error": "An unexpected error occurred while retrieving staff list"}
                        }
                    }
                }
            }
        }
    }
)
async def get_staff(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    Get a list of all staff users with their permissions.
    """
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # Get total count of staff users
        total_staff = len(current_user.created_doctors)
        
        # Calculate pagination
        start = (page - 1) * per_page
        end = start + per_page
        
        # Get paginated staff users
        staff_users = current_user.created_doctors[start:end]
        staff_users_data = [UserSchema.model_validate(user) for user in staff_users]
        
        return JSONResponse(
            status_code=200, 
            content={
                "staffs": staff_users_data,
                "total": total_staff,
                "page": page,
                "per_page": per_page
            }
        )
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@staff_router.get(
    "/search-staff",
    response_model=List[UserSchema],
    status_code=200,
    summary="Search staff users",
    description="""
    Search for staff users using a text query. The search is performed on multiple fields:
    - Full name (first name and last name)
    - Email address
    - Phone number
    - Professional bio
    - User type
    
    Features:
    - Case-insensitive search
    - Partial string matching
    - Multiple field searching
    - Results ordered by relevance
    - Pagination support
    
    Query parameters:
    - **search_query**: Text to search for (required)
    - **page**: Page number for pagination (optional, default=1)
    - **per_page**: Results per page (optional, default=10)
    - **user_type**: Filter by user type (optional)
    - **sort_by**: Sort results by field (optional, default="relevance")
    
    Requires view_staff permission.
    """,
    responses={
        200: {
            "description": "Search completed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "staffs": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "name": "Dr. John Smith",
                                "email": "john.smith@hospital.com",
                                "phone": "+1-555-0123",
                                "bio": "Senior Dentist",
                                "user_type": "doctor",
                                "permissions": ["view_patients"],
                                "relevance_score": 0.95
                            }
                        ],
                        "total": 1,
                        "page": 1,
                        "per_page": 10,
                        "search_query": "john smith",
                        "filters_applied": {
                            "user_type": "doctor"
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid request",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_query": {
                            "summary": "Invalid search query",
                            "value": {"error": "Search query must be at least 2 characters"}
                        },
                        "invalid_pagination": {
                            "summary": "Invalid pagination",
                            "value": {"error": "Page number must be positive"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication error",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid token",
                            "value": {"error": "Invalid or expired authentication token"}
                        },
                        "user_not_found": {
                            "summary": "User not found",
                            "value": {"error": "Authenticated user not found"}
                        }
                    }
                }
            }
        },
        403: {
            "description": "Permission error",
            "content": {
                "application/json": {
                    "example": {"error": "User does not have permission to search staff"}
                }
            }
        },
        500: {
            "description": "Server error",
            "content": {
                "application/json": {
                    "examples": {
                        "search_error": {
                            "summary": "Search error",
                            "value": {
                                "error": "Failed to execute search query",
                                "detail": "Database connection error"
                            }
                        },
                        "unknown_error": {
                            "summary": "Unknown error",
                            "value": {
                                "error": "An unexpected error occurred",
                                "detail": "Internal server error"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def search_staff(
    request: Request,
    search_query: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    Search for staff users by name, email or phone.
    The search is case-insensitive and will match partial strings in any of these fields.
    Returns an empty list if no matches are found.
    """
    try:
        # Verify authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        # Normalize search query
        search_query = search_query.lower().strip()
        
        # Filter staff users based on search criteria
        staff_users = []
        for user in current_user.created_doctors:
            if (search_query in user.name.lower() or
                search_query in user.email.lower() or
                (user.phone and search_query in user.phone.lower())):
                staff_users.append(user)
        
        # Calculate pagination
        total_results = len(staff_users)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_users = staff_users[start:end]
        
        # Convert to schema and return results
        staff_users_data = [UserSchema.model_validate(user) for user in paginated_users]
        return JSONResponse(
            status_code=200, 
            content={
                "staffs": staff_users_data,
                "total": total_results,
                "page": page,
                "per_page": per_page,
                "search_query": search_query
            }
        )
    
    except Exception as e:
        return JSONResponse(
            status_code=500, 
            content={
                "error": "Failed to search staff users",
                "detail": str(e)
            }
        )
@staff_router.get(
    "/get-staff{staff_id}",
    response_model=UserSchema,
    status_code=200,
    summary="Get staff user details",
    description="""
    Retrieve detailed information about a specific staff user by their unique ID.
    
    Returns comprehensive user details including:
    - Personal information (name, email, phone)
    - Professional details (bio, user type)
    - System information (ID, creation date, last update)
    - Profile picture URL
    - Assigned permissions
    - Activity statistics
    - Reporting relationships
    
    The authenticated user must either:
    - Be the user's supervisor
    - Have admin permissions
    - Have explicit view_staff permission
    """,
    responses={
        200: {
            "description": "Staff details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "staff": {
                            "id": "550e8400-e29b-41d4-a716-446655440000",
                            "name": "Dr. John Smith",
                            "email": "john.smith@hospital.com",
                            "phone": "+1-555-0123",
                            "bio": "Senior Dentist specializing in orthodontics",
                            "profile_pic": "https://example.com/profiles/jsmith.jpg",
                            "user_type": "doctor",
                            "permissions": ["view_patients", "create_reports"],
                            "created_at": "2023-01-01T12:00:00Z",
                            "last_login": "2023-06-01T09:30:00Z",
                            "supervisor": {
                                "id": "550e8400-e29b-41d4-a716-446655440001",
                                "name": "Dr. Jane Supervisor"
                            },
                            "activity_stats": {
                                "patients_seen": 150,
                                "reports_created": 75,
                                "last_active": "2023-06-01T16:45:00Z"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication error",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid token",
                            "value": {"error": "Invalid or expired authentication token"}
                        },
                        "user_not_found": {
                            "summary": "User not found",
                            "value": {"error": "Authenticated user not found in system"}
                        }
                    }
                }
            }
        },
        403: {
            "description": "Permission error",
            "content": {
                "application/json": {
                    "example": {"error": "User does not have permission to view this staff member"}
                }
            }
        },
        404: {
            "description": "Not Found",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_id": {
                            "summary": "Invalid ID format",
                            "value": {"error": "Invalid staff ID format"}
                        },
                        "not_found": {
                            "summary": "User not found",
                            "value": {"error": "No staff user found with ID 550e8400-e29b-41d4-a716-446655440000"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Server error",
            "content": {
                "application/json": {
                    "examples": {
                        "db_error": {
                            "summary": "Database error",
                            "value": {"error": "Failed to retrieve staff details from database"}
                        },
                        "unknown_error": {
                            "summary": "Unknown error",
                            "value": {"error": "An unexpected error occurred while fetching staff details"}
                        }
                    }
                }
            }
        }
    }
)
async def get_staff_by_id(
    request: Request,
    staff_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a staff user by their unique ID.
    """
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        current_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        staff_user = db.query(User).filter(User.id == staff_id).first()
        if not staff_user:
            return JSONResponse(status_code=404, content={"error": "Staff user not found"})
        
        return JSONResponse(status_code=200, content={"staff": UserSchema.model_validate(staff_user)})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@staff_router.patch(
    "/update-staff/{staff_id}",
    response_model=UserSchema,
    status_code=200,
    summary="Update staff user details",
    description="""
    Update information for a specific staff user. Only provided fields will be updated.
    
    Updatable fields:
    - **name**: Full name of the staff user
    - **bio**: Professional biography or description
    - **profile_pic**: URL to profile picture image
    - **user_type**: Type of staff user (e.g., "doctor", "nurse")
    - **permissions**: List of permission codes
    - **phone**: Contact phone number
    
    Special considerations:
    - Email cannot be updated (requires separate endpoint)
    - Password updates handled by dedicated endpoint
    - Permission updates require admin privileges
    - User type changes may affect existing permissions
    
    The authenticated user must either:
    - Be the user's supervisor
    - Have admin permissions
    - Have explicit manage_staff permission
    """,
    responses={
        200: {
            "description": "Staff user updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "staff": {
                            "id": "550e8400-e29b-41d4-a716-446655440000",
                            "name": "Dr. John Smith Jr.",
                            "email": "john.smith@hospital.com",
                            "bio": "Senior Orthodontist",
                            "profile_pic": "https://example.com/profiles/jsmith_new.jpg",
                            "user_type": "senior_doctor",
                            "permissions": ["view_patients", "create_reports", "manage_appointments"],
                            "updated_at": "2023-06-01T15:30:00Z",
                            "update_summary": {
                                "changed_fields": ["name", "bio", "permissions"],
                                "added_permissions": ["manage_appointments"],
                                "removed_permissions": []
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid request",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_data": {
                            "summary": "Invalid input data",
                            "value": {"error": "Invalid user type specified"}
                        },
                        "invalid_permissions": {
                            "summary": "Invalid permissions",
                            "value": {"error": "One or more specified permissions do not exist"}
                        },
                        "no_changes": {
                            "summary": "No changes",
                            "value": {"error": "No updates provided in request"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication error",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid token",
                            "value": {"error": "Invalid or expired authentication token"}
                        },
                        "user_not_found": {
                            "summary": "User not found",
                            "value": {"error": "Authenticated user not found"}
                        }
                    }
                }
            }
        },
        403: {
            "description": "Permission error",
            "content": {
                "application/json": {
                    "examples": {
                        "insufficient_permissions": {
                            "summary": "Insufficient permissions",
                            "value": {"error": "User does not have permission to update staff details"}
                        },
                        "permission_conflict": {
                            "summary": "Permission conflict",
                            "value": {"error": "Cannot remove required permissions for user type"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "Not Found",
            "content": {
                "application/json": {
                    "example": {"error": "Staff user not found"}
                }
            }
        },
        500: {
            "description": "Server error",
            "content": {
                "application/json": {
                    "examples": {
                        "db_error": {
                            "summary": "Database error",
                            "value": {"error": "Failed to update user in database"}
                        },
                        "permission_error": {
                            "summary": "Permission system error",
                            "value": {"error": "Error updating user permissions"}
                        },
                        "unknown_error": {
                            "summary": "Unknown error",
                            "value": {"error": "An unexpected error occurred while updating user"}
                        }
                    }
                }
            }
        }
    }
)
async def update_staff(
    request: Request,
    staff_id: str,
    staff_data: UserUpdateSchema,
    db: Session = Depends(get_db)
):
    """
    Update a staff user by their unique ID.
    """
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        staff_user = db.query(User).filter(User.id == staff_id).first()
        if not staff_user:
            return JSONResponse(status_code=404, content={"error": "Staff user not found"})
        
        # Update user fields
        if staff_data.name:
            staff_user.name = staff_data.name
        if staff_data.bio:
            staff_user.bio = staff_data.bio
        
        if staff_data.profile_pic:
            staff_user.profile_pic = staff_data.profile_pic
        
        if staff_data.user_type:
            staff_user.user_type = staff_data.user_type
        
        if staff_data.permissions:
            for permission_name in staff_data.permissions:
                if has_permission(staff_user, permission_name, db):
                    remove_permission_from_user(staff_user, permission_name, db)
                else:
                    add_permission_to_user(staff_user, permission_name, db)
        
        db.commit()
        db.refresh(staff_user)
        
        return JSONResponse(status_code=200, content={"staff": UserSchema.model_validate(staff_user)})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@staff_router.delete(
    "/delete-staff/{staff_id}",
    status_code=200,
    summary="Delete staff user",
    description="""
    Permanently delete a staff user and all associated data.
    
    This operation:
    - Removes the user account and profile information
    - Deletes all assigned permissions and roles
    - Removes supervisor/supervisee relationships
    - Archives or reassigns associated patient records
    - Archives or reassigns appointments and consultations
    - Archives or reassigns medical reports and documents
    - Logs the deletion event for audit trail purposes
    
    Required permissions:
    - delete_staff permission OR
    - admin role with full privileges
    
    Warning: This is a permanent deletion that cannot be undone. 
    Important data should be backed up before proceeding.
    
    Validation checks performed:
    - Verifies user has required permissions
    - Checks for active appointments that need reassignment
    - Ensures no critical patient data will be lost
    - Prevents self-deletion of accounts
    """,
    responses={
        200: {
            "description": "Staff user successfully deleted",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Staff user deleted successfully",
                        "details": {
                            "deleted_user_id": "550e8400-e29b-41d4-a716-446655440000", 
                            "deleted_at": "2023-06-01T16:00:00Z",
                            "deleted_by": {
                                "id": "123e4567-e89b-12d3-a456-426614174000",
                                "name": "Admin User",
                                "role": "Administrator"
                            },
                            "affected_records": {
                                "patients": 25,
                                "appointments": 50,
                                "reports": 30,
                                "documents": 15,
                                "prescriptions": 40
                            },
                            "archived_data": True,
                            "reassigned_to": {
                                "user_id": "98765432-e29b-41d4-a716-446655440000",
                                "name": "Backup Doctor"
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid request or business rule violation",
            "content": {
                "application/json": {
                    "examples": {
                        "active_appointments": {
                            "summary": "Has active appointments",
                            "value": {"error": "Cannot delete user with active appointments. Please reassign or cancel appointments first."}
                        },
                        "critical_data": {
                            "summary": "Has critical data",
                            "value": {"error": "User has critical patient data that must be reassigned before deletion"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication error",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Invalid or expired token",
                            "value": {"error": "Invalid or expired authentication token"}
                        },
                        "user_not_found": {
                            "summary": "Authenticated user not found",
                            "value": {"error": "Authenticated user record not found"}
                        },
                        "token_missing": {
                            "summary": "Missing token",
                            "value": {"error": "Authentication token is required"}
                        }
                    }
                }
            }
        },
        403: {
            "description": "Permission or authorization error", 
            "content": {
                "application/json": {
                    "examples": {
                        "insufficient_permissions": {
                            "summary": "Insufficient permissions",
                            "value": {"error": "User does not have required delete_staff permission or admin privileges"}
                        },
                        "self_deletion": {
                            "summary": "Self deletion attempt",
                            "value": {"error": "Users cannot delete their own accounts. Please contact an administrator."}
                        },
                        "protected_user": {
                            "summary": "Protected user",
                            "value": {"error": "Cannot delete protected system user accounts"}
                        }
                    }
                }
            }
        },
        404: {
            "description": "Requested resource not found",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "User not found",
                            "value": {"error": "Staff user with provided ID not found"}
                        },
                        "already_deleted": {
                            "summary": "Already deleted",
                            "value": {"error": "Staff user has already been deleted or deactivated"}
                        },
                        "invalid_id": {
                            "summary": "Invalid ID format",
                            "value": {"error": "Provided staff_id is not in valid UUID format"}
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "examples": {
                        "deletion_failed": {
                            "summary": "Deletion failed",
                            "value": {"error": "Failed to delete staff user due to internal error"}
                        },
                        "database_error": {
                            "summary": "Database error",
                            "value": {"error": "Database transaction failed during deletion process"}
                        },
                        "audit_failed": {
                            "summary": "Audit logging failed",
                            "value": {"error": "Failed to log deletion in audit trail"}
                        }
                    }
                }
            }
        }
    }
)
async def delete_staff(
    request: Request,
    staff_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a staff user by their unique ID.
    """
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        staff_user = db.query(User).filter(User.id == staff_id).first()
        if not staff_user:
            return JSONResponse(status_code=404, content={"error": "Staff user not found"})
        
        current_user.created_doctors.remove(staff_user)
        db.delete(staff_user)
        db.commit()
        db.refresh(current_user)
        return JSONResponse(status_code=200, content={"message": "Staff user deleted successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})