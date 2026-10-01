from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.models import User

passwords = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return passwords.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return passwords.verify(password, hashed)


def create_token(user: User) -> str:
    memberships = user.memberships
    if not memberships:
        raise ValueError("User has no organization")
    payload = {"sub": user.id, "org": memberships[0].organization_id, "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise ValueError("Invalid authentication token") from exc
