from sqlalchemy.orm import Session

from app.services.settings_service import seed_defaults


def bootstrap_database(db: Session) -> None:
    seed_defaults(db)
