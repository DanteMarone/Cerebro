import json
import os
import time
from typing import List, Dict, Any, Literal, Union
from log_utils import logger  # Import logger
from screenshot import capture_screenshot_to_tempfile # Import for screenshot functionality

# Attempt to import pyautogui globally so tests can patch it easily.
try:
    import pyautogui  # type: ignore
except Exception:  # pragma: no cover - optional dependency may be missing
    pyautogui = None

AUTOMATIONS_FILE = "automations.json"
STEP_AUTOMATIONS_FILE = "step_automations.json"

# Define Step Types
STEP_TYPE_MOUSE_CLICK = "MouseClick"
STEP_TYPE_KEYBOARD_INPUT = "KeyboardInput"
STEP_TYPE_WAIT = "Wait"
STEP_TYPE_ASK_AGENT = "AskAgent"
STEP_TYPE_LOOP_START = "LoopStart"
STEP_TYPE_LOOP_END = "LoopEnd"
STEP_TYPE_IF_CONDITION = "IfCondition"
STEP_TYPE_ELSE = "Else"
STEP_TYPE_END_IF = "EndIf"
STEP_TYPE_MOUSE_DRAG = "MouseDrag"
STEP_TYPE_SET_VARIABLE = "SetVariable"

SupportedStepType = Literal[
    "MouseClick",
    "MouseDrag",
    "KeyboardInput",
    "Wait",
    "AskAgent",
    "LoopStart",
    "LoopEnd",
    "IfCondition",
    "Else",
    "EndIf",
    "SetVariable",
]

# Define parameter structures for each step type (optional, but good for clarity)
class MouseClickParams(Dict):
    x: int
    y: int
    button: str

class KeyboardInputParams(Dict):
    keys: str

class WaitParams(Dict):
    duration: float

class AskAgentParams(Dict):
    prompt: str
    agent_name: str
    send_screenshot: bool

class MouseDragParams(Dict):
    start_x: int
    start_y: int
    end_x: int
    end_y: int

class SetVariableParams(Dict):
    name: str
    value: Any

class LoopStartParams(Dict):
    count: Union[int, None]  # Optional, for count-based loops
    condition: Union[str, None]  # Optional, for condition-based loops

# LoopEnd, Else, EndIf typically don't have parameters, but can be empty dicts if needed.

StepParams = Union[
    MouseClickParams,
    KeyboardInputParams,
    WaitParams,
    AskAgentParams,
    LoopStartParams,
    MouseDragParams,
    SetVariableParams,
    Dict[str, Any],  # For steps with no specific params like LoopEnd, Else, EndIf
]

class Step(Dict):
    type: SupportedStepType
    params: StepParams

def load_automations(debug_enabled: bool = False) -> List[Dict[str, Any]]:
    """Return list of saved automations."""
    if not os.path.exists(AUTOMATIONS_FILE):
        return []
    try:
        with open(AUTOMATIONS_FILE, "r", encoding="utf-8") as f:
            autos = json.load(f)
        if debug_enabled: # Keep debug_enabled flag for selective print, or remove if logger handles all
            logger.debug(f"Automations loaded: {autos}")
        return autos
    except Exception as exc:
        if debug_enabled:
            logger.error(f"Failed to load automations: {exc}")
        return []

def save_automations(automations: List[Dict[str, Any]], debug_enabled: bool = False) -> None:
    """Persist automations to disk."""
    try:
        with open(AUTOMATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(automations, f, indent=2)
        if debug_enabled:
            logger.debug("Automations saved.")
    except Exception as exc:
        if debug_enabled:
            logger.error(f"Failed to save automations: {exc}")

def record_automation(duration: float = 5) -> List[Dict[str, Any]]:
    """Record mouse and keyboard events for the given duration."""
    try:
        from pynput import mouse, keyboard
    except Exception:
        return []

    events: List[Dict[str, Any]] = []
    start = time.time()

    def on_move(x, y):
        events.append({"type": "move", "x": x, "y": y, "time": time.time() - start})

    def on_click(x, y, button, pressed):
        events.append({
            "type": "click",
            "x": x,
            "y": y,
            "button": getattr(button, "name", str(button)),
            "pressed": pressed,
            "time": time.time() - start,
        })

    def on_press(key):
        events.append({"type": "press", "key": str(key), "time": time.time() - start})

    def on_release(key):
        events.append({"type": "release", "key": str(key), "time": time.time() - start})
        if key == keyboard.Key.esc:
            return False

    with mouse.Listener(on_move=on_move, on_click=on_click) as ml, \
            keyboard.Listener(on_press=on_press, on_release=on_release) as kl:
        end = time.time() + duration
        while time.time() < end and ml.running and kl.running:
            time.sleep(0.01)
    return events

def run_automation(automations: List[Dict[str, Any]], name: str,
                   step_delay: float = 0.5) -> str:
    """Replay events for the named automation.

    Mouse movement events are skipped. The cursor jumps to the coordinates of
    click/drag actions so sequences play back quickly regardless of the original
    recording speed. A small delay can be inserted between events using
    ``step_delay`` to simulate a more natural pace.
    """
    auto = next((a for a in automations if a.get("name") == name), None)
    if not auto:
        return f"[Automation Error] '{name}' not found"
    global pyautogui
    if pyautogui is None:
        try:
            import pyautogui as _pg  # type: ignore
            pyautogui = _pg
        except Exception:
            return "[Automation Error] pyautogui not installed."
    events = auto.get("events")
    if not isinstance(events, list):
        return f"[Automation Error] Invalid event list for '{name}'"
    button_down = None
    for evt in events:
        etype = evt.get("type")
        if etype == "click":
            btn = evt.get("button", "left")
            if evt.get("pressed"):
                pyautogui.moveTo(evt["x"], evt["y"])
                pyautogui.mouseDown(button=btn)
                button_down = btn
            else:
                pyautogui.moveTo(evt["x"], evt["y"])
                pyautogui.mouseUp(button=button_down or btn)
                button_down = None
        elif etype == "press":
            key = evt.get("key", "").replace("'", "")
            pyautogui.keyDown(key)
        elif etype == "release":
            key = evt.get("key", "").replace("'", "")
            pyautogui.keyUp(key)
        else:
            continue
        time.sleep(step_delay)
    return "Automation executed"


def add_automation(automations: List[Dict[str, Any]], name: str, events: List[Dict[str, Any]],
                   debug_enabled: bool = False) -> None:
    """Add a new automation and save."""
    automations.append({"name": name, "events": events})
    save_automations(automations, debug_enabled)


# --- Step-based Automation Execution ---

# Simplified list of special keys for pyautogui.press()
# This can be expanded. Keys should be lowercased for mapping.
PYAUTOGUI_SPECIAL_KEYS = [
    'enter', 'esc', 'shift', 'ctrl', 'alt', 'tab', 'backspace', 'delete', 'insert',
    'home', 'end', 'pageup', 'pagedown', 'up', 'down', 'left', 'right',
    'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
    'space', 'printscreen', 'capslock', 'numlock', 'scrolllock', 'win', 'cmd',
    'option', # Mac specific, maps to alt usually or cmd
    # pyautogui also supports specific left/right versions like 'shiftleft', 'ctrlright'
]

# Default execution context structure
DEFAULT_EXECUTION_CONTEXT = {
    'current_step_index': 0,
    'loop_stack': [],      # For LoopStart/LoopEnd
    'if_stack': [],        # For If/Else/EndIf (future)
    'status': 'pending',   # pending, running, paused_ask_agent, completed, error
    'error_message': None,
    # For AskAgent specific returns
    'ask_agent_prompt': None,
    'ask_agent_agent_name': None, # New field
    'ask_agent_send_screenshot': False, # New field
    'ask_agent_screenshot_path': None,
    'next_step_index_after_ask': None,
    'variables': {}
}

def run_step_automation(
    automation_steps: List[Dict[str, Any]],
    step_delay: float = 0.1,
    execution_context: Union[Dict[str, Any], None] = None
) -> Dict[str, Any]:
    """
    Executes a list of step-based automation dictionaries.
    Manages execution state via execution_context for resumability.
    Always returns an updated execution_context dictionary.
    """
    context = {}
    if execution_context is None:
        context.update(DEFAULT_EXECUTION_CONTEXT)
        logger.info("Starting execution of step-based automation from beginning.")
    else:
        context.update(execution_context)
        logger.info(f"Resuming execution of step-based automation from step {context.get('current_step_index', 0) + 1}.")
        # Reset transient fields if resuming
        context['ask_agent_prompt'] = None
        context['ask_agent_agent_name'] = None
        context['ask_agent_send_screenshot'] = False
        context['ask_agent_screenshot_path'] = None
        context['next_step_index_after_ask'] = None
        # Keep current_step_index, loop_stack, if_stack

    context['status'] = 'running'
    context['error_message'] = None
    # Ensure if_stack is initialized in the context
    if 'if_stack' not in context: # Should be handled by DEFAULT_EXECUTION_CONTEXT
        context['if_stack'] = []


    global pyautogui
    if pyautogui is None:
        try:
            import pyautogui as _pg  # type: ignore
            pyautogui = _pg
        except ImportError:
            context['status'] = 'error'
            context['error_message'] = "[Automation Error] pyautogui is not installed."
            logger.error(context['error_message'])
            return context
        except Exception as e:
            context['status'] = 'error'
            context['error_message'] = f"[Automation Error] Failed to import pyautogui: {e}"
            logger.error(context['error_message'])
            return context

    i = context['current_step_index']
    loop_stack = context['loop_stack']
    if_stack = context['if_stack'] # Local alias for if_stack

    while i < len(automation_steps):
        step = automation_steps[i]
        step_type = step.get("type")
        params = step.get("params", {})

        logger.debug(f"Executing step {i+1}/{len(automation_steps)}: {step_type} with params {params}")

        if not is_valid_step(step):
            context['status'] = 'error'
            context['error_message'] = f"[Automation Error] Step {i+1} ('{step_type}') is invalid or has missing parameters."
            context['current_step_index'] = i
            logger.error(context['error_message'])
            return context

        try:
            if step_type == STEP_TYPE_ASK_AGENT:
                context['status'] = 'paused_ask_agent'
                prompt = params.get("prompt", "Agent action required.")
                agent_name = params.get("agent_name", "") # Get agent_name
                send_screenshot = params.get("send_screenshot", False) # Get send_screenshot

                context['ask_agent_prompt'] = prompt
                context['ask_agent_agent_name'] = agent_name
                context['ask_agent_send_screenshot'] = send_screenshot
                context['current_step_index'] = i
                context['next_step_index_after_ask'] = i + 1

                if send_screenshot:
                    try:
                        screenshot_path = capture_screenshot_to_tempfile()
                        context['ask_agent_screenshot_path'] = screenshot_path
                        logger.info(f"Screenshot captured for AskAgent: {screenshot_path}")
                    except Exception as e:
                        logger.error(f"Failed to capture screenshot for AskAgent: {e}", exc_info=True)
                        # Decide if this is a fatal error or if we can proceed without screenshot
                        # For now, let's proceed without it but log the error.
                        context['ask_agent_screenshot_path'] = None
                else:
                    context['ask_agent_screenshot_path'] = None

                logger.info(f"Pausing for AskAgent at step {i+1}: Prompt='{prompt}', Agent='{agent_name}', SendScreenshot='{send_screenshot}'")
                return context

            elif step_type == STEP_TYPE_LOOP_START:
                count = params.get("count")
                if not isinstance(count, int) or count <= 0:
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (LoopStart): Invalid or missing 'count' ({count}). Must be a positive integer."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context
                loop_stack.append({
                    'type': 'loop',
                    'start_index_after_loopstart': i + 1,
                    'current_iteration': 0,
                    'total_iterations': count
                })

            elif step_type == STEP_TYPE_LOOP_END:
                if not loop_stack or loop_stack[-1].get('type') != 'loop':
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (LoopEnd): No matching LoopStart found."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context

                current_loop = loop_stack[-1]
                current_loop['current_iteration'] += 1

                if current_loop['current_iteration'] < current_loop['total_iterations']:
                    # Jump back to the step after LoopStart
                    i = current_loop['start_index_after_loopstart']
                    # Update context before continuing, as i might not be set if loop is empty
                    context['current_step_index'] = i
                    if step_delay > 0: time.sleep(step_delay) # Delay after processing LoopEnd before jump
                    continue # Skip normal increment of i at end of while loop
                else:
                    loop_stack.pop() # Loop finished

            elif step_type == STEP_TYPE_MOUSE_CLICK:
                x = params.get("x")
                y = params.get("y")
                button = params.get("button", "left").lower() # Ensure button is lowercase
                if not all(isinstance(val, int) for val in [x,y]):
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (MouseClick): X and Y must be integers. Got x={x}, y={y}."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context
                if button not in ["left", "right", "middle"]:
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (MouseClick): Invalid button '{button}'. Must be 'left', 'right', or 'middle'."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context
                pyautogui.moveTo(x, y)
                pyautogui.click(x=x, y=y, button=button)

            elif step_type == STEP_TYPE_MOUSE_DRAG:
                start_x = params.get("start_x")
                start_y = params.get("start_y")
                end_x = params.get("end_x")
                end_y = params.get("end_y")
                # TODO(agent): Consider adding button parameter for drag
                if not all(isinstance(val, int) for val in [start_x, start_y, end_x, end_y]):
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (MouseDrag): Start and End X, Y must be integers. Got start_x={start_x}, start_y={start_y}, end_x={end_x}, end_y={end_y}."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context
                pyautogui.moveTo(start_x, start_y)
                pyautogui.dragTo(end_x, end_y, duration=0.2) # Default duration, can be parameterized

            elif step_type == STEP_TYPE_KEYBOARD_INPUT:
                keys = params.get("keys", "")
                if not isinstance(keys, str):
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (KeyboardInput): 'keys' parameter must be a string. Got {type(keys)}."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context

                if keys.startswith("$") and keys.endswith("$"):
                    special_key_name = keys[1:-1].lower()
                    if special_key_name in PYAUTOGUI_SPECIAL_KEYS:
                        pyautogui.press(special_key_name)
                    elif '+' in special_key_name:
                        parts = [part.strip() for part in special_key_name.split('+')]
                        if all(part in PYAUTOGUI_SPECIAL_KEYS for part in parts):
                             pyautogui.hotkey(*parts)
                        else:
                            context['status'] = 'error'
                            context['error_message'] = f"[Automation Error] Step {i+1} (KeyboardInput): Invalid special key or hotkey part: '{special_key_name}'"
                            context['current_step_index'] = i
                            logger.error(context['error_message'])
                            return context
                    else:
                        context['status'] = 'error'
                        context['error_message'] = f"[Automation Error] Step {i+1} (KeyboardInput): Unknown special key '$ {special_key_name} $'."
                        context['current_step_index'] = i
                        logger.error(context['error_message'])
                        return context
                else:
                    pyautogui.typewrite(keys)

            elif step_type == STEP_TYPE_WAIT:
                duration = params.get("duration", 0.0)
                if not isinstance(duration, (int, float)) or duration < 0:
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (Wait): Duration must be a non-negative number. Got {duration}."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context
                time.sleep(duration)

            elif step_type == STEP_TYPE_SET_VARIABLE:
                var_name = params.get("name")
                var_value = params.get("value")
                if not isinstance(var_name, str):
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (SetVariable): 'name' must be a string."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context
                context.setdefault('variables', {})[var_name] = var_value

            elif step_type == STEP_TYPE_IF_CONDITION:
                condition_str = params.get("condition", "").lower()
                if condition_str not in ["true", "false"]:
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (IfCondition): Invalid condition '{params.get('condition')}'. Must be 'true' or 'false'."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context

                condition_eval_result = (condition_str == "true")
                if_stack.append({
                    'type': 'if',
                    'condition_met': condition_eval_result,
                    'else_encountered': False,
                    'if_start_index': i
                })

                if not condition_eval_result:
                    skip_to_index = _find_matching_block_end(
                        automation_steps, i,
                        open_type=STEP_TYPE_IF_CONDITION,
                        close_type=STEP_TYPE_END_IF,
                        intermediate_type=STEP_TYPE_ELSE
                    )
                    if skip_to_index is None:
                        context['status'] = 'error'
                        context['error_message'] = f"[Automation Error] Step {i+1} (IfCondition): No matching EndIf or Else found for false condition."
                        context['current_step_index'] = i
                        logger.error(context['error_message'])
                        return context
                    i = skip_to_index
                    if step_delay > 0: time.sleep(step_delay)
                    continue

            elif step_type == STEP_TYPE_ELSE:
                if not if_stack or if_stack[-1]['type'] != 'if':
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (Else): No matching IfCondition found."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context

                current_if_block = if_stack[-1]
                if current_if_block['else_encountered']:
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (Else): Duplicate Else statements for the same If."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context

                current_if_block['else_encountered'] = True

                if current_if_block['condition_met']:
                    skip_to_index = _find_matching_block_end(
                        automation_steps, i,
                        open_type=STEP_TYPE_IF_CONDITION,
                        close_type=STEP_TYPE_END_IF
                    )
                    if skip_to_index is None:
                        context['status'] = 'error'
                        context['error_message'] = f"[Automation Error] Step {i+1} (Else): No matching EndIf found for executed If."
                        context['current_step_index'] = i
                        logger.error(context['error_message'])
                        return context
                    i = skip_to_index
                    if step_delay > 0: time.sleep(step_delay)
                    continue

            elif step_type == STEP_TYPE_END_IF:
                if not if_stack or if_stack[-1]['type'] != 'if':
                    context['status'] = 'error'
                    context['error_message'] = f"[Automation Error] Step {i+1} (EndIf): No matching IfCondition found."
                    context['current_step_index'] = i
                    logger.error(context['error_message'])
                    return context
                if_stack.pop()
            else:
                context['status'] = 'error'
                context['error_message'] = f"[Automation Error] Step {i+1}: Unhandled valid step type '{step_type}'."
                context['current_step_index'] = i
                logger.error(context['error_message'])
                return context

            if step_delay > 0:
                time.sleep(step_delay)

            i += 1

        except Exception as e:
            context['status'] = 'error'
            context['error_message'] = f"[Automation Error] During step {i+1} ('{step_type}'): {e}."
            context['current_step_index'] = i
            logger.error(f"Exception during step {i+1} ('{step_type}'): {e}", exc_info=True)
            return context

    context['current_step_index'] = i
    if context['status'] == 'running':
        if loop_stack:
            context['status'] = 'error'
            context['error_message'] = f"[Automation Error] Reached end of script with unclosed loops on stack: {len(loop_stack)} remaining."
            logger.error(context['error_message'])
        elif if_stack: # Check if_stack, not context['if_stack']
            context['status'] = 'error'
            context['error_message'] = f"[Automation Error] Reached end of script with unclosed If blocks on stack: {len(if_stack)} remaining."
            logger.error(context['error_message'])
        else:
            context['status'] = 'completed'
            context['error_message'] = None
            logger.info("Step-based automation executed successfully.")
    return context

def _find_matching_block_end(
    steps: List[Dict[str, Any]],
    current_index: int,
    open_type: str,
    close_type: str,
    intermediate_type: Union[str, None] = None
) -> Union[int, None]:
    """
    Finds the index of the matching close_type or intermediate_type for an open_type.
    Skips nested structures of the same open_type.
    `current_index` is the index of the `open_type` step itself.
    """
    level = 1
    search_index = current_index + 1
    while search_index < len(steps):
        step = steps[search_index]
        s_type = step.get("type")

        if s_type == open_type:
            level += 1
        elif intermediate_type and s_type == intermediate_type and level == 1:
            return search_index # Found intermediate (e.g., Else) at the correct level
        elif s_type == close_type:
            level -= 1
            if level == 0:
                return search_index # Found matching close (e.g., EndIf)

        search_index += 1
    return None # Not found


# Helper functions for step-based automations

def create_step(step_type: SupportedStepType, params: StepParams) -> Step:
    """
    Creates a new step dictionary.
    """
    return {"type": step_type, "params": params}

def is_valid_step(step_dict: Dict[str, Any]) -> bool:
    """
    Validates a step dictionary.
    Checks for 'type' and 'params' keys, and validates known step types.
    """
    if not isinstance(step_dict, dict):
        return False
    if "type" not in step_dict or "params" not in step_dict:
        return False

    step_type = step_dict["type"]
    params = step_dict["params"]

    if not isinstance(params, dict):
        return False

    if step_type == STEP_TYPE_MOUSE_CLICK:
        return "x" in params and "y" in params and "button" in params and \
               isinstance(params["x"], int) and \
               isinstance(params["y"], int) and \
               isinstance(params["button"], str)
    elif step_type == STEP_TYPE_KEYBOARD_INPUT:
        return "keys" in params and isinstance(params["keys"], str)
    elif step_type == STEP_TYPE_WAIT:
        return "duration" in params and isinstance(params["duration"], (int, float))
    elif step_type == STEP_TYPE_ASK_AGENT:
        return "prompt" in params and isinstance(params["prompt"], str) and \
               "agent_name" in params and isinstance(params["agent_name"], str) and \
               "send_screenshot" in params and isinstance(params["send_screenshot"], bool)
    elif step_type == STEP_TYPE_LOOP_START:
        has_count = "count" in params and isinstance(params["count"], int)
        has_condition = "condition" in params and isinstance(params["condition"], str)
        return (has_count and not has_condition) or (has_condition and not has_count) # Mutually exclusive
    elif step_type in [STEP_TYPE_LOOP_END, STEP_TYPE_ELSE, STEP_TYPE_END_IF]:
        return True # No specific params required, or params can be an empty dict
    elif step_type == STEP_TYPE_IF_CONDITION:
        return "condition" in params and isinstance(params["condition"], str)
    elif step_type == STEP_TYPE_MOUSE_DRAG:
        return "start_x" in params and isinstance(params["start_x"], int) and \
               "start_y" in params and isinstance(params["start_y"], int) and \
               "end_x" in params and isinstance(params["end_x"], int) and \
               "end_y" in params and isinstance(params["end_y"], int)
    elif step_type == STEP_TYPE_SET_VARIABLE:
        return "name" in params and isinstance(params["name"], str) and "value" in params

    return False # Unknown step type

# New Save/Load Functions for Step-Based Automations

def load_step_automations(debug_enabled: bool = False) -> List[Dict[str, Any]]:
    """Return list of saved step-based automations."""
    if not os.path.exists(STEP_AUTOMATIONS_FILE):
        return []
    try:
        with open(STEP_AUTOMATIONS_FILE, "r", encoding="utf-8") as f:
            autos = json.load(f)
        if debug_enabled:
            logger.debug(f"Step automations loaded: {autos}")
        return autos
    except Exception as exc:
        if debug_enabled:
            logger.error(f"Failed to load step automations: {exc}", exc_info=True)
        return []

def save_step_automations(automations: List[Dict[str, Any]], debug_enabled: bool = False) -> None:
    """Persist step-based automations to disk."""
    try:
        with open(STEP_AUTOMATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(automations, f, indent=2)
        if debug_enabled:
            logger.debug("Step automations saved.")
    except Exception as exc:
        if debug_enabled:
            logger.error(f"Failed to save step automations: {exc}", exc_info=True)


def delete_automation(automations: List[Dict[str, Any]], name: str, debug_enabled: bool = False) -> None:
    """Delete automation by name."""
    idx = next((i for i, a in enumerate(automations) if a.get("name") == name), None)
    if idx is None:
        return
    del automations[idx]
    save_automations(automations, debug_enabled)
