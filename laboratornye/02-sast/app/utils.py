import ast


def calculate(expression):
    if not isinstance(expression, str):
        raise ValueError("ожидается строка")
    try:
        value = ast.literal_eval(expression)
    except (ValueError, SyntaxError):
        raise ValueError("ожидается число")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("ожидается число")
    return value
