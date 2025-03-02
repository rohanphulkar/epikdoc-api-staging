from fastapi import APIRouter, Depends, Request
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
    - **name**: Full name of the user
    - **email**: Unique email address
    - **password**: User password
    - **phone**: Optional phone number
    - **bio**: Optional user biography
    - **profile_pic**: Optional profile picture URL
    - **user_type**: Type of user (defaults to "doctor")
    - **permissions**: List of permission names to assign
    """,
    responses={
        201: {
            "description": "User created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "User created successfully",
                        "user": {
                            "id": "uuid",
                            "name": "John Doe",
                            "email": "john@example.com",
                            "permissions": ["view_patients", "create_reports"]
                        }
                    }
                }
            }
        },
        400: {
            "description": "Bad request",
            "content": {
                "application/json": {
                    "examples": {
                        "email_exists": {
                            "value": {"error": "Email already registered"}
                        },
                        "invalid_data": {
                            "value": {"error": "Invalid user data provided"}
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid or expired token"}
                }
            }
        },
        403: {
            "description": "Forbidden",
            "content": {
                "application/json": {
                    "example": {"error": "Insufficient permissions to create staff"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "An unexpected error occurred"}
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

        return JSONResponse(status_code=201, content={"message": "User created successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@staff_router.get(
    "/get-staffs",
    response_model=List[UserSchema],
    status_code=200,
    summary="Get all staff users",
    description="Retrieve a list of all staff users with their associated permissions and details",
    responses={
        200: {
            "description": "List of staff users retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "staffs": [
                            {
                                "id": "uuid1",
                                "name": "John Doe",
                                "email": "john@example.com",
                                "permissions": ["view_patients"]
                            },
                            {
                                "id": "uuid2", 
                                "name": "Jane Smith",
                                "email": "jane@example.com",
                                "permissions": ["create_reports"]
                            }
                        ]
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid or expired token"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Failed to retrieve staff list"}
                }
            }
        }
    }
)
async def get_staff(
    request: Request,
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

        
        staff_users = current_user.created_doctors
        staff_users_data = [UserSchema.model_validate(user) for user in staff_users]
        return JSONResponse(status_code=200, content={"staffs": staff_users_data})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@staff_router.get(
    "/search-staff",
    response_model=List[UserSchema],
    status_code=200,
    summary="Search staff users",
    description="""
    Search for staff users using a search query. The search is performed on:
    - Name
    - Email
    - Phone number
    
    The search is case-insensitive and matches partial strings.
    """,
    responses={
        200: {
            "description": "Search results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "staffs": [
                            {
                                "id": "uuid1",
                                "name": "John Doe",
                                "email": "john@example.com"
                            }
                        ],
                        "total": 1,
                        "search_query": "john"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid or expired token"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Failed to search staff users",
                        "detail": "Error message"
                    }
                }
            }
        }
    }
)
async def search_staff(
    request: Request,
    search_query: str,
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
        
        # Convert to schema and return results
        staff_users_data = [UserSchema.model_validate(user) for user in staff_users]
        return JSONResponse(
            status_code=200, 
            content={
                "staffs": staff_users_data,
                "total": len(staff_users_data),
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
    description="Retrieve detailed information about a specific staff user by their ID",
    responses={
        200: {
            "description": "Staff user details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "staff": {
                            "id": "uuid",
                            "name": "John Doe",
                            "email": "john@example.com",
                            "phone": "+1234567890",
                            "bio": "Senior Dentist",
                            "permissions": ["view_patients", "create_reports"]
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid or expired token"}
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
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Failed to retrieve staff details"}
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
    Update information for a specific staff user. Fields that can be updated:
    - Name
    - Bio
    - Profile picture
    - User type
    - Permissions
    
    Only provided fields will be updated.
    """,
    responses={
        200: {
            "description": "Staff user updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "staff": {
                            "id": "uuid",
                            "name": "Updated Name",
                            "email": "john@example.com",
                            "bio": "Updated bio",
                            "permissions": ["new_permission"]
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid or expired token"}
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
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Failed to update staff user"}
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
    description="Permanently delete a staff user and all associated data",
    responses={
        200: {
            "description": "Staff user deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Staff user deleted successfully"}
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"error": "Invalid or expired token"}
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
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"error": "Failed to delete staff user"}
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
        
        db.delete(staff_user)
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Staff user deleted successfully"})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})