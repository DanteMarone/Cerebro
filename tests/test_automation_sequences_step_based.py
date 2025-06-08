import unittest
from unittest.mock import patch, MagicMock, mock_open, call
import json # For load/save tests
import os # For load/save tests

# Assuming automation_sequences.py is in the parent directory or accessible via PYTHONPATH
# For local testing, ensure PYTHONPATH is set up correctly or adjust path.
# For this environment, it's expected to be found directly.
from automation_sequences import (
    create_step, is_valid_step,
    load_step_automations, save_step_automations,
    run_step_automation,
    STEP_TYPE_MOUSE_CLICK, STEP_TYPE_KEYBOARD_INPUT, STEP_TYPE_WAIT,
    STEP_TYPE_ASK_AGENT, STEP_TYPE_LOOP_START, STEP_TYPE_LOOP_END,
    STEP_TYPE_IF_CONDITION, STEP_TYPE_ELSE, STEP_TYPE_END_IF,
    STEP_AUTOMATIONS_FILE,
    DEFAULT_EXECUTION_CONTEXT,
    PYAUTOGUI_SPECIAL_KEYS # For testing keyboard input
)

class TestStepBasedHelperFunctions(unittest.TestCase):
    def test_create_step(self):
        step = create_step(STEP_TYPE_MOUSE_CLICK, {"x": 10, "y": 20, "button": "left"})
        self.assertEqual(step, {"type": STEP_TYPE_MOUSE_CLICK, "params": {"x": 10, "y": 20, "button": "left"}})
        step_wait = create_step(STEP_TYPE_WAIT, {"duration": 5})
        self.assertEqual(step_wait, {"type": STEP_TYPE_WAIT, "params": {"duration": 5}})

    def test_is_valid_step_mouse_click(self):
        self.assertTrue(is_valid_step({"type": STEP_TYPE_MOUSE_CLICK, "params": {"x": 1, "y": 1, "button": "left"}}))
        self.assertFalse(is_valid_step({"type": STEP_TYPE_MOUSE_CLICK, "params": {"x": 1, "y": "bad"}})) # Bad y
        self.assertFalse(is_valid_step({"type": STEP_TYPE_MOUSE_CLICK, "params": {"x": 1}})) # Missing params

    def test_is_valid_step_keyboard_input(self):
        self.assertTrue(is_valid_step({"type": STEP_TYPE_KEYBOARD_INPUT, "params": {"keys": "hello"}}))
        self.assertFalse(is_valid_step({"type": STEP_TYPE_KEYBOARD_INPUT, "params": {}})) # Missing keys

    def test_is_valid_step_wait(self):
        self.assertTrue(is_valid_step({"type": STEP_TYPE_WAIT, "params": {"duration": 1.5}}))
        self.assertFalse(is_valid_step({"type": STEP_TYPE_WAIT, "params": {"duration": "bad"}}))

    def test_is_valid_step_ask_agent(self):
        self.assertTrue(is_valid_step({"type": STEP_TYPE_ASK_AGENT, "params": {"prompt": "Test?"}}))
        self.assertTrue(is_valid_step({"type": STEP_TYPE_ASK_AGENT, "params": {"prompt": "Test?", "screenshot_path": "path.png"}}))
        self.assertFalse(is_valid_step({"type": STEP_TYPE_ASK_AGENT, "params": {}}))

    def test_is_valid_step_loop(self):
        self.assertTrue(is_valid_step({"type": STEP_TYPE_LOOP_START, "params": {"count": 3}}))
        self.assertFalse(is_valid_step({"type": STEP_TYPE_LOOP_START, "params": {"count": "bad"}}))
        self.assertFalse(is_valid_step({"type": STEP_TYPE_LOOP_START, "params": {}})) # Missing count/condition
        self.assertTrue(is_valid_step({"type": STEP_TYPE_LOOP_END, "params": {}}))

    def test_is_valid_step_if(self):
        self.assertTrue(is_valid_step({"type": STEP_TYPE_IF_CONDITION, "params": {"condition": "true"}}))
        self.assertFalse(is_valid_step({"type": STEP_TYPE_IF_CONDITION, "params": {}})) # Missing condition
        self.assertTrue(is_valid_step({"type": STEP_TYPE_ELSE, "params": {}}))
        self.assertTrue(is_valid_step({"type": STEP_TYPE_END_IF, "params": {}}))

    def test_is_valid_step_invalid_structure(self):
        self.assertFalse(is_valid_step(None))
        self.assertFalse(is_valid_step([]))
        self.assertFalse(is_valid_step({"type": "UnknownType", "params": {}}))
        self.assertFalse(is_valid_step({"no_type": "MouseClick", "params": {}}))


class TestStepBasedSaveLoad(unittest.TestCase):
    @patch("builtins.open", new_callable=mock_open)
    @patch("json.dump")
    def test_save_step_automations(self, mock_json_dump, mock_file_open):
        automations = [{"name": "TestAuto", "steps": [{"type": "Wait", "params": {"duration": 1}}]}]
        save_step_automations(automations, debug_enabled=False)
        mock_file_open.assert_called_once_with(STEP_AUTOMATIONS_FILE, "w", encoding="utf-8")
        mock_json_dump.assert_called_once_with(automations, mock_file_open(), indent=2)

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data='[{"name": "LoadedAuto"}]')
    @patch("json.load")
    def test_load_step_automations_file_exists(self, mock_json_load, mock_file_open, mock_exists):
        mock_json_load.return_value = [{"name": "LoadedAuto"}]
        result = load_step_automations(debug_enabled=False)
        mock_exists.assert_called_once_with(STEP_AUTOMATIONS_FILE)
        mock_file_open.assert_called_once_with(STEP_AUTOMATIONS_FILE, "r", encoding="utf-8")
        mock_json_load.assert_called_once_with(mock_file_open())
        self.assertEqual(result, [{"name": "LoadedAuto"}])

    @patch("os.path.exists", return_value=False)
    def test_load_step_automations_file_not_exists(self, mock_exists):
        result = load_step_automations(debug_enabled=False)
        mock_exists.assert_called_once_with(STEP_AUTOMATIONS_FILE)
        self.assertEqual(result, [])

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data='invalid json')
    @patch("json.load", side_effect=json.JSONDecodeError("err", "doc", 0))
    @patch("automation_sequences.logger.error") # Assuming logger is used for errors
    def test_load_step_automations_json_error(self, mock_logger_error, mock_json_load, mock_file_open, mock_exists):
        result = load_step_automations(debug_enabled=True) # Enable debug to trigger logger call
        self.assertEqual(result, [])
        mock_logger_error.assert_called_once()


class TestRunStepAutomation(unittest.TestCase):
    def setUp(self):
        self.mock_pyautogui = MagicMock()
        self.mock_time_sleep = MagicMock()

        self.pyautogui_patcher = patch('automation_sequences.pyautogui', self.mock_pyautogui)
        self.time_sleep_patcher = patch('automation_sequences.time.sleep', self.mock_time_sleep) # Patch time.sleep from automation_sequences context

        self.pyautogui_patcher.start()
        self.time_sleep_patcher.start()

    def tearDown(self):
        self.pyautogui_patcher.stop()
        self.time_sleep_patcher.stop()

    def test_run_mouse_click(self):
        steps = [create_step(STEP_TYPE_MOUSE_CLICK, {"x": 100, "y": 200, "button": "right"})]
        context = run_step_automation(steps)
        self.mock_pyautogui.moveTo.assert_called_once_with(100, 200)
        self.mock_pyautogui.click.assert_called_once_with(x=100, y=200, button="right")
        self.assertEqual(context['status'], 'completed')

    def test_run_keyboard_input_text(self):
        steps = [create_step(STEP_TYPE_KEYBOARD_INPUT, {"keys": "hello world"})]
        context = run_step_automation(steps)
        self.mock_pyautogui.typewrite.assert_called_once_with("hello world")
        self.assertEqual(context['status'], 'completed')

    def test_run_keyboard_input_special_key(self):
        steps = [create_step(STEP_TYPE_KEYBOARD_INPUT, {"keys": "$enter$"})]
        context = run_step_automation(steps)
        self.mock_pyautogui.press.assert_called_once_with("enter")
        self.assertEqual(context['status'], 'completed')

    def test_run_keyboard_input_hotkey(self):
        steps = [create_step(STEP_TYPE_KEYBOARD_INPUT, {"keys": "$ctrl+c$"})]
        context = run_step_automation(steps)
        self.mock_pyautogui.hotkey.assert_called_once_with("ctrl", "c")
        self.assertEqual(context['status'], 'completed')


    def test_run_wait(self):
        steps = [create_step(STEP_TYPE_WAIT, {"duration": 2.5})]
        context = run_step_automation(steps)
        self.mock_time_sleep.assert_called_once_with(2.5)
        self.assertEqual(context['status'], 'completed')

    def test_run_ask_agent(self):
        steps = [create_step(STEP_TYPE_ASK_AGENT, {"prompt": "User, do this.", "screenshot_path": "img.png"})]
        context = run_step_automation(steps)
        self.assertEqual(context['status'], 'paused_ask_agent')
        self.assertEqual(context['ask_agent_prompt'], "User, do this.")
        self.assertEqual(context['ask_agent_screenshot_path'], "img.png")
        self.assertEqual(context['current_step_index'], 0) # Paused at the AskAgent step
        self.assertEqual(context['next_step_index_after_ask'], 1)

    def test_run_simple_loop(self):
        steps = [
            create_step(STEP_TYPE_LOOP_START, {"count": 3}),
            create_step(STEP_TYPE_MOUSE_CLICK, {"x": 10, "y": 10, "button": "left"}),
            create_step(STEP_TYPE_LOOP_END, {})
        ]
        context = run_step_automation(steps)
        self.assertEqual(self.mock_pyautogui.click.call_count, 3)
        self.assertEqual(context['status'], 'completed')
        self.assertEqual(context['loop_stack'], []) # Stack should be empty

    def test_run_nested_loops(self):
        steps = [
            create_step(STEP_TYPE_LOOP_START, {"count": 2}), # Outer
            create_step(STEP_TYPE_LOOP_START, {"count": 3}), # Inner
            create_step(STEP_TYPE_MOUSE_CLICK, {"x": 1, "y": 1, "button": "left"}),
            create_step(STEP_TYPE_LOOP_END, {}), # Inner
            create_step(STEP_TYPE_LOOP_END, {})  # Outer
        ]
        context = run_step_automation(steps)
        self.assertEqual(self.mock_pyautogui.click.call_count, 6) # 2 * 3
        self.assertEqual(context['status'], 'completed')
        self.assertEqual(context['loop_stack'], [])

    def test_run_if_true(self):
        steps = [
            create_step(STEP_TYPE_IF_CONDITION, {"condition": "true"}),
            create_step(STEP_TYPE_MOUSE_CLICK, {"x": 1, "y": 1, "button": "left"}), # Should run
            create_step(STEP_TYPE_ELSE, {}),
            create_step(STEP_TYPE_MOUSE_CLICK, {"x": 2, "y": 2, "button": "right"}), # Should NOT run
            create_step(STEP_TYPE_END_IF, {})
        ]
        context = run_step_automation(steps)
        self.mock_pyautogui.click.assert_called_once_with(x=1, y=1, button="left")
        self.assertEqual(context['status'], 'completed')
        self.assertEqual(context['if_stack'], [])

    def test_run_if_false_else_executes(self):
        steps = [
            create_step(STEP_TYPE_IF_CONDITION, {"condition": "false"}),
            create_step(STEP_TYPE_MOUSE_CLICK, {"x": 1, "y": 1, "button": "left"}), # Should NOT run
            create_step(STEP_TYPE_ELSE, {}),
            create_step(STEP_TYPE_MOUSE_CLICK, {"x": 2, "y": 2, "button": "right"}), # Should run
            create_step(STEP_TYPE_END_IF, {})
        ]
        context = run_step_automation(steps)
        self.mock_pyautogui.click.assert_called_once_with(x=2, y=2, button="right")
        self.assertEqual(context['status'], 'completed')

    def test_run_if_false_no_else(self):
        steps = [
            create_step(STEP_TYPE_IF_CONDITION, {"condition": "false"}),
            create_step(STEP_TYPE_MOUSE_CLICK, {"x": 1, "y": 1, "button": "left"}), # Should NOT run
            create_step(STEP_TYPE_END_IF, {}),
            create_step(STEP_TYPE_MOUSE_CLICK, {"x": 3, "y": 3, "button": "middle"}) # Should run
        ]
        context = run_step_automation(steps)
        self.mock_pyautogui.click.assert_called_once_with(x=3,y=3,button="middle")
        self.assertEqual(context['status'], 'completed')

    def test_run_loop_with_if_and_ask_agent(self):
        steps = [
            create_step(STEP_TYPE_LOOP_START, {"count": 2}), # i=0, LoopStart
            create_step(STEP_TYPE_IF_CONDITION, {"condition": "true"}), # i=1, If
            create_step(STEP_TYPE_ASK_AGENT, {"prompt": "In loop"}),   # i=2, AskAgent
            create_step(STEP_TYPE_END_IF, {}),                         # i=3, EndIf
            create_step(STEP_TYPE_LOOP_END, {})                          # i=4, LoopEnd
        ]

        # First run, should pause at AskAgent
        exec_context = None
        exec_context = run_step_automation(steps, execution_context=exec_context)
        self.assertEqual(exec_context['status'], 'paused_ask_agent')
        self.assertEqual(exec_context['current_step_index'], 2) # Paused at AskAgent
        self.assertEqual(exec_context['loop_stack'][0]['current_iteration'], 0) # Iteration 0 of loop

        # Resume execution (simulate UI clicking OK)
        exec_context['current_step_index'] = exec_context['next_step_index_after_ask']
        exec_context = run_step_automation(steps, execution_context=exec_context)

        # Should pause again for AskAgent in the second iteration
        self.assertEqual(exec_context['status'], 'paused_ask_agent')
        self.assertEqual(exec_context['current_step_index'], 2) # Paused at AskAgent again
        self.assertEqual(exec_context['loop_stack'][0]['current_iteration'], 1) # Iteration 1 of loop

        # Resume again
        exec_context['current_step_index'] = exec_context['next_step_index_after_ask']
        exec_context = run_step_automation(steps, execution_context=exec_context)

        # Should complete
        self.assertEqual(exec_context['status'], 'completed')
        self.assertEqual(exec_context['loop_stack'], [])
        self.assertEqual(exec_context['if_stack'], [])


    def test_error_mismatched_loop_end(self):
        steps = [create_step(STEP_TYPE_LOOP_END, {})]
        context = run_step_automation(steps)
        self.assertEqual(context['status'], 'error')
        self.assertIn("No matching LoopStart", context['error_message'])

    def test_error_mismatched_end_if(self):
        steps = [create_step(STEP_TYPE_END_IF, {})]
        context = run_step_automation(steps)
        self.assertEqual(context['status'], 'error')
        self.assertIn("No matching IfCondition", context['error_message'])

    def test_error_unclosed_loop(self):
        steps = [create_step(STEP_TYPE_LOOP_START, {"count": 1})]
        context = run_step_automation(steps)
        self.assertEqual(context['status'], 'error')
        self.assertIn("unclosed loops on stack", context['error_message'])

    def test_error_unclosed_if(self):
        steps = [create_step(STEP_TYPE_IF_CONDITION, {"condition": "true"})]
        context = run_step_automation(steps)
        self.assertEqual(context['status'], 'error')
        self.assertIn("unclosed If blocks on stack", context['error_message'])

    @patch('automation_sequences.pyautogui', None) # Simulate pyautogui not being importable
    def test_pyautogui_not_installed(self):
        # Need to stop the class-level patch for this specific test
        self.pyautogui_patcher.stop()
        try:
            steps = [create_step(STEP_TYPE_MOUSE_CLICK, {"x": 1, "y": 1, "button": "left"})]
            context = run_step_automation(steps)
            self.assertEqual(context['status'], 'error')
            self.assertIn("pyautogui is not installed", context['error_message'])
        finally:
            # Restart the patcher so other tests are not affected
            self.pyautogui_patcher.start()


if __name__ == '__main__':
    unittest.main()
