from datetime import datetime
from decimal import Decimal

def dump(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "__table__"):
        return {column.name: dump(getattr(value, column.name)) for column in value.__table__.columns}
    if isinstance(value, list):
        return [dump(item) for item in value]
    return value

def case_view(case):
    data = dump(case)
    data["rca"] = dump(case.rca) if case.rca else None
    return data
