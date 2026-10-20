"""Schema-guided text generation with local validation, not native constrained sampling."""
import json

from pydantic import BaseModel


def json_instructions(instructions: str, response_model: type[BaseModel]) -> str:
    schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
    return instructions + "\nReturn exactly one JSON value matching this schema. No Markdown or extra text.\n" + schema


def parse_json_output(text: str, response_model: type[BaseModel]) -> BaseModel:
    # Do not repair, guess fields, coerce business-specific values or call the model again.
    return response_model.model_validate_json(text)
