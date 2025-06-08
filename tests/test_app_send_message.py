import unittest
from unittest.mock import MagicMock, patch

from PyQt5.QtWidgets import QApplication

# It's necessary to have a QApplication instance before creating QWidgets or QMainWindow
if QApplication.instance() is None:
    app = QApplication([])

from app import AIChatApp


class TestAppSendMessage(unittest.TestCase):
    def setUp(self):
        # Create an instance of AIChatApp
        self.app = AIChatApp()
        # Mock critical UI components and methods that are not directly part of the logic being tested
        self.app.chat_tab = MagicMock()
        self.app.chat_tab.last_user_message_id = None # Ensure this attribute exists
        self.app.tools = {} # Ensure tools attribute exists
        self.app.workflows = [] # Ensure workflows attribute exists
        self.app.metrics = {} # Ensure metrics attribute exists
        self.app.update_send_button_state = MagicMock() # Mock this to avoid side effects during tests


    def tearDown(self):
        # Clean up any resources if necessary
        for worker, thread in self.app.active_worker_threads:
            thread.quit()
            thread.wait()
        self.app.active_worker_threads.clear()
        del self.app

    @patch('app.AIWorker')
    @patch('app.QMessageBox')
    def test_send_message_only_coordinator_enabled(self, mock_qmessagebox, mock_aiworker):
        # Configure agents_data for this test case
        self.app.agents_data = {
            "CoordinatorAgent": {"enabled": True, "role": "Coordinator", "model": "coord_model"},
            "AssistantAgent": {"enabled": False, "role": "Assistant", "model": "assist_model"},
            "SpecialistAgent": {"enabled": False, "role": "Specialist", "model": "spec_model"},
        }

        # Call the method under test
        self.app.send_message("Test message to coordinator")

        # Assertions
        mock_aiworker.assert_called_once()
        args, kwargs = mock_aiworker.call_args
        self.assertEqual(args[0], "coord_model")
        self.assertEqual(args[5], "CoordinatorAgent")
        mock_qmessagebox.warning.assert_not_called()
        self.app.chat_tab.show_typing_indicator.assert_called_once()
        self.app.chat_tab.send_button.setEnabled.assert_any_call(False)

# Define side_effect function and its call list at the module level or class level if preferred
# For simplicity here, defined before the class, assuming it's reset appropriately.
def aiworker_side_effect_func(*args, **kwargs):
    aiworker_side_effect_func.called_args_list.append({'args': args, 'kwargs': kwargs})
    mock_instance = MagicMock()
    # To better mimic AIWorker, which is a QObject, we can give the instance a 'run' method
    # and other methods/signals if the main code interacts with them after creation
    # and before the test assertions.
    mock_instance.run = MagicMock()
    mock_instance.moveToThread = MagicMock()
    mock_instance.response_received = MagicMock()
    mock_instance.error_occurred = MagicMock()
    mock_instance.finished = MagicMock()
    return mock_instance
aiworker_side_effect_func.called_args_list = []


class TestAppSendMessage(unittest.TestCase):
    def setUp(self):
        # Create an instance of AIChatApp
        self.app = AIChatApp()

        # Standard mock for chat_tab; its attributes will be MagicMocks by default.
        self.app.chat_tab = MagicMock()
        # Ensure last_user_message_id is set for any checks within send_message
        self.app.chat_tab.last_user_message_id = "mock_msg_id"
        # Mock return value for append_message_html if its result is used
        self.app.chat_tab.append_message_html = MagicMock(return_value="mock_msg_id")


        self.app.tools = {}
        self.app.workflows = []
        self.app.metrics = {}
        self.app.update_send_button_state = MagicMock()
        # Reset side effect call list before each test that uses it
        aiworker_side_effect_func.called_args_list = []


    def tearDown(self):
        # Clean up any resources if necessary
        for worker, thread in self.app.active_worker_threads:
            thread.quit()
            thread.wait()
        self.app.active_worker_threads.clear()
        del self.app

    @patch('app.AIWorker')
    @patch('app.QMessageBox')
    def test_send_message_only_coordinator_enabled(self, mock_qmessagebox, mock_aiworker_class):
        # Configure agents_data for this test case
        self.app.agents_data = {
            "CoordinatorAgent": {"enabled": True, "role": "Coordinator", "model": "coord_model"},
            "AssistantAgent": {"enabled": False, "role": "Assistant", "model": "assist_model"},
            "SpecialistAgent": {"enabled": False, "role": "Specialist", "model": "spec_model"},
        }

        # Call the method under test
        self.app.send_message("Test message to coordinator")

        # Assertions
        mock_aiworker_class.assert_called_once() # Check class instantiation
        args, kwargs = mock_aiworker_class.call_args
        self.assertEqual(args[0], "coord_model")
        self.assertEqual(args[5], "CoordinatorAgent")
        mock_qmessagebox.warning.assert_not_called()
        self.app.chat_tab.show_typing_indicator.assert_called_once()
        self.app.chat_tab.send_button.setEnabled.assert_any_call(False)

    @patch('app.AIWorker') # This is the mock for the AIWorker CLASS
    @patch('app.QMessageBox')
    def test_send_message_only_assistant_enabled(self, mock_qmessagebox, mock_aiworker_class):
        # Assign the side_effect to the mock of the AIWorker class
        mock_aiworker_class.side_effect = aiworker_side_effect_func

        # Configure agents_data
        self.app.agents_data = {
            "CoordinatorAgent": {"enabled": False, "role": "Coordinator", "model": "coord_model"},
            "AssistantAgent": {"enabled": True, "role": "Assistant", "model": "assist_model"},
            "SpecialistAgent": {"enabled": False, "role": "Specialist", "model": "spec_model"},
        }

        # Call method
        self.app.send_message("Test message to assistant")

        # Assertions
        # Check that AIWorker was instantiated (side_effect_func was called)
        self.assertTrue(len(aiworker_side_effect_func.called_args_list) > 0, "AIWorker constructor was not called.")

        # If AIWorker was called, check its arguments
        call_info = aiworker_side_effect_func.called_args_list[0]
        self.assertEqual(call_info['args'][0], "assist_model", "AIWorker called with wrong model name.")
        self.assertEqual(call_info['args'][5], "AssistantAgent", "AIWorker called for wrong agent.")

        # Check other interactions
        mock_qmessagebox.warning.assert_not_called()
        self.app.chat_tab.show_typing_indicator.assert_called_once()
        # This is the critical assertion that was failing.
        self.app.chat_tab.send_button.setEnabled.assert_any_call(False)

        # Depending on how the mocked AIWorker and its thread behaves,
        # setEnabled(True) and hide_typing_indicator might be called.
        # For this test, we primarily care that the correct agent processing was initiated.
        # If the AIWorker mock doesn't emit 'finished', these might not be reliably testable here.
        # self.app.chat_tab.send_button.setEnabled.assert_any_call(True)
        # self.app.chat_tab.hide_typing_indicator.assert_called_once()


    @patch('app.AIWorker')
    @patch('app.QMessageBox')
    def test_send_message_coordinator_and_assistant_enabled(self, mock_qmessagebox, mock_aiworker):
        # Configure agents_data
        self.app.agents_data = {
            "CoordinatorAgent": {"enabled": True, "role": "Coordinator", "model": "coord_model"},
            "AssistantAgent": {"enabled": True, "role": "Assistant", "model": "assist_model"},
            "SpecialistAgent": {"enabled": False, "role": "Specialist", "model": "spec_model"},
        }

        # Call method
        self.app.send_message("Test message, coordinator preferred")

        # Assertions: Coordinator should be chosen
        mock_aiworker.assert_called_once()
        args, kwargs = mock_aiworker.call_args
        self.assertEqual(args[0], "coord_model")
        self.assertEqual(args[5], "CoordinatorAgent")
        mock_qmessagebox.warning.assert_not_called()
        self.app.chat_tab.show_typing_indicator.assert_called_once()
        self.app.chat_tab.send_button.setEnabled.assert_any_call(False)

    @patch('app.AIWorker')
    @patch('app.QMessageBox')
    def test_send_message_no_agents_enabled(self, mock_qmessagebox, mock_aiworker):
        # Configure agents_data
        self.app.agents_data = {
            "CoordinatorAgent": {"enabled": False, "role": "Coordinator", "model": "coord_model"},
            "AssistantAgent": {"enabled": False, "role": "Assistant", "model": "assist_model"},
            "SpecialistAgent": {"enabled": False, "role": "Specialist", "model": "spec_model"},
        }

        # Call method
        self.app.send_message("Test message, no agents")

        # Assertions
        mock_aiworker.assert_not_called()
        mock_qmessagebox.warning.assert_called_once_with(
            self.app, "No Agents Enabled", "Please enable at least one Assistant agent or a Coordinator agent."
        )
        self.app.chat_tab.show_typing_indicator.assert_called_once()
        self.app.chat_tab.hide_typing_indicator.assert_called_once()
        self.app.chat_tab.send_button.setEnabled.assert_any_call(False)
        self.app.chat_tab.send_button.setEnabled.assert_any_call(True)

    @patch('app.AIWorker')
    @patch('app.QMessageBox')
    def test_send_message_only_specialist_enabled(self, mock_qmessagebox, mock_aiworker):
        # Configure agents_data
        self.app.agents_data = {
            "CoordinatorAgent": {"enabled": False, "role": "Coordinator", "model": "coord_model"},
            "AssistantAgent": {"enabled": False, "role": "Assistant", "model": "assist_model"},
            "SpecialistAgent": {"enabled": True, "role": "Specialist", "model": "spec_model"},
        }

        # Call method
        self.app.send_message("Test message, only specialist")

        # Assertions: Specialist alone should not be able to handle a direct user message
        mock_aiworker.assert_not_called()
        mock_qmessagebox.warning.assert_called_once_with(
            self.app, "No Agents Enabled", "Please enable at least one Assistant agent or a Coordinator agent."
        )
        self.app.chat_tab.show_typing_indicator.assert_called_once()
        self.app.chat_tab.hide_typing_indicator.assert_called_once()
        self.app.chat_tab.send_button.setEnabled.assert_any_call(False)
        self.app.chat_tab.send_button.setEnabled.assert_any_call(True)

if __name__ == "__main__":
    unittest.main()
