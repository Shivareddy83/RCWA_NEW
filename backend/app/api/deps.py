from app.db.session import SessionLocal

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
