import json
from tool_plugins import math_solver


def test_solve_expression():
    result = math_solver.run_tool({"expression": "2+2*2"})
    data = json.loads(result)
    assert data["result"] == "6"


def test_solve_equation():
    result = math_solver.run_tool({"equation": "x+2=5"})
    data = json.loads(result)
    assert "solutions" in data
    assert data["solutions"][0] == "3"
