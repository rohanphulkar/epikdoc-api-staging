from sqlalchemy.orm import Session
from auth.models import User, Permission

def has_permission(user: User, permission_name: str, session: Session) -> bool:
    """Check if a user has a specific permission."""
    permission = session.query(Permission).filter_by(name=permission_name).first()
    return permission in user.permissions if permission else False

def add_permission_to_user(user: User, permission_name: str, session: Session) -> bool:
    """Grant a permission to a user."""
    permission = session.query(Permission).filter_by(name=permission_name).first()
    if not permission:
        print("Permission does not exist!")
        return False
    
    if permission not in user.permissions:
        user.permissions.append(permission)
        session.commit()
        print(f"Permission '{permission_name}' added to {user.email}")
        return True
    else:
        print("User already has this permission.")
        return False

def remove_permission_from_user(user: User, permission_name: str, session: Session) -> bool:
    """Revoke a permission from a user."""
    permission = session.query(Permission).filter_by(name=permission_name).first()
    if permission and permission in user.permissions:
        user.permissions.remove(permission)
        session.commit()
        print(f"Permission '{permission_name}' removed from {user.email}")
        return True
    else:
        print("User does not have this permission.")
        return False
