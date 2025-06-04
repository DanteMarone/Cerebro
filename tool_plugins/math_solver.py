TOOL_METADATA = {
    "name": "math-solver",
    "description": "Solve mathematical expressions or equations using SymPy and return a JSON-formatted result."
}

import json


def run_tool(args):
    """Evaluate an expression or solve an equation."""
    expression = args.get("expression")
    equation = args.get("equation")
    try:
        from sympy import Eq, sympify, solve
        from sympy.parsing.sympy_parser import parse_expr

        if equation:
            if "=" not in equation:
                return json.dumps({"error": "Equation must contain '='"})
            left, right = equation.split("=", 1)
            eq = Eq(parse_expr(left), parse_expr(right))
            solutions = solve(eq)
            return json.dumps({"solutions": [str(s) for s in solutions]})
        if expression:
            result = sympify(expression)
            return json.dumps({"result": str(result)})
        return json.dumps({"error": "No expression or equation provided"})
    except Exception as e:
        return json.dumps({"error": str(e)})
