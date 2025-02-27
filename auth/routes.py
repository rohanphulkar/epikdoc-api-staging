from fastapi import APIRouter, HTTPException, Depends, Request, File, UploadFile
from db.db import get_db
from sqlalchemy.orm import Session
from .model import User
from .schema import *
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from utils.auth import (
    validate_email, validate_phone, validate_password, signJWT, decodeJWT,
    verify_password, get_password_hash, generate_reset_token, verify_token, get_current_user, generate_otp
)
from utils.email import send_forgot_password_email
from utils.send_otp import send_otp_via_phone
from gauthuserinfo import get_user_info
from sqlalchemy import select

user_router = APIRouter()

@user_router.post("/register", 
    response_model=dict,
    status_code=201,
    summary="Register a new user",
    description="""
    Create a new user account with email, password, name and phone number
    
    Required fields:
    - email: Valid email address
    - password: Password meeting complexity requirements
    - name: User's full name
    - phone: Valid phone number
    """,
    responses={
        201: {"description": "User created successfully"},
        400: {"description": "Bad request - Invalid input"},
        500: {"description": "Internal server error"}
    }
)
async def register(user: UserCreateSchema, db: Session = Depends(get_db)):
    try:
        print(user)
        if not user.email or not user.password or not user.name or not user.phone:
            print("Error on all fields part")
            return JSONResponse(status_code=400, content={"error": "All fields are required"})

        if not validate_email(user.email):
            print("Error on email validation part")
            return JSONResponse(status_code=400, content={"error": "Invalid email format"})
        if not validate_phone(user.phone):
            print("Error on phone validation part")
            return JSONResponse(status_code=400, content={"error": "Invalid phone number"})
        if not validate_password(user.password):
            print("Error on password validation part")
            return JSONResponse(status_code=400, content={"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"})
        
        # Check if user exists with same email
        email_exists = db.query(User).filter(User.email == user.email).first()
        if email_exists:
            print("Error on email exists part")
            return JSONResponse(status_code=400, content={"error": "User already exists with this email"})

        # Check if user exists with same phone
        phone_exists = db.query(User).filter(User.phone == user.phone).first()
        if phone_exists:
            print("Error on phone exists part")
            return JSONResponse(status_code=400, content={"error": "User already exists with this phone number"})
        
        hashed_password = get_password_hash(user.password)
        new_user = User(email=user.email, password=hashed_password, name=user.name, phone=user.phone, user_type=user.user_type, is_active=True)
        if user.user_type == "admin":
            setattr(new_user, 'is_superuser', True)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        jwt_token = signJWT(str(new_user.id))
        return JSONResponse(status_code=201, content={"access_token": jwt_token["access_token"],"message": "User created successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@user_router.post("/login", response_model=dict, status_code=200, summary="Login user")
async def login(user: UserSchema, db: Session = Depends(get_db)):
    try:
        if not user.email or not user.password:
            return JSONResponse(status_code=400, content={"error": "Email and password are required"})
         
        db_user = db.query(User).filter(User.email == user.email).first()

        if not db_user:
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
        
        if not db_user.is_active:
            return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})
    
        if not db_user or not verify_password(user.password, str(db_user.password)):
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
        
        jwt_token = signJWT(str(db_user.id))
        return JSONResponse(status_code=200, content={"access_token": jwt_token["access_token"], "token_type": "bearer", "message": "Login successful"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.get("/profile", 
    response_model=UserResponse,
    status_code=200,
    summary="Get user profile",
    description="""
    Get authenticated user's profile details
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "User profile retrieved successfully"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_user(request: Request, db: Session = Depends(get_db)):   
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        user_data = {
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "bio": user.bio,
            "credits": user.credits,
            "account_type": user.account_type,
            "billing_frequency": user.billing_frequency,
            "tfa_enabled": user.tfa_enabled,
            "data_sharing": user.data_sharing,
            "plan_end_date": (user.credit_expiry + timedelta(days=1)).strftime("%Y-%m-%d") if user.credit_expiry else None,
            "has_subscription": user.has_subscription,
            "total_credits": user.total_credits,
            "used_credits": user.used_credits,
            
        }

        if user.account_type == "pro" or user.account_type == "max":
            user_data['can_use_opg'] = True
        else:
            user_data['can_use_opg'] = False

        if user.profile_url:
            profile_url = f"{request.base_url}{user.profile_url}"
        else:
            profile_url = None
        
        return JSONResponse(status_code=200, content={"user": user_data, "profile": profile_url})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/forgot-password",
    response_model=dict,
    status_code=200,
    summary="Forgot password",
    description="""
    Send password reset email to user
    
    Required fields:
    - email: Registered email address
    """,
    responses={
        200: {"description": "Password reset email sent"},
        400: {"description": "Invalid email"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def forgot_password(user: ForgotPasswordSchema, request: Request, db: Session = Depends(get_db)):
    try:
        if not user.email:
            return JSONResponse(status_code=400, content={"error": "Email is required"})
        if not validate_email(user.email):
            return JSONResponse(status_code=400, content={"error": "Invalid email"})
            
        db_user = db.query(User).filter(User.email == user.email).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
            
        reset_token = generate_reset_token()
        reset_link = f"{request.headers.get('origin') or request.base_url}/reset-password?token={reset_token}"
        
        setattr(db_user, 'reset_token', reset_token)
        setattr(db_user, 'reset_token_expiry', datetime.now() + timedelta(hours=3))
        
        db.commit()
        db.refresh(db_user)
        
        if send_forgot_password_email(user.email, reset_link):
            return JSONResponse(status_code=200, content={"message": "Password reset email sent"})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to send email"})
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.post("/reset-password",
    response_model=dict,
    status_code=200,
    summary="Reset password",
    description="""
    Reset user password using reset token
    
    Required parameters:
    - token: Reset token from email link
    
    Required fields:
    - password: New password
    - confirm_password: Confirm new password
    """,
    responses={
        200: {"description": "Password reset successfully"},
        400: {"description": "Invalid input or expired token"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def reset_password(token: str, user: ResetPasswordSchema, db: Session = Depends(get_db)):
    try:
        db_user = db.query(User).filter(User.reset_token == token).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
            
        expiry = getattr(db_user, 'reset_token_expiry', None)
        if expiry and expiry < datetime.now():
            return JSONResponse(status_code=400, content={"error": "Reset token expired"})
        
        if not user.password or not user.confirm_password:
            return JSONResponse(status_code=400, content={"error": "Password and confirm password are required"})
        
        if not validate_password(user.password):
            return JSONResponse(status_code=400, content={"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"})

        if user.password != user.confirm_password:
            return JSONResponse(status_code=400, content={"error": "Passwords do not match"})
            
        hashed_password = get_password_hash(user.password)
        setattr(db_user, 'password', hashed_password)
        setattr(db_user, 'reset_token', None)
        setattr(db_user, 'reset_token_expiry', None)

        db.commit()
        db.refresh(db_user)
        return JSONResponse(status_code=200, content={"message": "Password reset successfully"})

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})


@user_router.post("/change-password",
    response_model=dict,
    status_code=200,
    summary="Change password",
    description="""
    Change authenticated user's password
    
    Required headers:
    - Authorization: Bearer token from login
    
    Required fields:
    - old_password: Current password
    - new_password: New password
    - confirm_new_password: Confirm new password
    """,
    responses={
        200: {"description": "Password changed successfully"},
        400: {"description": "Invalid input"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def change_password(user: ChangePasswordSchema, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        
        db_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if user.old_password:
            if not verify_password(user.old_password, str(db_user.password)):
                return JSONResponse(status_code=400, content={"error": "Incorrect old password"})
            
        if not validate_password(user.new_password):
            return JSONResponse(status_code=400, content={"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"})
            
        if user.new_password != user.confirm_new_password:
            return JSONResponse(status_code=400, content={"error": "New passwords do not match"})
        
        setattr(db_user, 'password', get_password_hash(user.new_password))
        db.commit()
        db.refresh(db_user)
        return JSONResponse(status_code=200, content={"message": "Password changed successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@user_router.patch("/update-profile",
    response_model=dict,
    status_code=200,
    summary="Update profile",
    description="""
    Update authenticated user's profile details
    
    Required headers:
    - Authorization: Bearer token from login
    
    Optional fields:
    - name: New name
    - phone: New phone number
    """,
    responses={
        200: {"description": "Profile updated successfully"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_profile(user: UserProfileUpdateSchema, request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        
        db_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if user.name:
            setattr(db_user, 'name', user.name)
        if user.phone:
            setattr(db_user, 'phone', user.phone)
        if user.bio:
            setattr(db_user, 'bio', user.bio)
            
        db.commit()
        db.refresh(db_user)
        return JSONResponse(status_code=200, content={"message": "Profile updated successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    

@user_router.delete("/delete-profile",
    response_model=dict,
    status_code=200,
    summary="Delete profile",
    description="""
    Delete authenticated user's profile
    
    Required headers:
    - Authorization: Bearer token from login
    """,
    responses={
        200: {"description": "Profile deleted successfully"},
        404: {"description": "User not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_profile(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        
        db_user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not db_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
            
        db.delete(db_user)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Profile deleted successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@user_router.get("/get-all-users",
    response_model=list[UserResponse],
    status_code=200,
    summary="Get all users",
    description="Get list of all users",
    responses={
        200: {"description": "List of users retrieved successfully"},
        500: {"description": "Internal server error"}
    }
)
async def get_all_users(db: Session = Depends(get_db)):
    try:
        users = db.query(User).all()
        return JSONResponse(status_code=200, content={"users": users})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.get("/doctor-list",
    response_model=list[UserResponse],
    status_code=200,
    summary="Get doctor list",
    description="Get list of all doctors",
    responses={
        200: {"description": "List of doctors retrieved successfully"},
        500: {"description": "Internal server error"}
    }
)
async def doctor_list(db: Session = Depends(get_db)):
    try:
        doctors = db.query(User).filter(User.user_type == "doctor").all()
        return JSONResponse(status_code=200, content={"doctors": doctors})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@user_router.post("/google-login",
    response_model=dict,
    status_code=200,
    summary="Google login",
    description="""
    Login or register user with Google OAuth token
    
    Required fields:
    - token: Google OAuth token
    """,
    responses={
        200: {"description": "Google login successful"},
        500: {"description": "Internal server error"}
    }
)
async def google_login(user: GoogleLoginSchema, db: Session = Depends(get_db)):
    try:
        user_info = get_user_info(user.token)
        email = user_info["data"]['email']
        name = user_info["data"]['name']
        user_exists = db.query(User).filter(User.email == email).first()
        if not user_exists:
            new_user = User(email=email, name=name, password=None, user_type="doctor")
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            db_user = new_user
        else:
            db_user = user_exists
            
        if not db_user.is_active:
            return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})
            
        jwt_token = signJWT(str(db_user.id))
        return JSONResponse(status_code=200, content={"access_token": jwt_token["access_token"], "token_type": "bearer", "message": "Google login successful"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@user_router.post("/upload-profile-picture",
    response_model=dict,
    status_code=200,
    summary="Upload profile picture",
    description="Upload profile picture for authenticated user",
    responses={
        200: {"description": "Profile picture uploaded successfully"},
        500: {"description": "Internal server error"}
    }
)
async def upload_profile_picture(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Read file contents
        file_contents = await file.read()
        
        # Save file to disk/storage
        file_name = f"profile_{user.id}_{file.filename}"
        file_path = f"uploads/profile_pictures/{file_name}"
        
        with open(file_path, "wb") as f:
            f.write(file_contents)
            
        # Update user profile URL in database
        setattr(user, 'profile_url', str(file_path))
        db.commit()
        db.refresh(user)
        
        return JSONResponse(status_code=200, content={"message": "Profile picture uploaded successfully"})
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
        
@user_router.get("/check-token-validity",
    response_model=dict,
    status_code=200,
    summary="Check token validity",
    description="Check if token is valid",  
    responses={
        200: {"description": "Token is valid"},
        401: {"description": "Token is invalid"},
        500: {"description": "Internal server error"}
    }
)
async def check_token_validity(request: Request):
    try:
        token = request.headers.get("Authorization", "authorization")
        if token.split(" ")[0] == "Bearer":
            token = token.split(" ")[1]
        if not token:
            return JSONResponse(status_code=401, content={"error": "Invalid or missing Authorization header"})
        
        decoded_token = decodeJWT(token)
        user_id = decoded_token.get("user_id") if decoded_token else None
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Invalid token"})
        
        return JSONResponse(status_code=200, content={"message": "Token is valid"})
    except Exception as e:
        return JSONResponse(status_code=401, content={"error": str(e)})
    

@user_router.get("/enable-tfa", summary="Enable or disable TFA")
async def enable_tfa(
    request: Request,
    enable: bool,
    db: Session = Depends(get_db),
):
    try:
        user_id = get_current_user(request)
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == user_id).first()
        if not current_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if enable:
            current_user.tfa_enabled = True
        else:
            current_user.tfa_enabled = False
        db.commit()
        db.refresh(current_user)
        return JSONResponse(status_code=200, content={"message": f"TFA {'enabled' if enable else 'disabled'} successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.get("/toggle-data-sharing", summary="Toggle data sharing")
async def toggle_data_sharing(request: Request, enable: bool, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == user_id).first()
        if not current_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if current_user.data_sharing:
            current_user.data_sharing = False
        else:
            current_user.data_sharing = True
        db.commit()
        db.refresh(current_user)
        return JSONResponse(status_code=200, content={"message": f"Data sharing {'enabled' if enable else 'disabled'} successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.get("/notification-preferences", summary="Update notification preferences")
async def update_notification_preferences(
    request: Request, 
    email_alert: bool = False,
    push_notification: bool = False, 
    newsletter: bool = False,
    db: Session = Depends(get_db)
):
    try:
        user_id = get_current_user(request)
        print(user_id)
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == user_id).first()
        if not current_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        updates = {}
        messages = []
        
        current_user.email_alert = email_alert
        updates["email_alert"] = email_alert
        messages.append(f"Email alerts {'enabled' if email_alert else 'disabled'}")
            
        current_user.push_notification = push_notification
        updates["push_notification"] = push_notification
        messages.append(f"Push notifications {'enabled' if push_notification else 'disabled'}")
            
        current_user.newsletter = newsletter
        updates["newsletter"] = newsletter
        messages.append(f"Newsletter {'enabled' if newsletter else 'disabled'}")
            
        db.commit()
        db.refresh(current_user)
        return JSONResponse(
            status_code=200, 
            content={
                "message": " and ".join(messages) + " successfully",
                "preferences": updates
            }
        )
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
@user_router.get("/notification-settings", summary="Get notification settings")
async def get_notification_settings(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == user_id).first()
        if not current_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        notifications = {
            "email_alert": current_user.email_alert,
            "push_notification": current_user.push_notification,
            "newsletter": current_user.newsletter,
        }
        
        return JSONResponse(status_code=200, content={"notifications": notifications})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@user_router.get("/deactivate-account", summary="Deactivate account")
async def deactivate_account(request: Request, db: Session = Depends(get_db)):
    try:
        user_id = get_current_user(request)
        if not user_id:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        current_user = db.query(User).filter(User.id == user_id).first()
        if not current_user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        current_user.is_active = False
        db.commit()
        db.refresh(current_user)
        return JSONResponse(status_code=200, content={"message": "Account deactivated successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
