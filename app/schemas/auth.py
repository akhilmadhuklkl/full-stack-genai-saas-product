from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not any(character.isupper() for character in value):
            raise ValueError("Password must contain an uppercase letter")
        if not any(character.islower() for character in value):
            raise ValueError("Password must contain a lowercase letter")
        if not any(character.isdigit() for character in value):
            raise ValueError("Password must contain a number")
        return value


class LoginRequest(RegisterRequest):
    pass


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
