import sys
from sqlalchemy import text
sys.path.insert(0, 'backend')
from app.core.database import engine

with engine.connect() as conn:
    res = conn.execute(text("""
        SELECT tablename, rowsecurity 
        FROM pg_tables 
        WHERE tablename IN ('overrides', 'pipeline_errors');
    """)).fetchall()
    print('Tables and RLS:', res)

    policies = conn.execute(text("""
        SELECT tablename, policyname 
        FROM pg_policies 
        WHERE tablename IN ('overrides', 'pipeline_errors');
    """)).fetchall()
    print('Policies:', policies)
