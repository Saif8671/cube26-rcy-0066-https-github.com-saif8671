import os


os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SUPABASE_JWT_ISSUER", "https://test.supabase.co/auth/v1")
os.environ.setdefault("SUPABASE_JWT_AUDIENCE", "authenticated")
os.environ.setdefault("TRUSTED_TENANT_HEADER_ENABLED", "false")
